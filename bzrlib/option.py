# Copyright (C) 2004, 2005, 2006 by Canonical Ltd
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

# TODO: For things like --diff-prefix, we want a way to customize the display
# of the option argument.

import optparse
import re

from bzrlib.trace import warning
from bzrlib.revisionspec import RevisionSpec
from bzrlib.errors import BzrCommandError


def _parse_revision_str(revstr):
    """This handles a revision string -> revno.

    This always returns a list.  The list will have one element for
    each revision specifier supplied.

    >>> _parse_revision_str('234')
    [<RevisionSpec_int 234>]
    >>> _parse_revision_str('234..567')
    [<RevisionSpec_int 234>, <RevisionSpec_int 567>]
    >>> _parse_revision_str('..')
    [<RevisionSpec None>, <RevisionSpec None>]
    >>> _parse_revision_str('..234')
    [<RevisionSpec None>, <RevisionSpec_int 234>]
    >>> _parse_revision_str('234..')
    [<RevisionSpec_int 234>, <RevisionSpec None>]
    >>> _parse_revision_str('234..456..789') # Maybe this should be an error
    [<RevisionSpec_int 234>, <RevisionSpec_int 456>, <RevisionSpec_int 789>]
    >>> _parse_revision_str('234....789') #Error ?
    [<RevisionSpec_int 234>, <RevisionSpec None>, <RevisionSpec_int 789>]
    >>> _parse_revision_str('revid:test@other.com-234234')
    [<RevisionSpec_revid revid:test@other.com-234234>]
    >>> _parse_revision_str('revid:test@other.com-234234..revid:test@other.com-234235')
    [<RevisionSpec_revid revid:test@other.com-234234>, <RevisionSpec_revid revid:test@other.com-234235>]
    >>> _parse_revision_str('revid:test@other.com-234234..23')
    [<RevisionSpec_revid revid:test@other.com-234234>, <RevisionSpec_int 23>]
    >>> _parse_revision_str('date:2005-04-12')
    [<RevisionSpec_date date:2005-04-12>]
    >>> _parse_revision_str('date:2005-04-12 12:24:33')
    [<RevisionSpec_date date:2005-04-12 12:24:33>]
    >>> _parse_revision_str('date:2005-04-12T12:24:33')
    [<RevisionSpec_date date:2005-04-12T12:24:33>]
    >>> _parse_revision_str('date:2005-04-12,12:24:33')
    [<RevisionSpec_date date:2005-04-12,12:24:33>]
    >>> _parse_revision_str('-5..23')
    [<RevisionSpec_int -5>, <RevisionSpec_int 23>]
    >>> _parse_revision_str('-5')
    [<RevisionSpec_int -5>]
    >>> _parse_revision_str('123a')
    Traceback (most recent call last):
      ...
    BzrError: No namespace registered for string: '123a'
    >>> _parse_revision_str('abc')
    Traceback (most recent call last):
      ...
    BzrError: No namespace registered for string: 'abc'
    >>> _parse_revision_str('branch:../branch2')
    [<RevisionSpec_branch branch:../branch2>]
    >>> _parse_revision_str('branch:../../branch2')
    [<RevisionSpec_branch branch:../../branch2>]
    >>> _parse_revision_str('branch:../../branch2..23')
    [<RevisionSpec_branch branch:../../branch2>, <RevisionSpec_int 23>]
    """
    # TODO: Maybe move this into revisionspec.py
    old_format_re = re.compile('\d*:\d*')
    m = old_format_re.match(revstr)
    revs = []
    if m:
        warning('Colon separator for revision numbers is deprecated.'
                ' Use .. instead')
        for rev in revstr.split(':'):
            if rev:
                revs.append(RevisionSpec(int(rev)))
            else:
                revs.append(RevisionSpec(None))
    else:
        sep = re.compile("\\.\\.(?!/)")
        for x in sep.split(revstr):
            revs.append(RevisionSpec(x or None))
    return revs


def _parse_merge_type(typestring):
    return get_merge_type(typestring)

def get_merge_type(typestring):
    """Attempt to find the merge class/factory associated with a string."""
    from merge import merge_types
    try:
        return merge_types[typestring][0]
    except KeyError:
        templ = '%s%%7s: %%s' % (' '*12)
        lines = [templ % (f[0], f[1][1]) for f in merge_types.iteritems()]
        type_list = '\n'.join(lines)
        msg = "No known merge type %s. Supported types are:\n%s" %\
            (typestring, type_list)
        raise BzrCommandError(msg)

class EnumOption(object):

    def __init__(self, name, factory, choices):
        self.name = name
        self.factory = factory
        self.choices = choices 
        self.default = None

    def python_name(self):
        """Conver a name with spaces and caps to a python variable name"""
        return self.name.lower().replace(' ', '_')

    def add_option(self, parser, short_name):
        """Add this option to an Optparse parser"""
        group = optparse.OptionGroup(parser, self.name)
        for name, help in self.choices:
            option_strings = ['--%s' % name]
            group.add_option(action='callback', 
                              callback=self._optparse_callback,
                              callback_args=(name,),
                              metavar=self.name,
                              help=help,
                              default=OptionParser.DEFAULT_VALUE,
                              dest=self.python_name(),
                              *option_strings)
        parser.add_option_group(group)

    def _optparse_callback(self, option, opt, value, parser, evalue):
        setattr(parser.values, option.dest, self.factory(evalue))

    def iter_switches(self):
        """Iterate through the list of switches provided by the option
        
        :return: an iterator of (name, short_name, argname, help)
        """
        return ((n, None, None, h) for n, h in self.choices)


