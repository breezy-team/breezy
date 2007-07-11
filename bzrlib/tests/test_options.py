# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

import re

from bzrlib import (
    builtins,
    bzrdir,
    commands,
    errors,
    option,
    repository,
    symbol_versioning,
    )
from bzrlib.builtins import cmd_commit, cmd_log, cmd_status
from bzrlib.commands import Command, parse_args
from bzrlib.tests import TestCase
from bzrlib.repofmt import knitrepo


def parse(options, args):
    parser = option.get_optparser(dict((o.name, o) for o in options))
    return parser.parse_args(args)


class OptionTests(TestCase):
    """Command-line option tests"""

    def test_parse_args(self):
        """Option parser"""
        eq = self.assertEquals
        eq(parse_args(cmd_commit(), ['--help']),
           ([], {'fixes': [], 'help': True}))
        eq(parse_args(cmd_commit(), ['--message=biter']),
           ([], {'fixes': [], 'message': 'biter'}))

    def test_no_more_opts(self):
        """Terminated options"""
        self.assertEquals(parse_args(cmd_commit(), ['--', '-file-with-dashes']),
                          (['-file-with-dashes'], {'fixes': []}))

    def test_option_help(self):
        """Options have help strings."""
        out, err = self.run_bzr('commit --help')
        self.assertContainsRe(out,
                r'--file(.|\n)*Take commit message from this file\.')
        self.assertContainsRe(out, r'-h.*--help')

    def test_option_help_global(self):
        """Global options have help strings."""
        out, err = self.run_bzr('help status')
        self.assertContainsRe(out, r'--show-ids.*Show internal object.')

    def test_option_arg_help(self):
        """Help message shows option arguments."""
        out, err = self.run_bzr('help commit')
        self.assertEquals(err, '')
        self.assertContainsRe(out, r'--file[ =]MSGFILE')

    def test_unknown_short_opt(self):
        out, err = self.run_bzr('help -r', retcode=3)
        self.assertContainsRe(err, r'no such option')

    def test_set_short_name(self):
        o = option.Option('wiggle')
        o.set_short_name('w')
        self.assertEqual(o.short_name(), 'w')

    def test_allow_dash(self):
        """Test that we can pass a plain '-' as an argument."""
        self.assertEqual(
            (['-'], {'fixes': []}), parse_args(cmd_commit(), ['-']))

    def parse(self, options, args):
        parser = option.get_optparser(dict((o.name, o) for o in options))
        return parser.parse_args(args)

    def test_conversion(self):
        options = [option.Option('hello')]
        opts, args = self.parse(options, ['--no-hello', '--hello'])
        self.assertEqual(True, opts.hello)
        opts, args = self.parse(options, [])
        self.assertEqual(option.OptionParser.DEFAULT_VALUE, opts.hello)
        opts, args = self.parse(options, ['--hello', '--no-hello'])
        self.assertEqual(False, opts.hello)
        options = [option.Option('number', type=int)]
        opts, args = self.parse(options, ['--number', '6'])
        self.assertEqual(6, opts.number)
        self.assertRaises(errors.BzrCommandError, self.parse, options,
                          ['--number'])
        self.assertRaises(errors.BzrCommandError, self.parse, options,
                          ['--no-number'])

    def test_registry_conversion(self):
        registry = bzrdir.BzrDirFormatRegistry()
        registry.register_metadir('one', 'RepositoryFormat7', 'one help')
        registry.register_metadir('two', 'RepositoryFormatKnit1', 'two help')
        registry.register_metadir('hidden', 'RepositoryFormatKnit1',
            'two help', hidden=True)
        registry.set_default('one')
        options = [option.RegistryOption('format', '', registry, str)]
        opts, args = self.parse(options, ['--format', 'one'])
        self.assertEqual({'format':'one'}, opts)
        opts, args = self.parse(options, ['--format', 'two'])
        self.assertEqual({'format':'two'}, opts)
        self.assertRaises(errors.BadOptionValue, self.parse, options,
                          ['--format', 'three'])
        self.assertRaises(errors.BzrCommandError, self.parse, options,
                          ['--two'])
        options = [option.RegistryOption('format', '', registry, str,
                   value_switches=True)]
        opts, args = self.parse(options, ['--two'])
        self.assertEqual({'format':'two'}, opts)
        opts, args = self.parse(options, ['--two', '--one'])
        self.assertEqual({'format':'one'}, opts)
        opts, args = self.parse(options, ['--two', '--one',
                                          '--format', 'two'])
        self.assertEqual({'format':'two'}, opts)
        options = [option.RegistryOption('format', '', registry, str,
                   enum_switch=False)]
        self.assertRaises(errors.BzrCommandError, self.parse, options,
                          ['--format', 'two'])

    def test_registry_converter(self):
        options = [option.RegistryOption('format', '',
                   bzrdir.format_registry, bzrdir.format_registry.make_bzrdir)]
        opts, args = self.parse(options, ['--format', 'knit'])
        self.assertIsInstance(opts.format.repository_format,
                              knitrepo.RepositoryFormatKnit1)

    def test_from_kwargs(self):
        my_option = option.RegistryOption.from_kwargs('my-option',
            help='test option', short='be short', be_long='go long')
        self.assertEqual(['my-option'],
            [x[0] for x in my_option.iter_switches()])
        my_option = option.RegistryOption.from_kwargs('my-option',
            help='test option', title="My option", short='be short',
            be_long='go long', value_switches=True)
        self.assertEqual(['my-option', 'be-long', 'short'],
            [x[0] for x in my_option.iter_switches()])

    def test_help(self):
        registry = bzrdir.BzrDirFormatRegistry()
        registry.register_metadir('one', 'RepositoryFormat7', 'one help')
        registry.register_metadir('two',
            'bzrlib.repofmt.knitrepo.RepositoryFormatKnit1',
            'two help',
            )
        registry.register_metadir('hidden', 'RepositoryFormat7', 'hidden help',
            hidden=True)
        registry.set_default('one')
        options = [option.RegistryOption('format', 'format help', registry,
                   str, value_switches=True, title='Formats')]
        parser = option.get_optparser(dict((o.name, o) for o in options))
        value = parser.format_option_help()
        self.assertContainsRe(value, 'format.*format help')
        self.assertContainsRe(value, 'one.*one help')
        self.assertContainsRe(value, 'Formats:\n *--format')
        self.assertNotContainsRe(value, 'hidden help')

    def test_iter_switches(self):
        opt = option.Option('hello', help='fg')
        self.assertEqual(list(opt.iter_switches()),
                         [('hello', None, None, 'fg')])
        opt = option.Option('hello', help='fg', type=int)
        self.assertEqual(list(opt.iter_switches()),
                         [('hello', None, 'ARG', 'fg')])
        opt = option.Option('hello', help='fg', type=int, argname='gar')
        self.assertEqual(list(opt.iter_switches()),
                         [('hello', None, 'GAR', 'fg')])
        registry = bzrdir.BzrDirFormatRegistry()
        registry.register_metadir('one', 'RepositoryFormat7', 'one help')
        registry.register_metadir('two',
                'bzrlib.repofmt.knitrepo.RepositoryFormatKnit1',
                'two help',
                )
        registry.set_default('one')
        opt = option.RegistryOption('format', 'format help', registry,
                                    value_switches=False)
        self.assertEqual(list(opt.iter_switches()),
                         [('format', None, 'ARG', 'format help')])
        opt = option.RegistryOption('format', 'format help', registry,
                                    value_switches=True)
        self.assertEqual(list(opt.iter_switches()),
                         [('format', None, 'ARG', 'format help'),
                          ('default', None, None, 'one help'),
                          ('one', None, None, 'one help'),
                          ('two', None, None, 'two help'),
                          ])


