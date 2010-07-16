# -*-python-*-
# PythonHeaderParserHandler receiving Simple Global Authentication
# -----------------------------------------------------------------------

from mod_python import apache, Cookie, util

import os
import re
import sys
import struct
import cgi
import binascii
import time
import datetime
import urllib2
import anyjson

import ga_config

if not ga_config.gac.get('globalauth_server','') and not ga_config.gac.get('fof_sudo_server',''):
  raise Exception('ga_config.gac must contain at least globalauth_server="URL" or fof_sudo_server="URL"')

gac = {
  'cookie_name'       : 'simple_global_auth',
  'cookie_expire'     : 86400*7,
  'cookie_path'       : '/',
  'cookie_domain'     : '',
  'globalauth_server' : '',
  'cache_dir'         : os.path.abspath(os.path.dirname(__file__))+'/cache',
  'cut_email_at'      : 0,
  'ga_always_require' : 0,
  'fof_sudo_server'   : '',
  'fof_sudo_cookie'   : 'fof_sudo_id',
}

for i in gac:
  if ga_config.gac.get(i, None) is not None:
    gac[i] = ga_config.gac[i]

def cachefn(key):
  global gac
  key = re.sub('([^a-z0-9_\-]+)', lambda x: binascii.hexlify(x.group(1)), key)
  return gac['cache_dir']+'/'+key

def cacheset(key, value, expire = 86400):
  fn = cachefn(key)
  try:
    f = open(fn,'w')
    if not expire:
      expire = 86400
    expire = time.time()+expire
    f.write(str(expire)+"\n")
    f.write(value)
    f.close()
    os.chmod(fn,0600)
  except:
    raise
  return 1

def cacheget(key):
  fn = cachefn(key)
  try:
    f = open(fn,'r')
    expire = f.readline()
    value = f.read()
    f.close()
    if time.time() > float(expire):
      os.unlink(fn)
      return ''
    return value
  except:
    pass
  return ''

def cachedel(key):
  fn = cachefn(key)
  try:
    os.unlink(fn)
  except:
    pass

wd = { 0 : 'Mon', 1 : 'Tue', 2 : 'Wed', 3 : 'Thu', 4 : 'Fri', 5 : 'Sat', 6 : 'Sun' }
ms = { 1 : 'Jan', 2 : 'Feb', 3 : 'Mar', 4 : 'Apr', 5 : 'May', 6 : 'Jun', 7 : 'Jul', 8 : 'Aug', 9 : 'Sep', 10 : 'Oct', 11 : 'Nov', 12 : 'Dec' }

def setcookie(req, value):
  global gac, wd, ms
  exp = ''
  dom = gac['cookie_domain']
  if not dom:
    dom = req.hostname
  if gac['cookie_expire'] > 0:
    tm = int(time.time()+gac['cookie_expire'])
    tm = datetime.datetime.utcfromtimestamp(tm)
    tm = "%s, %02d-%s-%04d %02d:%02d:%02d GMT" % (wd[tm.weekday()], tm.day, ms[tm.month], tm.year, tm.hour, tm.minute, tm.second);
    exp = '; expires='+tm
  req.headers_out.add('Set-Cookie', "%s=%s; path=%s; domain=%s%s" % (gac['cookie_name'], value, gac['cookie_path'], dom, exp))

def http_build_query(params, topkey = ''):
  from urllib import quote
  if len(params) == 0:
    return ""
  result = ""
  if type (params) is dict:
    for key in params.keys():
      newkey = quote (key)
      if topkey != '':
        newkey = topkey + quote('[' + key + ']')
      if type(params[key]) is dict:
        result += http_build_query (params[key], newkey)
      elif type(params[key]) is list:
        i = 0
        for val in params[key]:
          result += newkey + quote('[' + str(i) + ']') + "=" + quote(str(val)) + "&"
          i = i + 1
      elif type(params[key]) is bool:
        result += newkey + "=" + quote (str(int(params[key]))) + "&"
      else:
        result += newkey + "=" + quote (str(params[key])) + "&"
  if (result) and (topkey == '') and (result[-1] == '&'):
    result = result[:-1]
  return result

def request_vars(req):
  v = {}
  if req.args:
    v.update(util.parse_qs(req.args))
  l = req.headers_in.get('Content-Length')
  if l:
    l = int(l)
  if l and l > 0:
    if req.headers_in.get('Content-Type').lower().find('multipart') >= 0:
      v.update(cgi.parse_multipart(req, req.headers_in))
    else:
      c = ''
      while len(c) < l:
        c = c + req.read(l-len(c))
      v.update(util.parse_qs(c))
  #log("--REQUEST--")
  for i in v:
    if v[i].__class__.__name__ == 'list':
      v[i] = v[i][0]
    #log("REQUEST: "+i+"="+v[i])
  return v

def log(s):
  sys.stderr.write(s+"\n")
  sys.stderr.flush()

def keydel(d, key):
  try: del d[key]
  except: pass

