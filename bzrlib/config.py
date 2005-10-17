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

"""Configuration that affects the behaviour of Bazaar.

Currently this configuration resides in ~/.bazaar/bazaar.conf
and ~/.bazaar/branches.conf, which is written to by bzr.

In bazaar.config the following options may be set:
[DEFAULT]
editor=name-of-program
email=Your Name <your@email.address>
check_signatures=require|ignore|check-available(default)
create_signatures=always|never|when-required(default)
gpg_signing_command=name-of-program

in branches.conf, you specify the url of a branch and options for it.
Wildcards may be used - * and ? as normal in shell completion. Options
set in both bazaar.conf and branches.conf are overriden by the branches.conf
setting.
[/home/robertc/source]
recurse=False|True(default)
email= as above
check_signatures= as abive 
create_signatures= as above.

explanation of options
----------------------
editor - this option sets the pop up editor to use during commits.
email - this option sets the user id bzr will use when committing.
check_signatures - this option controls whether bzr will require good gpg
                   signatures, ignore them, or check them if they are 
                   present.
create_signatures - this option controls whether bzr will always create 
                    gpg signatures, never create them, or create them if the
                    branch is configured to require them.
                    NB: This option is planned, but not implemented yet.
"""

from ConfigParser import ConfigParser
import os
from fnmatch import fnmatch
import errno
import re

import bzrlib
import bzrlib.errors as errors


CHECK_IF_POSSIBLE=0
CHECK_ALWAYS=1
CHECK_NEVER=2


class Config(object):
    """A configuration policy - what username, editor, gpg needs etc."""

    def get_editor(self):
        """Get the users pop up editor."""
        raise NotImplementedError

    def _get_signature_checking(self):
        """Template method to override signature checking policy."""

    def gpg_signing_command(self):
        """What program should be used to sign signatures?"""
        return "gpg"

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

    def signature_checking(self):
        """What is the current policy for signature checking?."""
        policy = self._get_signature_checking()
        if policy is not None:
            return policy
        return CHECK_IF_POSSIBLE

    def signature_needed(self):
        """Is a signature needed when committing ?."""
        policy = self._get_signature_checking()
        if policy == CHECK_ALWAYS:
            return True
        return False


class IniBasedConfig(Config):
    """A configuration policy that draws from ini files."""

    def _get_parser(self, file=None):
        if self._parser is not None:
            return self._parser
        parser = ConfigParser()
        if file is not None:
            parser.readfp(file)
        else:
            parser.read([self._get_filename()])
        self._parser = parser
        return parser

    def _get_section(self):
        """Override this to define the section used by the config."""
        return "DEFAULT"

    def _get_signature_checking(self):
        """See Config._get_signature_checking."""
        section = self._get_section()
        if section is None:
            return None
        if self._get_parser().has_option(section, 'check_signatures'):
            return self._string_to_signature_policy(
                self._get_parser().get(section, 'check_signatures'))

    def _get_user_id(self):
        """Get the user id from the 'email' key in the current section."""
        section = self._get_section()
        if section is not None:
            if self._get_parser().has_option(section, 'email'):
                return self._get_parser().get(section, 'email')

    def gpg_signing_command(self):
        """See Config.gpg_signing_command."""
        section = self._get_section()
        if section is not None:
            if self._get_parser().has_option(section, 'gpg_signing_command'):
                return self._get_parser().get(section, 'gpg_signing_command')

    def __init__(self, get_filename):
        super(IniBasedConfig, self).__init__()
        self._get_filename = get_filename
        self._parser = None

    def _string_to_signature_policy(self, signature_string):
        """Convert a string to a signing policy."""
        if signature_string.lower() == 'check-available':
            return CHECK_IF_POSSIBLE
        if signature_string.lower() == 'ignore':
            return CHECK_NEVER
        if signature_string.lower() == 'require':
            return CHECK_ALWAYS
        raise errors.BzrError("Invalid signatures policy '%s'"
                              % signature_string)


class GlobalConfig(IniBasedConfig):
    """The configuration that should be used for a specific location."""

    def get_editor(self):
        if self._get_parser().has_option(self._get_section(), 'editor'):
            return self._get_parser().get(self._get_section(), 'editor')

    def __init__(self):
        super(GlobalConfig, self).__init__(config_filename)


class LocationConfig(IniBasedConfig):
    """A configuration object that gives the policy for a location."""

    def __init__(self, location):
        super(LocationConfig, self).__init__(branches_config_filename)
        self._global_config = None
        self.location = location

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
        sections = self._get_parser().sections()
        location_names = self.location.split('/')
        if self.location.endswith('/'):
            del location_names[-1]
        matches=[]
        for section in sections:
            section_names = section.split('/')
            if section.endswith('/'):
                del section_names[-1]
            names = zip(location_names, section_names)
            matched = True
            for name in names:
                if not fnmatch(name[0], name[1]):
                    matched = False
                    break
            if not matched:
                continue
            # so, for the common prefix they matched.
            # if section is longer, no match.
            if len(section_names) > len(location_names):
                continue
            # if path is longer, and recurse is not true, no match
            if len(section_names) < len(location_names):
                if (self._get_parser().has_option(section, 'recurse')
                    and not self._get_parser().getboolean(section, 'recurse')):
                    continue
            matches.append((len(section_names), section))
        if not len(matches):
            return None
        matches.sort(reverse=True)
        return matches[0][1]

    def gpg_signing_command(self):
        """See Config.gpg_signing_command."""
        command = super(LocationConfig, self).gpg_signing_command()
        if command is not None:
            return command
        return self._get_global_config().gpg_signing_command()

    def _get_user_id(self):
        user_id = super(LocationConfig, self)._get_user_id()
        if user_id is not None:
            return user_id
        return self._get_global_config()._get_user_id()

    def _get_signature_checking(self):
        """See Config._get_signature_checking."""
        check = super(LocationConfig, self)._get_signature_checking()
        if check is not None:
            return check
        return self._get_global_config()._get_signature_checking()


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

    def _get_signature_checking(self):
        """See Config._get_signature_checking."""
        return self._get_location_config()._get_signature_checking()

    def gpg_signing_command(self):
        """See Config.gpg_signing_command."""
        return self._get_location_config().gpg_signing_command()
        
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


