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
from xml.dom.ext.reader import Sax2
from xml import xpath

class ViewVCAuthorizer(vcauth.GenericViewVCAuthorizer):
  """An authorizer making use of CVSnt access control lists (which are in form
     of XML files in CVS/ subdirectories in the repository)."""

  def __init__(self, username, params={}):
    self.username = username
    self.params = params
    self.cfg = params['__config']
    self.default = params.get('default', 0)
    self.cached = {}
    self.xmlcache = {}

  def checkr(self, element, paths):
    r = None
    for p in paths:
      nodes = xpath.Evaluate(p, element)
      if nodes and len(nodes):
        for c in nodes:
          if c.nodeName == 'read' and r is None:
            r = True
            if c.attributes and len(c.attributes):
              for a in c.attributes:
                if a.nodeName == 'deny':
                  r = not a.value
      if r is not None:
        break
    return r

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
          fp = open(xml, 'rb')
          doc = Sax2.Reader().fromStream(fp)
          fp.close()
	  self.xmlcache[xml] = doc
        if filename:
          r = self.checkr(doc.documentElement, [
            '/fileattr/file[@name=\'%s\']/acl[@user=\'%s\' and not(@branch)]/read' % (filename, self.username),
            '/fileattr/file[@name=\'%s\']/acl[not(@user) and not(@branch)]/read' % filename,
            '/fileattr/directory/acl[@user=\'%s\' and not(@branch)]/read' % self.username,
            '/fileattr/directory/acl[not(@user) and not(@branch)]/read'
          ] )
        else:
          r = self.checkr(doc.documentElement, [
            '/fileattr/directory/acl[@user=\'%s\' and not(@branch)]/read' % self.username,
            '/fileattr/directory/acl[not(@user) and not(@branch)]/read'
          ] )
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
