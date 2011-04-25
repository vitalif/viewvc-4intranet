# -*-python-*-
#
# Copyright (C) 2009 Vitaliy Filippov.
#
# By using this file, you agree to the terms and conditions set forth in
# the LICENSE.html file which can be found at the top level of the ViewVC
# distribution or at http://viewvc.org/license-1.html.
#
# For more information, visit http://viewvc.org/
#
# -----------------------------------------------------------------------

import vcauth
import vclib
import string
from xml.dom.minidom import parse

class ViewVCAuthorizer(vcauth.GenericViewVCAuthorizer):
  """An authorizer which uses CVSnt access control lists (which are in form
     of XML files in CVS/ subdirectories in the repository)."""

  def __init__(self, username, params={}):
    self.username = username
    self.params = params
    self.cfg = params['__config']
    self.default = params.get('default', 0)
    self.cached = {}
    self.xmlcache = {}

  def dom_rights(self, doc, rightname, filename, username):
    result = None
    if filename:
      for node in doc.getElementsByTagName('file'):
        if node.getAttribute('name') == filename:
          for acl in node.getElementsByTagName('acl'):
            if not acl.getAttribute('branch'):
              u = acl.getAttribute('user')
              if result is None and (not u or u == 'anonymous') or u == username:
                for r in acl.getElementsByTag(rightname):
                  result = not r.getAttribute('deny')
          break
    if result is None:
      for node in doc.getElementsByTagName('directory'):
        for acl in node.getElementsByTagName('acl'):
          if not acl.getAttribute('branch'):
            u = acl.getAttribute('user')
            if result is None and (not u or u == 'anonymous') or u == username:
              for r in acl.getElementsByTag(rightname):
                result = not r.getAttribute('deny')
    return result

  def check(self, rootname, path_parts, filename):
    d = self.cfg.general.cvs_roots.get(rootname,None)
    if not d:
      return self.default
    i = len(path_parts)
    r = None
    while i >= 0:
      try:
        xml = d
        if len(path_parts):
          xml = xml + '/' + string.join(path_parts, '/')
        xml = xml + '/CVS/fileattr.xml'
        if self.cached.get(xml, None) is not None:
          return self.cached.get(xml, None)
        doc = self.xmlcache.get(xml, None)
        if doc is None:
          doc = parse(xml)
          self.xmlcache[xml] = doc
        r = self.dom_rights(doc, 'read', filename, self.username)
        if r is not None:
          self.cached[xml] = r
          return r
        raise Exception(None)
      except:
        if len(path_parts) > 0:
          path_parts = path_parts[:-1]
        filename = ''
        i = i-1
    return self.default

  def check_root_access(self, rootname):
    return self.check(rootname, [], '')

  def check_path_access(self, rootname, path_parts, pathtype, rev=None):
    if not path_parts:
      return 1
    if pathtype == vclib.DIR:
      return self.check(rootname, path_parts, '')
    f = path_parts[-1]
    path_parts = path_parts[:-1]
    return self.check(rootname, path_parts, f)
