"""Configuration that affects the behaviour of Breezy.

Currently this configuration resides in ~/.config/breezy/breezy.conf
and ~/.config/breezy/locations.conf, which is written to by brz.

If the first location doesn't exist, then brz falls back to reading
Bazaar configuration files in ~/.bazaar or ~/.config/bazaar.

In breezy.conf the following options may be set:
[DEFAULT]
editor=name-of-program
email=Your Name <your@email.address>
check_signatures=require|ignore|check-available(default)
create_signatures=always|never|when-possible|when-required(default)
log_format=name-of-format
validate_signatures_in_log=true|false(default)
acceptable_keys=pattern1,pattern2
gpg_signing_key=amy@example.com

in locations.conf, you specify the url of a branch and options for it.
Wildcards may be used - * and ? as normal in shell completion. Options
set in both breezy.conf and locations.conf are overridden by the locations.conf
setting.
[/home/robertc/source]
recurse=False|True(default)
email= as above
check_signatures= as above
create_signatures= as above.
validate_signatures_in_log=as above
acceptable_keys=as above

explanation of options
----------------------
editor - this option sets the pop up editor to use during commits.
email - this option sets the user id brz will use when committing.
check_signatures - this option will control whether brz will require good gpg
                   signatures, ignore them, or check them if they are
                   present.  Currently it is unused except that
                   check_signatures turns on create_signatures.
create_signatures - this option controls whether brz will always create
                    gpg signatures or not on commits.  There is an unused
                    option which in future is expected to work if
                    branch settings require signatures.
log_format - this option sets the default log format.  Possible values are
             long, short, line, or a plugin can register new formats.
validate_signatures_in_log - show GPG signature validity in log output
acceptable_keys - comma separated list of key patterns acceptable for
                  verify-signatures command

In breezy.conf you can also define aliases in the ALIASES sections, example

[ALIASES]
lastlog=log --line -r-10..-1
ll=log --line -r-10..-1
h=help
up=pull
"""

# Copyright (C) 2005-2014, 2016 Canonical Ltd
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

__docformat__ = "google"

import os
import sys
from collections.abc import Iterable
from io import BytesIO
from typing import Callable, cast

import configobj

import breezy

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
import re

from breezy import (
    cmdline,
    controldir,
    lock,
    lockdir,
    ui,
    urlutils,
    win32utils,
    )
from breezy.i18n import gettext
""",
)
from . import (
    bedding,
    commands,
    debug,
    errors,
    hooks,
    lazy_regex,
    osutils,
    registry,
    trace,
    transport,
)
from .option import Option as CommandOption

CHECK_IF_POSSIBLE = 0
CHECK_ALWAYS = 1
CHECK_NEVER = 2


SIGN_WHEN_REQUIRED = 0
SIGN_ALWAYS = 1
SIGN_NEVER = 2
SIGN_WHEN_POSSIBLE = 3


POLICY_NONE = 0
POLICY_NORECURSE = 1
POLICY_APPENDPATH = 2

_policy_name = {
    POLICY_NONE: None,
    POLICY_NORECURSE: "norecurse",
    POLICY_APPENDPATH: "appendpath",
}
_policy_value = {
    None: POLICY_NONE,
    "none": POLICY_NONE,
    "norecurse": POLICY_NORECURSE,
    "appendpath": POLICY_APPENDPATH,
}


STORE_LOCATION = POLICY_NONE
STORE_LOCATION_NORECURSE = POLICY_NORECURSE
STORE_LOCATION_APPENDPATH = POLICY_APPENDPATH
STORE_BRANCH = 3
STORE_GLOBAL = 4


class OptionExpansionLoop(errors.BzrError):
    """Error raised when circular references are detected during option expansion."""

    _fmt = 'Loop involving %(refs)r while expanding "%(string)s".'

    def __init__(self, string, refs):
        """Initialize OptionExpansionLoop error.

        Args:
            string: The string being expanded when loop was detected.
            refs: List of references forming the expansion loop.
        """
        self.string = string
        self.refs = "->".join(refs)


class ExpandingUnknownOption(errors.BzrError):
    """Error raised when an undefined option is referenced during expansion."""

    _fmt = 'Option "%(name)s" is not defined while expanding "%(string)s".'

    def __init__(self, name, string):
        """Initialize ExpandingUnknownOption error.

        Args:
            name: Name of the undefined option.
            string: The string being expanded when error occurred.
        """
        self.name = name
        self.string = string


class IllegalOptionName(errors.BzrError):
    """Error raised when an option name contains illegal characters."""

    _fmt = 'Option "%(name)s" is not allowed.'

    def __init__(self, name):
        """Initialize IllegalOptionName error.

        Args:
            name: The illegal option name.
        """
        self.name = name


class ConfigContentError(errors.BzrError):
    """Error raised when a config file has encoding issues."""

    _fmt = "Config file %(filename)s is not UTF-8 encoded\n"

    def __init__(self, filename):
        """Initialize ConfigContentError.

        Args:
            filename: Path to the config file with encoding issues.
        """
        self.filename = filename


class ParseConfigError(errors.BzrError):
    """Error raised when a config file cannot be parsed."""

    _fmt = "Error(s) parsing config file %(filename)s:\n%(errors)s"

    def __init__(self, errors, filename):
        """Initialize ParseConfigError.

        Args:
            errors: List of parsing errors encountered.
            filename: Path to the config file that failed to parse.
        """
        self.filename = filename
        self.errors = "\n".join(e.msg for e in errors)


class ConfigOptionValueError(errors.BzrError):
    """Error raised when a config option has an invalid value."""

    _fmt = 'Bad value "%(value)s" for option "%(name)s".\nSee ``brz help %(name)s``'

    def __init__(self, name, value):
        """Initialize ConfigOptionValueError.

        Args:
            name: Name of the config option.
            value: The invalid value that was provided.
        """
        errors.BzrError.__init__(self, name=name, value=value)


class NoEmailInUsername(errors.BzrError):
    """Error raised when username doesn't contain a valid email address."""

    _fmt = "%(username)r does not seem to contain a reasonable email address"

    def __init__(self, username):
        """Initialize NoEmailInUsername error.

        Args:
            username: The username that lacks a valid email address.
        """
        self.username = username


class NoSuchConfig(errors.BzrError):
    """Error raised when a requested configuration doesn't exist."""

    _fmt = 'The "%(config_id)s" configuration does not exist.'

    def __init__(self, config_id):
        """Initialize NoSuchConfig error.

        Args:
            config_id: The ID of the non-existent configuration.
        """
        errors.BzrError.__init__(self, config_id=config_id)


class NoSuchConfigOption(errors.BzrError):
    """Error raised when a requested config option doesn't exist."""

    _fmt = 'The "%(option_name)s" configuration option does not exist.'

    def __init__(self, option_name):
        """Initialize NoSuchConfigOption error.

        Args:
            option_name: Name of the non-existent option.
        """
        errors.BzrError.__init__(self, option_name=option_name)


class NoSuchAlias(errors.BzrError):
    """Error raised when a requested alias doesn't exist."""

    _fmt = 'The alias "%(alias_name)s" does not exist.'

    def __init__(self, alias_name):
        """Initialize NoSuchAlias error.

        Args:
            alias_name: Name of the non-existent alias.
        """
        errors.BzrError.__init__(self, alias_name=alias_name)


def signature_policy_from_unicode(signature_string):
    """Convert a string to a signing policy."""
    if signature_string.lower() == "check-available":
        return CHECK_IF_POSSIBLE
    if signature_string.lower() == "ignore":
        return CHECK_NEVER
    if signature_string.lower() == "require":
        return CHECK_ALWAYS
    raise ValueError(f"Invalid signatures policy '{signature_string}'")


def signing_policy_from_unicode(signature_string):
    """Convert a string to a signing policy."""
    if signature_string.lower() == "when-required":
        return SIGN_WHEN_REQUIRED
    if signature_string.lower() == "never":
        return SIGN_NEVER
    if signature_string.lower() == "always":
        return SIGN_ALWAYS
    if signature_string.lower() == "when-possible":
        return SIGN_WHEN_POSSIBLE
    raise ValueError(f"Invalid signing policy '{signature_string}'")


def _has_triplequote_bug():
    """True if triple quote logic is reversed, see lp:710410."""
    conf = configobj.ConfigObj()
    quote = getattr(conf, "_get_triple_quote", None)
    return bool(quote and quote('"""') != "'''")


class ConfigObj(configobj.ConfigObj):
    """Extended ConfigObj with Breezy-specific functionality."""

    def __init__(self, infile=None, **kwargs):
        """Initialize ConfigObj with Breezy-specific defaults.

        Args:
            infile: Input file or file-like object to read from.
            **kwargs: Additional keyword arguments passed to parent.
        """
        # We define our own interpolation mechanism calling it option expansion
        super().__init__(infile=infile, interpolation=False, **kwargs)

    if _has_triplequote_bug():

        def _get_triple_quote(self, value):
            quot = super()._get_triple_quote(value)
            if quot == configobj.tdquot:
                return configobj.tsquot
            return configobj.tdquot

    def get_bool(self, section, key) -> bool:
        """Get a boolean value from a specific section and key.

        Args:
            section: Section name to look in.
            key: Key name to retrieve.

        Returns:
            Boolean value from the config.
        """
        return cast("bool", self[section].as_bool(key))

    def get_value(self, section, name):
        """Get a value from a specific section and name.

        Args:
            section: Section name to look in.
            name: Name of the configuration option.

        Returns:
            The configuration value.
        """
        # Try [] for the old DEFAULT section.
        if section == "DEFAULT":
            try:
                return self[name]
            except KeyError:
                pass
        return self[section][name]


class Config:
    """A configuration policy - what username, editor, gpg needs etc."""

    def __init__(self):
        """Initialize base configuration."""
        super().__init__()

    def config_id(self):
        """Returns a unique ID for the config."""
        raise NotImplementedError(self.config_id)

    def get_change_editor(self, old_tree, new_tree):
        """Get a change editor for comparing two trees.

        Args:
            old_tree: The old tree to compare.
            new_tree: The new tree to compare.

        Returns:
            A DiffFromTool instance or None if no editor is configured.
        """
        from breezy import diff

        cmd = self._get_change_editor()
        if cmd is None:
            return None
        cmd = cmd.replace("@old_path", "{old_path}")
        cmd = cmd.replace("@new_path", "{new_path}")
        cmd = cmdline.split(cmd)
        if "{old_path}" not in cmd:
            cmd.extend(["{old_path}", "{new_path}"])
        return diff.DiffFromTool.from_string(cmd, old_tree, new_tree, sys.stdout)

    def _get_signature_checking(self):
        """Template method to override signature checking policy."""

    def _get_signing_policy(self):
        """Template method to override signature creation policy."""

    option_ref_re = None

    def expand_options(self, string, env=None):
        """Expand option references in the string in the configuration context.

        Args:
          string: The string containing option to expand.
          env: An option dict defining additional configuration options or
            overriding existing ones.

        Returns:
          The expanded string.
        """
        return self._expand_options_in_string(string, env)

    def _expand_options_in_list(self, slist, env=None, _ref_stack=None):
        """Expand options in  a list of strings in the configuration context.

        Args:
          slist: A list of strings.

          env: An option dict defining additional configuration options or
            overriding existing ones.

          _ref_stack: Private list containing the options being
            expanded to detect loops.

        Returns: The flatten list of expanded strings.
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

        Args:
          string: The string to be expanded.

          env: An option dict defining additional configuration options or
            overriding existing ones.

          _ref_stack: Private list containing the options being
            expanded to detect loops.

        Returns:
          The expanded string
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
            self.option_ref_re = re.compile("({[^{}]+})")
        result = string
        # We need to iterate until no more refs appear ({{foo}} will need two
        # iterations for example).
        while True:
            raw_chunks = self.option_ref_re.split(result)
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
                        # Keep only non-empty strings (or we get bogus empty
                        # slots when a list value is involved).
                        chunks.append(chunk)
                    chunk_is_ref = True
                else:
                    name = chunk[1:-1]
                    if name in _ref_stack:
                        raise OptionExpansionLoop(string, _ref_stack)
                    _ref_stack.append(name)
                    value = self._expand_option(name, env, _ref_stack)
                    if value is None:
                        raise ExpandingUnknownOption(name, string)
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
                # defined as strings (no comma in their value) but their
                # expanded value is a list.
                return self._expand_options_in_list(chunks, env, _ref_stack)
            else:
                result = "".join(chunks)
        return result

    def _expand_option(self, name, env, _ref_stack):
        if env is not None and name in env:
            # Special case, values provided in env takes precedence over
            # anything else
            value = env[name]
        else:
            # FIXME: This is a limited implementation, what we really need is a
            # way to query the brz config for the value of an option,
            # respecting the scope rules (That is, once we implement fallback
            # configs, getting the option value should restart from the top
            # config, not the current one) -- vila 20101222
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

        Args:
          option_name: The queried option.
          expand: Whether options references should be expanded.

        Returns:
          The value of the option.
        """
        value = self._get_user_option(option_name)
        if expand:
            if isinstance(value, list):
                value = self._expand_options_in_list(value)
            elif isinstance(value, dict):
                trace.warning(
                    f'Cannot expand "{option_name}":'
                    " Dicts do not support option expansion"
                )
            else:
                value = self._expand_options_in_string(value)
        for hook in OldConfigHooks["get"]:
            hook(self, option_name, value)
        return value

    def get_user_option_as_bool(self, option_name, expand=None, default=None):
        """Get a generic option as a boolean.

        Args:
          expand: Allow expanding references to other config values.
          default: Default value if nothing is configured

        Returns:
          None if the option doesn't exist or its value can't be
            interpreted as a boolean. Returns True or False otherwise.
        """
        s = self.get_user_option(option_name, expand=expand)
        if s is None:
            # The option doesn't exist
            return default
        val = ui.bool_from_string(s)
        if val is None:
            # The value can't be interpreted as a boolean
            trace.warning('Value "%s" is not a boolean for "%s"', s, option_name)
        return val

    def get_user_option_as_list(self, option_name, expand=None):
        """Get a generic option as a list - no special process, no default.

        Returns:
          None if the option doesn't exist. Returns the value as a list
          otherwise.
        """
        l = self.get_user_option(option_name, expand=expand)
        if isinstance(l, str):
            # A single value, most probably the user forgot (or didn't care to
            # add) the final ','
            l = [l]
        return l

    def _log_format(self):
        """See log_format()."""
        return None

    def validate_signatures_in_log(self):
        """Show GPG signature validity in log."""
        result = self._validate_signatures_in_log()
        result = result == "true"
        return result

    def _validate_signatures_in_log(self):
        """See validate_signatures_in_log()."""
        return None

    def _post_commit(self):
        """See Config.post_commit."""
        return None

    def user_email(self):
        """Return just the email component of a username."""
        return extract_email_address(self.username())

    def username(self):
        """Return email-style username.

        Something similar to 'Martin Pool <mbp@sourcefrog.net>'

        $BRZ_EMAIL or $BZR_EMAIL can be set to override this, then
        the concrete policy type is checked, and finally
        $EMAIL is examined.
        If no username can be found, NoWhoami exception is raised.
        """
        v = os.environ.get("BRZ_EMAIL") or os.environ.get("BZR_EMAIL")
        if v:
            return v
        v = self._get_user_id()
        if v:
            return v
        return bedding.default_email()

    def get_alias(self, value):
        """Get an alias for the given value.

        Args:
            value: The value to find an alias for.

        Returns:
            The alias or None if not found.
        """
        return self._get_alias(value)

    def _get_alias(self, value):
        pass

    def get_nickname(self):
        """Get the nickname for this location.

        Returns:
            The nickname string or None if not configured.
        """
        return self._get_nickname()

    def _get_nickname(self):
        return None

    def get_bzr_remote_path(self):
        """Get the path for bzr on the remote machine.

        Returns:
            The remote path string or None if not configured.
        """
        try:
            return os.environ["BZR_REMOTE_PATH"]
        except KeyError:
            path = self.get_user_option("bzr_remote_path")
            if path is None:
                path = "bzr"
            return path

    def suppress_warning(self, warning):
        """Should the warning be suppressed or emitted.

        Args:
          warning: The name of the warning being tested.

        Returns:
          True if the warning should be suppressed, False otherwise.
        """
        warnings = self.get_user_option_as_list("suppress_warnings")
        return not (warnings is None or warning not in warnings)

    def get_merge_tools(self):
        tools = {}
        for oname, _value, _section, _conf_id, _parser in self._get_options():
            if oname.startswith("bzr.mergetool."):
                tool_name = oname[len("bzr.mergetool.") :]
                tools[tool_name] = self.get_user_option(oname, False)
        trace.mutter(f"loaded merge tools: {tools!r}")
        return tools

    def find_merge_tool(self, name):
        from .mergetools import known_merge_tools

        # We fake a defaults mechanism here by checking if the given name can
        # be found in the known_merge_tools if it's not found in the config.
        # This should be done through the proposed config defaults mechanism
        # when it becomes available in the future.
        command_line = self.get_user_option(
            f"bzr.mergetool.{name}", expand=False
        ) or known_merge_tools.get(name, None)
        return command_line


