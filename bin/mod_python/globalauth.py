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

cookie_name = 'simple_global_auth'
cookie_expire = 86400*7
cookie_path = '/viewvc'
cookie_domain = 'localhost'
globalauth_server = 'http://bugs3.office.custis.ru/globalauth.cgi'
cache_dir = os.path.abspath(os.path.dirname(__file__))+'/cache'
cut_email_at = 1

def cacheset(key, value, expire = 86400):
  global cache_dir
  try:
    f = open(cache_dir+'/'+key,'w')
    if not expire:
      expire = 86400
    expire = time.time()+expire
    f.write(str(expire)+"\n")
    f.write(value)
    f.close()
  except:
    raise
  return 1

def cacheget(key):
  global cache_dir
  try:
    f = open(cache_dir+'/'+key,'r')
    expire = f.readline()
    value = f.read()
    f.close()
    if time.time() > float(expire):
      os.unlink(cache_dir+'/'+key)
      return ''
    return value
  except:
    pass
  return ''

def cachedel(key):
  global cache_dir
  try:
    os.unlink(cache_dir+'/'+key)
  except:
    pass

wd = { 0 : 'Mon', 1 : 'Tue', 2 : 'Wed', 3 : 'Thu', 4 : 'Fri', 5 : 'Sat', 6 : 'Sun' }
ms = { 1 : 'Jan', 2 : 'Feb', 3 : 'Mar', 4 : 'Apr', 5 : 'May', 6 : 'Jun', 7 : 'Jul', 8 : 'Aug', 9 : 'Sep', 10 : 'Oct', 11 : 'Nov', 12 : 'Dec' }

def setcookie(req, value):
  global cookie_name, cookie_path, cookie_domain, cookie_expire, wd, ms
  exp = ''
  if cookie_expire > 0:
    tm = int(time.time()+cookie_expire)
    tm = datetime.datetime.utcfromtimestamp(tm)
    tm = "%s, %02d-%s-%04d %02d:%02d:%02d GMT" % (wd[tm.weekday()], tm.day, ms[tm.month], tm.year, tm.hour, tm.minute, tm.second);
    exp = '; expires='+tm
  req.headers_out.add('Set-Cookie', "%s=%s; path=%s; domain=%s%s" % (cookie_name, value, cookie_path, cookie_domain, exp))

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

def handler(req):
  global globalauth_server, cut_email_at
  os.environ['REMOTE_USER'] = ''
  req.subprocess_env['REMOTE_USER'] = ''
  set = 0
  jar = Cookie.get_cookies(req)
  r_id = jar.get(cookie_name, '')
  v = request_vars(req)
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
  if r_id:
    r_id = r_id.value
  if r_id == 'nologin':
    r_data = 'nologin'
  else:
    r_data = cacheget('D'+r_id)
    if r_data != 'nologin':
      try: r_data = anyjson.deserialize(r_data)
      except: r_data = ''
  if v.get('ga_client', '') == '' and (not r_data and re.match('opera|firefox|chrome|safari', req.headers_in.get('User-Agent', ''), re.I)
     or v.get('ga_require', '') != ''):
    ga_id = binascii.hexlify(os.urandom(16))
    ga_key = binascii.hexlify(os.urandom(16))
    url = globalauth_server
    if url.find('?') != -1:
      url = url+'&'
    else:
      url = url+'?'
    try:
      resp = urllib2.urlopen(url+'ga_id='+ga_id+'&ga_key='+ga_key)
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
    url = url+'ga_id='+ga_id+'&ga_url='+urllib2.quote(return_uri)
    if v.get('ga_require', '') == '':
      url = url+'&ga_check=1'
    util.redirect(req, url)
    raise apache.SERVER_RETURN, apache.HTTP_OK
  elif r_data and r_data != 'nologin':
    r_email = r_data.get('user_email', '').encode('utf-8')
    r_url = r_data.get('user_url', '').encode('utf-8')
    if cut_email_at:
      p = r_email.find('@')
      if p != -1:
        r_email = r_email[0:p]
    os.environ['REMOTE_USER'] = r_email
    req.subprocess_env['REMOTE_USER'] = r_email
    os.environ['user_url'] = r_url
    req.subprocess_env['user_url'] = r_url
  return apache.OK
