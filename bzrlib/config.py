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
import bzrlib.errors as errors


class Config(object):
    """A configuration policy - what username, editor, gpg needs etc."""

    def get_editor(self):
        """Get the users pop up editor."""
        raise NotImplementedError

    def __init__(self):
        super(Config, self).__init__()

    def user_email(self):
        """Return just the email component of a username."""
        e = self.username()
        m = re.search(r'[\w+.-]+@[\w+.-]+', e)
        if not m:
            raise BzrError("%r doesn't seem to contain "
                           "a reasonable email address" % e)
        return m.group(0)

    def username(self):
        """Return email-style username.
    
        Something similar to 'Martin Pool <mbp@sourcefrog.net>'
        
        $BZREMAIL can be set to override this, then
        the concrete policy type is checked, and finally
        $EMAIL is examinged.
        but if none is found, a reasonable default is (hopefully)
        created.
    
        TODO: Check it's reasonably well-formed.
        """
        v = os.environ.get('BZREMAIL')
        if v:
            return v.decode(bzrlib.user_encoding)
    
        v = self._get_user_id()
        if v:
            return v
        
        v = os.environ.get('EMAIL')
        if v:
            return v.decode(bzrlib.user_encoding)

        name, email = _auto_user_id()
        if name:
            return '%s <%s>' % (name, email)
        else:
            return email


class GlobalConfig(Config):
    """The configuration that should be used for a specific location."""

    def _get_parser(self, filename=None, file=None):
        parser = ConfigParser()
        if file is not None:
            parser.readfp(file)
        else:
            parser.read([filename])
        return parser

    def _get_config_parser(self, file=None):
        if self._parser is None:
            self._parser =  self._get_parser(config_filename(), file)
        return self._parser
    
    def _get_branches_config_parser(self, file=None):
        if self._branches_parser is None:
            self._branches_parser = self._get_parser(
                branches_config_filename(), file)
        return self._branches_parser

    def get_editor(self):
        if self._get_config_parser().has_option('DEFAULT', 'editor'):
            return self._get_config_parser().get('DEFAULT', 'editor')

    def _get_user_id(self, branch=None):
        """Return the full user id from the global config file.
    
        e.g. "John Hacker <jhacker@foo.org>"
        from 
        [DEFAULT]
        email=John Hacker <jhacker@foo.org>
        """
        if self._get_config_parser().has_option('DEFAULT', 'email'):
            email = self._get_config_parser().get('DEFAULT', 'email')
            if email is not None:
                return email
    
    def __init__(self):
        super(GlobalConfig, self).__init__()
        self._branches_parser = None
        self._parser = None


class LocationConfig(Config):
    """A configuration object that gives the policy for a location."""

    def __init__(self, location):
        self._global_config = None
        self.location = location

    def _get_branches_config_parser(self, file=None):
        return self._get_global_config()._get_branches_config_parser(file)

    def _get_global_config(self):
        if self._global_config is None:
            self._global_config = GlobalConfig()
        return self._global_config

    def _get_section(self):
        """Get the section we should look in for config items.

        Returns None if none exists. 
        TODO: perhaps return a NullSection that thunks through to the 
              global config.
        """
        return 'http://www.example.com'

    def _get_user_id(self):
        return self._get_global_config()._get_user_id()


class BranchConfig(Config):
    """A configuration object giving the policy for a branch."""

    def _get_location_config(self):
        if self._location_config is None:
            self._location_config = LocationConfig(self.branch.base)
        return self._location_config

    def _get_user_id(self):
        """Return the full user id for the branch.
    
        e.g. "John Hacker <jhacker@foo.org>"
        This is looked up in the email controlfile for the branch.
        """
        try:
            return (self.branch.controlfile("email", "r") 
                    .read()
                    .decode(bzrlib.user_encoding)
                    .rstrip("\r\n"))
        except errors.NoSuchFile, e:
            pass
        
        return self._get_location_config()._get_user_id()

    def __init__(self, branch):
        super(BranchConfig, self).__init__()
        self._location_config = None
        self.branch = branch


def config_dir():
    """Return per-user configuration directory.

    By default this is ~/.bazaar/
    
    TODO: Global option --config-dir to override this.
    """
    return os.path.join(os.path.expanduser("~"), ".bazaar")


def config_filename():
    """Return per-user configuration ini file filename."""
    return os.path.join(config_dir(), 'bazaar.conf')


def branches_config_filename():
    """Return per-user configuration ini file filename."""
    return os.path.join(config_dir(), 'branches.conf')


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