class _ConfigHooks(hooks.Hooks):
    """A dict mapping hook names and a list of callables for configs."""

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        super().__init__("breezy.config", "ConfigHooks")
        self.add_hook(
            "load",
            "Invoked when a config store is loaded. The signature is (store).",
            (2, 4),
        )
        self.add_hook(
            "save",
            "Invoked when a config store is saved. The signature is (store).",
            (2, 4),
        )
        # The hooks for config options
        self.add_hook(
            "get",
            "Invoked when a config option is read."
            " The signature is (stack, name, value).",
            (2, 4),
        )
        self.add_hook(
            "set",
            "Invoked when a config option is set."
            " The signature is (stack, name, value).",
            (2, 4),
        )
        self.add_hook(
            "remove",
            "Invoked when a config option is removed. The signature is (stack, name).",
            (2, 4),
        )


ConfigHooks = _ConfigHooks()


class _OldConfigHooks(hooks.Hooks):
    """A dict mapping hook names and a list of callables for configs."""

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        super().__init__("breezy.config", "OldConfigHooks")
        self.add_hook(
            "load",
            "Invoked when a config store is loaded. The signature is (config).",
            (2, 4),
        )
        self.add_hook(
            "save",
            "Invoked when a config store is saved. The signature is (config).",
            (2, 4),
        )
        # The hooks for config options
        self.add_hook(
            "get",
            "Invoked when a config option is read."
            " The signature is (config, name, value).",
            (2, 4),
        )
        self.add_hook(
            "set",
            "Invoked when a config option is set."
            " The signature is (config, name, value).",
            (2, 4),
        )
        self.add_hook(
            "remove",
            "Invoked when a config option is removed. The signature is (config, name).",
            (2, 4),
        )


OldConfigHooks = _OldConfigHooks()


class IniBasedConfig(Config):
    """A configuration policy that draws from ini files."""

    def __init__(self, file_name=None):
        """Base class for configuration files using an ini-like syntax.

        Args:
          file_name: The configuration file path.
        """
        super().__init__()
        self.file_name = file_name
        self.file_name = file_name
        self._content = None
        self._parser = None

    @classmethod
    def from_string(cls, str_or_unicode, file_name=None, save=False):
        """Create a config object from a string.

        Args:
          str_or_unicode: A string representing the file content. This
            will be utf-8 encoded.
          file_name: The configuration file path.
          _save: Whether the file should be saved upon creation.
        """
        conf = cls(file_name=file_name)
        conf._create_from_string(str_or_unicode, save)
        return conf

    def _create_from_string(self, str_or_unicode, save):
        if isinstance(str_or_unicode, str):
            str_or_unicode = str_or_unicode.encode("utf-8")
        self._content = BytesIO(str_or_unicode)
        # Some tests use in-memory configs, some other always need the config
        # file to exist on disk.
        if save:
            self._write_config_file()

    def _get_parser(self):
        if self._parser is not None:
            return self._parser
        if self._content is not None:
            co_input = self._content
        elif self.file_name is None:
            raise AssertionError("We have no content to create the config")
        else:
            co_input = str(self.file_name)
        try:
            self._parser = ConfigObj(co_input, encoding="utf-8")
        except configobj.ConfigObjError as e:
            raise ParseConfigError(e.errors, e.config.filename) from e
        except UnicodeDecodeError as e:
            raise ConfigContentError(self.file_name) from e
        # Make sure self.reload() will use the right file name
        self._parser.filename = self.file_name
        for hook in OldConfigHooks["load"]:
            hook(self)
        return self._parser

    def reload(self):
        """Reload the config file from disk."""
        if self.file_name is None:
            raise AssertionError("We need a file name to reload the config")
        if self._parser is not None:
            self._parser.reload()
        for hook in ConfigHooks["load"]:
            hook(self)

    def _get_matching_sections(self):
        """Return an ordered list of (section_name, extra_path) pairs.

        If the section contains inherited configuration, extra_path is
        a string containing the additional path components.
        """
        section = self._get_section()
        if section is not None:
            return [(section, "")]
        else:
            return []

    def _get_section(self):
        """Override this to define the section used by the config."""
        return "DEFAULT"

    def _get_sections(self, name=None):
        """Returns an iterator of the sections specified by ``name``.

        Args:
          name: The section name. If None is supplied, the default
            configurations are yielded.

        Returns:
          A tuple (name, section, config_id) for all sections that will
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

        Args:
          sections: Default to ``_get_matching_sections`` if not
             specified. This gives a better control to daughter classes about
             which sections should be searched. This is a list of (name,
             configobj) tuples.
        """
        if sections is None:
            parser = self._get_parser()
            sections = []
            for section_name, _ in self._get_matching_sections():
                try:
                    section = parser[section_name]
                except KeyError:
                    # This could happen for an empty file for which we define a
                    # DEFAULT section. FIXME: Force callers to provide sections
                    # instead ? -- vila 20100930
                    continue
                sections.append((section_name, section))
        config_id = self.config_id()
        for section_name, section in sections:
            for name, value in section.iteritems():
                yield (name, parser._quote(value), section_name, config_id, parser)

    def _get_option_policy(self, section, option_name):
        """Return the policy for the given (section, option_name) pair."""
        return POLICY_NONE

    def _get_change_editor(self):
        return self.get_user_option("change_editor", expand=False)

    def _get_signature_checking(self):
        """See Config._get_signature_checking."""
        policy = self._get_user_option("check_signatures")
        if policy:
            return signature_policy_from_unicode(policy)

    def _get_signing_policy(self):
        """See Config._get_signing_policy."""
        policy = self._get_user_option("create_signatures")
        if policy:
            return signing_policy_from_unicode(policy)

    def _get_user_id(self):
        """Get the user id from the 'email' key in the current section."""
        return self._get_user_option("email")

    def _get_user_option(self, option_name):
        """See Config._get_user_option."""
        for section, extra_path in self._get_matching_sections():
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
                raise AssertionError(f"Unexpected config policy {policy!r}")
        else:
            return None

    def _log_format(self):
        """See Config.log_format."""
        return self._get_user_option("log_format")

    def _validate_signatures_in_log(self):
        """See Config.validate_signatures_in_log."""
        return self._get_user_option("validate_signatures_in_log")

    def _acceptable_keys(self):
        """See Config.acceptable_keys."""
        return self._get_user_option("acceptable_keys")

    def _post_commit(self):
        """See Config.post_commit."""
        return self._get_user_option("post_commit")

    def _get_alias(self, value):
        try:
            return self._get_parser().get_value("ALIASES", value)
        except KeyError:
            pass

    def _get_nickname(self):
        return self.get_user_option("nickname")

    def remove_user_option(self, option_name, section_name=None):
        """Remove a user option and save the configuration file.

        Args:
          option_name: The option to be removed.
          section_name: The section the option is defined in, default to
            the default section.
        """
        self.reload()
        parser = self._get_parser()
        section = parser if section_name is None else parser[section_name]
        try:
            del section[option_name]
        except KeyError as e:
            raise NoSuchConfigOption(option_name) from e
        self._write_config_file()
        for hook in OldConfigHooks["remove"]:
            hook(self, option_name)

    def _write_config_file(self):
        if self.file_name is None:
            raise AssertionError("We cannot save, self.file_name is None")
        from . import atomicfile

        conf_dir = os.path.dirname(self.file_name)
        bedding.ensure_config_dir_exists(conf_dir)
        with atomicfile.AtomicFile(self.file_name) as atomic_file:
            self._get_parser().write(atomic_file)
        osutils.copy_ownership_from_path(self.file_name)
        for hook in OldConfigHooks["save"]:
            hook(self)


