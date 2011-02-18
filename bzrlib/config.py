# Copyright (C) 2005-2011 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
#            and others
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

import os
import sys

from bzrlib import commands
from bzrlib.decorators import needs_write_lock
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import errno
import fnmatch
import re
from cStringIO import StringIO

import bzrlib
from bzrlib import (
    atomicfile,
    bzrdir,
    debug,
    errors,
    lockdir,
    mail_client,
    mergetools,
    osutils,
    registry,
    symbol_versioning,
    trace,
    transport,
    ui,
    urlutils,
    win32utils,
    )
from bzrlib.util.configobj import configobj
""")


CHECK_IF_POSSIBLE=0
CHECK_ALWAYS=1
CHECK_NEVER=2


SIGN_WHEN_REQUIRED=0
SIGN_ALWAYS=1
SIGN_NEVER=2


POLICY_NONE = 0
POLICY_NORECURSE = 1
POLICY_APPENDPATH = 2

_policy_name = {
    POLICY_NONE: None,
    POLICY_NORECURSE: 'norecurse',
    POLICY_APPENDPATH: 'appendpath',
    }
_policy_value = {
    None: POLICY_NONE,
    'none': POLICY_NONE,
    'norecurse': POLICY_NORECURSE,
    'appendpath': POLICY_APPENDPATH,
    }


STORE_LOCATION = POLICY_NONE
STORE_LOCATION_NORECURSE = POLICY_NORECURSE
STORE_LOCATION_APPENDPATH = POLICY_APPENDPATH
STORE_BRANCH = 3
STORE_GLOBAL = 4


class ConfigObj(configobj.ConfigObj):

    def __init__(self, infile=None, **kwargs):
        # We define our own interpolation mechanism calling it option expansion
        super(ConfigObj, self).__init__(infile=infile,
                                        interpolation=False,
                                        **kwargs)


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

    def __init__(self):
        super(Config, self).__init__()

    def config_id(self):
        """Returns a unique ID for the config."""
        raise NotImplementedError(self.config_id)

    def get_editor(self):
        """Get the users pop up editor."""
        raise NotImplementedError

    def get_change_editor(self, old_tree, new_tree):
        from bzrlib import diff
        cmd = self._get_change_editor()
        if cmd is None:
            return None
        return diff.DiffFromTool.from_string(cmd, old_tree, new_tree,
                                             sys.stdout)


    def get_mail_client(self):
        """Get a mail client to use"""
        selected_client = self.get_user_option('mail_client')
        _registry = mail_client.mail_client_registry
        try:
            mail_client_class = _registry.get(selected_client)
        except KeyError:
            raise errors.UnknownMailClient(selected_client)
        return mail_client_class(self)

    def _get_signature_checking(self):
        """Template method to override signature checking policy."""

    def _get_signing_policy(self):
        """Template method to override signature creation policy."""

    option_ref_re = None

    def expand_options(self, string, env=None):
        """Expand option references in the string in the configuration context.

        :param string: The string containing option to expand.

        :param env: An option dict defining additional configuration options or
            overriding existing ones.

        :returns: The expanded string.
        """
        return self._expand_options_in_string(string, env)

    def _expand_options_in_list(self, slist, env=None, _ref_stack=None):
        """Expand options in  a list of strings in the configuration context.

        :param slist: A list of strings.

        :param env: An option dict defining additional configuration options or
            overriding existing ones.

        :param _ref_stack: Private list containing the options being
            expanded to detect loops.

        :returns: The flatten list of expanded strings.
        """
        # expand options in each value separately flattening lists
        result = []
        for s in slist:
            value = self._expand_options_in_string(s, env, _ref_stack)
            if isinstance(value, list):
                result.extend(value)
            else:
                result.append(value)
        return result

    def _expand_options_in_string(self, string, env=None, _ref_stack=None):
        """Expand options in the string in the configuration context.

        :param string: The string to be expanded.

        :param env: An option dict defining additional configuration options or
            overriding existing ones.

        :param _ref_stack: Private list containing the options being
            expanded to detect loops.

        :returns: The expanded string.
        """
        if string is None:
            # Not much to expand there
            return None
        if _ref_stack is None:
            # What references are currently resolved (to detect loops)
            _ref_stack = []
        if self.option_ref_re is None:
            # We want to match the most embedded reference first (i.e. for
            # '{{foo}}' we will get '{foo}',
            # for '{bar{baz}}' we will get '{baz}'
            self.option_ref_re = re.compile('({[^{}]+})')
        result = string
        # We need to iterate until no more refs appear ({{foo}} will need two
        # iterations for example).
        while True:
            try:
                raw_chunks = self.option_ref_re.split(result)
            except TypeError:
                import pdb; pdb.set_trace()
            if len(raw_chunks) == 1:
                # Shorcut the trivial case: no refs
                return result
            chunks = []
            list_value = False
            # Split will isolate refs so that every other chunk is a ref
            chunk_is_ref = False
            for chunk in raw_chunks:
                if not chunk_is_ref:
                    if chunk:
                        # Keep only non-empty strings
                        chunks.append(chunk)
                    chunk_is_ref = True
                else:
                    name = chunk[1:-1]
                    if name in _ref_stack:
                        raise errors.OptionExpansionLoop(string, _ref_stack)
                    _ref_stack.append(name)
                    value = self._expand_option(name, env, _ref_stack)
                    if value is None:
                        raise errors.ExpandingUnknownOption(name, string)
                    if isinstance(value, list):
                        list_value = True
                        chunks.extend(value)
                    else:
                        chunks.append(value)
                    _ref_stack.pop()
                    chunk_is_ref = False
            if list_value:
                # Once a list appears as the result of an expansion, all
                # callers will get a list result. This allows a consistent
                # behavior even when some options in the expansion chain
                # may be seen defined as strings even if their expanded
                # value is a list.
                return self._expand_options_in_list(chunks, env, _ref_stack)
            else:
                result = ''.join(chunks)
        return result

    def _expand_option(self, name, env, _ref_stack):
        if env is not None and name in env:
            # Special case, values provided in env takes precedence over
            # anything else
            value = env[name]
        else:
            # FIXME: This is a limited implementation, what we really need
            # is a way to query the bzr config for the value of an option,
            # respecting the scope rules -- vila 20101222
            value = self.get_user_option(name, expand=False)
            if isinstance(value, list):
                value = self._expand_options_in_list(value, env, _ref_stack)
            else:
                value = self._expand_options_in_string(value, env, _ref_stack)
        return value

    def _get_user_option(self, option_name):
        """Template method to provide a user option."""
        return None

    def get_user_option(self, option_name, expand=True):
        """Get a generic option - no special process, no default.


        :param option_name: The queried option.

        :param expand: Whether options references should be expanded.

        :returns: The value of the option.
        """
        value = self._get_user_option(option_name)
        if expand:
            if isinstance(value, list):
                value = self._expand_options_in_list(value)
            elif isinstance(value, dict):
                trace.warning('Cannot expand "%s":'
                              ' Dicts do not support option expansion'
                              % (option_name,))
            else:
                value = self._expand_options_in_string(value)
        return value

    def get_user_option_as_bool(self, option_name):
        """Get a generic option as a boolean - no special process, no default.

        :return None if the option doesn't exist or its value can't be
            interpreted as a boolean. Returns True or False otherwise.
        """
        s = self.get_user_option(option_name)
        if s is None:
            # The option doesn't exist
            return None
        val = ui.bool_from_string(s)
        if val is None:
            # The value can't be interpreted as a boolean
            trace.warning('Value "%s" is not a boolean for "%s"',
                          s, option_name)
        return val

    def get_user_option_as_list(self, option_name):
        """Get a generic option as a list - no special process, no default.

        :return None if the option doesn't exist. Returns the value as a list
            otherwise.
        """
        l = self.get_user_option(option_name)
        if isinstance(l, (str, unicode)):
            # A single value, most probably the user forgot (or didn't care to
            # add) the final ','
            l = [l]
        return l

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

        $BZR_EMAIL can be set to override this, then
        the concrete policy type is checked, and finally
        $EMAIL is examined.
        If no username can be found, errors.NoWhoami exception is raised.

        TODO: Check it's reasonably well-formed.
        """
        v = os.environ.get('BZR_EMAIL')
        if v:
            return v.decode(osutils.get_user_encoding())

        v = self._get_user_id()
        if v:
            return v

        v = os.environ.get('EMAIL')
        if v:
            return v.decode(osutils.get_user_encoding())

        raise errors.NoWhoami()

    def ensure_username(self):
        """Raise errors.NoWhoami if username is not set.

        This method relies on the username() function raising the error.
        """
        self.username()

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
                trace.warning("Please use create_signatures,"
                              " not check_signatures to set signing policy.")
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

    def get_bzr_remote_path(self):
        try:
            return os.environ['BZR_REMOTE_PATH']
        except KeyError:
            path = self.get_user_option("bzr_remote_path")
            if path is None:
                path = 'bzr'
            return path

    def suppress_warning(self, warning):
        """Should the warning be suppressed or emitted.

        :param warning: The name of the warning being tested.

        :returns: True if the warning should be suppressed, False otherwise.
        """
        warnings = self.get_user_option_as_list('suppress_warnings')
        if warnings is None or warning not in warnings:
            return False
        else:
            return True

    def get_merge_tools(self):
        tools = {}
        for (oname, value, section, conf_id, parser) in self._get_options():
            if oname.startswith('bzr.mergetool.'):
                tool_name = oname[len('bzr.mergetool.'):]
                tools[tool_name] = value
        trace.mutter('loaded merge tools: %r' % tools)
        return tools

    def find_merge_tool(self, name):
        # We fake a defaults mechanism here by checking if the given name can 
        # be found in the known_merge_tools if it's not found in the config.
        # This should be done through the proposed config defaults mechanism
        # when it becomes available in the future.
        command_line = (self.get_user_option('bzr.mergetool.%s' % name,
                                             expand=False)
                        or mergetools.known_merge_tools.get(name, None))
        return command_line


