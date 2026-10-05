# Copyright (C) 2005-2010 Canonical Ltd
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

"""Command line option parsing for Breezy.

This module provides the infrastructure for defining and parsing command line
options. It includes the Option class and its subclasses for different types
of options, as well as utilities for parsing and processing command arguments.
"""

# TODO: For things like --diff-prefix, we want a way to customize the display
# of the option argument.

__docformat__ = "google"

import optparse
from collections.abc import Callable

from . import errors, revisionspec
from . import registry as _mod_registry


class BadOptionValue(errors.BzrError):
    """Exception raised when an invalid value is provided for an option."""

    _fmt = """Bad value "%(value)s" for option "%(name)s"."""

    def __init__(self, name, value):
        """Initialize BadOptionValue.

        Args:
            name: The name of the option.
            value: The bad value that was provided.
        """
        errors.BzrError.__init__(self, name=name, value=value)


def _parse_revision_str(revstr):
    r"""This handles a revision string -> revno.

    This always returns a list.  The list will have one element for
    each revision specifier supplied.

    >>> _parse_revision_str('234')
    [<RevisionSpec_dwim 234>]
    >>> _parse_revision_str('234..567')
    [<RevisionSpec_dwim 234>, <RevisionSpec_dwim 567>]
    >>> _parse_revision_str('..')
    [<RevisionSpec None>, <RevisionSpec None>]
    >>> _parse_revision_str('..234')
    [<RevisionSpec None>, <RevisionSpec_dwim 234>]
    >>> _parse_revision_str('234..')
    [<RevisionSpec_dwim 234>, <RevisionSpec None>]
    >>> _parse_revision_str('234..456..789') # Maybe this should be an error
    [<RevisionSpec_dwim 234>, <RevisionSpec_dwim 456>, <RevisionSpec_dwim 789>]
    >>> _parse_revision_str('234....789') #Error ?
    [<RevisionSpec_dwim 234>, <RevisionSpec None>, <RevisionSpec_dwim 789>]
    >>> _parse_revision_str('revid:test@other.com-234234')
    [<RevisionSpec_revid revid:test@other.com-234234>]
    >>> _parse_revision_str('revid:test@other.com-234234..revid:test@other.com-234235')
    [<RevisionSpec_revid revid:test@other.com-234234>, <RevisionSpec_revid revid:test@other.com-234235>]
    >>> _parse_revision_str('revid:test@other.com-234234..23')
    [<RevisionSpec_revid revid:test@other.com-234234>, <RevisionSpec_dwim 23>]
    >>> _parse_revision_str('date:2005-04-12')
    [<RevisionSpec_date date:2005-04-12>]
    >>> _parse_revision_str('date:2005-04-12 12:24:33')
    [<RevisionSpec_date date:2005-04-12 12:24:33>]
    >>> _parse_revision_str('date:2005-04-12T12:24:33')
    [<RevisionSpec_date date:2005-04-12T12:24:33>]
    >>> _parse_revision_str('date:2005-04-12,12:24:33')
    [<RevisionSpec_date date:2005-04-12,12:24:33>]
    >>> _parse_revision_str('-5..23')
    [<RevisionSpec_dwim -5>, <RevisionSpec_dwim 23>]
    >>> _parse_revision_str('-5')
    [<RevisionSpec_dwim -5>]
    >>> _parse_revision_str('123a')
    [<RevisionSpec_dwim 123a>]
    >>> _parse_revision_str('abc')
    [<RevisionSpec_dwim abc>]
    >>> _parse_revision_str('branch:../branch2')
    [<RevisionSpec_branch branch:../branch2>]
    >>> _parse_revision_str('branch:../../branch2')
    [<RevisionSpec_branch branch:../../branch2>]
    >>> _parse_revision_str('branch:../../branch2..23')
    [<RevisionSpec_branch branch:../../branch2>, <RevisionSpec_dwim 23>]
    >>> _parse_revision_str('branch:..\\\\branch2')
    [<RevisionSpec_branch branch:..\\branch2>]
    >>> _parse_revision_str('branch:..\\\\..\\\\branch2..23')
    [<RevisionSpec_branch branch:..\\..\\branch2>, <RevisionSpec_dwim 23>]
    """
    # TODO: Maybe move this into revisionspec.py
    # A ".." followed by / or \ is part of a path, not a range separator.
    from ._cmd_rs.optparse import split_revision_range

    return [
        revisionspec.RevisionSpec.from_string(x or None)
        for x in split_revision_range(revstr)
    ]


