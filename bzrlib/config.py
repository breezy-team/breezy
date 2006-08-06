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
and ~/.bazaar/locations.conf, which is written to by bzr.

In bazaar.conf the following options may be set:
[DEFAULT]
editor=name-of-program
email=Your Name <your@email.address>
check_signatures=require|ignore|check-available(default)
create_signatures=always|never|when-required(default)
gpg_signing_command=name-of-program
log_format=name-of-format

in locations.conf, you specify the url of a branch and options for it.
Wildcards may be used - * and ? as normal in shell completion. Options
set in both bazaar.conf and locations.conf are overridden by the locations.conf
setting.
[/home/robertc/source]
recurse=False|True(default)
email= as above
check_signatures= as above 
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
log_format - this option sets the default log format.  Possible values are
             long, short, line, or a plugin can register new formats.

In bazaar.conf you can also define aliases in the ALIASES sections, example

[ALIASES]
lastlog=log --line -r-10..-1
ll=log --line -r-10..-1
h=help
up=pull
"""


import errno
from fnmatch import fnmatch
import os
import re
import sys
from StringIO import StringIO

import bzrlib
from bzrlib import errors, urlutils
from bzrlib.osutils import pathjoin
from bzrlib.trace import mutter, warning
import bzrlib.util.configobj.configobj as configobj


CHECK_IF_POSSIBLE=0
CHECK_ALWAYS=1
CHECK_NEVER=2


SIGN_WHEN_REQUIRED=0
SIGN_ALWAYS=1
SIGN_NEVER=2


class ConfigObj(configobj.ConfigObj):

    def get_bool(self, section, key):
        return self[section].as_bool(key)

    def get_value(self, section, name):
        # Try [] for the old DEFAULT section.
        if section == "DEFAULT":
            try:
                return self[name]
            except KeyError:
                pass
        return self[section][name]


class Config(object):
    """A configuration policy - what username, editor, gpg needs etc."""

    def get_editor(self):
        """Get the users pop up editor."""
        raise NotImplementedError

    def _get_signature_checking(self):
        """Template method to override signature checking policy."""

    def _get_signing_policy(self):
        """Template method to override signature creation policy."""

    def _get_user_option(self, option_name):
        """Template method to provide a user option."""
        return None

    def get_user_option(self, option_name):
        """Get a generic option - no special process, no default."""
        return self._get_user_option(option_name)

    def gpg_signing_command(self):
        """What program should be used to sign signatures?"""
        result = self._gpg_signing_command()
        if result is None:
            result = "gpg"
        return result

    def _gpg_signing_command(self):
        """See gpg_signing_command()."""
        return None

    def log_format(self):
        """What log format should be used"""
        result = self._log_format()
        if result is None:
            result = "long"
        return result

    def _log_format(self):
        """See log_format()."""
        return None

    def __init__(self):
        super(Config, self).__init__()

    def post_commit(self):
        """An ordered list of python functions to call.

        Each function takes branch, rev_id as parameters.
        """
        return self._post_commit()

    def _post_commit(self):
        """See Config.post_commit."""
        return None

    def user_email(self):
        """Return just the email component of a username."""
        return extract_email_address(self.username())

    def username(self):
        """Return email-style username.
    
        Something similar to 'Martin Pool <mbp@sourcefrog.net>'
        
        $BZREMAIL can be set to override this, then
        the concrete policy type is checked, and finally
        $EMAIL is examined.
        If none is found, a reasonable default is (hopefully)
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

    def signing_policy(self):
        """What is the current policy for signature checking?."""
        policy = self._get_signing_policy()
        if policy is not None:
            return policy
        return SIGN_WHEN_REQUIRED

    def signature_needed(self):
        """Is a signature needed when committing ?."""
        policy = self._get_signing_policy()
        if policy is None:
            policy = self._get_signature_checking()
            if policy is not None:
                warning("Please use create_signatures, not check_signatures "
                        "to set signing policy.")
            if policy == CHECK_ALWAYS:
                return True
        elif policy == SIGN_ALWAYS:
            return True
        return False

    def get_alias(self, value):
        return self._get_alias(value)

    def _get_alias(self, value):
        pass

    def get_nickname(self):
        return self._get_nickname()

    def _get_nickname(self):
        return None


