# -*-python-*-
#
# Copyright (C) 1999-2010 The ViewCVS Group. All Rights Reserved.
#
# By using this file, you agree to the terms and conditions set forth in
# the LICENSE.html file which can be found at the top level of the ViewVC
# distribution or at http://viewvc.org/license-1.html.
#
# For more information, visit http://viewvc.org/
#
# -----------------------------------------------------------------------

"Version Control lib driver for locally accessible Subversion repositories"

import vclib
import os
import os.path
import cStringIO
import time
import tempfile
import popen
import re
from svn import fs, repos, core, client, delta


### Require Subversion 1.3.1 or better.
if (core.SVN_VER_MAJOR, core.SVN_VER_MINOR, core.SVN_VER_PATCH) < (1, 3, 1):
  raise Exception, "Version requirement not met (needs 1.3.1 or better)"


### Pre-1.5 Subversion doesn't have SVN_ERR_CEASE_INVOCATION
try:
  _SVN_ERR_CEASE_INVOCATION = core.SVN_ERR_CEASE_INVOCATION
except:
  _SVN_ERR_CEASE_INVOCATION = core.SVN_ERR_CANCELLED

### Pre-1.5 SubversionException's might not have the .msg and .apr_err members
def _fix_subversion_exception(e):
  if not hasattr(e, 'apr_err'):
    e.apr_err = e[1]
  if not hasattr(e, 'message'):
    e.message = e[0]
  
def _allow_all(root, path, pool):
  """Generic authz_read_func that permits access to all paths"""
  return 1


def _path_parts(path):
  return filter(None, path.split('/'))


def _cleanup_path(path):
  """Return a cleaned-up Subversion filesystem path"""
  return '/'.join(_path_parts(path))
  

def _fs_path_join(base, relative):
  return _cleanup_path(base + '/' + relative)


def _compare_paths(path1, path2):
  path1_len = len (path1);
  path2_len = len (path2);
  min_len = min(path1_len, path2_len)
  i = 0

  # Are the paths exactly the same?
  if path1 == path2:
    return 0
  
  # Skip past common prefix
  while (i < min_len) and (path1[i] == path2[i]):
    i = i + 1

  # Children of paths are greater than their parents, but less than
  # greater siblings of their parents
  char1 = '\0'
  char2 = '\0'
  if (i < path1_len):
    char1 = path1[i]
  if (i < path2_len):
    char2 = path2[i]
    
  if (char1 == '/') and (i == path2_len):
    return 1
  if (char2 == '/') and (i == path1_len):
    return -1
  if (i < path1_len) and (char1 == '/'):
    return -1
  if (i < path2_len) and (char2 == '/'):
    return 1

  # Common prefix was skipped above, next character is compared to
  # determine order
  return cmp(char1, char2)


def _rev2optrev(rev):
  assert type(rev) is int
  rt = core.svn_opt_revision_t()
  rt.kind = core.svn_opt_revision_number
  rt.value.number = rev
  return rt


def _rootpath2url(rootpath, path):
  rootpath = os.path.abspath(rootpath)
  if rootpath and rootpath[0] != '/':
    rootpath = '/' + rootpath
  if os.sep != '/':
    rootpath = rootpath.replace(os.sep, '/')
  return 'file://' + rootpath + '/' + path


# Given a dictionary REVPROPS of revision properties, pull special
# ones out of them and return a 4-tuple containing the log message,
# the author, the date (converted from the date string property), and
# a dictionary of any/all other revprops.
def _split_revprops(revprops):
  special_props = []
  for prop in core.SVN_PROP_REVISION_LOG, \
              core.SVN_PROP_REVISION_AUTHOR, \
              core.SVN_PROP_REVISION_DATE:
    if revprops.has_key(prop):
      special_props.append(revprops[prop])
      del(revprops[prop])
    else:
      special_props.append(None)
  msg, author, datestr = tuple(special_props)
  date = _datestr_to_date(datestr)
  return msg, author, date, revprops  


