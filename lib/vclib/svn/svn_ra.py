# -*-python-*-
#
# Copyright (C) 1999-2008 The ViewCVS Group. All Rights Reserved.
#
# By using this file, you agree to the terms and conditions set forth in
# the LICENSE.html file which can be found at the top level of the ViewVC
# distribution or at http://viewvc.org/license-1.html.
#
# For more information, visit http://viewvc.org/
#
# -----------------------------------------------------------------------

"Version Control lib driver for remotely accessible Subversion repositories."

import vclib
import sys
import os
import string
import re
import tempfile
import popen2
import time
import urllib
from svn_repos import Revision, SVNChangedPath, _datestr_to_date, _compare_paths, _cleanup_path, _rev2optrev
from svn import core, delta, client, wc, ra


### Require Subversion 1.3.1 or better. (for svn_ra_get_locations support)
if (core.SVN_VER_MAJOR, core.SVN_VER_MINOR, core.SVN_VER_PATCH) < (1, 3, 1):
  raise Exception, "Version requirement not met (needs 1.3.1 or better)"

  
def date_from_rev(svnrepos, rev):
  return _datestr_to_date(ra.svn_ra_rev_prop(svnrepos.ra_session, rev,
                                             core.SVN_PROP_REVISION_DATE))


class LastHistoryCollector:
  def __init__(self):
    self.has_history = 0

  def add_history(self, paths, revision, author, date, message, pool):
    if not self.has_history:
      self.has_history = 1
      self.revision = revision
      self.author = author
      self.date = _datestr_to_date(date)
      self.message = message
      self.changes = []

      if not paths:
        return
      changed_paths = paths.keys()
      changed_paths.sort(lambda a, b: _compare_paths(a, b))
      action_map = { 'D' : vclib.DELETED,
                     'A' : vclib.ADDED,
                     'R' : vclib.REPLACED,
                     'M' : vclib.MODIFIED,
                     }
      for changed_path in changed_paths:
        pathtype = None
        change = paths[changed_path]
        action = action_map.get(change.action, vclib.MODIFIED)
        is_copy = 0
        base_path = changed_path
        base_rev = revision - 1
        ### Wrong, diddily wrong wrong wrong.  Can you say,
        ### "Manufacturing data left and right because it hurts to
        ### figure out the right stuff?"
        if change.copyfrom_path and change.copyfrom_rev:
          is_copy = 1
          base_path = change.copyfrom_path
          base_rev = change.copyfrom_rev
        elif action == vclib.ADDED or action == vclib.REPLACED:
          base_path = base_rev = None
        self.changes.append(SVNChangedPath(changed_path, revision, pathtype,
                                           base_path, base_rev, action,
                                           is_copy, 0, 0))

  def get_history(self):
    if not self.has_history:
      return None, None, None, None, None
    return self.revision, self.author, self.date, self.message, self.changes


def _get_rev_details(svnrepos, rev):
  lhc = LastHistoryCollector()
  client.svn_client_log([svnrepos.rootpath],
                        _rev2optrev(rev), _rev2optrev(rev),
                        1, 0, lhc.add_history, svnrepos.ctx)
  return lhc.get_history()

  
class LogCollector:
  def __init__(self, path, show_all_logs, lockinfo):
    # This class uses leading slashes for paths internally
    if not path:
      self.path = '/'
    else:
      self.path = path[0] == '/' and path or '/' + path
    self.logs = []
    self.show_all_logs = show_all_logs
    self.lockinfo = lockinfo
    
  def add_log(self, paths, revision, author, date, message, pool):
    # Changed paths have leading slashes
    changed_paths = paths.keys()
    changed_paths.sort(lambda a, b: _compare_paths(a, b))
    this_path = None
    if self.path in changed_paths:
      this_path = self.path
      change = paths[self.path]
      if change.copyfrom_path:
        this_path = change.copyfrom_path
    for changed_path in changed_paths:
      if changed_path != self.path:
        # If a parent of our path was copied, our "next previous"
        # (huh?) path will exist elsewhere (under the copy source).
        if (string.rfind(self.path, changed_path) == 0) and \
               self.path[len(changed_path)] == '/':
          change = paths[changed_path]
          if change.copyfrom_path:
            this_path = change.copyfrom_path + self.path[len(changed_path):]
    if self.show_all_logs or this_path:
      entry = Revision(revision, _datestr_to_date(date), author, message, None,
                       self.lockinfo, self.path[1:], None, None)
      self.logs.append(entry)
    if this_path:
      self.path = this_path
    