class IniBasedConfig(Config):
    """A configuration policy that draws from ini files."""

    def __init__(self, get_filename=symbol_versioning.DEPRECATED_PARAMETER,
                 file_name=None):
        """Base class for configuration files using an ini-like syntax.

        :param file_name: The configuration file path.
        """
        super(IniBasedConfig, self).__init__()
        self.file_name = file_name
        if symbol_versioning.deprecated_passed(get_filename):
            symbol_versioning.warn(
                'IniBasedConfig.__init__(get_filename) was deprecated in 2.3.'
                ' Use file_name instead.',
                DeprecationWarning,
                stacklevel=2)
            if get_filename is not None:
                self.file_name = get_filename()
        else:
            self.file_name = file_name
        self._content = None
        self._parser = None

    @classmethod
    def from_string(cls, str_or_unicode, file_name=None, save=False):
        """Create a config object from a string.

        :param str_or_unicode: A string representing the file content. This will
            be utf-8 encoded.

        :param file_name: The configuration file path.

        :param _save: Whether the file should be saved upon creation.
        """
        conf = cls(file_name=file_name)
        conf._create_from_string(str_or_unicode, save)
        return conf

    def _create_from_string(self, str_or_unicode, save):
        self._content = StringIO(str_or_unicode.encode('utf-8'))
        # Some tests use in-memory configs, some other always need the config
        # file to exist on disk.
        if save:
            self._write_config_file()

    def _get_parser(self, file=symbol_versioning.DEPRECATED_PARAMETER):
        if self._parser is not None:
            return self._parser
        if symbol_versioning.deprecated_passed(file):
            symbol_versioning.warn(
                'IniBasedConfig._get_parser(file=xxx) was deprecated in 2.3.'
                ' Use IniBasedConfig(_content=xxx) instead.',
                DeprecationWarning,
                stacklevel=2)
        if self._content is not None:
            co_input = self._content
        elif self.file_name is None:
            raise AssertionError('We have no content to create the config')
        else:
            co_input = self.file_name
        try:
            self._parser = ConfigObj(co_input, encoding='utf-8')
        except configobj.ConfigObjError, e:
            raise errors.ParseConfigError(e.errors, e.config.filename)
        # Make sure self.reload() will use the right file name
        self._parser.filename = self.file_name
        return self._parser

    def reload(self):
        """Reload the config file from disk."""
        if self.file_name is None:
            raise AssertionError('We need a file name to reload the config')
        if self._parser is not None:
            self._parser.reload()

    def _get_matching_sections(self):
        """Return an ordered list of (section_name, extra_path) pairs.

        If the section contains inherited configuration, extra_path is
        a string containing the additional path components.
        """
        section = self._get_section()
        if section is not None:
            return [(section, '')]
        else:
            return []

    def _get_section(self):
        """Override this to define the section used by the config."""
        return "DEFAULT"

    def _get_sections(self, name=None):
        """Returns an iterator of the sections specified by ``name``.

        :param name: The section name. If None is supplied, the default
            configurations are yielded.

        :return: A tuple (name, section, config_id) for all sections that will
            be walked by user_get_option() in the 'right' order. The first one
            is where set_user_option() will update the value.
        """
        parser = self._get_parser()
        if name is not None:
            yield (name, parser[name], self.config_id())
        else:
            # No section name has been given so we fallback to the configobj
            # itself which holds the variables defined outside of any section.
            yield (None, parser, self.config_id())

    def _get_options(self, sections=None):
        """Return an ordered list of (name, value, section, config_id) tuples.

        All options are returned with their associated value and the section
        they appeared in. ``config_id`` is a unique identifier for the
        configuration file the option is defined in.

        :param sections: Default to ``_get_matching_sections`` if not
            specified. This gives a better control to daughter classes about
            which sections should be searched. This is a list of (name,
            configobj) tuples.
        """
        opts = []
        if sections is None:
            parser = self._get_parser()
            sections = []
            for (section_name, _) in self._get_matching_sections():
                try:
                    section = parser[section_name]
                except KeyError:
                    # This could happen for an empty file for which we define a
                    # DEFAULT section. FIXME: Force callers to provide sections
                    # instead ? -- vila 20100930
                    continue
                sections.append((section_name, section))
        config_id = self.config_id()
        for (section_name, section) in sections:
            for (name, value) in section.iteritems():
                yield (name, parser._quote(value), section_name,
                       config_id, parser)

    def _get_option_policy(self, section, option_name):
        """Return the policy for the given (section, option_name) pair."""
        return POLICY_NONE

    def _get_change_editor(self):
        return self.get_user_option('change_editor')

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
        for (section, extra_path) in self._get_matching_sections():
            try:
                value = self._get_parser().get_value(section, option_name)
            except KeyError:
                continue
            policy = self._get_option_policy(section, option_name)
            if policy == POLICY_NONE:
                return value
            elif policy == POLICY_NORECURSE:
                # norecurse items only apply to the exact path
                if extra_path:
                    continue
                else:
                    return value
            elif policy == POLICY_APPENDPATH:
                if extra_path:
                    value = urlutils.join(value, extra_path)
                return value
            else:
                raise AssertionError('Unexpected config policy %r' % policy)
        else:
            return None

    def _gpg_signing_command(self):
        """See Config.gpg_signing_command."""
        return self._get_user_option('gpg_signing_command')

    def _log_format(self):
        """See Config.log_format."""
        return self._get_user_option('log_format')

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

    def remove_user_option(self, option_name, section_name=None):
        """Remove a user option and save the configuration file.

        :param option_name: The option to be removed.

        :param section_name: The section the option is defined in, default to
            the default section.
        """
        self.reload()
        parser = self._get_parser()
        if section_name is None:
            section = parser
        else:
            section = parser[section_name]
        try:
            del section[option_name]
        except KeyError:
            raise errors.NoSuchConfigOption(option_name)
        self._write_config_file()

    def _write_config_file(self):
        if self.file_name is None:
            raise AssertionError('We cannot save, self.file_name is None')
        conf_dir = os.path.dirname(self.file_name)
        ensure_config_dir_exists(conf_dir)
        atomic_file = atomicfile.AtomicFile(self.file_name)
        self._get_parser().write(atomic_file)
        atomic_file.commit()
        atomic_file.close()
        osutils.copy_ownership_from_path(self.file_name)