def _datestr_to_date(datestr):
  try:
    return core.svn_time_from_cstring(datestr) / 1000000
  except:
    return None

  
class Revision(vclib.Revision):
  "Hold state for each revision's log entry."
  def __init__(self, rev, date, author, msg, size, lockinfo,
               filename, copy_path, copy_rev):
    vclib.Revision.__init__(self, rev, str(rev), date, author, None,
                            msg, size, lockinfo)
    self.filename = filename
    self.copy_path = copy_path
    self.copy_rev = copy_rev


class NodeHistory:
  """An iterable object that returns 2-tuples of (revision, path)
  locations along a node's change history, ordered from youngest to
  oldest."""
  
  def __init__(self, fs_ptr, show_all_logs, limit=0):
    self.histories = []
    self.fs_ptr = fs_ptr
    self.show_all_logs = show_all_logs
    self.oldest_rev = None
    self.limit = limit
    
  def add_history(self, path, revision, pool):
    # If filtering, only add the path and revision to the histories
    # list if they were actually changed in this revision (where
    # change means the path itself was changed, or one of its parents
    # was copied).  This is useful for omitting bubble-up directory
    # changes.
    if not self.oldest_rev:
      self.oldest_rev = revision
    else:
      assert(revision < self.oldest_rev)
      
    if not self.show_all_logs:
      rev_root = fs.revision_root(self.fs_ptr, revision)
      changed_paths = fs.paths_changed(rev_root)
      paths = changed_paths.keys()
      if path not in paths:
        # Look for a copied parent
        test_path = path
        found = 0
        while 1:
          off = test_path.rfind('/')
          if off < 0:
            break
          test_path = test_path[0:off]
          if test_path in paths:
            copyfrom_rev, copyfrom_path = fs.copied_from(rev_root, test_path)
            if copyfrom_rev >= 0 and copyfrom_path:
              found = 1
              break
        if not found:
          return
    self.histories.append([revision, _cleanup_path(path)])
    if self.limit and len(self.histories) == self.limit:
      raise core.SubversionException("", _SVN_ERR_CEASE_INVOCATION)

  def __getitem__(self, idx):
    return self.histories[idx]


def _get_history(svnrepos, path, rev, path_type, limit=0, options={}):
  if svnrepos.youngest == 0:
    return []

  rev_paths = []
  fsroot = svnrepos._getroot(rev)
  show_all_logs = options.get('svn_show_all_dir_logs', 0)
  if not show_all_logs:
    # See if the path is a file or directory.
    kind = fs.check_path(fsroot, path)
    if kind is core.svn_node_file:
      show_all_logs = 1
      
  # Instantiate a NodeHistory collector object, and use it to collect
  # history items for PATH@REV.
  history = NodeHistory(svnrepos.fs_ptr, show_all_logs, limit)
  try:
    repos.svn_repos_history(svnrepos.fs_ptr, path, history.add_history,
                            1, rev, options.get('svn_cross_copies', 0))
  except core.SubversionException, e:
    _fix_subversion_exception(e)
    if e.apr_err != _SVN_ERR_CEASE_INVOCATION:
      raise

  # Now, iterate over those history items, checking for changes of
  # location, pruning as necessitated by authz rules.
  for hist_rev, hist_path in history:
    path_parts = _path_parts(hist_path)
    if not vclib.check_path_access(svnrepos, path_parts, path_type, hist_rev):
      break
    rev_paths.append([hist_rev, hist_path])
  return rev_paths


def _log_helper(svnrepos, path, rev, lockinfo):
  rev_root = fs.revision_root(svnrepos.fs_ptr, rev)

  # Was this path@rev the target of a copy?
  copyfrom_rev, copyfrom_path = fs.copied_from(rev_root, path)

  # Assemble our LogEntry
  date, author, msg, revprops, changes = svnrepos._revinfo(rev)
  if fs.is_file(rev_root, path):
    size = fs.file_length(rev_root, path)
  else:
    size = None
  entry = Revision(rev, date, author, msg, size, lockinfo, path,
                   copyfrom_path and _cleanup_path(copyfrom_path),
                   copyfrom_rev)
  return entry
  

