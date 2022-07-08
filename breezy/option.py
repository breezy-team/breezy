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

# TODO: For things like --diff-prefix, we want a way to customize the display
# of the option argument.

import optparse
import re

from . import (
    errors,
    registry as _mod_registry,
    revisionspec,
    )


class BadOptionValue(errors.BzrError):

    _fmt = """Bad value "%(value)s" for option "%(name)s"."""

    def __init__(self, name, value):
        errors.BzrError.__init__(self, name=name, value=value)


def _parse_revision_str(revstr):
    """This handles a revision string -> revno.

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
    revs = []
    # split on .. that is not followed by a / or \
    sep = re.compile(r'\.\.(?![\\/])')
    for x in sep.split(revstr):
        revs.append(revisionspec.RevisionSpec.from_string(x or None))
    return revs


def _parse_change_str(revstr):
    """Parse the revision string and return a tuple with left-most
    parent of the revision.

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
    return (revisionspec.RevisionSpec.from_string('before:' + revstr),
            revs[0])


def _parse_merge_type(typestring):
    return get_merge_type(typestring)


def get_merge_type(typestring):
    """Attempt to find the merge class/factory associated with a string."""
    from merge import merge_types
    try:
        return merge_types[typestring][0]
    except KeyError:
        templ = '%s%%7s: %%s' % (' ' * 12)
        lines = [templ % (f[0], f[1][1]) for f in merge_types.items()]
        type_list = '\n'.join(lines)
        msg = "No known merge type %s. Supported types are:\n%s" %\
            (typestring, type_list)
        raise errors.CommandError(msg)


class Option(object):
    """Description of a command line option

    :ivar _short_name: If this option has a single-letter name, this is it.
    Otherwise None.
    """

    # The dictionary of standard options. These are always legal.
    STD_OPTIONS = {}

    # The dictionary of commonly used options. these are only legal
    # if a command explicitly references them by name in the list
    # of supported options.
    OPTIONS = {}

    def __init__(self, name, help='', type=None, argname=None,
                 short_name=None, param_name=None, custom_callback=None,
                 hidden=False):
        """Make a new command option.

        :param name: regular name of the command, used in the double-dash
            form and also as the parameter to the command's run()
            method (unless param_name is specified).

        :param help: help message displayed in command help

        :param type: function called to parse the option argument, or
            None (default) if this option doesn't take an argument.

        :param argname: name of option argument, if any

        :param short_name: short option code for use with a single -, e.g.
            short_name="v" to enable parsing of -v.

        :param param_name: name of the parameter which will be passed to
            the command's run() method.

        :param custom_callback: a callback routine to be called after normal
            processing. The signature of the callback routine is
            (option, name, new_value, parser).
        :param hidden: If True, the option should be hidden in help and
            documentation.
        """
        self.name = name
        self.help = help
        self.type = type
        self._short_name = short_name
        if type is None:
            if argname:
                raise ValueError('argname not valid for booleans')
        elif argname is None:
            argname = 'ARG'
        self.argname = argname
        if param_name is None:
            self._param_name = self.name.replace('-', '_')
        else:
            self._param_name = param_name
        self.custom_callback = custom_callback
        self.hidden = hidden

    def short_name(self):
        if self._short_name:
            return self._short_name

    def set_short_name(self, short_name):
        self._short_name = short_name

    def get_negation_name(self):
        if self.name.startswith('no-'):
            return self.name[3:]
        else:
            return 'no-' + self.name

    def add_option(self, parser, short_name):
        """Add this option to an Optparse parser"""
        option_strings = ['--%s' % self.name]
        if short_name is not None:
            option_strings.append('-%s' % short_name)
        if self.hidden:
            help = optparse.SUPPRESS_HELP
        else:
            help = self.help
        optargfn = self.type
        if optargfn is None:
            parser.add_option(action='callback',
                              callback=self._optparse_bool_callback,
                              callback_args=(True,),
                              help=help,
                              *option_strings)
            negation_strings = ['--%s' % self.get_negation_name()]
            parser.add_option(action='callback',
                              callback=self._optparse_bool_callback,
                              callback_args=(False,),
                              help=optparse.SUPPRESS_HELP, *negation_strings)
        else:
            parser.add_option(action='callback',
                              callback=self._optparse_callback,
                              type='string', metavar=self.argname.upper(),
                              help=help,
                              default=OptionParser.DEFAULT_VALUE,
                              *option_strings)

    def _optparse_bool_callback(self, option, opt_str, value, parser, bool_v):
        setattr(parser.values, self._param_name, bool_v)
        if self.custom_callback is not None:
            self.custom_callback(option, self._param_name, bool_v, parser)

    def _optparse_callback(self, option, opt, value, parser):
        try:
            v = self.type(value)
        except ValueError as e:
            raise optparse.OptionValueError(
                'invalid value for option %s: %s' % (option, value))
        setattr(parser.values, self._param_name, v)
        if self.custom_callback is not None:
            self.custom_callback(option, self.name, v, parser)

    def iter_switches(self):
        """Iterate through the list of switches provided by the option

        :return: an iterator of (name, short_name, argname, help)
        """
        argname = self.argname
        if argname is not None:
            argname = argname.upper()
        yield self.name, self.short_name(), argname, self.help

    def is_hidden(self, name):
        return self.hidden


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
        option_strings = ['--%s' % self.name]
        if short_name is not None:
            option_strings.append('-%s' % short_name)
        parser.add_option(action='callback',
                          callback=self._optparse_callback,
                          type='string', metavar=self.argname.upper(),
                          help=self.help, dest=self._param_name, default=[],
                          *option_strings)

    def _optparse_callback(self, option, opt, value, parser):
        values = getattr(parser.values, self._param_name)
        if value == '-':
            del values[:]
        else:
            values.append(self.type(value))
        if self.custom_callback is not None:
            self.custom_callback(option, self._param_name, values, parser)


