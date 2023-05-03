# Copyright (C) 2005-2014, 2016 Canonical Ltd
# Copyright (C) 2019 Breezy developers
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Functions for deriving user configuration from system environment."""

import os
import sys

from .lazy_import import lazy_import

lazy_import(globals(), """
from breezy import (
    osutils,
    trace,
    win32utils,
    )
""")
from . import errors, _cmd_rs


ensure_config_dir_exists = _cmd_rs.ensure_config_dir_exists
bazaar_config_dir = _cmd_rs.bazaar_config_dir
config_dir = _cmd_rs.config_dir
_config_dir = _cmd_rs._config_dir
config_path = _cmd_rs.config_path
locations_config_path = _cmd_rs.locations_config_path
authentication_config_path = _cmd_rs.authentication_config_path
user_ignore_config_path = _cmd_rs.user_ignore_config_path
crash_dir = _cmd_rs.crash_dir
cache_dir = _cmd_rs.cache_dir


def _get_default_mail_domain(mailname_file='/etc/mailname'):
    """If possible, return the assumed default email domain.

    :returns: string mail domain, or None.
    """
    if sys.platform == 'win32':
        # No implementation yet; patches welcome
        return None
    try:
        f = open(mailname_file)
    except OSError:
        return None
    try:
        domain = f.readline().strip()
        return domain
    finally:
        f.close()


def default_email():
    v = os.environ.get('BRZ_EMAIL')
    if v:
        return v
    v = os.environ.get('EMAIL')
    if v:
        return v
    name, email = _auto_user_id()
    if name and email:
        return '{} <{}>'.format(name, email)
    elif email:
        return email
    raise errors.NoWhoami()


def _auto_user_id():
    """Calculate automatic user identification.

    :returns: (realname, email), either of which may be None if they can't be
    determined.

    Only used when none is set in the environment or the id file.

    This only returns an email address if we can be fairly sure the
    address is reasonable, ie if /etc/mailname is set on unix.

    This doesn't use the FQDN as the default domain because that may be
    slow, and it doesn't use the hostname alone because that's not normally
    a reasonable address.
    """
    if sys.platform == 'win32':
        # No implementation to reliably determine Windows default mail
        # address; please add one.
        return None, None

    default_mail_domain = _get_default_mail_domain()
    if not default_mail_domain:
        return None, None

    import pwd
    uid = os.getuid()
    try:
        w = pwd.getpwuid(uid)
    except KeyError:
        trace.mutter('no passwd entry for uid %d?' % uid)
        return None, None

    # we try utf-8 first, because on many variants (like Linux),
    # /etc/passwd "should" be in utf-8, and because it's unlikely to give
    # false positives.  (many users will have their user encoding set to
    # latin-1, which cannot raise UnicodeError.)
    gecos = w.pw_gecos
    if isinstance(gecos, bytes):
        try:
            gecos = gecos.decode('utf-8')
            encoding = 'utf-8'
        except UnicodeError:
            try:
                encoding = osutils.get_user_encoding()
                gecos = gecos.decode(encoding)
            except UnicodeError:
                trace.mutter("cannot decode passwd entry %s" % w)
                return None, None

    username = w.pw_name
    if isinstance(username, bytes):
        try:
            username = username.decode(encoding)
        except UnicodeError:
            trace.mutter("cannot decode passwd entry %s" % w)
            return None, None

    comma = gecos.find(',')
    if comma == -1:
        realname = gecos
    else:
        realname = gecos[:comma]

    return realname, (username + '@' + default_mail_domain)