class IniBasedConfig(Config):
    """A configuration policy that draws from ini files."""

    def _get_parser(self, file=None):
        if self._parser is not None:
            return self._parser
        if file is None:
            input = self._get_filename()
        else:
            input = file
        try:
            self._parser = ConfigObj(input, encoding='utf-8')
        except configobj.ConfigObjError, e:
            raise errors.ParseConfigError(e.errors, e.config.filename)
        return self._parser

    def _get_section(self):
        """Override this to define the section used by the config."""
        return "DEFAULT"

    def _get_signature_checking(self):
        """See Config._get_signature_checking."""
        policy = self._get_user_option('check_signatures')
        if policy:
            return self._string_to_signature_policy(policy)

    def _get_signing_policy(self):
        """See Config._get_signing_policy"""
        policy = self._get_user_option('create_signatures')
        if policy:
            return self._string_to_signing_policy(policy)

    def _get_user_id(self):
        """Get the user id from the 'email' key in the current section."""
        return self._get_user_option('email')

    def _get_user_option(self, option_name):
        """See Config._get_user_option."""
        try:
            return self._get_parser().get_value(self._get_section(),
                                                option_name)
        except KeyError:
            pass

    def _gpg_signing_command(self):
        """See Config.gpg_signing_command."""
        return self._get_user_option('gpg_signing_command')

    def _log_format(self):
        """See Config.log_format."""
        return self._get_user_option('log_format')

    def __init__(self, get_filename):
        super(IniBasedConfig, self).__init__()
        self._get_filename = get_filename
        self._parser = None
        
    def _post_commit(self):
        """See Config.post_commit."""
        return self._get_user_option('post_commit')

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

    def _string_to_signing_policy(self, signature_string):
        """Convert a string to a signing policy."""
        if signature_string.lower() == 'when-required':
            return SIGN_WHEN_REQUIRED
        if signature_string.lower() == 'never':
            return SIGN_NEVER
        if signature_string.lower() == 'always':
            return SIGN_ALWAYS
        raise errors.BzrError("Invalid signing policy '%s'"
                              % signature_string)

    def _get_alias(self, value):
        try:
            return self._get_parser().get_value("ALIASES", 
                                                value)
        except KeyError:
            pass

    def _get_nickname(self):
        return self.get_user_option('nickname')


class GlobalConfig(IniBasedConfig):
    """The configuration that should be used for a specific location."""

    def get_editor(self):
        return self._get_user_option('editor')

    def __init__(self):
        super(GlobalConfig, self).__init__(config_filename)

    def set_user_option(self, option, value):
        """Save option and its value in the configuration."""
        # FIXME: RBC 20051029 This should refresh the parser and also take a
        # file lock on bazaar.conf.
        conf_dir = os.path.dirname(self._get_filename())
        ensure_config_dir_exists(conf_dir)
        if 'DEFAULT' not in self._get_parser():
            self._get_parser()['DEFAULT'] = {}
        self._get_parser()['DEFAULT'][option] = value
        f = open(self._get_filename(), 'wb')
        self._get_parser().write(f)
        f.close()


class LocationConfig(IniBasedConfig):
    """A configuration object that gives the policy for a location."""

    def __init__(self, location):
        name_generator = locations_config_filename
        if (not os.path.exists(name_generator()) and 
                os.path.exists(branches_config_filename())):
            if sys.platform == 'win32':
                warning('Please rename %s to %s' 
                         % (branches_config_filename(),
                            locations_config_filename()))
            else:
                warning('Please rename ~/.bazaar/branches.conf'
                        ' to ~/.bazaar/locations.conf')
            name_generator = branches_config_filename
        super(LocationConfig, self).__init__(name_generator)
        # local file locations are looked up by local path, rather than
        # by file url. This is because the config file is a user
        # file, and we would rather not expose the user to file urls.
        if location.startswith('file://'):
            location = urlutils.local_path_from_url(location)
        self.location = location

    def _get_section(self):
        """Get the section we should look in for config items.

        Returns None if none exists. 
        TODO: perhaps return a NullSection that thunks through to the 
              global config.
        """
        sections = self._get_parser()
        location_names = self.location.split('/')
        if self.location.endswith('/'):
            del location_names[-1]
        matches=[]
        for section in sections:
            # location is a local path if possible, so we need
            # to convert 'file://' urls to local paths if necessary.
            # This also avoids having file:///path be a more exact
            # match than '/path'.
            if section.startswith('file://'):
                section_path = urlutils.local_path_from_url(section)
            else:
                section_path = section
            section_names = section_path.split('/')
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
                try:
                    if not self._get_parser()[section].as_bool('recurse'):
                        continue
                except KeyError:
                    pass
            matches.append((len(section_names), section))
        if not len(matches):
            return None
        matches.sort(reverse=True)
        return matches[0][1]

    def set_user_option(self, option, value):
        """Save option and its value in the configuration."""
        # FIXME: RBC 20051029 This should refresh the parser and also take a
        # file lock on locations.conf.
        conf_dir = os.path.dirname(self._get_filename())
        ensure_config_dir_exists(conf_dir)
        location = self.location
        if location.endswith('/'):
            location = location[:-1]
        if (not location in self._get_parser() and
            not location + '/' in self._get_parser()):
            self._get_parser()[location]={}
        elif location + '/' in self._get_parser():
            location = location + '/'
        self._get_parser()[location][option]=value
        self._get_parser().write(file(self._get_filename(), 'wb'))