class LockableConfig(IniBasedConfig):
    """A configuration needing explicit locking for access.

    If several processes try to write the config file, the accesses need to be
    serialized.

    Daughter classes should use the self.lock_write() decorator method when
    they upate a config (they call, directly or indirectly, the
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

    lock_name = "lock"

    def __init__(self, file_name):
        """Initialize a lockable configuration.

        Args:
            file_name: Path to the configuration file.
        """
        super().__init__(file_name=file_name)
        self.dir = osutils.dirname(osutils.safe_unicode(self.file_name))
        # FIXME: It doesn't matter that we don't provide possible_transports
        # below since this is currently used only for local config files ;
        # local transports are not shared. But if/when we start using
        # LockableConfig for other kind of transports, we will need to reuse
        # whatever connection is already established -- vila 20100929
        self.transport = transport.get_transport_from_path(self.dir)
        self._lock = lockdir.LockDir(self.transport, self.lock_name)

    def _create_from_string(self, unicode_bytes, save):
        super()._create_from_string(unicode_bytes, False)
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
        bedding.ensure_config_dir_exists(self.dir)
        token = self._lock.lock_write(token)
        return lock.LogicalLockResult(self.unlock, token)

    def unlock(self):
        self._lock.unlock()

    def break_lock(self):
        self._lock.break_lock()

    def remove_user_option(self, option_name, section_name=None):
        with self.lock_write():
            super().remove_user_option(option_name, section_name)

    def _write_config_file(self):
        if self._lock is None or not self._lock.is_held:
            # NB: if the following exception is raised it probably means a
            # missing call to lock_write() by one of the callers.
            raise errors.ObjectNotLocked(self)
        super()._write_config_file()


class GlobalConfig(LockableConfig):
    """The configuration that should be used for a specific location."""

    def __init__(self):
        super().__init__(file_name=bedding.config_path())

    def config_id(self):
        return "breezy"

    @classmethod
    def from_string(cls, str_or_unicode, save=False):
        """Create a config object from a string.

        Args:
          str_or_unicode: A string representing the file content. This
            will be utf-8 encoded.
          save: Whether the file should be saved upon creation.
        """
        conf = cls()
        conf._create_from_string(str_or_unicode, save)
        return conf

    def set_user_option(self, option, value):
        """Save option and its value in the configuration."""
        with self.lock_write():
            self._set_option(option, value, "DEFAULT")

    def get_aliases(self):
        """Return the aliases section."""
        if "ALIASES" in self._get_parser():
            return self._get_parser()["ALIASES"]
        else:
            return {}

    def set_alias(self, alias_name, alias_command):
        """Save the alias in the configuration."""
        with self.lock_write():
            self._set_option(alias_name, alias_command, "ALIASES")

    def unset_alias(self, alias_name):
        """Unset an existing alias."""
        with self.lock_write():
            self.reload()
            aliases = self._get_parser().get("ALIASES")
            if not aliases or alias_name not in aliases:
                raise NoSuchAlias(alias_name)
            del aliases[alias_name]
            self._write_config_file()

    def _set_option(self, option, value, section):
        self.reload()
        self._get_parser().setdefault(section, {})[option] = value
        self._write_config_file()
        for hook in OldConfigHooks["set"]:
            hook(self, option, value)

    def _get_sections(self, name=None):
        """See IniBasedConfig._get_sections()."""
        parser = self._get_parser()
        # We don't give access to options defined outside of any section, we
        # used the DEFAULT section by... default.
        if name in (None, "DEFAULT"):
            # This could happen for an empty file where the DEFAULT section
            # doesn't exist yet. So we force DEFAULT when yielding
            name = "DEFAULT"
            if "DEFAULT" not in parser:
                parser["DEFAULT"] = {}
        yield (name, parser[name], self.config_id())

    def remove_user_option(self, option_name, section_name=None):
        if section_name is None:
            # We need to force the default section.
            section_name = "DEFAULT"
        with self.lock_write():
            # We need to avoid the LockableConfig implementation or we'll lock
            # twice
            super(LockableConfig, self).remove_user_option(option_name, section_name)


def _iter_for_location_by_parts(sections, location):
    """Keep only the sessions matching the specified location.

    Args:
      sections: An iterable of section names.
      location: An url or a local path to match against.

    Returns:
      An iterator of (section, extra_path, nb_parts) where nb is the
      number of path components in the section name, section is the section
      name and extra_path is the difference between location and the section
      name.

    ``location`` will always be a local path and never a 'file://' url but the
    section names themselves can be in either form.
    """
    import fnmatch

    location_parts = location.rstrip("/").split("/")

    for section in sections:
        # location is a local path if possible, so we need to convert 'file://'
        # urls in section names to local paths if necessary.

        # This also avoids having file:///path be a more exact
        # match than '/path'.

        # FIXME: This still raises an issue if a user defines both file:///path
        # *and* /path. Should we raise an error in this case -- vila 20110505

        if section.startswith("file://"):
            section_path = urlutils.local_path_from_url(section)
        else:
            section_path = section
        section_parts = section_path.rstrip("/").split("/")

        matched = True
        if len(section_parts) > len(location_parts):
            # More path components in the section, they can't match
            matched = False
        else:
            # Rely on zip truncating in length to the length of the shortest
            # argument sequence.
            for name in zip(location_parts, section_parts):
                if not fnmatch.fnmatch(name[0], name[1]):
                    matched = False
                    break
        if not matched:
            continue
        # build the path difference between the section and the location
        extra_path = "/".join(location_parts[len(section_parts) :])
        yield section, extra_path, len(section_parts)


class LocationConfig(LockableConfig):
    """A configuration object that gives the policy for a location."""

    def __init__(self, location):
        super().__init__(file_name=bedding.locations_config_path())
        # local file locations are looked up by local path, rather than
        # by file url. This is because the config file is a user
        # file, and we would rather not expose the user to file urls.
        if location.startswith("file://"):
            location = urlutils.local_path_from_url(location)
        self.location = location

    def config_id(self):
        return "locations"

    @classmethod
    def from_string(cls, str_or_unicode, location, save=False):
        """Create a config object from a string.

        Args:
          str_or_unicode: A string representing the file content. This will
            be utf-8 encoded.
          location: The location url to filter the configuration.
          save: Whether the file should be saved upon creation.
        """
        conf = cls(location)
        conf._create_from_string(str_or_unicode, save)
        return conf

    def _get_matching_sections(self):
        """Return an ordered list of section names matching this location."""
        # put the longest (aka more specific) locations first
        matches = sorted(
            _iter_for_location_by_parts(self._get_parser(), self.location),
            key=lambda match: (match[2], match[0]),
            reverse=True,
        )
        for section, extra_path, _length in matches:
            yield section, extra_path
            # should we stop looking for parent configs here?
            try:
                if self._get_parser()[section].as_bool("ignore_parents"):
                    break
            except KeyError:
                pass

    def _get_sections(self, name=None):
        """See IniBasedConfig._get_sections()."""
        # We ignore the name here as the only sections handled are named with
        # the location path and we don't expose embedded sections either.
        parser = self._get_parser()
        for name, _extra_path in self._get_matching_sections():
            yield (name, parser[name], self.config_id())

    def _get_option_policy(self, section, option_name):
        """Return the policy for the given (section, option_name) pair."""
        # check for the old 'recurse=False' flag
        try:
            recurse = self._get_parser()[section].as_bool("recurse")
        except KeyError:
            recurse = True
        if not recurse:
            return POLICY_NORECURSE

        policy_key = option_name + ":policy"
        try:
            policy_name = self._get_parser()[section][policy_key]
        except KeyError:
            policy_name = None

        return _policy_value[policy_name]

    def _set_option_policy(self, section, option_name, option_policy):
        """Set the policy for the given option name in the given section."""
        policy_key = option_name + ":policy"
        policy_name = _policy_name[option_policy]
        if policy_name is not None:
            self._get_parser()[section][policy_key] = policy_name
        else:
            if policy_key in self._get_parser()[section]:
                del self._get_parser()[section][policy_key]

    def set_user_option(self, option, value, store=STORE_LOCATION):
        """Save option and its value in the configuration."""
        if store not in [
            STORE_LOCATION,
            STORE_LOCATION_NORECURSE,
            STORE_LOCATION_APPENDPATH,
        ]:
            raise ValueError(f"bad storage policy {store!r} for {option!r}")
        with self.lock_write():
            self.reload()
            location = self.location
            if location.endswith("/"):
                location = location[:-1]
            parser = self._get_parser()
            if location not in parser and location + "/" not in parser:
                parser[location] = {}
            elif location + "/" in parser:
                location = location + "/"
            parser[location][option] = value
            # the allowed values of store match the config policies
            self._set_option_policy(location, option, store)
            self._write_config_file()
            for hook in OldConfigHooks["set"]:
                hook(self, option, value)


class BranchConfig(Config):
    """A configuration object giving the policy for a branch."""

    def __init__(self, branch):
        super().__init__()
        self._location_config = None
        self._branch_data_config = None
        self._global_config = None
        self.branch = branch
        self.option_sources = (
            self._get_location_config,
            self._get_branch_data_config,
            self._get_global_config,
        )

    def config_id(self):
        return "branch"

    def _get_branch_data_config(self):
        if self._branch_data_config is None:
            self._branch_data_config = TreeConfig(self.branch)
            self._branch_data_config.config_id = self.config_id
        return self._branch_data_config

    def _get_location_config(self):
        if self._location_config is None:
            if self.branch.base is None:
                self.branch.base = "memory://"
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
        return self._get_best_value("_get_user_id")

    def _get_change_editor(self):
        return self._get_best_value("_get_change_editor")

    def _get_signature_checking(self):
        """See Config._get_signature_checking."""
        return self._get_best_value("_get_signature_checking")

    def _get_signing_policy(self):
        """See Config._get_signing_policy."""
        return self._get_best_value("_get_signing_policy")

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
            yield from source()._get_sections(name)

    def _get_options(self, sections=None):
        # First the locations options
        yield from self._get_location_config()._get_options()
        # Then the branch options
        branch_config = self._get_branch_data_config()
        if sections is None:
            sections = [("DEFAULT", branch_config._get_parser())]
        # FIXME: We shouldn't have to duplicate the code in IniBasedConfig but
        # Config itself has no notion of sections :( -- vila 20101001
        config_id = self.config_id()
        for section_name, section in sections:
            for name, value in section.iteritems():
                yield (
                    name,
                    value,
                    section_name,
                    config_id,
                    branch_config._get_parser(),
                )
        # Then the global options
        yield from self._get_global_config()._get_options()

    def set_user_option(self, name, value, store=STORE_BRANCH, warn_masked=False):
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
                trace.warning(
                    'Value "%s" is masked by "%s" from locations.conf',
                    value,
                    mask_value,
                )
            else:
                if store == STORE_GLOBAL:
                    branch_config = self._get_branch_data_config()
                    mask_value = branch_config.get_user_option(name)
                    if mask_value is not None:
                        trace.warning(
                            'Value "%s" is masked by "%s" from branch.conf',
                            value,
                            mask_value,
                        )

    def remove_user_option(self, option_name, section_name=None):
        self._get_branch_data_config().remove_option(option_name, section_name)

    def _post_commit(self):
        """See Config.post_commit."""
        return self._get_safe_value("_post_commit")

    def _get_nickname(self):
        value = self._get_explicit_nickname()
        if value is not None:
            return value
        if self.branch.name:
            return self.branch.name
        return urlutils.unescape(self.branch.base.split("/")[-2])

    def has_explicit_nickname(self):
        """Return true if a nickname has been explicitly assigned."""
        return self._get_explicit_nickname() is not None

    def _get_explicit_nickname(self):
        return self._get_best_value("_get_nickname")

    def _log_format(self):
        """See Config.log_format."""
        return self._get_best_value("_log_format")

    def _validate_signatures_in_log(self):
        """See Config.validate_signatures_in_log."""
        return self._get_best_value("_validate_signatures_in_log")

    def _acceptable_keys(self):
        """See Config.acceptable_keys."""
        return self._get_best_value("_acceptable_keys")


_username_re = lazy_regex.lazy_compile(r"(.*?)\s*<?([\[\]\w+.-]+@[\w+.-]+)>?")


def parse_username(username):
    """Parse e-mail username and return a (name, address) tuple."""
    match = _username_re.match(username)
    if match is None:
        return (username, "")
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
        raise NoEmailInUsername(e)
    return email


class TreeConfig(IniBasedConfig):
    """Branch configuration data associated with its contents, not location."""

    # XXX: Really needs a better name, as this is not part of the tree!
    # -- mbp 20080507

    def __init__(self, branch):
        self._config = branch._get_config()
        self.branch = branch

    def _get_parser(self, file=None):
        if file is not None:
            return IniBasedConfig._get_parser(file)
        return self._config._get_configobj()

    def get_option(self, name, section=None, default=None):
        with self.branch.lock_read():
            return self._config.get_option(name, section, default)

    def set_option(self, value, name, section=None):
        """Set a per-branch configuration option."""
        # FIXME: We shouldn't need to lock explicitly here but rather rely on
        # higher levels providing the right lock -- vila 20101004
        with self.branch.lock_write():
            self._config.set_option(value, name, section)

    def remove_option(self, option_name, section_name=None):
        # FIXME: We shouldn't need to lock explicitly here but rather rely on
        # higher levels providing the right lock -- vila 20101004
        with self.branch.lock_write():
            self._config.remove_option(option_name, section_name)


_authentication_config_permission_errors = set()


class AuthenticationConfig:
    """The authentication configuration file based on a ini file.

    Implements the authentication.conf file described in
    doc/developers/authentication-ring.txt.
    """

    def __init__(self, _file=None):
        self._config = None  # The ConfigObj
        if _file is None:
            self._input = self._filename = bedding.authentication_config_path()
            self._check_permissions()
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
            self._config = ConfigObj(self._input, encoding="utf-8")
        except configobj.ConfigObjError as e:
            raise ParseConfigError(e.errors, e.config.filename) from e
        except UnicodeError as e:
            raise ConfigContentError(self._filename) from e
        return self._config

    def _check_permissions(self):
        """Check permission of auth file are user read/write able only."""
        import stat

        try:
            st = os.stat(self._filename)
        except FileNotFoundError:
            return
        except OSError as e:
            trace.mutter("Unable to stat %r: %r", self._filename, e)
            return
        mode = stat.S_IMODE(st.st_mode)
        if (
            stat.S_IXOTH
            | stat.S_IWOTH
            | stat.S_IROTH
            | stat.S_IXGRP
            | stat.S_IWGRP
            | stat.S_IRGRP
        ) & mode:
            # Only warn once
            if (
                self._filename not in _authentication_config_permission_errors
                and not GlobalConfig().suppress_warning("insecure_permissions")
            ):
                trace.warning(
                    "The file '%s' has insecure "
                    "file permissions. Saved passwords may be accessible "
                    "by other users.",
                    self._filename,
                )
                _authentication_config_permission_errors.add(self._filename)

    def _save(self):
        """Save the config file, only tests should use it for now."""
        conf_dir = os.path.dirname(self._filename)
        bedding.ensure_config_dir_exists(conf_dir)
        fd = os.open(self._filename, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            f = os.fdopen(fd, "wb")
            self._get_config().write(f)
        finally:
            f.close()

    def _set_option(self, section_name, option_name, value):
        """Set an authentication configuration option."""
        conf = self._get_config()
        section = conf.get(section_name)
        if section is None:
            conf[section_name] = {}
            section = conf[section_name]
        section[option_name] = value
        self._save()

    def get_credentials(
        self, scheme, host, port=None, user=None, path=None, realm=None
    ):
        """Returns the matching credentials from authentication.conf file.

        Args:
          scheme: protocol
          host: the server address
          port: the associated port (optional)
          user: login (optional)
          path: the absolute path on the server (optional)
          realm: the http authentication realm (optional)

        Returns:
          A dict containing the matching credentials or None.
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
        for auth_def_name, auth_def in self._get_config().iteritems():
            if not isinstance(auth_def, configobj.Section):
                raise ValueError(f"{auth_def_name} defined outside a section")

            a_scheme, a_host, a_user, a_path = map(
                auth_def.get, ["scheme", "host", "user", "path"]
            )

            try:
                a_port = auth_def.as_int("port")
            except KeyError:
                a_port = None
            except ValueError as e:
                raise ValueError(f"'port' not numeric in {auth_def_name}") from e
            try:
                a_verify_certificates = auth_def.as_bool("verify_certificates")
            except KeyError:
                a_verify_certificates = True
            except ValueError as e:
                raise ValueError(
                    f"'verify_certificates' not boolean in {auth_def_name}"
                ) from e

            # Attempt matching
            if a_scheme is not None and scheme != a_scheme:
                continue
            if a_host is not None and not (
                host == a_host or (a_host.startswith(".") and host.endswith(a_host))
            ):
                continue
            if a_port is not None and port != a_port:
                continue
            if a_path is not None and path is not None and not path.startswith(a_path):
                continue
            if a_user is not None and user is not None and a_user != user:
                # Never contradict the caller about the user to be used
                continue
            if a_user is None:
                # Can't find a user
                continue
            # Prepare a credentials dictionary with additional keys
            # for the credential providers
            credentials = {
                "name": auth_def_name,
                "user": a_user,
                "scheme": a_scheme,
                "host": host,
                "port": port,
                "path": path,
                "realm": realm,
                "password": auth_def.get("password", None),
                "verify_certificates": a_verify_certificates,
            }
            # Decode the password in the credentials (or get one)
            self.decode_password(credentials, auth_def.get("password_encoding", None))
            if debug.debug_flag_enabled("auth"):
                trace.mutter("Using authentication section: %r", auth_def_name)
            break

        if credentials is None:
            # No credentials were found in authentication.conf, try the fallback
            # credentials stores.
            credentials = credential_store_registry.get_fallback_credentials(
                scheme, host, port, user, path, realm
            )

        return credentials

    def set_credentials(
        self,
        name,
        host,
        user,
        scheme=None,
        password=None,
        port=None,
        path=None,
        verify_certificates=None,
        realm=None,
    ):
        """Set authentication credentials for a host.

        Any existing credentials with matching scheme, host, port and path
        will be deleted, regardless of name.

        Args:
          name: An arbitrary name to describe this set of credentials.
          host: Name of the host that accepts these credentials.
          user: The username portion of these credentials.
          scheme: The URL scheme (e.g. ssh, http) the credentials apply to.
          password: Password portion of these credentials.
          port: The IP port on the host that these credentials apply to.
          path: A filesystem path on the host that these credentials apply to.
          verify_certificates: On https, verify server certificates if True.
          realm: The http authentication realm (optional).
        """
        values = {"host": host, "user": user}
        if password is not None:
            values["password"] = password
        if scheme is not None:
            values["scheme"] = scheme
        if port is not None:
            values["port"] = "%d" % port
        if path is not None:
            values["path"] = path
        if verify_certificates is not None:
            values["verify_certificates"] = str(verify_certificates)
        if realm is not None:
            values["realm"] = realm
        config = self._get_config()
        for section, existing_values in config.iteritems():
            for key in ("scheme", "host", "port", "path", "realm"):
                if existing_values.get(key) != values.get(key):
                    break
            else:
                del config[section]
        config.update({name: values})
        self._save()

    def get_user(
        self,
        scheme,
        host,
        port=None,
        realm=None,
        path=None,
        prompt=None,
        ask=False,
        default=None,
    ):
        """Get a user from authentication file.

        Args:
          scheme: protocol
          host: the server address
          port: the associated port (optional)
          realm: the realm sent by the server (optional)
          path: the absolute path on the server (optional)
          ask: Ask the user if there is no explicitly configured username
                    (optional)
          default: The username returned if none is defined (optional).

        Returns:
          The found user.
        """
        credentials = self.get_credentials(
            scheme, host, port, user=None, path=path, realm=realm
        )
        user = credentials["user"] if credentials is not None else None
        if user is None:
            if ask:
                if prompt is None:
                    # Create a default prompt suitable for most cases
                    prompt = f"{scheme.upper()}" + " %(host)s username"
                # Special handling for optional fields in the prompt
                prompt_host = "%s:%d" % (host, port) if port is not None else host
                user = ui.ui_factory.get_username(prompt, host=prompt_host)
            else:
                user = default
        return user

    def get_password(
        self, scheme, host, user, port=None, realm=None, path=None, prompt=None
    ):
        """Get a password from authentication file or prompt the user for one.

        Args:
          scheme: protocol
          host: the server address
          port: the associated port (optional)
          user: login
          realm: the realm sent by the server (optional)
          path: the absolute path on the server (optional)

        Returns:
          The found password or the one entered by the user.
        """
        credentials = self.get_credentials(scheme, host, port, user, path, realm)
        if credentials is not None:
            password = credentials["password"]
            if password is not None and scheme == "ssh":
                trace.warning(
                    "password ignored in section [{}], use an ssh agent instead".format(
                        credentials["name"]
                    )
                )
                password = None
        else:
            password = None
        # Prompt user only if we could't find a password
        if password is None:
            if prompt is None:
                # Create a default prompt suitable for most cases
                prompt = f"{scheme.upper()}" + " %(user)s@%(host)s password"
            # Special handling for optional fields in the prompt
            prompt_host = "%s:%d" % (host, port) if port is not None else host
            password = ui.ui_factory.get_password(prompt, host=prompt_host, user=user)
        return password

    def decode_password(self, credentials, encoding):
        try:
            cs = credential_store_registry.get_credential_store(encoding)
        except KeyError as e:
            raise ValueError(f"{encoding!r} is not a known password_encoding") from e
        credentials["password"] = cs.decode_password(credentials)
        return credentials