def _get_last_history_rev(fsroot, path):
  history = fs.node_history(fsroot, path)
  history = fs.history_prev(history, 0)
  history_path, history_rev = fs.history_location(history)
  return history_rev
  
def temp_checkout(svnrepos, path, rev):
  """Check out file revision to temporary file"""
  temp = tempfile.mktemp()
  fp = open(temp, 'wb')
  try:
    root = svnrepos._getroot(rev)
    stream = fs.file_contents(root, path)
    try:
      while 1:
        chunk = core.svn_stream_read(stream, core.SVN_STREAM_CHUNK_SIZE)
        if not chunk:
          break
        fp.write(chunk)
    finally:
      core.svn_stream_close(stream)
  finally:
    fp.close()
  return temp

class FileContentsPipe:
  def __init__(self, root, path):
    self._stream = fs.file_contents(root, path)
    self._eof = 0

  def read(self, len=None):
    chunk = None
    if not self._eof:
      if len is None:
        buffer = cStringIO.StringIO()
        try:
          while 1:
            hunk = core.svn_stream_read(self._stream, 8192)
            if not hunk:
              break
            buffer.write(hunk)
          chunk = buffer.getvalue()
        finally:
          buffer.close()

      else:
        chunk = core.svn_stream_read(self._stream, len)   
    if not chunk:
      self._eof = 1
    return chunk
  
  def readline(self):
    chunk = None
    if not self._eof:
      chunk, self._eof = core.svn_stream_readline(self._stream, '\n')
      if not self._eof:
        chunk = chunk + '\n'
    if not chunk:
      self._eof = 1
    return chunk

  def readlines(self):
    lines = []
    while True:
      line = self.readline()
      if not line:
        break
      lines.append(line)
    return lines

  def close(self):
    return core.svn_stream_close(self._stream)

  def eof(self):
    return self._eof


class BlameSource:
  def __init__(self, local_url, rev, first_rev, config_dir):
    self.idx = -1
    self.first_rev = first_rev
    self.blame_data = []

    ctx = client.ctx_t()
    core.svn_config_ensure(config_dir)
    ctx.config = core.svn_config_get_config(config_dir)
    ctx.auth_baton = core.svn_auth_open([])
    try:
      ### TODO: Is this use of FIRST_REV always what we want?  Should we
      ### pass 1 here instead and do filtering later?
      client.blame2(local_url, _rev2optrev(rev), _rev2optrev(first_rev),
                    _rev2optrev(rev), self._blame_cb, ctx)
    except core.SubversionException, e:
      _fix_subversion_exception(e)
      if e.apr_err == core.SVN_ERR_CLIENT_IS_BINARY_FILE:
        raise vclib.NonTextualFileContents
      raise

  def _blame_cb(self, line_no, rev, author, date, text, pool):
    prev_rev = None
    if rev > self.first_rev:
      prev_rev = rev - 1
    self.blame_data.append(vclib.Annotation(text, line_no + 1, rev,
                                            prev_rev, author, None))

  def __getitem__(self, idx):
    if idx != self.idx + 1:
      raise BlameSequencingError()
    self.idx = idx
    return self.blame_data[idx]


class BlameSequencingError(Exception):
  pass


class SVNChangedPath(vclib.ChangedPath):
  """Wrapper around vclib.ChangedPath which handles path splitting."""
  
  def __init__(self, path, rev, pathtype, base_path, base_rev,
               action, copied, text_changed, props_changed):
    path_parts = _path_parts(path or '')
    base_path_parts = _path_parts(base_path or '')
    vclib.ChangedPath.__init__(self, path_parts, rev, pathtype,
                               base_path_parts, base_rev, action,
                               copied, text_changed, props_changed)

  
