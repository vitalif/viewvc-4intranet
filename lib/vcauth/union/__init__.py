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

class ViewVCAuthorizer(vcauth.GenericViewVCAuthorizer):
  """A 'union' authorizer: it makes possible to use one authorizer for
     one root and other authorizer for other roots."""

  def __init__(self, username, params={}):
    self.username = username
    self.params = params
    self.cfg = params['__config']
    self.default = params.get('default', '')
    self.byroot = {}
    self.authz = {}
    union = params.get('union', '')
    for i in union.split(','):
      if i.find(':') < 0:
        continue
      (root, auth) = i.split(':', 2)
      self.byroot[root.strip()] = auth.strip()

  def create_authz(self, rootname):
    aname = self.byroot.get(rootname, '') or self.default
    if not aname:
      return None
    if self.authz.get(aname, None):
      return self.authz[aname]
    import imp
    fp = None
    try:
      try:
        fp, path, desc = imp.find_module(aname, vcauth.__path__)
        my_auth = imp.load_module('viewvc', fp, path, desc)
      except ImportError:
        raise debug.ViewVCException(
          'Invalid authorizer (%s) specified for root "%s"' \
          % (self.cfg.options.authorizer, rootname),
          '500 Internal Server Error')
    finally:
      if fp:
        fp.close()
    params = self.cfg.get_authorizer_params(aname, rootname)
    self.authz[aname] = my_auth.ViewVCAuthorizer(self.username, params)
    return self.authz[aname]

  def check_root_access(self, rootname):
    a = self.create_authz(rootname)
    if a:
      return a.check_root_access(rootname)
    return None

  def check_path_access(self, rootname, path_parts, pathtype, rev=None):
    a = self.create_authz(rootname)
    if a:
      return a.check_path_access(rootname, path_parts, pathtype, rev)
    return None