class BranchConfig(Config):
    """A configuration object giving the policy for a branch."""

    def _get_branch_data_config(self):
        if self._branch_data_config is None:
            self._branch_data_config = TreeConfig(self.branch)
        return self._branch_data_config

    def _get_location_config(self):
        if self._location_config is None:
            self._location_config = LocationConfig(self.branch.base)
        return self._location_config

    def _get_global_config(self):
        if self._global_config is None:
            self._global_config = GlobalConfig()
        return self._global_config

    def _get_best_value(self, option_name):
        """This returns a user option from local, tree or global config.

        They are tried in that order.  Use get_safe_value if trusted values
        are necessary.
        """
        for source in self.option_sources:
            value = getattr(source(), option_name)()
            if value is not None:
                return value
        return None

    def _get_safe_value(self, option_name):
        """This variant of get_best_value never returns untrusted values.
        
        It does not return values from the branch data, because the branch may
        not be controlled by the user.

        We may wish to allow locations.conf to control whether branches are
        trusted in the future.
        """
        for source in (self._get_location_config, self._get_global_config):
            value = getattr(source(), option_name)()
            if value is not None:
                return value
        return None

    def _get_user_id(self):
        """Return the full user id for the branch.
    
        e.g. "John Hacker <jhacker@foo.org>"
        This is looked up in the email controlfile for the branch.
        """
        try:
            return (self.branch.control_files.get_utf8("email") 
                    .read()
                    .decode(bzrlib.user_encoding)
                    .rstrip("\r\n"))
        except errors.NoSuchFile, e:
            pass
        
        return self._get_best_value('_get_user_id')

    def _get_signature_checking(self):
        """See Config._get_signature_checking."""
        return self._get_best_value('_get_signature_checking')

    def _get_signing_policy(self):
        """See Config._get_signing_policy."""
        return self._get_best_value('_get_signing_policy')

    def _get_user_option(self, option_name):
        """See Config._get_user_option."""
        for source in self.option_sources:
            value = source()._get_user_option(option_name)
            if value is not None:
                return value
        return None

    def set_user_option(self, name, value, local=False):
        if local is True:
            self._get_location_config().set_user_option(name, value)
        else:
            self._get_branch_data_config().set_option(value, name)


    def _gpg_signing_command(self):
        """See Config.gpg_signing_command."""
        return self._get_safe_value('_gpg_signing_command')
        
    def __init__(self, branch):
        super(BranchConfig, self).__init__()
        self._location_config = None
        self._branch_data_config = None
        self._global_config = None
        self.branch = branch
        self.option_sources = (self._get_location_config, 
                               self._get_branch_data_config,
                               self._get_global_config)

    def _post_commit(self):
        """See Config.post_commit."""
        return self._get_safe_value('_post_commit')

    def _get_nickname(self):
        value = self._get_explicit_nickname()
        if value is not None:
            return value
        return self.branch.base.split('/')[-2]

    def has_explicit_nickname(self):
        """Return true if a nickname has been explicitly assigned."""
        return self._get_explicit_nickname() is not None

    def _get_explicit_nickname(self):
        return self._get_best_value('_get_nickname')

    def _log_format(self):
        """See Config.log_format."""
        return self._get_best_value('_log_format')