class CredentialStoreRegistry(registry.Registry):
    """A class that registers credential stores.

    A credential store provides access to credentials via the password_encoding
    field in authentication.conf sections.

    Except for stores provided by brz itself, most stores are expected to be
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

    def get_fallback_credentials(
        self, scheme, host, port=None, user=None, path=None, realm=None
    ):
        """Request credentials from all fallback credentials stores.

        The first credentials store that can provide credentials wins.
        """
        credentials = None
        for name in self.keys():
            if not self.is_fallback(name):
                continue
            cs = self.get_credential_store(name)
            credentials = cs.get_credentials(scheme, host, port, user, path, realm)
            if credentials is not None:
                # We found some credentials
                break
        return credentials

    def register(self, key, obj, help=None, override_existing=False, fallback=False):
        """Register a new object to a name.

        Args:
          key: This is the key to use to request the object later.
          obj: The object to register.
          help: Help text for this entry. This may be a string or
                a callable. If it is a callable, it should take two
                parameters (registry, key): this registry and the key that
                the help was registered under.
          override_existing: Raise KeyErorr if False and something has
                already been registered for that key. If True, ignore if there
                is an existing key (always register the new value).
          fallback: Whether this credential store should be
                used as fallback.
        """
        return super().register(
            key, obj, help, info=fallback, override_existing=override_existing
        )

    def register_lazy(
        self,
        key,
        module_name,
        member_name,
        help=None,
        override_existing=False,
        fallback=False,
    ):
        """Register a new credential store to be loaded on request.

        Args:
          module_name: The python path to the module. Such as 'os.path'.
          member_name: The member of the module to return.  If empty or
                None, get() will return the module itself.
          help: Help text for this entry. This may be a string or
                a callable.
          override_existing: If True, replace the existing object
                with the new one. If False, if there is already something
                registered with the same key, raise a KeyError
          fallback: Whether this credential store should be
                used as fallback.
        """
        return super().register_lazy(
            key,
            module_name,
            member_name,
            help,
            info=fallback,
            override_existing=override_existing,
        )


credential_store_registry = CredentialStoreRegistry()


class CredentialStore:
    """An abstract class to implement storage for credentials."""

    def decode_password(self, credentials):
        """Returns a clear text password for the provided credentials."""
        raise NotImplementedError(self.decode_password)

    def get_credentials(
        self, scheme, host, port=None, user=None, path=None, realm=None
    ):
        """Return the matching credentials from this credential store.

        This method is only called on fallback credential stores.
        """
        raise NotImplementedError(self.get_credentials)


class PlainTextCredentialStore(CredentialStore):
    """Plain text credential store for the authentication.conf file."""

    def decode_password(self, credentials):
        """See CredentialStore.decode_password."""
        return credentials["password"]


credential_store_registry.register(
    "plain", PlainTextCredentialStore, help=PlainTextCredentialStore.__doc__
)
credential_store_registry.default_key = "plain"


class Base64CredentialStore(CredentialStore):
    """Base64 credential store for the authentication.conf file."""

    def decode_password(self, credentials):
        """See CredentialStore.decode_password."""
        # GZ 2012-07-28: Will raise binascii.Error if password is not base64,
        #                should probably propogate as something more useful.
        import base64

        return base64.standard_b64decode(credentials["password"])


credential_store_registry.register(
    "base64", Base64CredentialStore, help=Base64CredentialStore.__doc__
)


class BzrDirConfig:
    """Configuration manager for a Breezy control directory."""

    def __init__(self, bzrdir):
        """Initialize BzrDirConfig.

        Args:
            bzrdir: The control directory to manage config for.
        """
        self._bzrdir = bzrdir
        self._config = bzrdir._get_config()

    def set_default_stack_on(self, value):
        """Set the default stacking location.

        It may be set to a location, or None.

        This policy affects all branches contained by this control dir, except
        for those under repositories.
        """
        if self._config is None:
            raise errors.BzrError(f"Cannot set configuration in {self._bzrdir}")
        if value is None:
            self._config.set_option("", "default_stack_on")
        else:
            self._config.set_option(value, "default_stack_on")

    def get_default_stack_on(self):
        """Return the default stacking location.

        This will either be a location, or None.

        This policy affects all branches contained by this control dir, except
        for those under repositories.
        """
        if self._config is None:
            return None
        value = self._config.get_option("default_stack_on")
        if value == "":
            value = None
        return value


class TransportConfig:
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

        Args:
          name: The name of the value
          section: The section the option is in (if any)
          default: The value to return if the value is not set
        Returns: The value or default value
        """
        configobj = self._get_configobj()
        if section is None:
            section_obj = configobj
        else:
            try:
                section_obj = configobj[section]
            except KeyError:
                return default
        value = section_obj.get(name, default)
        for hook in OldConfigHooks["get"]:
            hook(self, name, value)
        return value

    def set_option(self, value, name, section=None):
        """Set the value associated with a named option.

        Args:
          value: The value to set
          name: The name of the value to set
          section: The section the option is in (if any)
        """
        configobj = self._get_configobj()
        if section is None:
            configobj[name] = value
        else:
            configobj.setdefault(section, {})[name] = value
        for hook in OldConfigHooks["set"]:
            hook(self, name, value)
        self._set_configobj(configobj)

    def remove_option(self, option_name, section_name=None):
        configobj = self._get_configobj()
        if section_name is None:
            del configobj[option_name]
        else:
            del configobj[section_name][option_name]
        for hook in OldConfigHooks["remove"]:
            hook(self, option_name)
        self._set_configobj(configobj)

    def _get_config_file(self):
        try:
            f = BytesIO(self._transport.get_bytes(self._filename))
            for hook in OldConfigHooks["load"]:
                hook(self)
            return f
        except transport.NoSuchFile:
            return BytesIO()
        except errors.PermissionDenied:
            trace.warning(
                "Permission denied while trying to open configuration file %s.",
                urlutils.unescape_for_display(
                    urlutils.join(self._transport.base, self._filename), "utf-8"
                ),
            )
            return BytesIO()

    def _external_url(self):
        return urlutils.join(self._transport.external_url(), self._filename)

    def _get_configobj(self):
        f = self._get_config_file()
        try:
            try:
                conf = ConfigObj(f, encoding="utf-8")
            except configobj.ConfigObjError as e:
                raise ParseConfigError(e.errors, self._external_url()) from e
            except UnicodeDecodeError as e:
                raise ConfigContentError(self._external_url()) from e
        finally:
            f.close()
        return conf

    def _set_configobj(self, configobj):
        out_file = BytesIO()
        configobj.write(out_file)
        out_file.seek(0)
        self._transport.put_file(self._filename, out_file)
        for hook in OldConfigHooks["save"]:
            hook(self)


class Option:
    """An option definition.

    The option *values* are stored in config files and found in sections.

    Here we define various properties about the option itself, its default
    value, how to convert it from stores, what to do when invalid values are
    encoutered, in which config files it can be stored.
    """

    def __init__(
        self,
        name,
        override_from_env=None,
        default=None,
        default_from_env=None,
        help=None,
        from_unicode=None,
        invalid=None,
        unquote=True,
    ):
        """Build an option definition.

        Args:
          name: the name used to refer to the option.

          override_from_env: A list of environment variables which can
           provide override any configuration setting.

          default: the default value to use when none exist in the config
            stores. This is either a string that ``from_unicode`` will convert
            into the proper type, a callable returning a unicode string so that
            ``from_unicode`` can be used on the return value, or a python
            object that can be stringified (so only the empty list is supported
            for example).

          default_from_env: A list of environment variables which can
           provide a default value. 'default' will be used only if none of the
           variables specified here are set in the environment.

          help: a doc string to explain the option to the user.

          from_unicode: a callable to convert the unicode string
            representing the option value in a store or its default value.

          invalid: the action to be taken when an invalid value is
            encountered in a store. This is called only when from_unicode is
            invoked to convert a string and returns None or raise ValueError or
            TypeError. Accepted values are: None (ignore invalid values),
            'warning' (emit a warning), 'error' (emit an error message and
            terminates).

          unquote: should the unicode value be unquoted before conversion.
           This should be used only when the store providing the values cannot
           safely unquote them (see http://pad.lv/906897). It is provided so
           daughter classes can handle the quoting themselves.
        """
        if override_from_env is None:
            override_from_env = []
        if default_from_env is None:
            default_from_env = []
        self.name = name
        self.override_from_env = override_from_env
        # Convert the default value to a unicode string so all values are
        # strings internally before conversion (via from_unicode) is attempted.
        if default is None:
            self.default = None
        elif isinstance(default, list):
            # Only the empty list is supported
            if default:
                raise AssertionError("Only empty lists are supported as default values")
            self.default = ","
        elif isinstance(default, (bytes, str, bool, int, float)):
            # Rely on python to convert strings, booleans and integers
            self.default = f"{default}"
        elif callable(default):
            self.default = default
        else:
            # other python objects are not expected
            raise AssertionError(f"{default!r} is not supported as a default value")
        self.default_from_env = default_from_env
        self._help = help
        self.from_unicode = from_unicode
        self.unquote = unquote
        if invalid and invalid not in ("warning", "error"):
            raise AssertionError(f"{invalid} not supported for 'invalid'")
        self.invalid = invalid

    @property
    def help(self):
        return self._help

    def convert_from_unicode(self, store, unicode_value):
        if self.unquote and store is not None and unicode_value is not None:
            unicode_value = store.unquote(unicode_value)
        if self.from_unicode is None or unicode_value is None:
            # Don't convert or nothing to convert
            return unicode_value
        try:
            converted = self.from_unicode(unicode_value)
        except (ValueError, TypeError):
            # Invalid values are ignored
            converted = None
        if converted is None and self.invalid is not None:
            # The conversion failed
            if self.invalid == "warning":
                trace.warning(
                    'Value "%s" is not valid for "%s"', unicode_value, self.name
                )
            elif self.invalid == "error":
                raise ConfigOptionValueError(self.name, unicode_value)
        return converted

    def get_override(self):
        value = None
        for var in self.override_from_env:
            try:
                # If the env variable is defined, its value takes precedence
                value = os.environ[var]
                break
            except KeyError:
                continue
        return value

    def get_default(self):
        value = None
        for var in self.default_from_env:
            try:
                # If the env variable is defined, its value is the default one
                value = os.environ[var]
                break
            except KeyError:
                continue
        if value is None:
            # Otherwise, fallback to the value defined at registration
            if callable(self.default):
                value = self.default()
                if not isinstance(value, str):
                    raise AssertionError(
                        f"Callable default value for '{self.name}' should be unicode"
                    )
            else:
                value = self.default
        return value

    def get_help_topic(self):
        return self.name

    def get_help_text(self, additional_see_also=None, plain=True):
        result = self.help
        from breezy import help_topics

        result += help_topics._format_see_also(additional_see_also)
        if plain:
            result = help_topics.help_as_plain_text(result)
        return result


