# -*-python-*-

"Version Control lib driver for locally accessible Git repositories based on the GitPython library"

import vclib
import os
import os.path
import cStringIO
import time
import tempfile
import popen
import re
import urllib
from git import *

def _allow_all(root, path, pool):
  """Generic authz_read_func that permits access to all paths"""
  return 1

def _path_parts(path):
  return filter(None, path.split('/'))

def _cleanup_path(path):
  return '/'.join(_path_parts(path))

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

def temp_checkout(blob):
  temp = tempfile.mktemp()
  fp = open(temp, 'wb')
  blob.stream_data(fp)
  fp.close()
  return temp

class OStreamWrapper:

  def __init__(self, fp):
    self.fp = fp

  def read(self, bytes):
    return self.fp.read(bytes)

  def readlines(self):
    text = self.fp.read()
    return text.rstrip().split('\n')

  def close(self):
    pass

  def __del__(self):
    self.close()

class LocalGitRepository(vclib.Repository):
  def __init__(self, name, rootpath, authorizer, utilities):
    if not (os.path.isdir(rootpath) and (
        os.path.isdir(os.path.join(rootpath, '.git')) or os.path.isfile(os.path.join(rootpath, '.git', 'config')))):
      raise vclib.ReposNotFound(name)

    # Initialize some stuff.
    self.rootpath = rootpath
    self.name = name
    self.auth = authorizer
    self.diff_cmd = utilities.diff or 'diff'

    # See if this repository is even viewable, authz-wise.
    if not vclib.check_root_access(self):
      raise vclib.ReposNotFound(name)

  def open(self):
    # Open the repository and init some other variables.
    self.repo = Repo(self.rootpath)

    # See if a universal read access determination can be made.
    if self.auth and self.auth.check_universal_access(self.name) == 1:
      self.auth = None

  def rootname(self):
    return self.name

  def rootpath(self):
    return self.rootpath

  def roottype(self):
    return vclib.GIT

  def authorizer(self):
    return self.auth

  def itemtype(self, path_parts, rev):
    c, f, t = self._obj(path_parts, rev) # does authz-check
    return t

  def openfile(self, path_parts, rev, options):
    c, f, t = self._obj(path_parts, rev) # does authz-check
    return OStreamWrapper(f.data_stream), c.hexsha

  def listdir(self, path_parts, rev, options):
    c, f, t = self._obj(path_parts, rev) # does authz-check
    if f.type != 'tree':
      raise vclib.Error("Path '%s' is not a directory." % self._getpath(path))
    entries = []
    path = self._getpath(path_parts)
    if path:
      path = path+'/'
    for i in f:
      if i.type == 'tree':
        kind = vclib.DIR
      else:
        kind = vclib.FILE
      if vclib.check_path_access(self, path_parts + [ i.name ], kind, rev):
        e = vclib.DirEntry(i.name, kind)
        # <dirlogs>
        h = self.repo.iter_commits(c.hexsha, path+i.name).next()
        e.rev = h.binsha
        e.date = h.authored_date
        e.author = h.author
        e.log = h.message
        e.lockinfo = None
        # </dirlogs>
        entries.append(e)
    return entries

  def dirlogs(self, path_parts, rev, entries, options):
    pass

  def itemlog(self, path_parts, rev, sortby, first, limit, options):
    # FIXME sortby has no effect
    path = self._getpath(path_parts)
    path_type = self.itemtype(path_parts, rev)  # does auth-check
    c = self.repo.iter_commits(rev, path)
    # FIXME (???) Include c.name_rev into data? (it's the symbolic commit name based on closest reference)
    revs = []
    i = 0
    for c in self.repo.iter_commits(rev, path):
      if i >= first:
        if path_type == vclib.FILE:
          f = c.tree
          for p in path_parts:
            f = f[p]
          s = f.size
        else:
          s = 0
        revs.append(vclib.Revision(c.authored_date, c.hexsha, c.authored_date, c.author, c.authored_date, c.message, s, None))
      i = i+1
      if i >= first+limit:
        break
    return revs

  def itemprops(self, path_parts, rev):
    c, f, t = self._obj(path_parts, rev) # does authz-check
    return { 'filemode': "0%o" % f.mode }

  def annotate(self, path_parts, rev, include_text=False):
    path = self._getpath(path_parts)
    path_type = self.itemtype(path_parts, rev)  # does auth-check
    if path_type != vclib.FILE:
      raise vclib.Error("Path '%s' is not a file." % path)
    blame = self.repo.blame(rev, path)
    source = []
    line_num = 1
    youngest_rev = None
    for (commit, lines) in blame:
      if youngest_rev is None or youngest_rev.authored_date > commit.authored_date:
        youngest_rev = commit
      for line in lines:
        # prev_rev=None
        source.append(vclib.Annotation(line, line_num, commit.hexsha, None, commit.author, commit.authored_date))
        line_num = line_num+1
    return source, youngest_rev.hexsha

  def revinfo(self, rev):
    commit = self.repo.commit(rev)
    changes = []
    # FIXME we only pick the first parent commit ;-(
    base_rev = commit.parents[0].hexsha
    for i in commit.stats.files:
      p = _path_parts(i)
      t = self.itemtype(p, rev) # does auth-check
      # FIXME handle renames... 4th parameter is base path
      # FIXME handle filemode change (last param is 'props changed?')
      changes.append(ChangedPath(
        p, commit.hexsha, t, p, base_rev, action, False, commit.stats.files[i].lines > 0, False
      ))
    return (commit.authored_date, commit.author, commit.message, changes, {})

  def rawdiff(self, path_parts1, rev1, path_parts2, rev2, type, options={}):
    if path_parts1:
      c1, f1, t = self._obj(path_parts1, rev1) # does authz-check
      if t != vclib.FILE:
        raise vclib.Error("Path '%s' is not a file." % self._getpath(path_parts1))
    else:
      f1 = None
    if path_parts2:
      c2, f2, t = self._obj(path_parts2, rev2) # does authz-check
      if t != vclib.FILE:
        raise vclib.Error("Path '%s' is not a file." % self._getpath(path_parts2))
    else:
      f2 = None
    args = vclib._diff_args(type, options)
    if p1:
      temp1 = temp_checkout(f1)
      info1 = p1, c1.authored_date, r1
    else:
      temp1 = '/dev/null'
      info1 = '/dev/null', '', rev1
    if p2:
      temp2 = temp_checkout(f2)
      info2 = p2, c2.authored_date, r2
    else:
      temp2 = '/dev/null'
      info2 = '/dev/null', '', rev1
    return vclib._diff_fp(temp1, temp2, info1, info2, self.diff_cmd, args)

  def isexecutable(self, path_parts, rev):
    c, f, t = self._obj(path_parts, rev) # does authz-check
    if f.mode & 0777:
      return True
    return False

  def filesize(self, path_parts, rev):
    c, f, t = self._obj(path_parts, rev) # does authz-check
    if f.type != 'blob':
      raise vclib.Error("Path '%s' is not a file." % path)
    return f.size

  ##--- helpers ---##

  # Returns (commit, object, type)
  def _obj(self, path_parts, rev):
    c = self.repo.commit(rev)
    f = c.tree
    if path_parts:
      for i in path_parts[:-1]:
        if not f or f.type != 'tree':
          raise vclib.ItemNotFound(path_parts)
        f = f[i]
      f = f[path_parts[-1]]
      if not f:
        raise vclib.ItemNotFound(path_parts)
    if f.type == 'blob':
      t = vclib.FILE
    else:
      t = vclib.DIR
    if not vclib.check_path_access(self, path_parts, t, rev):
      raise vclib.ItemNotFound(t)
    return c, f, t

  def _getpath(self, path_parts):
    return '/'.join(path_parts)

  ##--- custom ---##

  def _getrev(self, rev):
    rev = self.repo.commit(rev)
    return rev.hexsha

  def get_location(self, path, rev, old_rev):
    old = self.repo.commit(old_rev)
    diff = old.diff(rev)
    old_path = None
    for i in diff:
      if i.b_blob and i.b_blob.path == path:
        old_path = i.a_blob.path
      elif i.rename_to == path:
        old_path = i.rename_from
    if old_path is None:
      return path
    return _cleanup_path(old_path)

  def get_symlink_target(self, path_parts, rev):
    """Return the target of the symbolic link versioned at PATH_PARTS
    in REV, or None if that object is not a symlink."""
    c, f, t = self._obj(path_parts, rev) # does authz-check
    if f.type != 'blob':
      raise vclib.Error("Path '%s' is not a file." % path)
    if f.mode & 20000:
      return f.data_stream.read()
    return None