class Option(object):
    """Description of a command line option"""
    # TODO: Some way to show in help a description of the option argument

    OPTIONS = {}
    SHORT_OPTIONS = {}

    def __init__(self, name, help='', type=None, argname=None):
        """Make a new command option.

        name -- regular name of the command, used in the double-dash
            form and also as the parameter to the command's run() 
            method.

        help -- help message displayed in command help

        type -- function called to parse the option argument, or 
            None (default) if this option doesn't take an argument.

        argname -- name of option argument, if any
        """
        # TODO: perhaps a subclass that automatically does 
        # --option, --no-option for reversible booleans
        self.name = name
        self.help = help
        self.type = type
        if type is None:
            assert argname is None
        elif argname is None:
            argname = 'ARG'
        self.argname = argname

    def short_name(self):
        """Return the single character option for this command, if any.

        Short options are globally registered.
        """
        for short, option in Option.SHORT_OPTIONS.iteritems():
            if option is self:
                return short

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
        optargfn = self.type
        if optargfn is None:
            parser.add_option(action='store_true', dest=self.name, 
                              help=self.help,
                              default=OptionParser.DEFAULT_VALUE,
                              *option_strings)
            negation_strings = ['--%s' % self.get_negation_name()]
            parser.add_option(action='store_const', dest=self.name, 
                              help=optparse.SUPPRESS_HELP,
                              const=OptionParser.DEFAULT_VALUE,
                              *negation_strings)
        else:
            parser.add_option(action='callback', 
                              callback=self._optparse_callback, 
                              type='string', metavar=self.argname.upper(),
                              help=self.help,
                              default=OptionParser.DEFAULT_VALUE, 
                              *option_strings)

    def _optparse_callback(self, option, opt, value, parser):
        setattr(parser.values, self.name, self.type(value))

    def iter_switches(self):
        """Iterate through the list of switches provided by the option
        
        :return: an iterator of (name, short_name, argname, help)
        """
        argname =  self.argname
        if argname is not None:
            argname = argname.upper()
        yield self.name, self.short_name(), argname, self.help


class OptionParser(optparse.OptionParser):
    """OptionParser that raises exceptions instead of exiting"""

    DEFAULT_VALUE = object()

    def error(self, message):
        raise BzrCommandError(message)


def get_optparser(options):
    """Generate an optparse parser for bzrlib-style options"""

    parser = OptionParser()
    parser.remove_option('--help')
    short_options = dict((k.name, v) for v, k in 
                         Option.SHORT_OPTIONS.iteritems())
    for option in options.itervalues():
        option.add_option(parser, short_options.get(option.name))
    return parser


def _global_option(name, **kwargs):
    """Register o as a global option."""
    Option.OPTIONS[name] = Option(name, **kwargs)

Option.OPTIONS['merge-type']=EnumOption('Merge type', get_merge_type, [
                            ('merge3', 'Use built-in diff3-style merge'),
                            ('diff3', 'Use external diff3 merge'),
                            ('weave', 'Use knit merge')])

Option.OPTIONS['log-format']=EnumOption('Log format', str, [
                            ('long', 'Multi-line logs with merges shown'),
                            ('short', 'Two-line logs'),
                            ('line', 'One-line logs')])

_global_option('all')
_global_option('overwrite', help='Ignore differences between branches and '
               'overwrite unconditionally')
_global_option('basis', type=str)
_global_option('bound')
_global_option('diff-options', type=str)
_global_option('help',
               help='show help message')
_global_option('file', type=unicode)
_global_option('force')
_global_option('format', type=unicode)
_global_option('forward')
_global_option('message', type=unicode)
_global_option('no-recurse')
_global_option('prefix', type=str, 
               help='Set prefixes to added to old and new filenames, as '
                    'two values separated by a colon.')
_global_option('profile',
               help='show performance profiling information')
_global_option('revision', type=_parse_revision_str)
_global_option('show-ids', 
               help='show internal object ids')
_global_option('timezone', 
               type=str,
               help='display timezone as local, original, or utc')
_global_option('unbound')
_global_option('verbose',
               help='display more information')
_global_option('version')
_global_option('email')
_global_option('update')
_global_option('root', type=str)
_global_option('no-backup')
_global_option('pattern', type=str)
_global_option('quiet')
_global_option('remember', help='Remember the specified location as a'
               ' default.')
_global_option('reprocess', help='Reprocess to reduce spurious conflicts')
_global_option('kind', type=str)
_global_option('dry-run',
               help="show what would be done, but don't actually do anything")


def _global_short(short_name, long_name):
    assert short_name not in Option.SHORT_OPTIONS
    Option.SHORT_OPTIONS[short_name] = Option.OPTIONS[long_name]
    

Option.SHORT_OPTIONS['F'] = Option.OPTIONS['file']
Option.SHORT_OPTIONS['h'] = Option.OPTIONS['help']
Option.SHORT_OPTIONS['m'] = Option.OPTIONS['message']
Option.SHORT_OPTIONS['r'] = Option.OPTIONS['revision']
Option.SHORT_OPTIONS['v'] = Option.OPTIONS['verbose']
Option.SHORT_OPTIONS['q'] = Option.OPTIONS['quiet']
Option.SHORT_OPTIONS['p'] = Option.OPTIONS['prefix']