# Predefined converters to get proper values from store


def bool_from_store(unicode_str):
    return ui.bool_from_string(unicode_str)


def int_from_store(unicode_str):
    return int(unicode_str)


_unit_suffixes = {"K": 10**3, "M": 10**6, "G": 10**9}


def int_SI_from_store(unicode_str):
    """Convert a human readable size in SI units, e.g 10MB into an integer.

    Accepted suffixes are K,M,G. It is case-insensitive and may be followed
    by a trailing b (i.e. Kb, MB). This is intended to be practical and not
    pedantic.

    Returns: Integer, expanded to its base-10 value if a proper SI unit is
        found, None otherwise.
    """
    regexp = "^(\\d+)(([" + "".join(_unit_suffixes) + "])b?)?$"
    p = re.compile(regexp, re.IGNORECASE)
    m = p.match(unicode_str)
    val = None
    if m is not None:
        val, _, unit = m.groups()
        val = int(val)
        if unit:
            try:
                coeff = _unit_suffixes[unit.upper()]
            except KeyError as e:
                raise ValueError(gettext("{0} is not an SI unit.").format(unit)) from e
            val *= coeff
    return val


def float_from_store(unicode_str):
    return float(unicode_str)


# Use an empty dict to initialize an empty configobj avoiding all parsing and
# encoding checks
_list_converter_config = configobj.ConfigObj(
    {}, encoding="utf-8", list_values=True, interpolation=False
)


class ListOption(Option):
    """Option definition for list values."""

    def __init__(
        self, name, default=None, default_from_env=None, help=None, invalid=None
    ):
        """A list Option definition.

        This overrides the base class so the conversion from a unicode string
        can take quoting into account.
        """
        super().__init__(
            name,
            default=default,
            default_from_env=default_from_env,
            from_unicode=self.from_unicode,
            help=help,
            invalid=invalid,
            unquote=False,
        )

    def from_unicode(self, unicode_str):
        if not isinstance(unicode_str, str):
            raise TypeError
        # Now inject our string directly as unicode. All callers got their
        # value from configobj, so values that need to be quoted are already
        # properly quoted.
        _list_converter_config.reset()
        _list_converter_config._parse([f"list={unicode_str}"])
        maybe_list = _list_converter_config["list"]
        if isinstance(maybe_list, str):
            if maybe_list:
                # A single value, most probably the user forgot (or didn't care
                # to add) the final ','
                l = [maybe_list]
            else:
                # The empty string, convert to empty list
                l = []
        else:
            # We rely on ConfigObj providing us with a list already
            l = maybe_list
        return l


class RegistryOption(Option):
    """Option for a choice from a registry."""

    def __init__(self, name, registry, default_from_env=None, help=None, invalid=None):
        """A registry based Option definition.

        This overrides the base class so the conversion from a unicode string
        can take quoting into account.
        """
        super().__init__(
            name,
            default=lambda: registry.default_key,
            default_from_env=default_from_env,
            from_unicode=self.from_unicode,
            help=help,
            invalid=invalid,
            unquote=False,
        )
        self.registry = registry

    def from_unicode(self, unicode_str):
        if not isinstance(unicode_str, str):
            raise TypeError
        try:
            return self.registry.get(unicode_str)
        except KeyError as e:
            raise ValueError(
                f"Invalid value {unicode_str} for {self.name}."
                "See help for a list of possible values."
            ) from e

    @property
    def help(self):
        ret = [self._help, "\n\nThe following values are supported:\n"]
        for key in self.registry.keys():
            ret.append(f" {key} - {self.registry.get_help(key)}\n")
        return "".join(ret)


_option_ref_re = lazy_regex.lazy_compile("({[^\\d\\W](?:\\.\\w|-\\w|\\w)*})")
"""Describes an expandable option reference.

We want to match the most embedded reference first.

I.e. for '{{foo}}' we will get '{foo}',
for '{bar{baz}}' we will get '{baz}'
"""


def iter_option_refs(string):
    # Split isolate refs so every other chunk is a ref
    is_ref = False
    for chunk in _option_ref_re.split(string):
        yield is_ref, chunk
        is_ref = not is_ref


class OptionRegistry(registry.Registry):
    """Register config options by their name.

    This overrides ``registry.Registry`` to simplify registration by acquiring
    some information from the option object itself.
    """

    def _check_option_name(self, option_name):
        """Ensures an option name is valid.

        Args:
          option_name: The name to validate.
        """
        if _option_ref_re.match("{{{}}}".format(option_name)) is None:
            raise IllegalOptionName(option_name)

    def register(self, option):
        """Register a new option to its name.

        Args:
          option: The option to register. Its name is used as the key.
        """
        self._check_option_name(option.name)
        super().register(option.name, option, help=option.help)

    def register_lazy(self, key, module_name, member_name):
        """Register a new option to be loaded on request.

        Args:
          key: the key to request the option later. Since the registration
            is lazy, it should be provided and match the option name.

          module_name: the python path to the module. Such as 'os.path'.

          member_name: the member of the module to return.  If empty or
                None, get() will return the module itself.
        """
        self._check_option_name(key)
        super().register_lazy(key, module_name, member_name)

    def get_help(self, key=None):
        """Get the help text associated with the given key."""
        option = self.get(key)
        the_help = option.help
        if callable(the_help):
            return the_help(self, key)
        return the_help


option_registry = OptionRegistry()


# Registered options in lexicographical order

option_registry.register(
    Option(
        "append_revisions_only",
        default=None,
        from_unicode=bool_from_store,
        invalid="warning",
        help="""\
Whether to only append revisions to the mainline.

If this is set to true, then it is not possible to change the
existing mainline of the branch.
""",
    )
)
option_registry.register(
    ListOption(
        "acceptable_keys",
        default=None,
        help="""\
List of GPG key patterns which are acceptable for verification.
""",
    )
)
option_registry.register(
    Option(
        "add.maximum_file_size",
        default="20MB",
        from_unicode=int_SI_from_store,
        help="""\
Size above which files should be added manually.

Files below this size are added automatically when using ``bzr add`` without
arguments.

A negative value means disable the size check.
""",
    )
)
option_registry.register(
    Option(
        "bound",
        default=None,
        from_unicode=bool_from_store,
        help="""\
Is the branch bound to ``bound_location``.

If set to "True", the branch should act as a checkout, and push each commit to
the bound_location.  This option is normally set by ``bind``/``unbind``.

See also: bound_location.
""",
    )
)
option_registry.register(
    Option(
        "bound_location",
        default=None,
        help="""\
The location that commits should go to when acting as a checkout.

This option is normally set by ``bind``.

See also: bound.
""",
    )
)
option_registry.register(
    Option(
        "branch.fetch_tags",
        default=False,
        from_unicode=bool_from_store,
        help="""\
Whether revisions associated with tags should be fetched.
""",
    )
)
option_registry.register_lazy(
    "transform.orphan_policy", "breezy.transform", "opt_transform_orphan"
)
option_registry.register(
    Option(
        "bzr.workingtree.worth_saving_limit",
        default=10,
        from_unicode=int_from_store,
        invalid="warning",
        help="""\
How many changes before saving the dirstate.

-1 means that we will never rewrite the dirstate file for only
stat-cache changes. Regardless of this setting, we will always rewrite
the dirstate file if a file is added/removed/renamed/etc. This flag only
affects the behavior of updating the dirstate file after we notice that
a file has been touched.
""",
    )
)
option_registry.register(
    Option(
        "bugtracker",
        default=None,
        help="""\
Default bug tracker to use.

This bug tracker will be used for example when marking bugs
as fixed using ``bzr commit --fixes``, if no explicit
bug tracker was specified.
""",
    )
)
option_registry.register(
    Option(
        "calculate_revnos",
        default=True,
        from_unicode=bool_from_store,
        help="""\
Calculate revision numbers if they are not known.

Always show revision numbers, even for branch formats that don't store them
natively (such as Git). Calculating the revision number requires traversing
the left hand ancestry of the branch and can be slow on very large branches.
""",
    )
)
option_registry.register(
    Option(
        "check_signatures",
        default=CHECK_IF_POSSIBLE,
        from_unicode=signature_policy_from_unicode,
        help="""\
GPG checking policy.

Possible values: require, ignore, check-available (default)

this option will control whether bzr will require good gpg
signatures, ignore them, or check them if they are
present.
""",
    )
)
option_registry.register(
    Option(
        "child_submit_format",
        help="""The preferred format of submissions to this branch.""",
    )
)
option_registry.register(
    Option(
        "child_submit_to", help="""Where submissions to this branch are mailed to."""
    )
)
option_registry.register(
    Option(
        "create_signatures",
        default=SIGN_WHEN_REQUIRED,
        from_unicode=signing_policy_from_unicode,
        help="""\
GPG Signing policy.

Possible values: always, never, when-required (default), when-possible

This option controls whether bzr will always create
gpg signatures or not on commits.
""",
    )
)
option_registry.register(
    Option(
        "dirstate.fdatasync",
        default=True,
        from_unicode=bool_from_store,
        help="""\
Flush dirstate changes onto physical disk?

If true (default), working tree metadata changes are flushed through the
OS buffers to physical disk.  This is somewhat slower, but means data
should not be lost if the machine crashes.  See also repository.fdatasync.
""",
    )
)
option_registry.register(
    ListOption("debug_flags", default=[], help="Debug flags to activate.")
)
option_registry.register(
    Option("default_format", default="2a", help="Format used when creating branches.")
)
option_registry.register(
    Option("editor", help="The command called to launch an editor to enter a message.")
)
option_registry.register(
    Option(
        "email",
        override_from_env=["BRZ_EMAIL", "BZR_EMAIL"],
        default=bedding.default_email,
        help="The users identity",
    )
)
option_registry.register(
    Option(
        "gpg_signing_key",
        default=None,
        help="""\
GPG key to use for signing.

This defaults to the first key associated with the users email.
""",
    )
)
option_registry.register(
    Option("language", help="Language to translate messages into.")
)
option_registry.register(
    Option(
        "locks.steal_dead",
        default=True,
        from_unicode=bool_from_store,
        help="""\
Steal locks that appears to be dead.

If set to True, bzr will check if a lock is supposed to be held by an
active process from the same user on the same machine. If the user and
machine match, but no process with the given PID is active, then bzr
will automatically break the stale lock, and create a new lock for
this process.
Otherwise, bzr will prompt as normal to break the lock.
""",
    )
)
option_registry.register(
    Option(
        "log_format",
        default="long",
        help="""\
Log format to use when displaying revisions.

Standard log formats are ``long``, ``short`` and ``line``. Additional formats
may be provided by plugins.
""",
    )
)
option_registry.register_lazy("mail_client", "breezy.mail_client", "opt_mail_client")
option_registry.register(
    Option(
        "output_encoding",
        help="Unicode encoding for output (terminal encoding if not specified).",
    )
)
option_registry.register(
    Option(
        "parent_location",
        default=None,
        help="""\
The location of the default branch for pull or merge.

This option is normally set when creating a branch, the first ``pull`` or by
``pull --remember``.
""",
    )
)
option_registry.register(
    Option(
        "post_commit",
        default=None,
        help="""\
Post commit functions.

An ordered list of python functions to call, separated by spaces.

Each function takes branch, rev_id as parameters.
""",
    )
)
option_registry.register_lazy("progress_bar", "breezy.ui.text", "opt_progress_bar")
option_registry.register(
    Option(
        "public_branch",
        default=None,
        help="""\
A publically-accessible version of this branch.

This implies that the branch setting this option is not publically-accessible.
Used and set by ``bzr send``.
""",
    )
)
option_registry.register(
    Option(
        "push_location",
        default=None,
        help="""\
The location of the default branch for push.

This option is normally set by the first ``push`` or ``push --remember``.
""",
    )
)
option_registry.register(
    Option(
        "push_strict",
        default=None,
        from_unicode=bool_from_store,
        help="""\
The default value for ``push --strict``.

If present, defines the ``--strict`` option default value for checking
uncommitted changes before sending a merge directive.
""",
    )
)
option_registry.register(
    Option(
        "repository.fdatasync",
        default=True,
        from_unicode=bool_from_store,
        help="""\
Flush repository changes onto physical disk?

If true (default), repository changes are flushed through the OS buffers
to physical disk.  This is somewhat slower, but means data should not be
lost if the machine crashes.  See also dirstate.fdatasync.
""",
    )
)
option_registry.register_lazy("smtp_server", "breezy.smtp_connection", "smtp_server")
option_registry.register_lazy(
    "smtp_password", "breezy.smtp_connection", "smtp_password"
)
option_registry.register_lazy(
    "smtp_username", "breezy.smtp_connection", "smtp_username"
)
option_registry.register(
    Option(
        "selftest.timeout",
        default="1200",
        from_unicode=int_from_store,
        help="Abort selftest if one test takes longer than this many seconds",
    )
)