def _parse_change_str(revstr):
    """Parse the revision string for the --change option.

    Args:
        revstr: Revision string to parse.

    Returns:
        Tuple of (before_revision, revision) specs.

    Raises:
        RangeInChangeOption: If a revision range is provided.

    >>> _parse_change_str('123')
    (<RevisionSpec_before before:123>, <RevisionSpec_dwim 123>)
    >>> _parse_change_str('123..124')
    Traceback (most recent call last):
      ...
    breezy.errors.RangeInChangeOption: Option --change does not accept revision ranges
    """
    revs = _parse_revision_str(revstr)
    if len(revs) > 1:
        raise errors.RangeInChangeOption()
    return (revisionspec.RevisionSpec.from_string("before:" + revstr), revs[0])


def _parse_merge_type(typestring):
    """Parse a merge type string.

    Args:
        typestring: String identifying the merge type.

    Returns:
        The merge type class.
    """
    return get_merge_type(typestring)


def get_merge_type(typestring):
    """Attempt to find the merge class/factory associated with a string."""
    from merge import merge_types

    try:
        return merge_types[typestring][0]
    except KeyError as e:
        templ = "%s%%7s: %%s" % (" " * 12)
        lines = [templ % (f[0], f[1][1]) for f in merge_types.items()]
        type_list = "\n".join(lines)
        msg = f"No known merge type {typestring}. Supported types are:\n{type_list}"
        raise errors.CommandError(msg) from e


# The optparse add_option/_optparse_*callback methods register the option with
# the optparse parsers used by breezy.bash_completion and breezy.zsh_completion.
from ._cmd_rs.optparse import Option as _RustOption


class Option(_RustOption):
    """Description of a command line option.

    Attributes:
      _short_name: If this option has a single-letter name, this is it.
         Otherwise None.
    """

    # The dictionary of standard options. These are always legal.
    STD_OPTIONS: dict[str, "Option"] = {}

    # The dictionary of commonly used options. these are only legal
    # if a command explicitly references them by name in the list
    # of supported options.
    OPTIONS: dict[str, "Option"] = {}

    def add_option(self, parser, short_name):
        """Add this option to an Optparse parser."""
        option_strings = [f"--{self.name}"]
        if short_name is not None:
            option_strings.append(f"-{short_name}")
        help = optparse.SUPPRESS_HELP if self.hidden else self.help
        optargfn = self.type
        if optargfn is None:
            parser.add_option(
                *option_strings,
                action="callback",
                callback=self._optparse_bool_callback,
                callback_args=(True,),
                help=help,
            )
            negation_strings = [f"--{self.get_negation_name()}"]
            parser.add_option(
                *negation_strings,
                action="callback",
                callback=self._optparse_bool_callback,
                callback_args=(False,),
                help=optparse.SUPPRESS_HELP,
            )
        else:
            parser.add_option(
                *option_strings,
                action="callback",
                callback=self._optparse_callback,
                type="string",
                metavar=self.argname.upper(),
                help=help,
                default=OptionParser.DEFAULT_VALUE,
            )

    def _optparse_bool_callback(self, option, opt_str, value, parser, bool_v):
        setattr(parser.values, self._param_name, bool_v)
        if self.custom_callback is not None:
            self.custom_callback(option, self._param_name, bool_v, parser)

    def _optparse_callback(self, option, opt, value, parser):
        try:
            v = self.type(value)
        except ValueError as e:
            raise optparse.OptionValueError(
                f"invalid value for option {option}: {value}"
            ) from e
        setattr(parser.values, self._param_name, v)
        if self.custom_callback is not None:
            self.custom_callback(option, self.name, v, parser)


class ListOption(Option):
    """Option used to provide a list of values.

    On the command line, arguments are specified by a repeated use of the
    option. '-' is a special argument that resets the list. For example,
      --foo=a --foo=b
    sets the value of the 'foo' option to ['a', 'b'], and
      --foo=a --foo=b --foo=- --foo=c
    sets the value of the 'foo' option to ['c'].
    """

    def add_option(self, parser, short_name):
        """Add this option to an Optparse parser."""
        option_strings = [f"--{self.name}"]
        if short_name is not None:
            option_strings.append(f"-{short_name}")
        parser.add_option(
            *option_strings,
            action="callback",
            callback=self._optparse_callback,
            type="string",
            metavar=self.argname.upper(),
            help=self.help,
            dest=self._param_name,
            default=[],
        )

    def _optparse_callback(self, option, opt, value, parser):
        values = getattr(parser.values, self._param_name)
        if value == "-":
            del values[:]
        else:
            values.append(self.type(value))
        if self.custom_callback is not None:
            self.custom_callback(option, self._param_name, values, parser)


# The subclass adds the optparse add_option method used by
# breezy.bash_completion and breezy.zsh_completion, and inherits Option's
# callbacks.
from ._cmd_rs.optparse import RegistryOption as _RustRegistryOption