class LockableConfig(IniBasedConfig):
    """A configuration needing explicit locking for access.

    If several processes try to write the config file, the accesses need to be
    serialized.

    Daughter classes should decorate all methods that update a config with the
    ``@needs_write_lock`` decorator (they call, directly or indirectly, the
    ``_write_config_file()`` method. These methods (typically ``set_option()``
    and variants must reload the config file from disk before calling
    ``_write_config_file()``), this can be achieved by calling the
    ``self.reload()`` method. Note that the lock scope should cover both the
    reading and the writing of the config file which is why the decorator can't
    be applied to ``_write_config_file()`` only.

    This should be enough to implement the following logic:
    - lock for exclusive write access,
    - reload the config file from disk,
    - set the new value
    - unlock

    This logic guarantees that a writer can update a value without erasing an
    update made by another writer.
    """

    lock_name = 'lock'

    def __init__(self, file_name):
        super(LockableConfig, self).__init__(file_name=file_name)
        self.dir = osutils.dirname(osutils.safe_unicode(self.file_name))
        # FIXME: It doesn't matter that we don't provide possible_transports
        # below since this is currently used only for local config files ;
        # local transports are not shared. But if/when we start using
        # LockableConfig for other kind of transports, we will need to reuse
        # whatever connection is already established -- vila 20100929
        self.transport = transport.get_transport(self.dir)
        self._lock = lockdir.LockDir(self.transport, 'lock')

    def _create_from_string(self, unicode_bytes, save):
        super(LockableConfig, self)._create_from_string(unicode_bytes, False)
        if save:
            # We need to handle the saving here (as opposed to IniBasedConfig)
            # to be able to lock
            self.lock_write()
            self._write_config_file()
            self.unlock()

    def lock_write(self, token=None):
        """Takes a write lock in the directory containing the config file.

        If the directory doesn't exist it is created.
        """
        ensure_config_dir_exists(self.dir)
        return self._lock.lock_write(token)

    def unlock(self):
        self._lock.unlock()

    def break_lock(self):
        self._lock.break_lock()

    @needs_write_lock
    def remove_user_option(self, option_name, section_name=None):
        super(LockableConfig, self).remove_user_option(option_name,
                                                       section_name)

    def _write_config_file(self):
        if self._lock is None or not self._lock.is_held:
            # NB: if the following exception is raised it probably means a
            # missing @needs_write_lock decorator on one of the callers.
            raise errors.ObjectNotLocked(self)
        super(LockableConfig, self)._write_config_file()