def temp_checkout(svnrepos, path, rev):
  """Check out file revision to temporary file"""
  temp = tempfile.mktemp()
  stream = core.svn_stream_from_aprfile(temp)
  url = svnrepos._geturl(path)
  client.svn_client_cat(core.Stream(stream), url, _rev2optrev(rev),
                        svnrepos.ctx)
  core.svn_stream_close(stream)
  return temp

class SelfCleanFP:
  def __init__(self, path):
    self._fp = open(path, 'r')
    self._path = path
    self._eof = 0
    
  def read(self, len=None):
    if len:
      chunk = self._fp.read(len)
    else:
      chunk = self._fp.read()
    if chunk == '':
      self._eof = 1
    return chunk
  
  def readline(self):
    chunk = self._fp.readline()
    if chunk == '':
      self._eof = 1
    return chunk

  def close(self):
    self._fp.close()
    os.remove(self._path)

  def __del__(self):
    self.close()
    
  def eof(self):
    return self._eof


class RemoteSubversionRepository(vclib.Repository):
  def __init__(self, name, rootpath, authorizer, utilities):
    self.name = name
    self.rootpath = rootpath
    self.auth = authorizer
    self.diff_cmd = utilities.diff or 'diff'

    # See if this repository is even viewable, authz-wise.
    if not vclib.check_root_access(self):
      raise vclib.ReposNotFound(name)

  def open(self):
    # Setup the client context baton, complete with non-prompting authstuffs.
    # TODO: svn_cmdline_setup_auth_baton() is mo' better (when available)
    core.svn_config_ensure(None)
    self.ctx = client.svn_client_ctx_t()
    self.ctx.auth_baton = core.svn_auth_open([
      client.svn_client_get_simple_provider(),
      client.svn_client_get_username_provider(),
      client.svn_client_get_ssl_server_trust_file_provider(),
      client.svn_client_get_ssl_client_cert_file_provider(),
      client.svn_client_get_ssl_client_cert_pw_file_provider(),
      ])
    self.ctx.config = core.svn_config_get_config(None)

    ra_callbacks = ra.svn_ra_callbacks_t()
    ra_callbacks.auth_baton = self.ctx.auth_baton
    self.ra_session = ra.svn_ra_open(self.rootpath, ra_callbacks, None,
                                     self.ctx.config)
    self.youngest = ra.svn_ra_get_latest_revnum(self.ra_session)
    self._dirent_cache = { }

  def rootname(self):
    return self.name

  def rootpath(self):
    return self.rootpath

  def roottype(self):
    return vclib.SVN

  def authorizer(self):
    return self.auth
  
  def itemtype(self, path_parts, rev):
    path = self._getpath(path_parts[:-1])
    rev = self._getrev(rev)
    if not len(path_parts):
      return vclib.DIR
    dirents, locks = self._get_dirents(path, rev)
    try:
      entry = dirents[path_parts[-1]]
      if entry.kind == core.svn_node_dir:
        return vclib.DIR
      if entry.kind == core.svn_node_file:
        return vclib.FILE
    except KeyError:
      raise vclib.ItemNotFound(path_parts)

  def openfile(self, path_parts, rev):
    path = self._getpath(path_parts)
    rev = self._getrev(rev)
    url = self._geturl(path)
    
    tmp_file = tempfile.mktemp()
    stream = core.svn_stream_from_aprfile(tmp_file)
    ### rev here should be the last history revision of the URL
    client.svn_client_cat(core.Stream(stream), url, _rev2optrev(rev), self.ctx)
    core.svn_stream_close(stream)
    return SelfCleanFP(tmp_file), rev

  def listdir(self, path_parts, rev, options):
    path = self._getpath(path_parts)
    rev = self._getrev(rev)
    entries = [ ]
    dirents, locks = self._get_dirents(path, rev)
    for name in dirents.keys():
      entry = dirents[name]
      if entry.kind == core.svn_node_dir:
        kind = vclib.DIR
      elif entry.kind == core.svn_node_file:
        kind = vclib.FILE
      entries.append(vclib.DirEntry(name, kind))
    return entries

  def dirlogs(self, path_parts, rev, entries, options):
    rev_info_cache = { }
    dirents, locks = self._get_dirents(self._getpath(path_parts),
                                       self._getrev(rev))
    for entry in entries:
      dirent = dirents[entry.name]
      if rev_info_cache.has_key(dirent.created_rev):
        rev, author, date, log = rev_info_cache[dirent.created_rev]
      else:
        ### i think this needs some get_last_history action to be accurate
        rev, author, date, log, changes = \
             _get_rev_details(self, dirent.created_rev)
        rev_info_cache[dirent.created_rev] = rev, author, date, log
      entry.rev = rev
      entry.author = author
      entry.date = _datestr_to_date(date)
      entry.log = log
      entry.size = dirent.size
      entry.lockinfo = None
      if locks.has_key(entry.name):
        entry.lockinfo = locks[entry.name].owner

  def itemlog(self, path_parts, rev, sortby, first, limit, options):
    assert sortby == vclib.SORTBY_DEFAULT or sortby == vclib.SORTBY_REV   
    path = self._getpath(path_parts)
    rev = self._getrev(rev)
    url = self._geturl(path)

    # Use ls3 to fetch the lock status for this item.
    lockinfo = None
    dirents, locks = client.svn_client_ls3(url, _rev2optrev(rev),
                                           _rev2optrev(rev), 0, self.ctx)
    if locks.has_key(path_parts[-1]):
      lockinfo = locks[path_parts[-1]].owner

    # It's okay if we're told to not show all logs on a file -- all
    # the revisions should match correctly anyway.
    lc = LogCollector(path, options.get('svn_show_all_dir_logs', 0), lockinfo)

    cross_copies = options.get('svn_cross_copies', 0)
    log_limit = 0
    if limit:
      log_limit = first + limit
    client.svn_client_log2([url], _rev2optrev(rev), _rev2optrev(1),
                           log_limit, 1, not cross_copies, lc.add_log, self.ctx)
    revs = lc.logs
    revs.sort()
    prev = None
    for rev in revs:
      rev.prev = prev
      prev = rev
    revs.reverse()

    if len(revs) < first:
      return []
    if limit:
      return revs[first:first+limit]
    return revs

  def itemprops(self, path_parts, rev):
    path = self._getpath(path_parts)
    rev = self._getrev(rev)
    url = self._geturl(path)
    pairs = client.svn_client_proplist2(url, _rev2optrev(rev),
                                        _rev2optrev(rev), 0, self.ctx)
    return pairs and pairs[0][1] or {}
  
  def annotate(self, path_parts, rev):
    path = self._getpath(path_parts)
    rev = self._getrev(rev)
    url = self._geturl(path)

    blame_data = []

    def _blame_cb(line_no, revision, author, date,
                  line, pool, blame_data=blame_data):
      prev_rev = None
      if revision > 1:
        prev_rev = revision - 1
      blame_data.append(vclib.Annotation(line, line_no+1, revision, prev_rev,
                                         author, None))
      
    client.svn_client_blame(url, _rev2optrev(1), _rev2optrev(rev),
                            _blame_cb, self.ctx)

    return blame_data, rev

  def revinfo(self, rev):
    rev, author, date, log, changes = _get_rev_details(self, rev)
    return date, author, log, changes
    
  def rawdiff(self, path_parts1, rev1, path_parts2, rev2, type, options={}):
    p1 = self._getpath(path_parts1)
    p2 = self._getpath(path_parts2)
    r1 = self._getrev(rev1)
    r2 = self._getrev(rev2)
    args = vclib._diff_args(type, options)

    try:
      temp1 = temp_checkout(self, p1, r1)
      temp2 = temp_checkout(self, p2, r2)
      info1 = p1, date_from_rev(self, r1), r1
      info2 = p2, date_from_rev(self, r2), r2
      return vclib._diff_fp(temp1, temp2, info1, info2, self.diff_cmd, args)
    except core.SubversionException, e:
      if e.apr_err == vclib.svn.core.SVN_ERR_FS_NOT_FOUND:
        raise vclib.InvalidRevision
      raise

  def _getpath(self, path_parts):
    return string.join(path_parts, '/')

  def _getrev(self, rev):
    if rev is None or rev == 'HEAD':
      return self.youngest
    try:
      rev = int(rev)
    except ValueError:
      raise vclib.InvalidRevision(rev)
    if (rev < 0) or (rev > self.youngest):
      raise vclib.InvalidRevision(rev)
    return rev

  def _geturl(self, path=None):
    if not path:
      return self.rootpath
    return self.rootpath + '/' + urllib.quote(path, "/*~")

  def _get_dirents(self, path, rev):
    """Return a 2-type of dirents and locks, possibly reading/writing
    from a local cache of that information."""

    dir_url = self._geturl(path)
    if path:
      key = str(rev) + '/' + path
    else:
      key = str(rev)
    dirents_locks = self._dirent_cache.get(key)
    if not dirents_locks:
      dirents, locks = client.svn_client_ls3(dir_url, _rev2optrev(rev),
                                             _rev2optrev(rev), 0, self.ctx)
      dirents_locks = [dirents, locks]
      self._dirent_cache[key] = dirents_locks
    return dirents_locks[0], dirents_locks[1]

  ##--- custom --##

  def get_youngest_revision(self):
    return self.youngest
  
  def get_location(self, path, rev, old_rev):
    try:
      results = ra.get_locations(self.ra_session, path, rev, [old_rev])
    except core.SubversionException, e:
      if e.apr_err == core.SVN_ERR_FS_NOT_FOUND:
        raise vclib.ItemNotFound(path)
      raise
    try:
      old_path = results[old_rev]
    except KeyError:
      raise vclib.ItemNotFound(path)
  
    return _cleanup_path(old_path)
  
  def created_rev(self, path, rev):
    # NOTE: We can't use svn_client_propget here because the
    # interfaces in that layer strip out the properties not meant for
    # human consumption (such as svn:entry:committed-rev, which we are
    # using here to get the created revision of PATH@REV).
    kind = ra.svn_ra_check_path(self.ra_session, path, rev)
    if kind == core.svn_node_none:
      raise vclib.ItemNotFound(_path_parts(path))
    elif kind == core.svn_node_dir:
      try:
        dirents, fetched_rev, props = ra.svn_ra_get_dir(self.ra_session,
                                                        path, rev)
      except ValueError:
        # older versions of the bindings didn't handle ra.svn_ra_get_dir()
        # correctly.
        props = ra.svn_ra_get_dir(self.ra_session, path, rev)
    elif kind == core.svn_node_file:
      fetched_rev, props = ra.svn_ra_get_file(self.ra_session, path, rev, None)
    return int(props.get(core.SVN_PROP_ENTRY_COMMITTED_REV,
                         core.SVN_INVALID_REVNUM))

  def last_rev(self, path, peg_revision, limit_revision=None):
    """Given PATH, known to exist in PEG_REVISION, find the youngest
    revision older than, or equal to, LIMIT_REVISION in which path
    exists.  Return that revision, and the path at which PATH exists in
    that revision."""
    
    # Here's the plan, man.  In the trivial case (where PEG_REVISION is
    # the same as LIMIT_REVISION), this is a no-brainer.  If
    # LIMIT_REVISION is older than PEG_REVISION, we can use Subversion's
    # history tracing code to find the right location.  If, however,
    # LIMIT_REVISION is younger than PEG_REVISION, we suffer from
    # Subversion's lack of forward history searching.  Our workaround,
    # ugly as it may be, involves a binary search through the revisions
    # between PEG_REVISION and LIMIT_REVISION to find our last live
    # revision.
    peg_revision = self._getrev(peg_revision)
    limit_revision = self._getrev(limit_revision)
    if peg_revision == limit_revision:
      return peg_revision, path
    elif peg_revision > limit_revision:
      path = self.get_location(path, peg_revision, limit_revision)
      return limit_revision, path
    else:
      direction = 1
      while peg_revision != limit_revision:
        mid = (peg_revision + 1 + limit_revision) / 2
        try:
          path = self.get_location(path, peg_revision, mid)
        except vclib.ItemNotFound:
          limit_revision = mid - 1
        else:
          peg_revision = mid
      return peg_revision, path