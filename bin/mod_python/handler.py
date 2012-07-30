# -*-python-*-
#
# Copyright (C) 1999-2006 The ViewCVS Group. All Rights Reserved.
#
# By using this file, you agree to the terms and conditions set forth in
# the LICENSE.html file which can be found at the top level of the ViewVC
# distribution or at http://viewvc.org/license-1.html.
#
# For more information, visit http://viewvc.org/
#
# -----------------------------------------------------------------------
#
# Mod_Python handler based on mod_python.publisher
#
# -----------------------------------------------------------------------

from mod_python import apache
import os.path

def handler(req):
  path, module_name = os.path.split(req.filename)
  module_name, module_ext = os.path.splitext(module_name)
  # Let it be 500 Internal Server Error in case of import error
  module = apache.import_module(module_name, path=[path])

  req.add_common_vars()
  module.index(req)

  return apache.OK