class GlobalConfig(LockableConfig):
    """The configuration that should be used for a specific location."""

    def __init__(self):
        super(GlobalConfig, self).__init__(file_name=config_filename())

    def config_id(self):
        return 'bazaar'

    @classmethod
    def from_string(cls, str_or_unicode, save=False):
        """Create a config object from a string.

        :param str_or_unicode: A string representing the file content. This
            will be utf-8 encoded.

        :param save: Whether the file should be saved upon creation.
        """
        conf = cls()
        conf._create_from_string(str_or_unicode, save)
        return conf

    def get_editor(self):
        return self._get_user_option('editor')

    @needs_write_lock
    def set_user_option(self, option, value):
        """Save option and its value in the configuration."""
        self._set_option(option, value, 'DEFAULT')

    def get_aliases(self):
        """Return the aliases section."""
        if 'ALIASES' in self._get_parser():
            return self._get_parser()['ALIASES']
        else:
            return {}

    @needs_write_lock
    def set_alias(self, alias_name, alias_command):
        """Save the alias in the configuration."""
        self._set_option(alias_name, alias_command, 'ALIASES')

    @needs_write_lock
    def unset_alias(self, alias_name):
        """Unset an existing alias."""
        self.reload()
        aliases = self._get_parser().get('ALIASES')
        if not aliases or alias_name not in aliases:
            raise errors.NoSuchAlias(alias_name)
        del aliases[alias_name]
        self._write_config_file()

    def _set_option(self, option, value, section):
        self.reload()
        self._get_parser().setdefault(section, {})[option] = value
        self._write_config_file()


    def _get_sections(self, name=None):
        """See IniBasedConfig._get_sections()."""
        parser = self._get_parser()
        # We don't give access to options defined outside of any section, we
        # used the DEFAULT section by... default.
        if name in (None, 'DEFAULT'):
            # This could happen for an empty file where the DEFAULT section
            # doesn't exist yet. So we force DEFAULT when yielding
            name = 'DEFAULT'
            if 'DEFAULT' not in parser:
               parser['DEFAULT']= {}
        yield (name, parser[name], self.config_id())

    @needs_write_lock
    def remove_user_option(self, option_name, section_name=None):
        if section_name is None:
            # We need to force the default section.
            section_name = 'DEFAULT'
        # We need to avoid the LockableConfig implementation or we'll lock
        # twice
        super(LockableConfig, self).remove_user_option(option_name,
                                                       section_name)


class LocationConfig(LockableConfig):
    """A configuration object that gives the policy for a location."""

    def __init__(self, location):
        super(LocationConfig, self).__init__(
            file_name=locations_config_filename())
        # local file locations are looked up by local path, rather than
        # by file url. This is because the config file is a user
        # file, and we would rather not expose the user to file urls.
        if location.startswith('file://'):
            location = urlutils.local_path_from_url(location)
        self.location = location

    def config_id(self):
        return 'locations'

    @classmethod
    def from_string(cls, str_or_unicode, location, save=False):
        """Create a config object from a string.

        :param str_or_unicode: A string representing the file content. This will
            be utf-8 encoded.

        :param location: The location url to filter the configuration.

        :param save: Whether the file should be saved upon creation.
        """
        conf = cls(location)
        conf._create_from_string(str_or_unicode, save)
        return conf

    def _get_matching_sections(self):
        """Return an ordered list of section names matching this location."""
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
                if not fnmatch.fnmatch(name[0], name[1]):
                    matched = False
                    break
            if not matched:
                continue
            # so, for the common prefix they matched.
            # if section is longer, no match.
            if len(section_names) > len(location_names):
                continue
            matches.append((len(section_names), section,
                            '/'.join(location_names[len(section_names):])))
        # put the longest (aka more specific) locations first
        matches.sort(reverse=True)
        sections = []
        for (length, section, extra_path) in matches:
            sections.append((section, extra_path))
            # should we stop looking for parent configs here?
            try:
                if self._get_parser()[section].as_bool('ignore_parents'):
                    break
            except KeyError:
                pass
        return sections

    def _get_sections(self, name=None):
        """See IniBasedConfig._get_sections()."""
        # We ignore the name here as the only sections handled are named with
        # the location path and we don't expose embedded sections either.
        parser = self._get_parser()
        for name, extra_path in self._get_matching_sections():
            yield (name, parser[name], self.config_id())

    def _get_option_policy(self, section, option_name):
        """Return the policy for the given (section, option_name) pair."""
        # check for the old 'recurse=False' flag
        try:
            recurse = self._get_parser()[section].as_bool('recurse')
        except KeyError:
            recurse = True
        if not recurse:
            return POLICY_NORECURSE

        policy_key = option_name + ':policy'
        try:
            policy_name = self._get_parser()[section][policy_key]
        except KeyError:
            policy_name = None

        return _policy_value[policy_name]

    def _set_option_policy(self, section, option_name, option_policy):
        """Set the policy for the given option name in the given section."""
        # The old recurse=False option affects all options in the
        # section.  To handle multiple policies in the section, we
        # need to convert it to a policy_norecurse key.
        try:
            recurse = self._get_parser()[section].as_bool('recurse')
        except KeyError:
            pass
        else:
            symbol_versioning.warn(
                'The recurse option is deprecated as of 0.14.  '
                'The section "%s" has been converted to use policies.'
                % section,
                DeprecationWarning)
            del self._get_parser()[section]['recurse']
            if not recurse:
                for key in self._get_parser()[section].keys():
                    if not key.endswith(':policy'):
                        self._get_parser()[section][key +
                                                    ':policy'] = 'norecurse'

        policy_key = option_name + ':policy'
        policy_name = _policy_name[option_policy]
        if policy_name is not None:
            self._get_parser()[section][policy_key] = policy_name
        else:
            if policy_key in self._get_parser()[section]:
                del self._get_parser()[section][policy_key]

    @needs_write_lock
    def set_user_option(self, option, value, store=STORE_LOCATION):
        """Save option and its value in the configuration."""
        if store not in [STORE_LOCATION,
                         STORE_LOCATION_NORECURSE,
                         STORE_LOCATION_APPENDPATH]:
            raise ValueError('bad storage policy %r for %r' %
                (store, option))
        self.reload()
        location = self.location
        if location.endswith('/'):
            location = location[:-1]
        parser = self._get_parser()
        if not location in parser and not location + '/' in parser:
            parser[location] = {}
        elif location + '/' in parser:
            location = location + '/'
        parser[location][option]=value
        # the allowed values of store match the config policies
        self._set_option_policy(location, option, store)
        self._write_config_file()