class LocalSubversionRepository(vclib.Repository):
  def __init__(self, name, rootpath, authorizer, utilities, config_dir):
    if not (os.path.isdir(rootpath) \
            and os.path.isfile(os.path.join(rootpath, 'format'))):
      raise vclib.ReposNotFound(name)

    # Initialize some stuff.
    self.rootpath = rootpath
    self.name = name
    self.auth = authorizer
    self.svn_client_path = utilities.svn or 'svn'
    self.diff_cmd = utilities.diff or 'diff'
    self.config_dir = config_dir or None

    # See if this repository is even viewable, authz-wise.
    if not vclib.check_root_access(self):
      raise vclib.ReposNotFound(name)

  def open(self):
    # Open the repository and init some other variables.
    self.repos = repos.svn_repos_open(self.rootpath)
    self.fs_ptr = repos.svn_repos_fs(self.repos)
    self.youngest = fs.youngest_rev(self.fs_ptr)
    self._fsroots = {}
    self._revinfo_cache = {}

  def rootname(self):
    return self.name

  def rootpath(self):
    return self.rootpath

  def roottype(self):
    return vclib.SVN

  def authorizer(self):
    return self.auth
  
  def itemtype(self, path_parts, rev):
    rev = self._getrev(rev)
    basepath = self._getpath(path_parts)
    kind = fs.check_path(self._getroot(rev), basepath)
    pathtype = None
    if kind == core.svn_node_dir:
      pathtype = vclib.DIR
    elif kind == core.svn_node_file:
      pathtype = vclib.FILE
    else:
      raise vclib.ItemNotFound(path_parts)
    if not vclib.check_path_access(self, path_parts, pathtype, rev):
      raise vclib.ItemNotFound(path_parts)
    return pathtype

  def openfile(self, path_parts, rev):
    path = self._getpath(path_parts)
    if self.itemtype(path_parts, rev) != vclib.FILE:  # does auth-check
      raise vclib.Error("Path '%s' is not a file." % path)
    rev = self._getrev(rev)
    fsroot = self._getroot(rev)
    revision = str(_get_last_history_rev(fsroot, path))
    fp = FileContentsPipe(fsroot, path)
    return fp, revision

  def listdir(self, path_parts, rev, options):
    path = self._getpath(path_parts)
    if self.itemtype(path_parts, rev) != vclib.DIR:  # does auth-check
      raise vclib.Error("Path '%s' is not a directory." % path)
    rev = self._getrev(rev)
    fsroot = self._getroot(rev)
    dirents = fs.dir_entries(fsroot, path)
    entries = [ ]
    for entry in dirents.values():
      if entry.kind == core.svn_node_dir:
        kind = vclib.DIR
      elif entry.kind == core.svn_node_file:
        kind = vclib.FILE
      if vclib.check_path_access(self, path_parts + [entry.name], kind, rev):
        entries.append(vclib.DirEntry(entry.name, kind))
    return entries

  def dirlogs(self, path_parts, rev, entries, options):
    path = self._getpath(path_parts)
    if self.itemtype(path_parts, rev) != vclib.DIR:  # does auth-check
      raise vclib.Error("Path '%s' is not a directory." % path)
    fsroot = self._getroot(self._getrev(rev))
    rev = self._getrev(rev)
    for entry in entries:
      entry_path_parts = path_parts + [entry.name]
      if not vclib.check_path_access(self, entry_path_parts, entry.kind, rev):
        continue
      path = self._getpath(entry_path_parts)
      entry_rev = _get_last_history_rev(fsroot, path)
      date, author, msg, revprops, changes = self._revinfo(entry_rev)
      entry.rev = str(entry_rev)
      entry.date = date
      entry.author = author
      entry.log = msg
      if entry.kind == vclib.FILE:
        entry.size = fs.file_length(fsroot, path)
      lock = fs.get_lock(self.fs_ptr, path)
      entry.lockinfo = lock and lock.owner or None

  def itemlog(self, path_parts, rev, sortby, first, limit, options):
    """see vclib.Repository.itemlog docstring

    Option values recognized by this implementation

      svn_show_all_dir_logs
        boolean, default false. if set for a directory path, will include
        revisions where files underneath the directory have changed

      svn_cross_copies
        boolean, default false. if set for a path created by a copy, will
        include revisions from before the copy

      svn_latest_log
        boolean, default false. if set will return only newest single log
        entry
    """
    assert sortby == vclib.SORTBY_DEFAULT or sortby == vclib.SORTBY_REV   

    path = self._getpath(path_parts)
    path_type = self.itemtype(path_parts, rev)  # does auth-check
    rev = self._getrev(rev)
    revs = []
    lockinfo = None

    # See if this path is locked.
    try:
      lock = fs.get_lock(self.fs_ptr, path)
      if lock:
        lockinfo = lock.owner
    except NameError:
      pass

    # If our caller only wants the latest log, we'll invoke
    # _log_helper for just the one revision.  Otherwise, we go off
    # into history-fetching mode.  ### TODO: we could stand to have a
    # 'limit' parameter here as numeric cut-off for the depth of our
    # history search.
    if options.get('svn_latest_log', 0):
      revision = _log_helper(self, path, rev, lockinfo)
      if revision:
        revision.prev = None
        revs.append(revision)
    else:
      history = _get_history(self, path, rev, path_type,
                             first + limit, options)
      if len(history) < first:
        history = []
      if limit:
        history = history[first:first+limit]

      for hist_rev, hist_path in history:
        revision = _log_helper(self, hist_path, hist_rev, lockinfo)
        if revision:
          # If we have unreadable copyfrom data, obscure it.
          if revision.copy_path is not None:
            cp_parts = _path_parts(revision.copy_path)
            if not vclib.check_path_access(self, cp_parts, path_type,
                                           revision.copy_rev):
              revision.copy_path = revision.copy_rev = None
          revision.prev = None
          if len(revs):
            revs[-1].prev = revision
          revs.append(revision)
    return revs

  def itemprops(self, path_parts, rev):
    path = self._getpath(path_parts)
    path_type = self.itemtype(path_parts, rev)  # does auth-check
    rev = self._getrev(rev)
    fsroot = self._getroot(rev)
    return fs.node_proplist(fsroot, path)
  
  def annotate(self, path_parts, rev):
    path = self._getpath(path_parts)
    path_type = self.itemtype(path_parts, rev)  # does auth-check
    if path_type != vclib.FILE:
      raise vclib.Error("Path '%s' is not a file." % path)
    rev = self._getrev(rev)
    fsroot = self._getroot(rev)
    history = _get_history(self, path, rev, path_type, 0,
                           {'svn_cross_copies': 1})
    youngest_rev, youngest_path = history[0]
    oldest_rev, oldest_path = history[-1]
    source = BlameSource(_rootpath2url(self.rootpath, path),
                         youngest_rev, oldest_rev, self.config_dir)
    return source, youngest_rev

  def _revinfo(self, rev, include_changed_paths=0):
    """Internal-use, cache-friendly revision information harvester."""
    
    def _revinfo_helper(rev, include_changed_paths):
      # Get the revision property info.  (Would use
      # editor.get_root_props(), but something is broken there...)
      revprops = fs.revision_proplist(self.fs_ptr, rev)
      msg, author, date, revprops = _split_revprops(revprops)
  
      # Optimization: If our caller doesn't care about the changed
      # paths, and we don't need them to do authz determinations, let's
      # get outta here.
      if self.auth is None and not include_changed_paths:
        return date, author, msg, revprops, None
  
      # If we get here, then we either need the changed paths because we
      # were asked for them, or we need them to do authorization checks.
      # Either way, we need 'em, so let's get 'em.
      fsroot = self._getroot(rev)
      editor = repos.ChangeCollector(self.fs_ptr, fsroot)
      e_ptr, e_baton = delta.make_editor(editor)
      repos.svn_repos_replay(fsroot, e_ptr, e_baton)
      changedpaths = {}
      changes = editor.get_changes()
    
      # Copy the Subversion changes into a new hash, checking
      # authorization and converting them into ChangedPath objects.
      found_readable = found_unreadable = 0
      for path in changes.keys():
        change = changes[path]
        if change.path:
          change.path = _cleanup_path(change.path)
        if change.base_path:
          change.base_path = _cleanup_path(change.base_path)
        is_copy = 0
        if not hasattr(change, 'action'): # new to subversion 1.4.0
          action = vclib.MODIFIED
          if not change.path:
            action = vclib.DELETED
          elif change.added:
            action = vclib.ADDED
            replace_check_path = path
            if change.base_path and change.base_rev:
              replace_check_path = change.base_path
            if changedpaths.has_key(replace_check_path) \
               and changedpaths[replace_check_path].action == vclib.DELETED:
              action = vclib.REPLACED
        else:
          if change.action == repos.CHANGE_ACTION_ADD:
            action = vclib.ADDED
          elif change.action == repos.CHANGE_ACTION_DELETE:
            action = vclib.DELETED
          elif change.action == repos.CHANGE_ACTION_REPLACE:
            action = vclib.REPLACED
          else:
            action = vclib.MODIFIED
        if (action == vclib.ADDED or action == vclib.REPLACED) \
           and change.base_path \
           and change.base_rev:
          is_copy = 1
        if change.item_kind == core.svn_node_dir:
          pathtype = vclib.DIR
        elif change.item_kind == core.svn_node_file:
          pathtype = vclib.FILE
        else:
          pathtype = None
  
        parts = _path_parts(path)
        if vclib.check_path_access(self, parts, pathtype, rev):
          if is_copy and change.base_path and (change.base_path != path):
            parts = _path_parts(change.base_path)
            if not vclib.check_path_access(self, parts, pathtype, change.base_rev):
              is_copy = 0
              change.base_path = None
              change.base_rev = None
          changedpaths[path] = SVNChangedPath(path, rev, pathtype,
                                              change.base_path,
                                              change.base_rev, action,
                                              is_copy, change.text_changed,
                                              change.prop_changes)
          found_readable = 1
        else:
          found_unreadable = 1
  
        # If our caller doesn't care about changed paths, we must be
        # here for authz reasons only.  That means the minute we've
        # found both a readable and an unreadable path, we can bail out.
        if (not include_changed_paths) and found_readable and found_unreadable:
          return date, author, None, None, None
        
      # Okay, we've process all our paths.  Let's filter our metadata,
      # and return the requested data.
      if found_unreadable:
        msg = None
        if not found_readable:
          author = None
          date = None
      if include_changed_paths:
        return date, author, msg, revprops, changedpaths.values()
      else:
        return date, author, msg, revprops, None

    # Consult the revinfo cache first.  If we don't have cached info,
    # or our caller wants changed paths and we don't have those for
    # this revision, go do the real work.
    rev = self._getrev(rev)
    cached_info = self._revinfo_cache.get(rev)
    if not cached_info \
       or (include_changed_paths and cached_info[4] is None):
      cached_info = _revinfo_helper(rev, include_changed_paths)
      self._revinfo_cache[rev] = cached_info
    return tuple(cached_info)
  
  def revinfo(self, rev):
    return self._revinfo(rev, 1) 
  
  def rawdiff(self, path_parts1, rev1, path_parts2, rev2, type, options={}):
    p1 = self._getpath(path_parts1)
    p2 = self._getpath(path_parts2)
    r1 = self._getrev(rev1)
    r2 = self._getrev(rev2)
    if not vclib.check_path_access(self, path_parts1, vclib.FILE, rev1):
      raise vclib.ItemNotFound(path_parts1)
    if not vclib.check_path_access(self, path_parts2, vclib.FILE, rev2):
      raise vclib.ItemNotFound(path_parts2)
    
    args = vclib._diff_args(type, options)

    def _date_from_rev(rev):
      date, author, msg, revprops, changes = self._revinfo(rev)
      return date

    try:
      temp1 = temp_checkout(self, p1, r1)
      temp2 = temp_checkout(self, p2, r2)
      info1 = p1, _date_from_rev(r1), r1
      info2 = p2, _date_from_rev(r2), r2
      return vclib._diff_fp(temp1, temp2, info1, info2, self.diff_cmd, args)
    except core.SubversionException, e:
      _fix_subversion_exception(e)
      if e.apr_err == core.SVN_ERR_FS_NOT_FOUND:
        raise vclib.InvalidRevision
      raise

  def isexecutable(self, path_parts, rev):
    props = self.itemprops(path_parts, rev) # does authz-check
    return props.has_key(core.SVN_PROP_EXECUTABLE)
  
  def _getpath(self, path_parts):
    return '/'.join(path_parts)

  def _getrev(self, rev):
    if rev is None or rev == 'HEAD':
      return self.youngest
    try:
      if type(rev) == type('') and rev[0] == 'r':
        rev = rev[1:]
      rev = int(rev)
    except ValueError:
      raise vclib.InvalidRevision(rev)
    if (rev < 0) or (rev > self.youngest):
      raise vclib.InvalidRevision(rev)
    return rev

  def _getroot(self, rev):
    try:
      return self._fsroots[rev]
    except KeyError:
      r = self._fsroots[rev] = fs.revision_root(self.fs_ptr, rev)
      return r

  ##--- custom --##

  def get_youngest_revision(self):
    return self.youngest

  def get_location(self, path, rev, old_rev):
    try:
      results = repos.svn_repos_trace_node_locations(self.fs_ptr, path,
                                                     rev, [old_rev], _allow_all)
    except core.SubversionException, e:
      _fix_subversion_exception(e)
      if e.apr_err == core.SVN_ERR_FS_NOT_FOUND:
        raise vclib.ItemNotFound(path)
      raise
    try:
      old_path = results[old_rev]
    except KeyError:
      raise vclib.ItemNotFound(path)
  
    return _cleanup_path(old_path)
  
  def created_rev(self, full_name, rev):
    return fs.node_created_rev(self._getroot(rev), full_name)
  
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
    try:
      if peg_revision == limit_revision:
        return peg_revision, path
      elif peg_revision > limit_revision:
        fsroot = self._getroot(peg_revision)
        history = fs.node_history(fsroot, path)
        while history:
          path, peg_revision = fs.history_location(history)
          if peg_revision <= limit_revision:
            return max(peg_revision, limit_revision), _cleanup_path(path)
          history = fs.history_prev(history, 1)
        return peg_revision, _cleanup_path(path)
      else:
        orig_id = fs.node_id(self._getroot(peg_revision), path)
        while peg_revision != limit_revision:
          mid = (peg_revision + 1 + limit_revision) / 2
          try:
            mid_id = fs.node_id(self._getroot(mid), path)
          except core.SubversionException, e:
            _fix_subversion_exception(e)
            if e.apr_err == core.SVN_ERR_FS_NOT_FOUND:
              cmp = -1
            else:
              raise
          else:
            ### Not quite right.  Need a comparison function that only returns
            ### true when the two nodes are the same copy, not just related.
            cmp = fs.compare_ids(orig_id, mid_id)
  
          if cmp in (0, 1):
            peg_revision = mid
          else:
            limit_revision = mid - 1
  
        return peg_revision, path
    finally:
      pass