class TestListOptions(TestCase):
    """Tests for ListOption, used to specify lists on the command-line."""

    def parse(self, options, args):
        parser = option.get_optparser(dict((o.name, o) for o in options))
        return parser.parse_args(args)

    def test_list_option(self):
        options = [option.ListOption('hello', type=str)]
        opts, args = self.parse(options, ['--hello=world', '--hello=sailor'])
        self.assertEqual(['world', 'sailor'], opts.hello)

    def test_list_option_no_arguments(self):
        options = [option.ListOption('hello', type=str)]
        opts, args = self.parse(options, [])
        self.assertEqual([], opts.hello)

    def test_list_option_with_int_type(self):
        options = [option.ListOption('hello', type=int)]
        opts, args = self.parse(options, ['--hello=2', '--hello=3'])
        self.assertEqual([2, 3], opts.hello)

    def test_list_option_with_int_type_can_be_reset(self):
        options = [option.ListOption('hello', type=int)]
        opts, args = self.parse(options, ['--hello=2', '--hello=3',
                                          '--hello=-', '--hello=5'])
        self.assertEqual([5], opts.hello)

    def test_list_option_can_be_reset(self):
        """Passing an option of '-' to a list option should reset the list."""
        options = [option.ListOption('hello', type=str)]
        opts, args = self.parse(
            options, ['--hello=a', '--hello=b', '--hello=-', '--hello=c'])
        self.assertEqual(['c'], opts.hello)


