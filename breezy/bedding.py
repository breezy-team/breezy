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
from . import (
    errors,
    )


def ensure_config_dir_exists(path=None):
    """Make sure a configuration directory exists.

    This makes sure that the directory exists.
    On windows, since configuration directories are 2 levels deep,
    it makes sure both the directory and the parent directory exists.
    """
    if path is None:
        path = config_dir()
    if not os.path.isdir(path):
        parent_dir = os.path.dirname(path)
        if not os.path.isdir(parent_dir):
            trace.mutter(
                'creating config parent directory: %r', parent_dir)
            os.mkdir(parent_dir)
            osutils.copy_ownership_from_path(parent_dir)
        trace.mutter('creating config directory: %r', path)
        os.mkdir(path)
        osutils.copy_ownership_from_path(path)


def bazaar_config_dir():
    """Return per-user configuration directory as unicode string

    By default this is %APPDATA%/bazaar/2.0 on Windows, ~/.bazaar on Mac OS X
    and Linux.  On Mac OS X and Linux, if there is a $XDG_CONFIG_HOME/bazaar
    directory, that will be used instead

    TODO: Global option --config-dir to override this.
    """
    base = os.environ.get('BZR_HOME')
    if sys.platform == 'win32':
        if base is None:
            base = win32utils.get_appdata_location()
        if base is None:
            base = win32utils.get_home_location()
        return osutils.pathjoin(base, 'bazaar', '2.0')
    if base is None:
        xdg_dir = os.environ.get('XDG_CONFIG_HOME')
        if xdg_dir is None:
            xdg_dir = osutils.pathjoin(osutils._get_home_dir(), ".config")
        xdg_dir = osutils.pathjoin(xdg_dir, 'bazaar')
        if osutils.isdir(xdg_dir):
            trace.mutter(
                "Using configuration in XDG directory %s." % xdg_dir)
            return xdg_dir
        base = osutils._get_home_dir()
    return osutils.pathjoin(base, ".bazaar")


def _config_dir():
    """Return per-user configuration directory as unicode string

    By default this is %APPDATA%/breezy on Windows, $XDG_CONFIG_HOME/breezy on
    Mac OS X and Linux. If the breezy config directory doesn't exist but
    the bazaar one (see bazaar_config_dir()) does, use that instead.
    """
    # TODO: Global option --config-dir to override this.
    base = os.environ.get('BRZ_HOME')
    if sys.platform == 'win32':
        if base is None:
            base = win32utils.get_appdata_location()
        if base is None:
            # Assume that AppData location is ALWAYS DEFINED,
            # and don't look for %HOME%, as we aren't sure about
            # where the files should be stored in %HOME%:
            # on other platforms the directory is ~/.config/,
            # but that would be incompatible with older Bazaar versions.
            raise RuntimeError('Unable to determine AppData location')

    if base is None:
        base = os.environ.get('XDG_CONFIG_HOME')
        if base is None:
            base = osutils.pathjoin(osutils._get_home_dir(), ".config")
    breezy_dir = osutils.pathjoin(base, 'breezy')
    if osutils.isdir(breezy_dir):
        return (breezy_dir, 'breezy')
    # If the breezy directory doesn't exist, but the bazaar one does, use that:
    bazaar_dir = bazaar_config_dir()
    if osutils.isdir(bazaar_dir):
        trace.mutter(
            "Using Bazaar configuration directory (%s)", bazaar_dir)
        return (bazaar_dir, 'bazaar')
    return (breezy_dir, 'breezy')


def config_dir():
    """Return per-user configuration directory as unicode string

    By default this is %APPDATA%/breezy on Windows, $XDG_CONFIG_HOME/breezy on
    Mac OS X and Linux. If the breezy config directory doesn't exist but
    the bazaar one (see bazaar_config_dir()) does, use that instead.
    """
    return _config_dir()[0]


def config_path():
    """Return per-user configuration ini file filename."""
    path, kind = _config_dir()
    if kind == 'bazaar':
        return osutils.pathjoin(path, 'bazaar.conf')
    else:
        return osutils.pathjoin(path, 'breezy.conf')


def locations_config_path():
    """Return per-user configuration ini file filename."""
    return osutils.pathjoin(config_dir(), 'locations.conf')


def authentication_config_path():
    """Return per-user authentication ini file filename."""
    return osutils.pathjoin(config_dir(), 'authentication.conf')


def user_ignore_config_path():
    """Return per-user authentication ini file filename."""
    return osutils.pathjoin(config_dir(), 'ignore')


def crash_dir():
    """Return the directory name to store crash files.

    This doesn't implicitly create it.

    On Windows it's in the config directory; elsewhere it's /var/crash
    which may be monitored by apport.  It can be overridden by
    $APPORT_CRASH_DIR.
    """
    if sys.platform == 'win32':
        return osutils.pathjoin(config_dir(), 'Crash')
    else:
        # XXX: hardcoded in apport_python_hook.py; therefore here too -- mbp
        # 2010-01-31
        return os.environ.get('APPORT_CRASH_DIR', '/var/crash')


def cache_dir():
    """Return the cache directory to use."""
    base = os.environ.get('BRZ_HOME')
    if sys.platform in "win32":
        if base is None:
            base = win32utils.get_local_appdata_location()
        if base is None:
            base = win32utils.get_home_location()
    else:
        base = os.environ.get('XDG_CACHE_HOME')
        if base is None:
            base = osutils.pathjoin(osutils._get_home_dir(), ".cache")

    cache_dir = osutils.pathjoin(base, "breezy")

    # GZ 2019-06-15: Move responsibility for ensuring dir exists elsewhere?
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    return cache_dir


def _get_default_mail_domain(mailname_file='/etc/mailname'):
    """If possible, return the assumed default email domain.

    :returns: string mail domain, or None.
    """
    if sys.platform == 'win32':
        # No implementation yet; patches welcome
        return None
    try:
        f = open(mailname_file)
    except (IOError, OSError):
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
        return u'%s <%s>' % (name, email)
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
