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
import grp
import re

class ViewVCAuthorizer(vcauth.GenericViewVCAuthorizer):
  """A simple authorizer checking system group membership for every
     repository and every user."""

  def __init__(self, username, params={}):
    self.username = username
    self.params = params
    self.cfg = params['__config']
    self.fmt = params.get('group_name_format', 'svn.%s.ro')
    self.cached = {}
    self.grp = {}
    self.byroot = {}
    byr = params.get('by_root', '')
    for i in byr.split(','):
      if i.find(':') < 0:
        continue
      (root, auth) = i.split(':', 2)
      self.byroot[root.strip()] = auth.strip()

  def check_root_access(self, rootname):
    r = self.cached.get(rootname, None)
    if r is not None:
      return r
    try:
      grent = self.grp.get(rootname, None)
      if grent is None:
        grn = self.byroot.get(rootname, self.fmt)
	if grn.find('%s') >= 0:
	  grn = grn % re.sub('[^\w\.\-]+', '', rootname)
	grent = grp.getgrnam(grn)
        self.grp[rootname] = grent
      if grent.gr_mem and len(grent.gr_mem) and self.username in grent.gr_mem:
        r = 1
    except:
      r = 0
    self.cached[rootname] = r
    return r

  def check_path_access(self, rootname, path_parts, pathtype, rev=None):
    return self.check_root_access(rootname)
