#!/usr/bin/python

import mimetypes
import magic

have_chardet = 0
try:
    import chardet
    have_chardet = 1
except: pass

class ContentMagic:

    def __init__(self, encodings):
        self.encodings = encodings.split(':')
        self.mime_magic = None
        self.errors = []
        # Try to load magic
        self.mime_magic = magic.open(magic.MAGIC_MIME_TYPE)
        self.mime_magic.load()

    # returns MIME type
    def guess_mime(self, mime, filename, tempfile):
        if mime == 'application/octet-stream':
            mime = ''
        if not mime and filename:
            mime = mimetypes.guess_type(filename)[0]
        if not mime and tempfile and self.mime_magic:
            if type(tempfile) == type(''):
                mime = self.mime_magic.file(tempfile)
            else:
                c = tempfile.read(4096)
                mime = self.mime_magic.buffer(c)
        return mime

    # returns (utf8_content, charset)
    def guess_charset(self, content):
        # Try UTF-8
        charset = 'utf-8'
        try: content = content.decode('utf-8')
        except: charset = None
        if charset is None and have_chardet and len(content) > 64:
            # Try to guess with chardet
            try:
                # Only detect on first 256KB if content is longer
                if len(content) > 256*1024:
                    charset = chardet.detect(content[0:256*1024])
                else:
                    charset = chardet.detect(content)
                if charset and charset['encoding']:
                    charset = charset['encoding']
                if charset == 'MacCyrillic':
                    # Silly MacCyr, try cp1251
                    try:
                        content = content.decode('windows-1251')
                        charset = 'windows-1251'
                    except: content = content.decode(charset)
                else:
                    content = content.decode(charset)
            except: charset = None
        # Then try to guess primitively
        if charset is None:
            for charset in self.encodings:
                try:
                    content = content.decode(charset)
                    break
                except: charset = None
        return (content, charset)

    # guess and encode return value into UTF-8
    def utf8(self, content):
        (uni, charset) = self.guess_charset(content)
        if charset:
            return uni.encode('utf-8')
        return content