option_registry.register(
    Option(
        "send_strict",
        default=None,
        from_unicode=bool_from_store,
        help="""\
The default value for ``send --strict``.

If present, defines the ``--strict`` option default value for checking
uncommitted changes before sending a bundle.
""",
    )
)

option_registry.register(
    Option(
        "serve.client_timeout",
        default=300.0,
        from_unicode=float_from_store,
        help="If we wait for a new request from a client for more than"
        " X seconds, consider the client idle, and hangup.",
    )
)
option_registry.register(
    Option(
        "ssh", default=None, override_from_env=["BRZ_SSH"], help="SSH vendor to use."
    )
)
option_registry.register(
    Option(
        "stacked_on_location",
        default=None,
        help="""The location where this branch is stacked on.""",
    )
)
option_registry.register(
    Option(
        "submit_branch",
        default=None,
        help="""\
The branch you intend to submit your current work to.

This is automatically set by ``bzr send`` and ``bzr merge``, and is also used
by the ``submit:`` revision spec.
""",
    )
)
option_registry.register(
    Option("submit_to", help="""Where submissions from this branch are mailed to.""")
)
option_registry.register(
    ListOption(
        "suppress_warnings", default=[], help="List of warning classes to suppress."
    )
)
option_registry.register(
    Option(
        "validate_signatures_in_log",
        default=False,
        from_unicode=bool_from_store,
        invalid="warning",
        help="""Whether to validate signatures in brz log.""",
    )
)
option_registry.register_lazy(
    "ssl.ca_certs", "breezy.transport.http", "opt_ssl_ca_certs"
)

option_registry.register_lazy(
    "ssl.cert_reqs", "breezy.transport.http", "opt_ssl_cert_reqs"
)


class Section:
    """A section defines a dict of option name => value.

    This is merely a read-only dict which can add some knowledge about the
    options. It is *not* a python dict object though and doesn't try to mimic
    its API.
    """

    def __init__(self, section_id, options):
        self.id = section_id
        # We re-use the dict-like object received
        self.options = options

    def get(self, name, default=None, expand=True):
        return self.options.get(name, default)

    def iter_option_names(self):
        yield from self.options.keys()

    def __repr__(self):
        """Return string representation of the section."""
        # Mostly for debugging use
        return f"<config.{self.__class__.__name__} id={self.id}>"


_NewlyCreatedOption = object()
"""Was the option created during the MutableSection lifetime"""
_DeletedOption = object()
"""Was the option deleted during the MutableSection lifetime"""


class MutableSection(Section):
    """A section allowing changes and keeping track of the original values."""

    def __init__(self, section_id, options):
        super().__init__(section_id, options)
        self.reset_changes()

    def set(self, name, value):
        if name not in self.options:
            # This is a new option
            self.orig[name] = _NewlyCreatedOption
        elif name not in self.orig:
            self.orig[name] = self.get(name, None)
        self.options[name] = value

    def remove(self, name):
        if name not in self.orig and name in self.options:
            self.orig[name] = self.get(name, None)
        del self.options[name]

    def reset_changes(self):
        self.orig = {}

    def apply_changes(self, dirty, store):
        """Apply option value changes.

        ``self`` has been reloaded from the persistent storage. ``dirty``
        contains the changes made since the previous loading.

        Args:
          dirty: the mutable section containing the changes.
          store: the store containing the section
        """
        for k, expected in dirty.orig.items():
            actual = dirty.get(k, _DeletedOption)
            reloaded = self.get(k, _NewlyCreatedOption)
            if actual is _DeletedOption:
                if k in self.options:
                    self.remove(k)
            else:
                self.set(k, actual)
            # Report concurrent updates in an ad-hoc way. This should only
            # occurs when different processes try to update the same option
            # which is not supported (as in: the config framework is not meant
            # to be used as a sharing mechanism).
            if expected != reloaded:
                if actual is _DeletedOption:
                    actual = "<DELETED>"
                if reloaded is _NewlyCreatedOption:
                    reloaded = "<CREATED>"
                if expected is _NewlyCreatedOption:
                    expected = "<CREATED>"
                # Someone changed the value since we get it from the persistent
                # storage.
                trace.warning(
                    gettext(
                        "Option {} in section {} of {} was changed"
                        " from {} to {}. The {} value will be saved."
                    ).format(
                        k, self.id, store.external_url(), expected, reloaded, actual
                    )
                )
        # No need to keep track of these changes
        self.reset_changes()


class Store:
    """Abstract interface to persistent storage for configuration options."""

    readonly_section_class = Section
    mutable_section_class = MutableSection

    def __init__(self):
        # Which sections need to be saved (by section id). We use a dict here
        # so the dirty sections can be shared by multiple callers.
        self.dirty_sections = {}

    def is_loaded(self):
        """Returns True if the Store has been loaded.

        This is used to implement lazy loading and ensure the persistent
        storage is queried only when needed.
        """
        raise NotImplementedError(self.is_loaded)

    def load(self):
        """Loads the Store from persistent storage."""
        raise NotImplementedError(self.load)

    def _load_from_string(self, bytes):
        """Create a store from a string in configobj syntax.

        Args:
          bytes: A string representing the file content.
        """
        raise NotImplementedError(self._load_from_string)

    def unload(self):
        """Unloads the Store.

        This should make is_loaded() return False. This is used when the caller
        knows that the persistent storage has changed or may have change since
        the last load.
        """
        raise NotImplementedError(self.unload)

    def quote(self, value):
        """Quote a configuration option value for storing purposes.

        This allows Stacks to present values as they will be stored.
        """
        return value

    def unquote(self, value):
        """Unquote a configuration option value into unicode.

        The received value is quoted as stored.
        """
        return value

    def save(self):
        """Saves the Store to persistent storage."""
        raise NotImplementedError(self.save)

    def _need_saving(self):
        return any(s.orig for s in self.dirty_sections.values())

    def apply_changes(self, dirty_sections):
        """Apply changes from dirty sections while checking for coherency.

        The Store content is discarded and reloaded from persistent storage to
        acquire up-to-date values.

        Dirty sections are MutableSection which kept track of the value they
        are expected to update.
        """
        # We need an up-to-date version from the persistent storage, unload the
        # store. The reload will occur when needed (triggered by the first
        # get_mutable_section() call below.
        self.unload()
        # Apply the changes from the preserved dirty sections
        for section_id, dirty in dirty_sections.items():
            clean = self.get_mutable_section(section_id)
            clean.apply_changes(dirty, self)
        # Everything is clean now
        self.dirty_sections = {}

    def save_changes(self):
        """Saves the Store to persistent storage if changes occurred.

        Apply the changes recorded in the mutable sections to a store content
        refreshed from persistent storage.
        """
        raise NotImplementedError(self.save_changes)

    def external_url(self):
        raise NotImplementedError(self.external_url)

    def get_sections(self):
        """Returns an ordered iterable of existing sections.

        Returns: An iterable of (store, section).
        """
        raise NotImplementedError(self.get_sections)

    def get_mutable_section(self, section_id=None):
        """Returns the specified mutable section.

        Args:
          section_id: The section identifier
        """
        raise NotImplementedError(self.get_mutable_section)

    def __repr__(self):
        """Return string representation of the section."""
        # Mostly for debugging use
        return f"<config.{self.__class__.__name__}({self.external_url()})>"


class CommandLineStore(Store):
    """A store to carry command line overrides for the config options."""

    def __init__(self, opts=None):
        super().__init__()
        if opts is None:
            opts = {}
        self.options = {}
        self.id = "cmdline"

    def _reset(self):
        # The dict should be cleared but not replaced so it can be shared.
        self.options.clear()

    def _from_cmdline(self, overrides):
        # Reset before accepting new definitions
        self._reset()
        for over in overrides:
            try:
                name, value = over.split("=", 1)
            except ValueError as e:
                raise errors.CommandError(
                    gettext("Invalid '%s', should be of the form 'name=value'")
                    % (over,)
                ) from e
            self.options[name] = value

    def external_url(self):
        # Not an url but it makes debugging easier and is never needed
        # otherwise
        return "cmdline"

    def get_sections(self):
        yield self, self.readonly_section_class(None, self.options)


class IniFileStore(Store):
    """A config Store using ConfigObj for storage.

    :ivar _config_obj: Private member to hold the ConfigObj instance used to
        serialize/deserialize the config file.
    """

    def __init__(self):
        """A config Store using ConfigObj for storage."""
        super().__init__()
        self._config_obj = None

    def is_loaded(self):
        return self._config_obj is not None

    def unload(self):
        self._config_obj = None
        self.dirty_sections = {}

    def _load_content(self):
        """Load the config file bytes.

        This should be provided by subclasses

        Returns:
          Byte string
        """
        raise NotImplementedError(self._load_content)

    def _save_content(self, content):
        """Save the config file bytes.

        This should be provided by subclasses

        Args:
          content: Config file bytes to write
        """
        raise NotImplementedError(self._save_content)

    def load(self):
        """Load the store from the associated file."""
        if self.is_loaded():
            return
        content = self._load_content()
        self._load_from_string(content)
        for hook in ConfigHooks["load"]:
            hook(self)

    def _load_from_string(self, bytes):
        """Create a config store from a string.

        Args:
          bytes: A string representing the file content.
        """
        co_input = BytesIO(bytes)
        try:
            # The config files are always stored utf8-encoded
            new_config_obj = ConfigObj(co_input, encoding="utf-8", list_values=False)
        except configobj.ConfigObjError as e:
            self._config_obj = None
            raise ParseConfigError(e.errors, self.external_url()) from e
        except UnicodeDecodeError as e:
            raise ConfigContentError(self.external_url()) from e

        if self._config_obj is not None:
            if new_config_obj != self._config_obj:
                raise AssertionError("ConfigObj instances are not equal")

        self._config_obj = new_config_obj

        if self._config_obj is not None:
            if new_config_obj != self._config_obj:
                raise AssertionError("ConfigObj instances are not equal")

        self._config_obj = new_config_obj

    def save_changes(self):
        if not self.is_loaded():
            # Nothing to save
            return
        if not self._need_saving():
            return
        # Preserve the current version
        dirty_sections = self.dirty_sections.copy()
        self.apply_changes(dirty_sections)
        # Save to the persistent storage
        self.save()

    def save(self):
        if not self.is_loaded():
            # Nothing to save
            return
        out = BytesIO()
        self._config_obj.write(out)
        self._save_content(out.getvalue())
        for hook in ConfigHooks["save"]:
            hook(self)

    def get_sections(self) -> Iterable[tuple[Store, Section]]:
        """Get the configobj section in the file order.

        Returns: An iterable of (store, section).
        """
        # We need a loaded store
        try:
            self.load()
        except (transport.NoSuchFile, errors.PermissionDenied):
            # If the file can't be read, there is no sections
            return
        cobj = self._config_obj
        if cobj.scalars:
            yield self, self.readonly_section_class(None, cobj)
        for section_name in cobj.sections:
            yield (self, self.readonly_section_class(section_name, cobj[section_name]))

    def get_mutable_section(self, section_id=None):
        # We need a loaded store
        try:
            self.load()
        except transport.NoSuchFile:
            # The file doesn't exist, let's pretend it was empty
            self._load_from_string(b"")
        if section_id in self.dirty_sections:
            # We already created a mutable section for this id
            return self.dirty_sections[section_id]
        if section_id is None:
            section = self._config_obj
        else:
            section = self._config_obj.setdefault(section_id, {})
        mutable_section = self.mutable_section_class(section_id, section)
        # All mutable sections can become dirty
        self.dirty_sections[section_id] = mutable_section
        return mutable_section

    def quote(self, value):
        try:
            # configobj conflates automagical list values and quoting
            self._config_obj.list_values = True
            return self._config_obj._quote(value)
        finally:
            self._config_obj.list_values = False

    def unquote(self, value):
        if value and isinstance(value, str):
            # _unquote doesn't handle None nor empty strings nor anything that
            # is not a string, really.
            value = self._config_obj._unquote(value)
        return value

    def external_url(self):
        # Since an IniFileStore can be used without a file (at least in tests),
        # it's better to provide something than raising a NotImplementedError.
        # All daughter classes are supposed to provide an implementation
        # anyway.
        return "In-Process Store, no URL"


class TransportIniFileStore(IniFileStore):
    """IniFileStore that loads files from a transport.

    :ivar transport: The transport object where the config file is located.

    :ivar file_name: The config file basename in the transport directory.
    """

    def __init__(self, transport, file_name):
        """A Store using a ini file on a Transport.

        Args:
          transport: The transport object where the config file is located.
          file_name: The config file basename in the transport directory.
        """
        super().__init__()
        self.transport = transport
        self.file_name = file_name

    def _load_content(self):
        try:
            return self.transport.get_bytes(self.file_name)
        except errors.PermissionDenied:
            trace.warning(
                "Permission denied while trying to load configuration store %s.",
                self.external_url(),
            )
            raise

    def _save_content(self, content):
        self.transport.put_bytes(self.file_name, content)

    def external_url(self):
        # FIXME: external_url should really accepts an optional relpath
        # parameter (bug #750169) :-/ -- vila 2011-04-04
        # The following will do in the interim but maybe we don't want to
        # expose a path here but rather a config ID and its associated
        # object </hand wawe>.
        return urlutils.join(
            self.transport.external_url(), urlutils.escape(self.file_name)
        )