class BranchConfig(Config):
    """A configuration object giving the policy for a branch."""

    def __init__(self, branch):
        super(BranchConfig, self).__init__()
        self._location_config = None
        self._branch_data_config = None
        self._global_config = None
        self.branch = branch
        self.option_sources = (self._get_location_config,
                               self._get_branch_data_config,
                               self._get_global_config)

    def config_id(self):
        return 'branch'

    def _get_branch_data_config(self):
        if self._branch_data_config is None:
            self._branch_data_config = TreeConfig(self.branch)
            self._branch_data_config.config_id = self.config_id
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

        e.g. "John Hacker <jhacker@example.com>"
        This is looked up in the email controlfile for the branch.
        """
        try:
            return (self.branch._transport.get_bytes("email")
                    .decode(osutils.get_user_encoding())
                    .rstrip("\r\n"))
        except errors.NoSuchFile, e:
            pass

        return self._get_best_value('_get_user_id')

    def _get_change_editor(self):
        return self._get_best_value('_get_change_editor')

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

    def _get_sections(self, name=None):
        """See IniBasedConfig.get_sections()."""
        for source in self.option_sources:
            for section in source()._get_sections(name):
                yield section

    def _get_options(self, sections=None):
        opts = []
        # First the locations options
        for option in self._get_location_config()._get_options():
            yield option
        # Then the branch options
        branch_config = self._get_branch_data_config()
        if sections is None:
            sections = [('DEFAULT', branch_config._get_parser())]
        # FIXME: We shouldn't have to duplicate the code in IniBasedConfig but
        # Config itself has no notion of sections :( -- vila 20101001
        config_id = self.config_id()
        for (section_name, section) in sections:
            for (name, value) in section.iteritems():
                yield (name, value, section_name,
                       config_id, branch_config._get_parser())
        # Then the global options
        for option in self._get_global_config()._get_options():
            yield option

    def set_user_option(self, name, value, store=STORE_BRANCH,
        warn_masked=False):
        if store == STORE_BRANCH:
            self._get_branch_data_config().set_option(value, name)
        elif store == STORE_GLOBAL:
            self._get_global_config().set_user_option(name, value)
        else:
            self._get_location_config().set_user_option(name, value, store)
        if not warn_masked:
            return
        if store in (STORE_GLOBAL, STORE_BRANCH):
            mask_value = self._get_location_config().get_user_option(name)
            if mask_value is not None:
                trace.warning('Value "%s" is masked by "%s" from'
                              ' locations.conf', value, mask_value)
            else:
                if store == STORE_GLOBAL:
                    branch_config = self._get_branch_data_config()
                    mask_value = branch_config.get_user_option(name)
                    if mask_value is not None:
                        trace.warning('Value "%s" is masked by "%s" from'
                                      ' branch.conf', value, mask_value)

    def remove_user_option(self, option_name, section_name=None):
        self._get_branch_data_config().remove_option(option_name, section_name)

    def _gpg_signing_command(self):
        """See Config.gpg_signing_command."""
        return self._get_safe_value('_gpg_signing_command')

    def _post_commit(self):
        """See Config.post_commit."""
        return self._get_safe_value('_post_commit')

    def _get_nickname(self):
        value = self._get_explicit_nickname()
        if value is not None:
            return value
        return urlutils.unescape(self.branch.base.split('/')[-2])

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
                trace.mutter('creating config parent directory: %r', parent_dir)
                os.mkdir(parent_dir)
        trace.mutter('creating config directory: %r', path)
        os.mkdir(path)
        osutils.copy_ownership_from_path(path)


def config_dir():
    """Return per-user configuration directory.

    By default this is %APPDATA%/bazaar/2.0 on Windows, ~/.bazaar on Mac OS X
    and Linux.  On Linux, if there is a $XDG_CONFIG_HOME/bazaar directory,
    that will be used instead.

    TODO: Global option --config-dir to override this.
    """
    base = os.environ.get('BZR_HOME', None)
    if sys.platform == 'win32':
        # environ variables on Windows are in user encoding/mbcs. So decode
        # before using one
        if base is not None:
            base = base.decode('mbcs')
        if base is None:
            base = win32utils.get_appdata_location_unicode()
        if base is None:
            base = os.environ.get('HOME', None)
            if base is not None:
                base = base.decode('mbcs')
        if base is None:
            raise errors.BzrError('You must have one of BZR_HOME, APPDATA,'
                                  ' or HOME set')
        return osutils.pathjoin(base, 'bazaar', '2.0')
    elif sys.platform == 'darwin':
        if base is None:
            # this takes into account $HOME
            base = os.path.expanduser("~")
        return osutils.pathjoin(base, '.bazaar')
    else:
        if base is None:

            xdg_dir = os.environ.get('XDG_CONFIG_HOME', None)
            if xdg_dir is None:
                xdg_dir = osutils.pathjoin(os.path.expanduser("~"), ".config")
            xdg_dir = osutils.pathjoin(xdg_dir, 'bazaar')
            if osutils.isdir(xdg_dir):
                trace.mutter(
                    "Using configuration in XDG directory %s." % xdg_dir)
                return xdg_dir

            base = os.path.expanduser("~")
        return osutils.pathjoin(base, ".bazaar")


def config_filename():
    """Return per-user configuration ini file filename."""
    return osutils.pathjoin(config_dir(), 'bazaar.conf')


def locations_config_filename():
    """Return per-user configuration ini file filename."""
    return osutils.pathjoin(config_dir(), 'locations.conf')


def authentication_config_filename():
    """Return per-user authentication ini file filename."""
    return osutils.pathjoin(config_dir(), 'authentication.conf')


def user_ignore_config_filename():
    """Return the user default ignore filename"""
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


def xdg_cache_dir():
    # See http://standards.freedesktop.org/basedir-spec/latest/ar01s03.html
    # Possibly this should be different on Windows?
    e = os.environ.get('XDG_CACHE_DIR', None)
    if e:
        return e
    else:
        return os.path.expanduser('~/.cache')


def parse_username(username):
    """Parse e-mail username and return a (name, address) tuple."""
    match = re.match(r'(.*?)\s*<?([\w+.-]+@[\w+.-]+)>?', username)
    if match is None:
        return (username, '')
    else:
        return (match.group(1), match.group(2))


def extract_email_address(e):
    """Return just the address part of an email string.

    That is just the user@domain part, nothing else.
    This part is required to contain only ascii characters.
    If it can't be extracted, raises an error.

    >>> extract_email_address('Jane Tester <jane@test.com>')
    "jane@test.com"
    """
    name, email = parse_username(e)
    if not email:
        raise errors.NoEmailInUsername(e)
    return email


class TreeConfig(IniBasedConfig):
    """Branch configuration data associated with its contents, not location"""

    # XXX: Really needs a better name, as this is not part of the tree! -- mbp 20080507

    def __init__(self, branch):
        self._config = branch._get_config()
        self.branch = branch

    def _get_parser(self, file=None):
        if file is not None:
            return IniBasedConfig._get_parser(file)
        return self._config._get_configobj()

    def get_option(self, name, section=None, default=None):
        self.branch.lock_read()
        try:
            return self._config.get_option(name, section, default)
        finally:
            self.branch.unlock()

    def set_option(self, value, name, section=None):
        """Set a per-branch configuration option"""
        # FIXME: We shouldn't need to lock explicitly here but rather rely on
        # higher levels providing the right lock -- vila 20101004
        self.branch.lock_write()
        try:
            self._config.set_option(value, name, section)
        finally:
            self.branch.unlock()

    def remove_option(self, option_name, section_name=None):
        # FIXME: We shouldn't need to lock explicitly here but rather rely on
        # higher levels providing the right lock -- vila 20101004
        self.branch.lock_write()
        try:
            self._config.remove_option(option_name, section_name)
        finally:
            self.branch.unlock()


class AuthenticationConfig(object):
    """The authentication configuration file based on a ini file.

    Implements the authentication.conf file described in
    doc/developers/authentication-ring.txt.
    """

    def __init__(self, _file=None):
        self._config = None # The ConfigObj
        if _file is None:
            self._filename = authentication_config_filename()
            self._input = self._filename = authentication_config_filename()
        else:
            # Tests can provide a string as _file
            self._filename = None
            self._input = _file

    def _get_config(self):
        if self._config is not None:
            return self._config
        try:
            # FIXME: Should we validate something here ? Includes: empty
            # sections are useless, at least one of
            # user/password/password_encoding should be defined, etc.

            # Note: the encoding below declares that the file itself is utf-8
            # encoded, but the values in the ConfigObj are always Unicode.
            self._config = ConfigObj(self._input, encoding='utf-8')
        except configobj.ConfigObjError, e:
            raise errors.ParseConfigError(e.errors, e.config.filename)
        return self._config

    def _save(self):
        """Save the config file, only tests should use it for now."""
        conf_dir = os.path.dirname(self._filename)
        ensure_config_dir_exists(conf_dir)
        f = file(self._filename, 'wb')
        try:
            self._get_config().write(f)
        finally:
            f.close()

    def _set_option(self, section_name, option_name, value):
        """Set an authentication configuration option"""
        conf = self._get_config()
        section = conf.get(section_name)
        if section is None:
            conf[section] = {}
            section = conf[section]
        section[option_name] = value
        self._save()

    def get_credentials(self, scheme, host, port=None, user=None, path=None, 
                        realm=None):
        """Returns the matching credentials from authentication.conf file.

        :param scheme: protocol

        :param host: the server address

        :param port: the associated port (optional)

        :param user: login (optional)

        :param path: the absolute path on the server (optional)
        
        :param realm: the http authentication realm (optional)

        :return: A dict containing the matching credentials or None.
           This includes:
           - name: the section name of the credentials in the
             authentication.conf file,
           - user: can't be different from the provided user if any,
           - scheme: the server protocol,
           - host: the server address,
           - port: the server port (can be None),
           - path: the absolute server path (can be None),
           - realm: the http specific authentication realm (can be None),
           - password: the decoded password, could be None if the credential
             defines only the user
           - verify_certificates: https specific, True if the server
             certificate should be verified, False otherwise.
        """
        credentials = None
        for auth_def_name, auth_def in self._get_config().items():
            if type(auth_def) is not configobj.Section:
                raise ValueError("%s defined outside a section" % auth_def_name)

            a_scheme, a_host, a_user, a_path = map(
                auth_def.get, ['scheme', 'host', 'user', 'path'])

            try:
                a_port = auth_def.as_int('port')
            except KeyError:
                a_port = None
            except ValueError:
                raise ValueError("'port' not numeric in %s" % auth_def_name)
            try:
                a_verify_certificates = auth_def.as_bool('verify_certificates')
            except KeyError:
                a_verify_certificates = True
            except ValueError:
                raise ValueError(
                    "'verify_certificates' not boolean in %s" % auth_def_name)

            # Attempt matching
            if a_scheme is not None and scheme != a_scheme:
                continue
            if a_host is not None:
                if not (host == a_host
                        or (a_host.startswith('.') and host.endswith(a_host))):
                    continue
            if a_port is not None and port != a_port:
                continue
            if (a_path is not None and path is not None
                and not path.startswith(a_path)):
                continue
            if (a_user is not None and user is not None
                and a_user != user):
                # Never contradict the caller about the user to be used
                continue
            if a_user is None:
                # Can't find a user
                continue
            # Prepare a credentials dictionary with additional keys
            # for the credential providers
            credentials = dict(name=auth_def_name,
                               user=a_user,
                               scheme=a_scheme,
                               host=host,
                               port=port,
                               path=path,
                               realm=realm,
                               password=auth_def.get('password', None),
                               verify_certificates=a_verify_certificates)
            # Decode the password in the credentials (or get one)
            self.decode_password(credentials,
                                 auth_def.get('password_encoding', None))
            if 'auth' in debug.debug_flags:
                trace.mutter("Using authentication section: %r", auth_def_name)
            break

        if credentials is None:
            # No credentials were found in authentication.conf, try the fallback
            # credentials stores.
            credentials = credential_store_registry.get_fallback_credentials(
                scheme, host, port, user, path, realm)

        return credentials

    def set_credentials(self, name, host, user, scheme=None, password=None,
                        port=None, path=None, verify_certificates=None,
                        realm=None):
        """Set authentication credentials for a host.

        Any existing credentials with matching scheme, host, port and path
        will be deleted, regardless of name.

        :param name: An arbitrary name to describe this set of credentials.
        :param host: Name of the host that accepts these credentials.
        :param user: The username portion of these credentials.
        :param scheme: The URL scheme (e.g. ssh, http) the credentials apply
            to.
        :param password: Password portion of these credentials.
        :param port: The IP port on the host that these credentials apply to.
        :param path: A filesystem path on the host that these credentials
            apply to.
        :param verify_certificates: On https, verify server certificates if
            True.
        :param realm: The http authentication realm (optional).
        """
        values = {'host': host, 'user': user}
        if password is not None:
            values['password'] = password
        if scheme is not None:
            values['scheme'] = scheme
        if port is not None:
            values['port'] = '%d' % port
        if path is not None:
            values['path'] = path
        if verify_certificates is not None:
            values['verify_certificates'] = str(verify_certificates)
        if realm is not None:
            values['realm'] = realm
        config = self._get_config()
        for_deletion = []
        for section, existing_values in config.items():
            for key in ('scheme', 'host', 'port', 'path', 'realm'):
                if existing_values.get(key) != values.get(key):
                    break
            else:
                del config[section]
        config.update({name: values})
        self._save()

    def get_user(self, scheme, host, port=None, realm=None, path=None,
                 prompt=None, ask=False, default=None):
        """Get a user from authentication file.

        :param scheme: protocol

        :param host: the server address

        :param port: the associated port (optional)

        :param realm: the realm sent by the server (optional)

        :param path: the absolute path on the server (optional)

        :param ask: Ask the user if there is no explicitly configured username 
                    (optional)

        :param default: The username returned if none is defined (optional).

        :return: The found user.
        """
        credentials = self.get_credentials(scheme, host, port, user=None,
                                           path=path, realm=realm)
        if credentials is not None:
            user = credentials['user']
        else:
            user = None
        if user is None:
            if ask:
                if prompt is None:
                    # Create a default prompt suitable for most cases
                    prompt = scheme.upper() + ' %(host)s username'
                # Special handling for optional fields in the prompt
                if port is not None:
                    prompt_host = '%s:%d' % (host, port)
                else:
                    prompt_host = host
                user = ui.ui_factory.get_username(prompt, host=prompt_host)
            else:
                user = default
        return user

    def get_password(self, scheme, host, user, port=None,
                     realm=None, path=None, prompt=None):
        """Get a password from authentication file or prompt the user for one.

        :param scheme: protocol

        :param host: the server address

        :param port: the associated port (optional)

        :param user: login

        :param realm: the realm sent by the server (optional)

        :param path: the absolute path on the server (optional)

        :return: The found password or the one entered by the user.
        """
        credentials = self.get_credentials(scheme, host, port, user, path,
                                           realm)
        if credentials is not None:
            password = credentials['password']
            if password is not None and scheme is 'ssh':
                trace.warning('password ignored in section [%s],'
                              ' use an ssh agent instead'
                              % credentials['name'])
                password = None
        else:
            password = None
        # Prompt user only if we could't find a password
        if password is None:
            if prompt is None:
                # Create a default prompt suitable for most cases
                prompt = '%s' % scheme.upper() + ' %(user)s@%(host)s password'
            # Special handling for optional fields in the prompt
            if port is not None:
                prompt_host = '%s:%d' % (host, port)
            else:
                prompt_host = host
            password = ui.ui_factory.get_password(prompt,
                                                  host=prompt_host, user=user)
        return password

    def decode_password(self, credentials, encoding):
        try:
            cs = credential_store_registry.get_credential_store(encoding)
        except KeyError:
            raise ValueError('%r is not a known password_encoding' % encoding)
        credentials['password'] = cs.decode_password(credentials)
        return credentials


class CredentialStoreRegistry(registry.Registry):
    """A class that registers credential stores.

    A credential store provides access to credentials via the password_encoding
    field in authentication.conf sections.

    Except for stores provided by bzr itself, most stores are expected to be
    provided by plugins that will therefore use
    register_lazy(password_encoding, module_name, member_name, help=help,
    fallback=fallback) to install themselves.

    A fallback credential store is one that is queried if no credentials can be
    found via authentication.conf.
    """

    def get_credential_store(self, encoding=None):
        cs = self.get(encoding)
        if callable(cs):
            cs = cs()
        return cs

    def is_fallback(self, name):
        """Check if the named credentials store should be used as fallback."""
        return self.get_info(name)

    def get_fallback_credentials(self, scheme, host, port=None, user=None,
                                 path=None, realm=None):
        """Request credentials from all fallback credentials stores.

        The first credentials store that can provide credentials wins.
        """
        credentials = None
        for name in self.keys():
            if not self.is_fallback(name):
                continue
            cs = self.get_credential_store(name)
            credentials = cs.get_credentials(scheme, host, port, user,
                                             path, realm)
            if credentials is not None:
                # We found some credentials
                break
        return credentials

    def register(self, key, obj, help=None, override_existing=False,
                 fallback=False):
        """Register a new object to a name.

        :param key: This is the key to use to request the object later.
        :param obj: The object to register.
        :param help: Help text for this entry. This may be a string or
                a callable. If it is a callable, it should take two
                parameters (registry, key): this registry and the key that
                the help was registered under.
        :param override_existing: Raise KeyErorr if False and something has
                already been registered for that key. If True, ignore if there
                is an existing key (always register the new value).
        :param fallback: Whether this credential store should be 
                used as fallback.
        """
        return super(CredentialStoreRegistry,
                     self).register(key, obj, help, info=fallback,
                                    override_existing=override_existing)

    def register_lazy(self, key, module_name, member_name,
                      help=None, override_existing=False,
                      fallback=False):
        """Register a new credential store to be loaded on request.

        :param module_name: The python path to the module. Such as 'os.path'.
        :param member_name: The member of the module to return.  If empty or
                None, get() will return the module itself.
        :param help: Help text for this entry. This may be a string or
                a callable.
        :param override_existing: If True, replace the existing object
                with the new one. If False, if there is already something
                registered with the same key, raise a KeyError
        :param fallback: Whether this credential store should be 
                used as fallback.
        """
        return super(CredentialStoreRegistry, self).register_lazy(
            key, module_name, member_name, help,
            info=fallback, override_existing=override_existing)


credential_store_registry = CredentialStoreRegistry()


class CredentialStore(object):
    """An abstract class to implement storage for credentials"""

    def decode_password(self, credentials):
        """Returns a clear text password for the provided credentials."""
        raise NotImplementedError(self.decode_password)

    def get_credentials(self, scheme, host, port=None, user=None, path=None,
                        realm=None):
        """Return the matching credentials from this credential store.

        This method is only called on fallback credential stores.
        """
        raise NotImplementedError(self.get_credentials)



class PlainTextCredentialStore(CredentialStore):
    __doc__ = """Plain text credential store for the authentication.conf file"""

    def decode_password(self, credentials):
        """See CredentialStore.decode_password."""
        return credentials['password']


credential_store_registry.register('plain', PlainTextCredentialStore,
                                   help=PlainTextCredentialStore.__doc__)
credential_store_registry.default_key = 'plain'


class BzrDirConfig(object):

    def __init__(self, bzrdir):
        self._bzrdir = bzrdir
        self._config = bzrdir._get_config()

    def set_default_stack_on(self, value):
        """Set the default stacking location.

        It may be set to a location, or None.

        This policy affects all branches contained by this bzrdir, except for
        those under repositories.
        """
        if self._config is None:
            raise errors.BzrError("Cannot set configuration in %s" % self._bzrdir)
        if value is None:
            self._config.set_option('', 'default_stack_on')
        else:
            self._config.set_option(value, 'default_stack_on')

    def get_default_stack_on(self):
        """Return the default stacking location.

        This will either be a location, or None.

        This policy affects all branches contained by this bzrdir, except for
        those under repositories.
        """
        if self._config is None:
            return None
        value = self._config.get_option('default_stack_on')
        if value == '':
            value = None
        return value


class TransportConfig(object):
    """A Config that reads/writes a config file on a Transport.

    It is a low-level object that considers config data to be name/value pairs
    that may be associated with a section.  Assigning meaning to these values
    is done at higher levels like TreeConfig.
    """

    def __init__(self, transport, filename):
        self._transport = transport
        self._filename = filename

    def get_option(self, name, section=None, default=None):
        """Return the value associated with a named option.

        :param name: The name of the value
        :param section: The section the option is in (if any)
        :param default: The value to return if the value is not set
        :return: The value or default value
        """
        configobj = self._get_configobj()
        if section is None:
            section_obj = configobj
        else:
            try:
                section_obj = configobj[section]
            except KeyError:
                return default
        return section_obj.get(name, default)

    def set_option(self, value, name, section=None):
        """Set the value associated with a named option.

        :param value: The value to set
        :param name: The name of the value to set
        :param section: The section the option is in (if any)
        """
        configobj = self._get_configobj()
        if section is None:
            configobj[name] = value
        else:
            configobj.setdefault(section, {})[name] = value
        self._set_configobj(configobj)

    def remove_option(self, option_name, section_name=None):
        configobj = self._get_configobj()
        if section_name is None:
            del configobj[option_name]
        else:
            del configobj[section_name][option_name]
        self._set_configobj(configobj)

    def _get_config_file(self):
        try:
            return StringIO(self._transport.get_bytes(self._filename))
        except errors.NoSuchFile:
            return StringIO()

    def _get_configobj(self):
        f = self._get_config_file()
        try:
            return ConfigObj(f, encoding='utf-8')
        finally:
            f.close()

    def _set_configobj(self, configobj):
        out_file = StringIO()
        configobj.write(out_file)
        out_file.seek(0)
        self._transport.put_file(self._filename, out_file)


class cmd_config(commands.Command):
    __doc__ = """Display, set or remove a configuration option.

    Display the active value for a given option.

    If --all is specified, NAME is interpreted as a regular expression and all
    matching options are displayed mentioning their scope. The active value
    that bzr will take into account is the first one displayed for each option.

    If no NAME is given, --all .* is implied.

    Setting a value is achieved by using name=value without spaces. The value
    is set in the most relevant scope and can be checked by displaying the
    option again.
    """

    takes_args = ['name?']

    takes_options = [
        'directory',
        # FIXME: This should be a registry option so that plugins can register
        # their own config files (or not) -- vila 20101002
        commands.Option('scope', help='Reduce the scope to the specified'
                        ' configuration file',
                        type=unicode),
        commands.Option('all',
            help='Display all the defined values for the matching options.',
            ),
        commands.Option('remove', help='Remove the option from'
                        ' the configuration file'),
        ]

    @commands.display_command
    def run(self, name=None, all=False, directory=None, scope=None,
            remove=False):
        if directory is None:
            directory = '.'
        directory = urlutils.normalize_url(directory)
        if remove and all:
            raise errors.BzrError(
                '--all and --remove are mutually exclusive.')
        elif remove:
            # Delete the option in the given scope
            self._remove_config_option(name, directory, scope)
        elif name is None:
            # Defaults to all options
            self._show_matching_options('.*', directory, scope)
        else:
            try:
                name, value = name.split('=', 1)
            except ValueError:
                # Display the option(s) value(s)
                if all:
                    self._show_matching_options(name, directory, scope)
                else:
                    self._show_value(name, directory, scope)
            else:
                if all:
                    raise errors.BzrError(
                        'Only one option can be set.')
                # Set the option value
                self._set_config_option(name, value, directory, scope)

    def _get_configs(self, directory, scope=None):
        """Iterate the configurations specified by ``directory`` and ``scope``.

        :param directory: Where the configurations are derived from.

        :param scope: A specific config to start from.
        """
        if scope is not None:
            if scope == 'bazaar':
                yield GlobalConfig()
            elif scope == 'locations':
                yield LocationConfig(directory)
            elif scope == 'branch':
                (_, br, _) = bzrdir.BzrDir.open_containing_tree_or_branch(
                    directory)
                yield br.get_config()
        else:
            try:
                (_, br, _) = bzrdir.BzrDir.open_containing_tree_or_branch(
                    directory)
                yield br.get_config()
            except errors.NotBranchError:
                yield LocationConfig(directory)
                yield GlobalConfig()

    def _show_value(self, name, directory, scope):
        displayed = False
        for c in self._get_configs(directory, scope):
            if displayed:
                break
            for (oname, value, section, conf_id, parser) in c._get_options():
                if name == oname:
                    # Display only the first value and exit

                    # FIXME: We need to use get_user_option to take policies
                    # into account and we need to make sure the option exists
                    # too (hence the two for loops), this needs a better API
                    # -- vila 20101117
                    value = c.get_user_option(name)
                    # Quote the value appropriately
                    value = parser._quote(value)
                    self.outf.write('%s\n' % (value,))
                    displayed = True
                    break
        if not displayed:
            raise errors.NoSuchConfigOption(name)

    def _show_matching_options(self, name, directory, scope):
        name = re.compile(name)
        # We want any error in the regexp to be raised *now* so we need to
        # avoid the delay introduced by the lazy regexp.
        name._compile_and_collapse()
        cur_conf_id = None
        cur_section = None
        for c in self._get_configs(directory, scope):
            for (oname, value, section, conf_id, parser) in c._get_options():
                if name.search(oname):
                    if cur_conf_id != conf_id:
                        # Explain where the options are defined
                        self.outf.write('%s:\n' % (conf_id,))
                        cur_conf_id = conf_id
                        cur_section = None
                    if (section not in (None, 'DEFAULT')
                        and cur_section != section):
                        # Display the section if it's not the default (or only)
                        # one.
                        self.outf.write('  [%s]\n' % (section,))
                        cur_section = section
                    self.outf.write('  %s = %s\n' % (oname, value))

    def _set_config_option(self, name, value, directory, scope):
        for conf in self._get_configs(directory, scope):
            conf.set_user_option(name, value)
            break
        else:
            raise errors.NoSuchConfig(scope)

    def _remove_config_option(self, name, directory, scope):
        if name is None:
            raise errors.BzrCommandError(
                '--remove expects an option to remove.')
        removed = False
        for conf in self._get_configs(directory, scope):
            for (section_name, section, conf_id) in conf._get_sections():
                if scope is not None and conf_id != scope:
                    # Not the right configuration file
                    continue
                if name in section:
                    if conf_id != conf.config_id():
                        conf = self._get_configs(directory, conf_id).next()
                    # We use the first section in the first config where the
                    # option is defined to remove it
                    conf.remove_user_option(name, section_name)
                    removed = True
                    break
            break
        else:
            raise errors.NoSuchConfig(scope)
        if not removed:
            raise errors.NoSuchConfigOption(name)