def ensure_config_dir_exists(path=None):
    """Make sure a configuration directory exists.
    This makes sure that the directory exists.
    On windows, since configuration directories are 2 levels deep,
    it makes sure both the directory and the parent directory exists.
    """
    if path is None:
        path = config_dir()
    if not os.path.isdir(path):
        if sys.platform == 'win32':
            parent_dir = os.path.dirname(path)
            if not os.path.isdir(parent_dir):
                mutter('creating config parent directory: %r', parent_dir)
            os.mkdir(parent_dir)
        mutter('creating config directory: %r', path)
        os.mkdir(path)


def config_dir():
    """Return per-user configuration directory.

    By default this is ~/.bazaar/
    
    TODO: Global option --config-dir to override this.
    """
    base = os.environ.get('BZR_HOME', None)
    if sys.platform == 'win32':
        if base is None:
            base = os.environ.get('APPDATA', None)
        if base is None:
            base = os.environ.get('HOME', None)
        if base is None:
            raise errors.BzrError('You must have one of BZR_HOME, APPDATA, or HOME set')
        return pathjoin(base, 'bazaar', '2.0')
    else:
        # cygwin, linux, and darwin all have a $HOME directory
        if base is None:
            base = os.path.expanduser("~")
        return pathjoin(base, ".bazaar")


def config_filename():
    """Return per-user configuration ini file filename."""
    return pathjoin(config_dir(), 'bazaar.conf')


def branches_config_filename():
    """Return per-user configuration ini file filename."""
    return pathjoin(config_dir(), 'branches.conf')


def locations_config_filename():
    """Return per-user configuration ini file filename."""
    return pathjoin(config_dir(), 'locations.conf')


def user_ignore_config_filename():
    """Return the user default ignore filename"""
    return pathjoin(config_dir(), 'ignore')


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

        # we try utf-8 first, because on many variants (like Linux),
        # /etc/passwd "should" be in utf-8, and because it's unlikely to give
        # false positives.  (many users will have their user encoding set to
        # latin-1, which cannot raise UnicodeError.)
        try:
            gecos = w.pw_gecos.decode('utf-8')
            encoding = 'utf-8'
        except UnicodeError:
            try:
                gecos = w.pw_gecos.decode(bzrlib.user_encoding)
                encoding = bzrlib.user_encoding
            except UnicodeError:
                raise errors.BzrCommandError('Unable to determine your name.  '
                   'Use "bzr whoami" to set it.')
        try:
            username = w.pw_name.decode(encoding)
        except UnicodeError:
            raise errors.BzrCommandError('Unable to determine your name.  '
                'Use "bzr whoami" to set it.')

        comma = gecos.find(',')
        if comma == -1:
            realname = gecos
        else:
            realname = gecos[:comma]
        if not realname:
            realname = username

    except ImportError:
        import getpass
        try:
            realname = username = getpass.getuser().decode(bzrlib.user_encoding)
        except UnicodeDecodeError:
            raise errors.BzrError("Can't decode username as %s." % \
                    bzrlib.user_encoding)

    return realname, (username + '@' + socket.gethostname())


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
        raise errors.BzrError("%r doesn't seem to contain "
                              "a reasonable email address" % e)
    return m.group(0)


class TreeConfig(IniBasedConfig):
    """Branch configuration data associated with its contents, not location"""
    def __init__(self, branch):
        self.branch = branch

    def _get_parser(self, file=None):
        if file is not None:
            return IniBasedConfig._get_parser(file)
        return self._get_config()

    def _get_config(self):
        try:
            obj = ConfigObj(self.branch.control_files.get('branch.conf'), 
                            encoding='utf-8')
        except errors.NoSuchFile:
            obj = ConfigObj(encoding='utf=8')
        return obj

    def get_option(self, name, section=None, default=None):
        self.branch.lock_read()
        try:
            obj = self._get_config()
            try:
                if section is not None:
                    obj[section]
                result = obj[name]
            except KeyError:
                result = default
        finally:
            self.branch.unlock()
        return result

    def set_option(self, value, name, section=None):
        """Set a per-branch configuration option"""
        self.branch.lock_write()
        try:
            cfg_obj = self._get_config()
            if section is None:
                obj = cfg_obj
            else:
                try:
                    obj = cfg_obj[section]
                except KeyError:
                    cfg_obj[section] = {}
                    obj = cfg_obj[section]
            obj[name] = value
            out_file = StringIO()
            cfg_obj.write(out_file)
            out_file.seek(0)
            self.branch.control_files.put('branch.conf', out_file)
        finally:
            self.branch.unlock()