# Note that LockableConfigObjStore inherits from ConfigObjStore because we need
# unlockable stores for use with objects that can already ensure the locking
# (think branches). If different stores (not based on ConfigObj) are created,
# they may face the same issue.


class LockableIniFileStore(TransportIniFileStore):
    """A ConfigObjStore using locks on save to ensure store integrity."""

    def __init__(self, transport, file_name, lock_dir_name=None):
        """A config Store using ConfigObj for storage.

        Args:
          transport: The transport object where the config file is located.
          file_name: The config file basename in the transport directory.
        """
        if lock_dir_name is None:
            lock_dir_name = "lock"
        self.lock_dir_name = lock_dir_name
        super().__init__(transport, file_name)
        self._lock = lockdir.LockDir(self.transport, self.lock_dir_name)

    def lock_write(self, token=None):
        """Takes a write lock in the directory containing the config file.

        If the directory doesn't exist it is created.
        """
        # FIXME: This doesn't check the ownership of the created directories as
        # ensure_config_dir_exists does. It should if the transport is local
        # -- vila 2011-04-06
        self.transport.create_prefix()
        token = self._lock.lock_write(token)
        return lock.LogicalLockResult(self.unlock, token)

    def unlock(self):
        self._lock.unlock()

    def break_lock(self):
        self._lock.break_lock()

    def save(self):
        with self.lock_write():
            # We need to be able to override the undecorated implementation
            self.save_without_locking()

    def save_without_locking(self):
        super().save()


# FIXME: global, breezy, shouldn't that be 'user' instead or even
# 'user_defaults' as opposed to 'user_overrides', 'system_defaults'
# (/etc/bzr/bazaar.conf) and 'system_overrides' ? -- vila 2011-04-05


# FIXME: Moreover, we shouldn't need classes for these stores either, factory
# functions or a registry will make it easier and clearer for tests, focusing
# on the relevant parts of the API that needs testing -- vila 20110503 (based
# on a poolie's remark)
class GlobalStore(LockableIniFileStore):
    """A config store for global options.

    There is a single GlobalStore for a given process.
    """

    def __init__(self, possible_transports=None):
        path, kind = bedding._config_dir()
        t = transport.get_transport_from_path(
            path, possible_transports=possible_transports
        )
        super().__init__(t, kind + ".conf")
        self.id = "breezy"


class LocationStore(LockableIniFileStore):
    """A config store for options specific to a location.

    There is a single LocationStore for a given process.
    """

    def __init__(self, possible_transports=None):
        t = transport.get_transport_from_path(
            bedding.config_dir(), possible_transports=possible_transports
        )
        super().__init__(t, "locations.conf")
        self.id = "locations"


class BranchStore(TransportIniFileStore):
    """A config store for branch options.

    There is a single BranchStore for a given branch.
    """

    def __init__(self, branch):
        super().__init__(branch.control_transport, "branch.conf")
        self.branch = branch
        self.id = "branch"


class ControlStore(LockableIniFileStore):
    """Configuration store for control directory settings."""

    def __init__(self, bzrdir):
        """Initialize ControlStore.

        Args:
            bzrdir: The control directory to manage config for.
        """
        super().__init__(bzrdir.transport, "control.conf", lock_dir_name="branch_lock")
        self.id = "control"


class SectionMatcher:
    """Select sections into a given Store.

    This is intended to be used to postpone getting an iterable of sections
    from a store.
    """

    def __init__(self, store):
        self.store = store

    def get_sections(self):
        # This is where we require loading the store so we can see all defined
        # sections.
        sections = self.store.get_sections()
        # Walk the revisions in the order provided
        for store, s in sections:
            if self.match(s):
                yield store, s

    def match(self, section):
        """Does the proposed section match.

        Args:
          section: A Section object.

        Returns:
          True if the section matches, False otherwise.
        """
        raise NotImplementedError(self.match)


class NameMatcher(SectionMatcher):
    """Matches configuration sections by exact name."""

    def __init__(self, store, section_id):
        """Initialize NameMatcher.

        Args:
            store: The configuration store to search.
            section_id: The section ID to match.
        """
        super().__init__(store)
        self.section_id = section_id

    def match(self, section):
        return section.id == self.section_id


class LocationSection(Section):
    """A section that provides location-specific variable expansion."""

    def __init__(self, section, extra_path, branch_name=None):
        """Initialize LocationSection.

        Args:
            section: The base section to extend.
            extra_path: Additional path information for expansion.
            branch_name: Optional branch name for expansion.
        """
        super().__init__(section.id, section.options)
        self.extra_path = extra_path
        if branch_name is None:
            branch_name = ""
        self.locals = {
            "relpath": extra_path,
            "basename": urlutils.basename(extra_path),
            "branchname": branch_name,
        }

    def get(self, name, default=None, expand=True):
        value = super().get(name, default)
        if value is not None and expand:
            policy_name = self.get(name + ":policy", None)
            policy = _policy_value.get(policy_name, POLICY_NONE)
            if policy == POLICY_APPENDPATH:
                value = urlutils.join(value, self.extra_path)
            # expand section local options right now (since POLICY_APPENDPATH
            # will never add options references, it's ok to expand after it).
            chunks = []
            for is_ref, chunk in iter_option_refs(value):
                if not is_ref:
                    chunks.append(chunk)
                else:
                    ref = chunk[1:-1]
                    if ref in self.locals:
                        chunks.append(self.locals[ref])
                    else:
                        chunks.append(chunk)
            value = "".join(chunks)
        return value


class StartingPathMatcher(SectionMatcher):
    """Select sections for a given location respecting the Store order."""

    # FIXME: Both local paths and urls can be used for section names as well as
    # ``location`` to stay consistent with ``LocationMatcher`` which itself
    # inherited the fuzziness from the previous ``LocationConfig``
    # implementation. We probably need to revisit which encoding is allowed for
    # both ``location`` and section names and how we normalize
    # them. http://pad.lv/85479, http://pad.lv/437009 and http://359320 are
    # related too. -- vila 2012-01-04

    def __init__(self, store, location):
        super().__init__(store)
        if location.startswith("file://"):
            location = urlutils.local_path_from_url(location)
        self.location = location

    def get_sections(self):
        """Get all sections matching ``location`` in the store.

        The most generic sections are described first in the store, then more
        specific ones can be provided for reduced scopes.

        The returned section are therefore returned in the reversed order so
        the most specific ones can be found first.
        """
        import fnmatch

        location_parts = self.location.rstrip("/").split("/")
        store = self.store
        # Later sections are more specific, they should be returned first
        for _, section in reversed(list(store.get_sections())):
            if section.id is None:
                # The no-name section is always included if present
                yield store, LocationSection(section, self.location)
                continue
            section_path = section.id
            if section_path.startswith("file://"):
                # the location is already a local path or URL, convert the
                # section id to the same format
                section_path = urlutils.local_path_from_url(section_path)
            if self.location.startswith(section_path) or fnmatch.fnmatch(
                self.location, section_path
            ):
                section_parts = section_path.rstrip("/").split("/")
                extra_path = "/".join(location_parts[len(section_parts) :])
                yield store, LocationSection(section, extra_path)


class LocationMatcher(SectionMatcher):
    """Matches configuration sections by location pattern."""

    def __init__(self, store, location):
        """Initialize LocationMatcher.

        Args:
            store: The configuration store to search.
            location: The location path to match against.
        """
        super().__init__(store)
        url, params = urlutils.split_segment_parameters(location)
        if location.startswith("file://"):
            location = urlutils.local_path_from_url(location)
        self.location = location
        branch_name = params.get("branch")
        if branch_name is None:
            self.branch_name = urlutils.basename(self.location)
        else:
            self.branch_name = urlutils.unescape(branch_name)

    def _get_matching_sections(self):
        """Get all sections matching ``location``."""
        # We slightly diverge from LocalConfig here by allowing the no-name
        # section as the most generic one and the lower priority.
        no_name_section = None
        all_sections = []
        # Filter out the no_name_section so _iter_for_location_by_parts can be
        # used (it assumes all sections have a name).
        for _, section in self.store.get_sections():
            if section.id is None:
                no_name_section = section
            else:
                all_sections.append(section)
        # Unfortunately _iter_for_location_by_parts deals with section names so
        # we have to resync.
        filtered_sections = _iter_for_location_by_parts(
            [s.id for s in all_sections], self.location
        )
        iter_all_sections = iter(all_sections)
        matching_sections = []
        if no_name_section is not None:
            matching_sections.append(
                (0, LocationSection(no_name_section, self.location))
            )
        for section_id, extra_path, length in filtered_sections:
            # a section id is unique for a given store so it's safe to take the
            # first matching section while iterating. Also, all filtered
            # sections are part of 'all_sections' and will always be found
            # there.
            while True:
                section = next(iter_all_sections)
                if section_id == section.id:
                    section = LocationSection(section, extra_path, self.branch_name)
                    matching_sections.append((length, section))
                    break
        return matching_sections

    def get_sections(self):
        # Override the default implementation as we want to change the order
        # We want the longest (aka more specific) locations first
        sections = sorted(
            self._get_matching_sections(),
            key=lambda match: (match[0], match[1].id),
            reverse=True,
        )
        # Sections mentioning 'ignore_parents' restrict the selection
        for _, section in sections:
            # FIXME: We really want to use as_bool below -- vila 2011-04-07
            ignore = section.get("ignore_parents", None)
            if ignore is not None:
                ignore = ui.bool_from_string(ignore)
            if ignore:
                break
            # Finally, we have a valid section
            yield self.store, section


# FIXME: _shared_stores should be an attribute of a library state once a
# library_state object is always available.
_shared_stores: dict[str, Store] = {}
_shared_stores_at_exit_installed = False


class Stack:
    """A stack of configurations where an option can be defined."""

    def __init__(self, sections_def, store=None, mutable_section_id=None):
        """Creates a stack of sections with an optional store for changes.

        Args:
          sections_def: A list of Section or callables that returns an
            iterable of Section. This defines the Sections for the Stack and
            can be called repeatedly if needed.

          store: The optional Store where modifications will be
            recorded. If none is specified, no modifications can be done.

          mutable_section_id: The id of the MutableSection where changes
            are recorded. This requires the ``store`` parameter to be
            specified.
        """
        self.sections_def = sections_def
        self.store = store
        self.mutable_section_id = mutable_section_id

    def iter_sections(self):
        """Iterate all the defined sections."""
        # Ensuring lazy loading is achieved by delaying section matching (which
        # implies querying the persistent storage) until it can't be avoided
        # anymore by using callables to describe (possibly empty) section
        # lists.
        for sections in self.sections_def:
            yield from sections()

    def get(self, name, expand=True, convert=True):
        """Return the *first* option value found in the sections.

        This is where we guarantee that sections coming from Store are loaded
        lazily: the loading is delayed until we need to either check that an
        option exists or get its value, which in turn may require to discover
        in which sections it can be defined. Both of these (section and option
        existence) require loading the store (even partially).

        Args:
          name: The queried option.
          expand: Whether options references should be expanded.
          convert: Whether the option value should be converted from
            unicode (do nothing for non-registered options).

        Returns:
          The value of the option.
        """
        # FIXME: No caching of options nor sections yet -- vila 20110503
        value = None
        found_store = None  # Where the option value has been found
        # If the option is registered, it may provide additional info about
        # value handling
        try:
            opt = option_registry.get(name)
        except KeyError:
            # Not registered
            opt = None

        def expand_and_convert(val):
            # This may need to be called in different contexts if the value is
            # None or ends up being None during expansion or conversion.
            if val is not None:
                if expand:
                    if isinstance(val, str):
                        val = self._expand_options_in_string(val)
                    else:
                        trace.warning(
                            f'Cannot expand "{name}":'
                            f" {type(val)} does not support option expansion"
                        )
                if opt is None:
                    val = found_store.unquote(val)
                elif convert:
                    val = opt.convert_from_unicode(found_store, val)
            return val

        # First of all, check if the environment can override the configuration
        # value
        if opt is not None and opt.override_from_env:
            value = opt.get_override()
            value = expand_and_convert(value)
        if value is None:
            for store, section in self.iter_sections():
                value = section.get(name)
                if value is not None:
                    found_store = store
                    break
            value = expand_and_convert(value)
            if opt is not None and value is None:
                # If the option is registered, it may provide a default value
                value = opt.get_default()
                value = expand_and_convert(value)
        for hook in ConfigHooks["get"]:
            hook(self, name, value)
        return value

    def expand_options(self, string, env=None):
        """Expand option references in the string in the configuration context.

        Args:
          string: The string containing option(s) to expand.
          env: An option dict defining additional configuration options or
            overriding existing ones.

        Returns:
          The expanded string.
        """
        return self._expand_options_in_string(string, env)

    def _expand_options_in_string(self, string, env=None, _refs=None):
        """Expand options in the string in the configuration context.

        Args:
          string: The string to be expanded.
          env: An option dict defining additional configuration options or
            overriding existing ones.
          _refs: Private list (FIFO) containing the options being expanded
            to detect loops.

        Returns: The expanded string.
        """
        if string is None:
            # Not much to expand there
            return None
        if _refs is None:
            # What references are currently resolved (to detect loops)
            _refs = []
        result = string
        # We need to iterate until no more refs appear ({{foo}} will need two
        # iterations for example).
        expanded = True
        while expanded:
            expanded = False
            chunks = []
            for is_ref, chunk in iter_option_refs(result):
                if not is_ref:
                    chunks.append(chunk)
                else:
                    expanded = True
                    name = chunk[1:-1]
                    if name in _refs:
                        raise OptionExpansionLoop(string, _refs)
                    _refs.append(name)
                    value = self._expand_option(name, env, _refs)
                    if value is None:
                        raise ExpandingUnknownOption(name, string)
                    chunks.append(value)
                    _refs.pop()
            result = "".join(chunks)
        return result

    def _expand_option(self, name, env, _refs):
        if env is not None and name in env:
            # Special case, values provided in env takes precedence over
            # anything else
            value = env[name]
        else:
            value = self.get(name, expand=False, convert=False)
            value = self._expand_options_in_string(value, env, _refs)
        return value

    def _get_mutable_section(self):
        """Get the MutableSection for the Stack.

        This is where we guarantee that the mutable section is lazily loaded:
        this means we won't load the corresponding store before setting a value
        or deleting an option. In practice the store will often be loaded but
        this helps catching some programming errors.
        """
        store = self.store
        section = store.get_mutable_section(self.mutable_section_id)
        return store, section

    def set(self, name, value):
        """Set a new value for the option."""
        store, section = self._get_mutable_section()
        section.set(name, store.quote(value))
        for hook in ConfigHooks["set"]:
            hook(self, name, value)

    def remove(self, name):
        """Remove an existing option."""
        _, section = self._get_mutable_section()
        section.remove(name)
        for hook in ConfigHooks["remove"]:
            hook(self, name)

    def __repr__(self):
        """Return string representation of the section."""
        # Mostly for debugging use
        return f"<config.{self.__class__.__name__}({id(self)})>"

    def _get_overrides(self):
        if breezy._global_state is not None:
            # TODO(jelmer): Urgh, this is circular so we can't call breezy.get_global_state()
            return breezy._global_state.cmdline_overrides.get_sections()
        return []

    def get_shared_store(self, store, state=None):
        """Get a known shared store.

        Store urls uniquely identify them and are used to ensure a single copy
        is shared across all users.

        Args:
          store: The store known to the caller.
          state: The library state where the known stores are kept.

        Returns: The store received if it's not a known one, an already known
            otherwise.
        """
        if state is None:
            # TODO(jelmer): Urgh, this is circular so we can't call breezy.get_global_state()
            state = breezy._global_state
        if state is None:
            global _shared_stores_at_exit_installed
            stores = _shared_stores

            def save_config_changes():
                for _k, store in stores.items():
                    store.save_changes()

            if not _shared_stores_at_exit_installed:
                # FIXME: Ugly hack waiting for library_state to always be
                # available. -- vila 20120731
                import atexit

                atexit.register(save_config_changes)
                _shared_stores_at_exit_installed = True
        else:
            stores = state.config_stores
        url = store.external_url()
        try:
            return stores[url]
        except KeyError:
            stores[url] = store
            return store


