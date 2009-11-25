#!/bin/sh

VIEWVC_DIR=$1

test -f "$VIEWVC_DIR/.svn-updating" -o ! -f "$VIEWVC_DIR/.svn-updated" && exit 0
mv "$VIEWVC_DIR/.svn-updated" "$VIEWVC_DIR/.svn-updating"
"$VIEWVC_DIR/bin/svnupdate-async" "$VIEWVC_DIR/bin/svndbadmin" "$VIEWVC_DIR/.svn-updating" | sh &> /tmp/svnupdate-async.log
rm "$VIEWVC_DIR/.svn-updating"