def clean_uri(v, req):
  uriargs = v.copy()
  keydel(uriargs, 'ga_id')
  keydel(uriargs, 'ga_res')
  keydel(uriargs, 'ga_key')
  keydel(uriargs, 'ga_client')
  keydel(uriargs, 'ga_nologin')
  keydel(uriargs, 'ga_require')
  uri = 'http://'+req.hostname+req.uri+'?'+http_build_query(uriargs)
  return uri

def set_env_user(req, r_data):
  r_email = r_data.get('user_email', '').encode('utf-8')
  r_url = r_data.get('user_url', '').encode('utf-8')
  if gac['cut_email_at']:
    p = r_email.find('@')
    if p != -1:
      r_email = r_email[0:p]
  os.environ['REMOTE_USER'] = r_email
  req.subprocess_env['REMOTE_USER'] = r_email
  os.environ['user_url'] = r_url
  req.subprocess_env['user_url'] = r_url

def globalauth_handler(req, jar, v):
  global gac
  r_id = jar.get(gac['cookie_name'], '')
  if r_id:
    r_id = r_id.value
  ga_id = v.get('ga_id', '')
  if ga_id!='' and v.get('ga_client','')!='':
    ga_key = v.get('ga_key','')
    if ga_key != '' and ga_key == cacheget('K'+ga_id):
      cachedel('K'+ga_id)
      data = ''
      if v.get('ga_nologin','') != '':
        data = 'nologin'
      else:
        try: data = anyjson.deserialize(v.get('ga_data',''))
        except: raise
      if data != '':
        if data != 'nologin':
          data = anyjson.serialize(data)
        cacheset('D'+ga_id, data)
        raise apache.SERVER_RETURN, apache.HTTP_OK
      raise apache.SERVER_RETURN, apache.HTTP_NOT_FOUND
    elif ga_key == '' and r_id != ga_id:
      d = cacheget('D'+ga_id)
      if d != 'nologin' and d != '':
        try: d = anyjson.deserialize(d)
        except: d = ''
      if d != '':
        setcookie(req, ga_id)
        util.redirect(req, clean_uri(v, req))
        raise apache.SERVER_RETURN, apache.HTTP_OK
      raise apache.SERVER_RETURN, apache.HTTP_NOT_FOUND
  r_data = ''
  if r_id == 'nologin':
    r_data = 'nologin'
  elif r_id != '':
    r_data = cacheget('D'+r_id)
    if r_data != 'nologin':
      try: r_data = anyjson.deserialize(r_data)
      except: r_data = ''
  if v.get('ga_client', '') == '' and (not r_data and (re.match('opera|firefox|chrome|safari', req.headers_in.get('User-Agent', ''), re.I) or gac['ga_always_require'])
     or v.get('ga_require', '') != ''):
    ga_id = binascii.hexlify(os.urandom(16))
    ga_key = binascii.hexlify(os.urandom(16))
    url = gac['globalauth_server']
    if url.find('?') != -1:
      url = url+'&'
    else:
      url = url+'?'
    try:
      resp = urllib2.urlopen(url+'ga_id='+urllib2.quote(ga_id)+'&ga_key='+urllib2.quote(ga_key))
      resp.read()
      if resp.code != 200:
        raise Exception(resp)
    except:
      setcookie(req, 'nologin')
      util.redirect(req, clean_uri(v, req))
      raise apache.SERVER_RETURN, apache.HTTP_OK
    return_uri = 'http://'+req.hostname+req.uri+'?ga_client=1';
    if req.args:
      return_uri = return_uri+'&'+req.args
    cacheset('K'+ga_id, ga_key)
    url = url+'ga_id='+urllib2.quote(ga_id)+'&ga_url='+urllib2.quote(return_uri)
    if v.get('ga_require', '') == '' and not gac['ga_always_require']:
      url = url+'&ga_check=1'
    util.redirect(req, url)
    raise apache.SERVER_RETURN, apache.HTTP_OK
  elif r_data and r_data != 'nologin':
    set_env_user(req, r_data)

def fof_sudo_handler(req, jar, v):
  global gac
  sudo_id = jar.get(gac['fof_sudo_cookie'], '')
  if sudo_id:
    sudo_id = sudo_id.value
  if sudo_id != '':
    url = gac['fof_sudo_server']
    if url.find('?') != -1:
      url = url+'&'
    else:
      url = url+'?'
    try:
      resp = urllib2.urlopen(url+'id='+urllib2.quote(sudo_id))
      d = resp.read()
      if resp.code != 200:
        raise Exception(resp)
      d = anyjson.deserialize(d)
      set_env_user(req, d)
    except:
      pass

def handler(req):
  global gac
  os.environ['REMOTE_USER'] = ''
  req.subprocess_env['REMOTE_USER'] = ''
  os.environ['user_url'] = ''
  req.subprocess_env['user_url'] = ''
  jar = Cookie.get_cookies(req)
  v = request_vars(req)
  if gac['fof_sudo_server'] != '':
    fof_sudo_handler(req, jar, v)
  if os.environ['REMOTE_USER'] == '' and gac['globalauth_server'] != '':
    globalauth_handler(req, jar, v)
  return apache.OK