class RegistryOption(Option):
    """Option based on a registry

    The values for the options correspond to entries in the registry.  Input
    must be a registry key.  After validation, it is converted into an object
    using Registry.get or a caller-provided converter.
    """

    def validate_value(self, value):
        """Validate a value name"""
        if value not in self.registry:
            raise BadOptionValue(self.name, value)

    def convert(self, value):
        """Convert a value name into an output type"""
        self.validate_value(value)
        if self.converter is None:
            return self.registry.get(value)
        else:
            return self.converter(value)

    def __init__(self, name, help, registry=None, converter=None,
                 value_switches=False, title=None, enum_switch=True,
                 lazy_registry=None, short_name=None, short_value_switches=None):
        """
        Constructor.

        :param name: The option name.
        :param help: Help for the option.
        :param registry: A Registry containing the values
        :param converter: Callable to invoke with the value name to produce
            the value.  If not supplied, self.registry.get is used.
        :param value_switches: If true, each possible value is assigned its
            own switch.  For example, instead of '--format knit',
            '--knit' can be used interchangeably.
        :param enum_switch: If true, a switch is provided with the option name,
            which takes a value.
        :param lazy_registry: A tuple of (module name, attribute name) for a
            registry to be lazily loaded.
        :param short_name: The short name for the enum switch, if any
        :param short_value_switches: A dict mapping values to short names
        """
        Option.__init__(self, name, help, type=self.convert,
                        short_name=short_name)
        self._registry = registry
        if registry is None:
            if lazy_registry is None:
                raise AssertionError(
                    'One of registry or lazy_registry must be given.')
            self._lazy_registry = _mod_registry._LazyObjectGetter(
                *lazy_registry)
        if registry is not None and lazy_registry is not None:
            raise AssertionError(
                'registry and lazy_registry are mutually exclusive')
        self.name = name
        self.converter = converter
        self.value_switches = value_switches
        self.enum_switch = enum_switch
        self.short_value_switches = short_value_switches
        self.title = title
        if self.title is None:
            self.title = name

    @property
    def registry(self):
        if self._registry is None:
            self._registry = self._lazy_registry.get_obj()
        return self._registry

    @staticmethod
    def from_kwargs(name_, help=None, title=None, value_switches=False,
                    enum_switch=True, **kwargs):
        """Convenience method to generate string-map registry options

        name, help, value_switches and enum_switch are passed to the
        RegistryOption constructor.  Any other keyword arguments are treated
        as values for the option, and their value is treated as the help.
        """
        reg = _mod_registry.Registry()
        for name, switch_help in sorted(kwargs.items()):
            name = name.replace('_', '-')
            reg.register(name, name, help=switch_help)
            if not value_switches:
                help = help + '  "' + name + '": ' + switch_help
                if not help.endswith("."):
                    help = help + "."
        return RegistryOption(name_, help, reg, title=title,
                              value_switches=value_switches, enum_switch=enum_switch)

    def add_option(self, parser, short_name):
        """Add this option to an Optparse parser"""
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
                    ('--%s' % name)
                    for name in [key] +
                    [alias for alias in alias_map.get(key, [])
                        if not self.is_hidden(alias)]]
                if self.is_hidden(key):
                    help = optparse.SUPPRESS_HELP
                else:
                    help = self.registry.get_help(key)
                if (self.short_value_switches and
                        key in self.short_value_switches):
                    option_strings.append('-%s' %
                                          self.short_value_switches[key])
                parser.add_option(action='callback',
                                  callback=self._optparse_value_callback(key),
                                  help=help,
                                  *option_strings)

    def _optparse_value_callback(self, cb_value):
        def cb(option, opt, value, parser):
            v = self.type(cb_value)
            setattr(parser.values, self._param_name, v)
            if self.custom_callback is not None:
                self.custom_callback(option, self._param_name, v, parser)
        return cb

    def iter_switches(self):
        """Iterate through the list of switches provided by the option

        :return: an iterator of (name, short_name, argname, help)
        """
        for value in Option.iter_switches(self):
            yield value
        if self.value_switches:
            for key in sorted(self.registry.keys()):
                yield key, None, None, self.registry.get_help(key)

    def is_alias(self, name):
        """Check whether a particular format is an alias."""
        if name == self.name:
            return False
        return name in self.registry.aliases()

    def is_hidden(self, name):
        if name == self.name:
            return Option.is_hidden(self, name)
        return getattr(self.registry.get_info(name), 'hidden', False)


