# Copyright (C) 2005 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Configuration that affects the behaviour of Bazaar."""

from ConfigParser import ConfigParser
import os
import errno
import re

import bzrlib


def config_dir():
    """Return per-user configuration directory.

    By default this is ~/.bazaar/
    
    TODO: Global option --config-dir to override this.
    """
    return os.path.join(os.path.expanduser("~"), ".bazaar")


def config_filename():
    """Return per-user configuration ini file filename."""
    return os.path.join(config_dir(), 'bazaar.conf')


def _get_config_parser(file=None):
    parser = ConfigParser()
    if file is not None:
        parser.readfp(file)
    else:
        parser.read([config_filename()])
    return parser


def get_editor(parser=None):
    if parser is None:
        parser = _get_config_parser()
    if parser.has_option('DEFAULT', 'editor'):
        return parser.get('DEFAULT', 'editor')


def _get_user_id(branch=None, parser = None):
    """Return the full user id from a file or environment variable.

    e.g. "John Hacker <jhacker@foo.org>"

    branch
        A branch to use for a per-branch configuration, or None.

    The following are searched in order:

    1. $BZREMAIL
    2. .bzr/email for this branch.
    3. ~/.bzr.conf/email
    4. $EMAIL
    """
    v = os.environ.get('BZREMAIL')
    if v:
        return v.decode(bzrlib.user_encoding)

    if branch:
        try:
            return (branch.controlfile("email", "r") 
                    .read()
                    .decode(bzrlib.user_encoding)
                    .rstrip("\r\n"))
        except IOError, e:
            if e.errno != errno.ENOENT:
                raise
        except BzrError, e:
            pass
    
    if parser is None:
        parser = _get_config_parser()
    if parser.has_option('DEFAULT', 'email'):
        email = parser.get('DEFAULT', 'email')
        if email is not None:
            return email

    v = os.environ.get('EMAIL')
    if v:
        return v.decode(bzrlib.user_encoding)
    else:    
        return None


def _auto_user_id():
    """Calculate automatic user identification.

    Returns (realname, email).

    Only used when none is set in the environment or the id file.

    This previously used the FQDN as the default domain, but that can
    be very slow on machines where DNS is broken.  So now we simply
    use the hostname.
    """
    import socket

    # XXX: Any good way to get real user name on win32?

    try:
        import pwd
        uid = os.getuid()
        w = pwd.getpwuid(uid)
        gecos = w.pw_gecos.decode(bzrlib.user_encoding)
        username = w.pw_name.decode(bzrlib.user_encoding)
        comma = gecos.find(',')
        if comma == -1:
            realname = gecos
        else:
            realname = gecos[:comma]
        if not realname:
            realname = username

    except ImportError:
        import getpass
        realname = username = getpass.getuser().decode(bzrlib.user_encoding)

    return realname, (username + '@' + socket.gethostname())


def username(branch):
    """Return email-style username.

    Something similar to 'Martin Pool <mbp@sourcefrog.net>'

    TODO: Check it's reasonably well-formed.
    """
    v = _get_user_id(branch)
    if v:
        return v
    
    name, email = _auto_user_id()
    if name:
        return '%s <%s>' % (name, email)
    else:
        return email


def user_email(branch):
    """Return just the email component of a username."""
    e = _get_user_id(branch)
    if e:
        return extract_email_address(e)
    return _auto_user_id()[1]


def extract_email_address(e):
    """Return just the address part of an email string.
    
    That is just the user@domain part, nothing else. 
    This part is required to contain only ascii characters.
    If it can't be extracted, raises an error.
    
    >>> extract_email_address('Jane Tester <jane@test.com>')
    "jane@test.com"
    """
    m = re.search(r'[\w+.-]+@[\w+.-]+', e)
    if not m:
        raise BzrError("%r doesn't seem to contain "
                       "a reasonable email address" % e)
    return m.group(0)
