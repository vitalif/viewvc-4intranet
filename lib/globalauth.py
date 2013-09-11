# -*-python-*-
# -----------------------------------------------------------------------
# Simple Global Authentication client for ViewVC
# License: GPLv2+
# Author: Vitaliy Filippov
# -----------------------------------------------------------------------
#
# USAGE:
#
# import globalauth
# c = globalauth.GlobalAuthClient()
# c.auth(server)
# user_name = c.user_name
# user_url = c.user_url
#
# auth() will call sys.exit() when it needs to stop request processing
#
# -----------------------------------------------------------------------

import os
import re
import sys
import struct
import cgi
import binascii
import time
import datetime
import urllib
import urllib2
import anyjson
import random
import Cookie

import ga_config

class FileCache:

  def __init__(self, dir):
    self.dir = dir
    if not os.path.isdir(dir):
      os.mkdir(dir)

  def fn(self, key):
    key = re.sub('([^a-zA-Z0-9_\-]+)', lambda x: binascii.hexlify(x.group(1)), key)
    return self.dir+'/'+key

  def clean(self):
    t = time.time()
    for fn in os.listdir(self.dir):
      if t > os.stat(self.dir+'/'+fn).st_mtime:
        os.unlink(self.dir+'/'+fn)

  def set(self, key, value, expire = 86400):
    fn = self.fn(key)
    try:
      f = open(fn,'w')
      if not expire:
        expire = 86400
      expire = time.time()+expire
      f.write(value)
      f.close()
      os.chmod(fn, 0600)
      os.utime(fn, (expire, expire))
    except:
      raise
    return 1

  def get(self, key):
    fn = self.fn(key)
    try:
      f = open(fn,'r')
      value = f.read()
      f.close()
      if time.time() > os.stat(fn).st_mtime:
        os.unlink(fn)
        return ''
      return value
    except:
      pass
    return ''

  def delete(self, key):
    fn = self.fn(key)
    try:
      os.unlink(fn)
    except:
      pass