class TestOptionDefinitions(TestCase):
    """Tests for options in the Bazaar codebase."""

    def get_all_options(self):
        """Return a list of all options used by Bazaar, both global and command.
        
        The list returned contains elements of (scope, option) where 'scope' 
        is either None for global options, or a command name.

        This includes options provided by plugins.
        """
        g = [(None, opt) for name, opt
             in sorted(option.Option.OPTIONS.items())]
        for cmd_name, cmd_class in sorted(commands.get_all_cmds()):
            cmd = cmd_class()
            for opt_name, opt in sorted(cmd.options().items()):
                g.append((cmd_name, opt))
        return g

    def test_get_all_options(self):
        all = self.get_all_options()
        self.assertTrue(len(all) > 100,
                "too few options found: %r" % all)

    def test_global_options_used(self):
        # In the distant memory, options could only be declared globally.  Now
        # we prefer to declare them in the command, unless like -r they really
        # are used very widely with the exact same meaning.  So this checks
        # for any that should be garbage collected.
        g = dict(option.Option.OPTIONS.items())
        used_globals = set()
        msgs = []
        for cmd_name, cmd_class in sorted(commands.get_all_cmds()):
            for option_or_name in sorted(cmd_class.takes_options):
                if not isinstance(option_or_name, basestring):
                    self.assertIsInstance(option_or_name, option.Option)
                elif not option_or_name in g:
                    msgs.append("apparent reference to undefined "
                        "global option %r from %r"
                        % (option_or_name, cmd_class))
                else:
                    used_globals.add(option_or_name)
        unused_globals = set(g.keys()) - used_globals
        for option_name in sorted(unused_globals):
            msgs.append("unused global option %r" % option_name)
        if msgs:
            self.fail("problems with global option definitions:\n"
                    + '\n'.join(msgs))

    def test_option_grammar(self):
        msgs = []
        # Option help should be written in sentence form, and have a final
        # period and be all on a single line, because the display code will
        # wrap it.
        option_re = re.compile(r'^[A-Z][^\n]+\.$')
        for scope, option in self.get_all_options():
            if not option.help:
                # msgs.append('%-16s %-16s %s' %
                #        ((scope or 'GLOBAL'), option.name, 'NO HELP'))
                pass
            elif not option_re.match(option.help):
                msgs.append('%-16s %-16s %s' %
                        ((scope or 'GLOBAL'), option.name, option.help))
        if msgs:
            self.fail("The following options don't match the style guide:\n"
                    + '\n'.join(msgs))

    # TODO: Scan for global options that aren't used by any command?
    #
    # TODO: Check that there are two spaces between sentences.
