#!/usr/bin/perl
# Very simple inetd/xinetd "cvsnt rcsfile" service

# Useful for ViewVC as there is an unpleasant non-stable bug, probably somewhere
# inside mod_python or Apache, which SOMETIMES causes cvsnt subprocesses forked
# from mod_python to die. This gives empty diff outputs or different errors like
# "Error: Rlog output ended early. Expected RCS file ..."
# This script removes forking from mod_python code and solves the issue.
# Additional profit of this script is that you can probably browse REMOTE cvs
# repositories, if you expose this service to ViewVC, although it is not tested.

# USAGE: (local) create an inetd service with this script as server listening
#        on some port of 127.0.0.1 and put "rcsfile_socket = 127.0.0.1:port"
#        into "utilities" section of viewvc.conf

$args = <STDIN>;
$args =~ s/\s+$//so;
@args = $args =~ /\'([^\']+)\'/giso;

# We don't execute shell, so this is mostly safe, not a backdoor :)
exec('/usr/bin/cvsnt', 'rcsfile', @args);