class GlobalAuthClient:

  wd = { 0 : 'Mon', 1 : 'Tue', 2 : 'Wed', 3 : 'Thu', 4 : 'Fri', 5 : 'Sat', 6 : 'Sun' }
  ms = { 1 : 'Jan', 2 : 'Feb', 3 : 'Mar', 4 : 'Apr', 5 : 'May', 6 : 'Jun', 7 : 'Jul', 8 : 'Aug', 9 : 'Sep', 10 : 'Oct', 11 : 'Nov', 12 : 'Dec' }

  def __init__(self, server):

    self.server = server
    self.v = {}
    for name, values in server.params().items():
      self.v[name] = values[0]
    fs = server.FieldStorage()
    for name in fs:
      self.v[name] = fs[name].value

    self.cookies = Cookie.SimpleCookie()
    # '' default value is needed here - else we die here under WSGI without any exception O_o
    self.cookies.load(self.server.getenv('HTTP_COOKIE', ''))
    self.user_name = ''
    self.user_url = ''

    if not ga_config.gac.get('globalauth_server', '') and not ga_config.gac.get('fof_sudo_server', ''):
      raise Exception('ga_config.gac must contain at least globalauth_server="URL" or fof_sudo_server="URL"')

    self.gac = {
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
      'gc_probability'    : 20,
    }

    for i in self.gac:
      if ga_config.gac.get(i, None) is not None:
        self.gac[i] = ga_config.gac[i]

    self.cache = FileCache(self.gac['cache_dir'])

  def auth(self):
    if self.gac['fof_sudo_server']:
      self.auth_fof_sudo()
    if not self.user_name and self.gac['globalauth_server']:
      self.auth_ga()

  def auth_ga(self):
    i = random.randint(1, self.gac['gc_probability'])
    if i == 1:
      self.cache.clean()
    r_id = self.cookies.get(self.gac['cookie_name'], '')
    if r_id:
      r_id = r_id.value
    ga_id = self.v.get('ga_id', '')
    if self.v.get('ga_client', ''):
      self.ga_client(r_id, ga_id)
      return
    r_data = ''
    if r_id == 'nologin':
      r_data = 'nologin'
    elif r_id != '':
      r_data = self.cache.get('D'+r_id)
      if r_data != 'nologin':
        try: r_data = anyjson.deserialize(r_data)
        except: r_data = ''
    is_browser = re.match('opera|firefox|chrome|safari', self.server.getenv('HTTP_USER_AGENT'), re.I)
    if not r_data and (is_browser or self.gac['ga_always_require']) or self.v.get('ga_require', None):
      self.ga_begin()
    elif r_data and r_data != 'nologin':
      self.set_user(r_data)

  def ga_client(self, r_id, ga_id):
    ga_key = self.v.get('ga_key', '')
    if ga_key and ga_key == self.cache.get('K'+ga_id):
      # Server-to-server request
      self.cache.delete('K'+ga_id)
      data = ''
      if self.v.get('ga_nologin','') != '':
        data = 'nologin'
      else:
        try: data = anyjson.deserialize(self.v.get('ga_data',''))
        except: raise
      if data != '':
        if data != 'nologin':
          data = anyjson.serialize(data)
        self.cache.set('D'+ga_id, data)
        self.server.header('text/plain')
        self.server.write('1')
        sys.exit()
    elif ga_key == '' and r_id != ga_id:
      # User redirect with different key
      d = self.cache.get('D'+ga_id)
      if d != 'nologin' and d != '':
        try: d = anyjson.deserialize(d)
        except: d = ''
      if d != '':
        self.setcookie(ga_id)
        self.redirect(self.clean_uri())
    self.server.header('text/plain', status=404)
    self.server.write('GlobalAuth key doesn\'t match')
    sys.exit()

  def ga_begin(self):
    ga_id = binascii.hexlify(os.urandom(16))
    ga_key = binascii.hexlify(os.urandom(16))
    url = self.add_param(self.gac['globalauth_server'], '')
    try:
      resp = urllib2.urlopen(url+'ga_id='+urllib2.quote(ga_id)+'&ga_key='+urllib2.quote(ga_key))
      resp.read()
      if resp.code != 200:
        raise Exception(resp)
    except:
      self.setcookie('nologin')
      self.redirect(self.clean_uri())
    return_uri = 'http://'+self.server.getenv('HTTP_HOST')+self.server.getenv('REQUEST_URI')
    return_uri = self.add_param(return_uri, 'ga_client=1')
    self.cache.set('K'+ga_id, ga_key)
    url = url+'ga_id='+urllib2.quote(ga_id)+'&ga_url='+urllib2.quote(return_uri)
    if self.v.get('ga_require', '') == '' and not self.gac['ga_always_require']:
      url = url+'&ga_check=1'
    self.redirect(url)

  def add_param(self, url, param):
    if url.find('?') != -1:
      url = url+'&'
    else:
      url = url+'?'
    return url+param

  def auth_fof_sudo(self):
    sudo_id = self.cookies.get(self.gac['fof_sudo_cookie'], '')
    if sudo_id:
      sudo_id = sudo_id.value
    if sudo_id != '':
      url = self.gac['fof_sudo_server']
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
        self.set_user(d)
      except:
        pass

  def log(self, s):
    sys.stderr.write(s+"\n")
    sys.stderr.flush()

  def redirect(self, url):
    self.server.addheader('Location', url)
    self.server.header(status='302 Moved Temporarily')
    self.server.write('This document is located <a href="%s">here</a>.' % url)
    sys.exit()

  def setcookie(self, value):
    dom = self.gac['cookie_domain']
    if not dom:
      dom = self.server.getenv('HTTP_HOST')
    exp = ''
    if self.gac['cookie_expire'] > 0:
      tm = int(time.time()+self.gac['cookie_expire'])
      tm = datetime.datetime.utcfromtimestamp(tm)
      tm = "%s, %02d-%s-%04d %02d:%02d:%02d GMT" % (self.wd[tm.weekday()], tm.day, self.ms[tm.month], tm.year, tm.hour, tm.minute, tm.second)
      exp = '; expires='+tm
    self.server.addheader('Set-Cookie', "%s=%s; path=%s; domain=%s%s" % (self.gac['cookie_name'], value, self.gac['cookie_path'], dom, exp))

  def clean_uri(self):
    uriargs = self.v.copy()
    for i in [ 'ga_id', 'ga_res', 'ga_key', 'ga_client', 'ga_nologin', 'ga_require' ]:
      uriargs.pop(i, None)
    uri = self.server.getenv('REQUEST_URI')
    p = uri.find('?')
    if p != -1:
      uri = uri[0:p]
    uri = 'http://'+self.server.getenv('HTTP_HOST')+uri+'?'+urllib.urlencode(uriargs)
    return uri

  def set_user(self, r_data):
    r_email = r_data.get('user_email', '').encode('utf-8')
    r_url = r_data.get('user_url', '').encode('utf-8')
    if self.gac['cut_email_at']:
      p = r_email.find('@')
      if p != -1:
        r_email = r_email[0:p]
    self.user_name = r_email
    self.user_url = r_url