class OptionParser(optparse.OptionParser):
    """OptionParser that raises exceptions instead of exiting"""

    DEFAULT_VALUE = object()

    def __init__(self):
        optparse.OptionParser.__init__(self)
        self.formatter = GettextIndentedHelpFormatter()

    def error(self, message):
        raise errors.CommandError(message)


class GettextIndentedHelpFormatter(optparse.IndentedHelpFormatter):
    """Adds gettext() call to format_option()"""

    def __init__(self):
        optparse.IndentedHelpFormatter.__init__(self)

    def format_option(self, option):
        """code taken from Python's optparse.py"""
        if option.help:
            from .i18n import gettext
            option.help = gettext(option.help)
        return optparse.IndentedHelpFormatter.format_option(self, option)


def get_optparser(options):
    """Generate an optparse parser for breezy-style options"""

    parser = OptionParser()
    parser.remove_option('--help')
    for option in options:
        option.add_option(parser, option.short_name())
    return parser


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


# This is the verbosity level detected during command line parsing.
# Note that the final value is dependent on the order in which the
# various flags (verbose, quiet, no-verbose, no-quiet) are given.
# The final value will be one of the following:
#
# * -ve for quiet
# * 0 for normal
# * +ve for verbose
_verbosity_level = 0


def _verbosity_level_callback(option, opt_str, value, parser):
    global _verbosity_level
    if not value:
        # Either --no-verbose or --no-quiet was specified
        _verbosity_level = 0
    elif opt_str == "verbose":
        if _verbosity_level > 0:
            _verbosity_level += 1
        else:
            _verbosity_level = 1
    else:
        if _verbosity_level < 0:
            _verbosity_level -= 1
        else:
            _verbosity_level = -1


# Declare the standard options
_standard_option('help', short_name='h',
                 help='Show help message.')
_standard_option('quiet', short_name='q',
                 help="Only display errors and warnings.",
                 custom_callback=_verbosity_level_callback)
_standard_option('usage',
                 help='Show usage message and options.')
_standard_option('verbose', short_name='v',
                 help='Display more information.',
                 custom_callback=_verbosity_level_callback)

# Declare commonly used options
_global_option('change',
               type=_parse_change_str,
               short_name='c',
               param_name='revision',
               help='Select changes introduced by the specified revision. See also "help revisionspec".')
_global_option('directory', short_name='d', type=str,
               help='Branch to operate on, instead of working directory.')
_global_option('file', type=str, short_name='F')
_global_registry_option('log-format', "Use specified log format.",
                        lazy_registry=('breezy.log', 'log_formatter_registry'),
                        value_switches=True, title='Log format',
                        short_value_switches={'short': 'S'})
_global_registry_option('merge-type', 'Select a particular merge algorithm.',
                        lazy_registry=('breezy.merge', 'merge_type_registry'),
                        value_switches=True, title='Merge algorithm')
_global_option('message', type=str,
               short_name='m',
               help='Message string.')
_global_option('null', short_name='0',
               help='Use an ASCII NUL (\\0) separator rather than '
               'a newline.')
_global_option('overwrite', help='Ignore differences between branches and '
               'overwrite unconditionally.')
_global_option('remember', help='Remember the specified location as a'
               ' default.')
_global_option('reprocess', help='Reprocess to reduce spurious conflicts.')
_global_option('revision',
               type=_parse_revision_str,
               short_name='r',
               help='See "help revisionspec" for details.')
_global_option('show-ids',
               help='Show internal object ids.')
_global_option('timezone',
               type=str,
               help='Display timezone as local, original, or utc.')

diff_writer_registry = _mod_registry.Registry()
diff_writer_registry.register('plain', lambda x: x, 'Plaintext diff output.')
diff_writer_registry.default_key = 'plain'