class MemoryStack(Stack):
    """A configuration stack defined from a string.

    This is mainly intended for tests and requires no disk resources.
    """

    def __init__(self, content=None):
        """Create an in-memory stack from a given content.

        It uses a single store based on configobj and support reading and
        writing options.

        Args:
          content: The initial content of the store. If None, the store is
            not loaded and ``_load_from_string`` can and should be used if
            needed.
        """
        store = IniFileStore()
        if content is not None:
            store._load_from_string(content)
        super().__init__([store.get_sections], store)


class _CompatibleStack(Stack):
    """Place holder for compatibility with previous design.

    This is intended to ease the transition from the Config-based design to the
    Stack-based design and should not be used nor relied upon by plugins.

    One assumption made here is that the daughter classes will all use Stores
    derived from LockableIniFileStore).

    It implements set() and remove () by re-loading the store before applying
    the modification and saving it.

    The long term plan being to implement a single write by store to save
    all modifications, this class should not be used in the interim.
    """

    def set(self, name, value):
        # Force a reload
        self.store.unload()
        super().set(name, value)
        # Force a write to persistent storage
        self.store.save()

    def remove(self, name):
        # Force a reload
        self.store.unload()
        super().remove(name)
        # Force a write to persistent storage
        self.store.save()


class GlobalStack(Stack):
    """Global options only stack.

    The following sections are queried:

    * command-line overrides,

    * the 'DEFAULT' section in bazaar.conf

    This stack will use the ``DEFAULT`` section in bazaar.conf as its
    MutableSection.
    """

    def __init__(self):
        gstore = self.get_shared_store(GlobalStore())
        super().__init__(
            [self._get_overrides, NameMatcher(gstore, "DEFAULT").get_sections],
            gstore,
            mutable_section_id="DEFAULT",
        )


class LocationStack(Stack):
    """Per-location options falling back to global options stack.

    The following sections are queried:

    * command-line overrides,

    * the sections matching ``location`` in ``locations.conf``, the order being
      defined by the number of path components in the section glob, higher
      numbers first (from most specific section to most generic).

    * the 'DEFAULT' section in bazaar.conf

    This stack will use the ``location`` section in locations.conf as its
    MutableSection.
    """

    def __init__(self, location):
        """Make a new stack for a location and global configuration.

        Args:
        location: A URL prefix to
        """
        lstore = self.get_shared_store(LocationStore())
        if location.startswith("file://"):
            location = urlutils.local_path_from_url(location)
        gstore = self.get_shared_store(GlobalStore())
        super().__init__(
            [
                self._get_overrides,
                LocationMatcher(lstore, location).get_sections,
                NameMatcher(gstore, "DEFAULT").get_sections,
            ],
            lstore,
            mutable_section_id=location,
        )


class BranchStack(Stack):
    """Per-location options falling back to branch then global options stack.

    The following sections are queried:

    * command-line overrides,

    * the sections matching ``location`` in ``locations.conf``, the order being
      defined by the number of path components in the section glob, higher
      numbers first (from most specific section to most generic),

    * the no-name section in branch.conf,

    * the ``DEFAULT`` section in ``bazaar.conf``.

    This stack will use the no-name section in ``branch.conf`` as its
    MutableSection.
    """

    def __init__(self, branch):
        lstore = self.get_shared_store(LocationStore())
        bstore = branch._get_config_store()
        gstore = self.get_shared_store(GlobalStore())
        super().__init__(
            [
                self._get_overrides,
                LocationMatcher(lstore, branch.base).get_sections,
                NameMatcher(bstore, None).get_sections,
                NameMatcher(gstore, "DEFAULT").get_sections,
            ],
            bstore,
        )
        self.branch = branch

    def lock_write(self, token=None):
        return self.branch.lock_write(token)

    def unlock(self):
        return self.branch.unlock()

    def set(self, name, value):
        with self.lock_write():
            super().set(name, value)
            # Unlocking the branch will trigger a store.save_changes() so the
            # last unlock saves all the changes.

    def remove(self, name):
        with self.lock_write():
            super().remove(name)
            # Unlocking the branch will trigger a store.save_changes() so the
            # last unlock saves all the changes.


class RemoteControlStack(Stack):
    """Remote control-only options stack."""

    # FIXME 2011-11-22 JRV This should probably be renamed to avoid confusion
    # with the stack used for remote bzr dirs. RemoteControlStack only uses
    # control.conf and is used only for stack options.

    def __init__(self, bzrdir):
        cstore = bzrdir._get_config_store()
        super().__init__([NameMatcher(cstore, None).get_sections], cstore)
        self.controldir = bzrdir


class BranchOnlyStack(Stack):
    """Branch-only options stack."""

    # FIXME: _BranchOnlyStack only uses branch.conf and is used only for the
    # stacked_on_location options waiting for http://pad.lv/832042 to be fixed.
    # -- vila 2011-12-16

    def __init__(self, branch):
        bstore = branch._get_config_store()
        super().__init__([NameMatcher(bstore, None).get_sections], bstore)
        self.branch = branch

    def lock_write(self, token=None):
        return self.branch.lock_write(token)

    def unlock(self):
        return self.branch.unlock()

    def set(self, name, value):
        with self.lock_write():
            super().set(name, value)
            # Force a write to persistent storage
            self.store.save_changes()

    def remove(self, name):
        with self.lock_write():
            super().remove(name)
            # Force a write to persistent storage
            self.store.save_changes()


class cmd_config(commands.Command):
    """Display, set or remove a configuration option.

    Display the active value for option NAME.

    If --all is specified, NAME is interpreted as a regular expression and all
    matching options are displayed mentioning their scope and without resolving
    option references in the value). The active value that bzr will take into
    account is the first one displayed for each option.

    If NAME is not given, --all .* is implied (all options are displayed for the
    current scope).

    Setting a value is achieved by using NAME=value without spaces. The value
    is set in the most relevant scope and can be checked by displaying the
    option again.

    Removing a value is achieved by using --remove NAME.
    """

    takes_args = ["name?"]

    takes_options = [
        "directory",
        # FIXME: This should be a registry option so that plugins can register
        # their own config files (or not) and will also address
        # http://pad.lv/788991 -- vila 20101115
        CommandOption(
            "scope",
            help="Reduce the scope to the specified configuration file.",
            type=str,
        ),
        CommandOption(
            "all",
            help="Display all the defined values for the matching options.",
        ),
        CommandOption("remove", help="Remove the option from the configuration file."),
    ]

    _see_also = ["configuration"]

    @commands.display_command
    def run(self, name=None, all=False, directory=None, scope=None, remove=False):
        from .directory_service import directories

        if directory is None:
            directory = "."
        directory = directories.dereference(directory)
        directory = urlutils.normalize_url(directory)
        if remove and all:
            raise errors.BzrError("--all and --remove are mutually exclusive.")
        elif remove:
            # Delete the option in the given scope
            self._remove_config_option(name, directory, scope)
        elif name is None:
            # Defaults to all options
            self._show_matching_options(".*", directory, scope)
        else:
            try:
                name, value = name.split("=", 1)
            except ValueError:
                # Display the option(s) value(s)
                if all:
                    self._show_matching_options(name, directory, scope)
                else:
                    self._show_value(name, directory, scope)
            else:
                if all:
                    raise errors.BzrError("Only one option can be set.")
                # Set the option value
                self._set_config_option(name, value, directory, scope)

    def _get_stack(self, directory, scope=None, write_access=False):
        """Get the configuration stack specified by ``directory`` and ``scope``.

        Args:
          directory: Where the configurations are derived from.
          scope: A specific config to start from.
          write_access: Whether a write access to the stack will be
            attempted.
        """
        # FIXME: scope should allow access to plugin-specific stacks (even
        # reduced to the plugin-specific store), related to
        # http://pad.lv/788991 -- vila 2011-11-15
        if scope is not None:
            if scope == "breezy":
                return GlobalStack()
            elif scope == "locations":
                return LocationStack(directory)
            elif scope == "branch":
                (_, br, _) = controldir.ControlDir.open_containing_tree_or_branch(
                    directory
                )
                if write_access:
                    self.add_cleanup(br.lock_write().unlock)
                return br.get_config_stack()
            raise NoSuchConfig(scope)
        else:
            try:
                (_, br, _) = controldir.ControlDir.open_containing_tree_or_branch(
                    directory
                )
                if write_access:
                    self.add_cleanup(br.lock_write().unlock)
                return br.get_config_stack()
            except errors.NotBranchError:
                return LocationStack(directory)

    def _quote_multiline(self, value):
        if "\n" in value:
            value = '"""' + value + '"""'
        return value

    def _show_value(self, name, directory, scope):
        conf = self._get_stack(directory, scope)
        value = conf.get(name, expand=True, convert=False)
        if value is not None:
            # Quote the value appropriately
            value = self._quote_multiline(value)
            self.outf.write(f"{value}\n")
        else:
            raise NoSuchConfigOption(name)

    def _show_matching_options(self, name, directory, scope):
        name = lazy_regex.lazy_compile(name)
        # We want any error in the regexp to be raised *now* so we need to
        # avoid the delay introduced by the lazy regexp.  But, we still do
        # want the nicer errors raised by lazy_regex.
        name._compile_and_collapse()
        cur_store_id = None
        cur_section = None
        conf = self._get_stack(directory, scope)
        for store, section in conf.iter_sections():
            for oname in section.iter_option_names():
                if name.search(oname):
                    if cur_store_id != store.id:
                        # Explain where the options are defined
                        self.outf.write(f"{store.id}:\n")
                        cur_store_id = store.id
                        cur_section = None
                    if section.id is not None and cur_section != section.id:
                        # Display the section id as it appears in the store
                        # (None doesn't appear by definition)
                        self.outf.write(f"  [{section.id}]\n")
                        cur_section = section.id
                    value = section.get(oname, expand=False)
                    # Quote the value appropriately
                    value = self._quote_multiline(value)
                    self.outf.write(f"  {oname} = {value}\n")

    def _set_config_option(self, name, value, directory, scope):
        conf = self._get_stack(directory, scope, write_access=True)
        conf.set(name, value)
        # Explicitly save the changes
        conf.store.save_changes()

    def _remove_config_option(self, name, directory, scope):
        if name is None:
            raise errors.CommandError("--remove expects an option to remove.")
        conf = self._get_stack(directory, scope, write_access=True)
        try:
            conf.remove(name)
            # Explicitly save the changes
            conf.store.save_changes()
        except KeyError as e:
            raise NoSuchConfigOption(name) from e


# Test registries
#
# We need adapters that can build a Store or a Stack in a test context. Test
# classes, based on TestCaseWithTransport, can use the registry to parametrize
# themselves. The builder will receive a test instance and should return a
# ready-to-use store or stack.  Plugins that define new store/stacks can also
# register themselves here to be tested against the tests defined in
# breezy.tests.test_config. Note that the builder can be called multiple times
# for the same test.

# The registered object should be a callable receiving a test instance
# parameter (inheriting from tests.TestCaseWithTransport) and returning a Store
# object.
test_store_builder_registry = registry.Registry[str, Callable, None]()

# The registered object should be a callable receiving a test instance
# parameter (inheriting from tests.TestCaseWithTransport) and returning a Stack
# object.
test_stack_builder_registry = registry.Registry[str, Callable, None]()