class RegistryOption(_RustRegistryOption, Option):
    """Option based on a registry.

    The values for the options correspond to entries in the registry.  Input
    must be a registry key.  After validation, it is converted into an object
    using Registry.get or a caller-provided converter.
    """

    def add_option(self, parser, short_name):
        """Add this option to an Optparse parser."""
        if self.value_switches:
            parser = parser.add_option_group(self.title)
        if self.enum_switch:
            Option.add_option(self, parser, short_name)
        if self.value_switches:
            alias_map = self.registry.alias_map()
            for key in self.registry.keys():
                if key in self.registry.aliases():
                    continue
                option_strings = [
                    f"--{name}"
                    for name in [key]
                    + [
                        alias
                        for alias in alias_map.get(key, [])
                        if not self.is_hidden(alias)
                    ]
                ]
                if self.is_hidden(key):
                    help = optparse.SUPPRESS_HELP
                else:
                    help = self.registry.get_help(key)
                if self.short_value_switches and key in self.short_value_switches:
                    option_strings.append(f"-{self.short_value_switches[key]}")
                parser.add_option(
                    *option_strings,
                    action="callback",
                    callback=self._optparse_value_callback(key),
                    help=help,
                )

    def _optparse_value_callback(self, cb_value):
        def cb(option, opt, value, parser):
            v = self.type(cb_value)
            setattr(parser.values, self._param_name, v)
            if self.custom_callback is not None:
                self.custom_callback(option, self._param_name, v, parser)

        return cb


class OptionParser:
    """Carrier for the sentinel marking an unset value option.

    Command-line parsing is done by :func:`get_optparser`. The
    ``DEFAULT_VALUE`` sentinel is used by :meth:`Option.add_option` (for
    breezy.bash_completion and breezy.zsh_completion) and by
    ``commands.parse_args``.
    """

    DEFAULT_VALUE = object()


class OptionValues:
    """Holds parsed option values.

    A drop-in for ``optparse.Values``: attributes hold the parsed values and
    equality compares against another ``OptionValues`` or a plain dict (matching
    the behaviour the option tests rely on).
    """

    def __init__(self):
        """Initialize with no values set."""

    def __eq__(self, other):
        """Compare values by their attribute dict, like optparse.Values."""
        if isinstance(other, OptionValues):
            return self.__dict__ == other.__dict__
        elif isinstance(other, dict):
            return self.__dict__ == other
        else:
            return NotImplemented

    def __repr__(self):
        """Return a debug representation of the held values."""
        return f"OptionValues({self.__dict__!r})"


def get_optparser(options):
    """Generate a parser for breezy-style options."""
    from ._cmd_rs.optparse import Parser

    return Parser(options)


def custom_help(name, help):
    """Clone a common option overriding the help."""
    import copy

    o = copy.copy(Option.OPTIONS[name])
    o.help = help
    return o


def _standard_option(name, **kwargs):
    """Register a standard option."""
    # All standard options are implicitly 'global' ones
    Option.STD_OPTIONS[name] = Option(name, **kwargs)
    Option.OPTIONS[name] = Option.STD_OPTIONS[name]


def _standard_list_option(name, **kwargs):
    """Register a standard option."""
    # All standard options are implicitly 'global' ones
    Option.STD_OPTIONS[name] = ListOption(name, **kwargs)
    Option.OPTIONS[name] = Option.STD_OPTIONS[name]


def _global_option(name, **kwargs):
    """Register a global option."""
    Option.OPTIONS[name] = Option(name, **kwargs)


def _global_registry_option(name, help, registry=None, **kwargs):
    Option.OPTIONS[name] = RegistryOption(name, help, registry, **kwargs)


# The verbosity level detected during command-line parsing. Its final value
# depends on the order of the verbose/quiet/no-verbose/no-quiet flags and is
# one of: -ve for quiet, 0 for normal, +ve for verbose.
from ._cmd_rs.optparse import (  # noqa: F401
    set_verbosity_level,
    verbosity_level,
)


def _verbosity_level_callback(option, opt_str, value, parser):
    """Callback function for handling verbosity level changes.

    Args:
        option: The Option object.
        opt_str: The option string that triggered this callback.
        value: The argument value (if any).
        parser: The OptionParser being used.
    """
    from ._cmd_rs.optparse import apply_verbosity

    apply_verbosity(opt_str == "verbose", bool(value))


# Declare the standard options
_standard_option("help", short_name="h", help="Show help message.")
_standard_option(
    "quiet",
    short_name="q",
    help="Only display errors and warnings.",
    custom_callback=_verbosity_level_callback,
)
_standard_option("usage", help="Show usage message and options.")
_standard_option(
    "verbose",
    short_name="v",
    help="Display more information.",
    custom_callback=_verbosity_level_callback,
)

# The commonly used options are shared with the native commands.
from ._cmd_rs.optparse import shared_options as _shared_options

for _option in _shared_options():
    Option.OPTIONS[_option.name] = _option
del _option

diff_writer_registry = _mod_registry.Registry[str, Callable, None]()
diff_writer_registry.register("plain", lambda x: x, "Plaintext diff output.")
diff_writer_registry.default_key = "plain"
