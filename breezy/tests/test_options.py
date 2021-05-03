# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

import re

from .. import (
    bzr,
    commands,
    controldir,
    errors,
    option,
    registry,
    )
from ..builtins import cmd_commit
from ..commands import parse_args
from . import TestCase
from ..bzr import knitrepo


def parse(options, args):
    parser = option.get_optparser(options)
    return parser.parse_args(args)


class OptionTests(TestCase):
    """Command-line option tests"""

    def test_parse_args(self):
        """Option parser"""
        # XXX: Using cmd_commit makes these tests overly sensitive to changes
        # to cmd_commit, when they are meant to be about option parsing in
        # general.
        self.assertEqual(
            ([], {'author': [], 'exclude': [], 'fixes': [], 'help': True,
                  'bugs': []}),
            parse_args(cmd_commit(), ['--help']))
        self.assertEqual(
            ([], {'author': [], 'exclude': [], 'fixes': [], 'message': 'biter',
                  'bugs': []}),
            parse_args(cmd_commit(), ['--message=biter']))

    def test_no_more_opts(self):
        """Terminated options"""
        self.assertEqual(
            (['-file-with-dashes'], {
                'author': [], 'exclude': [], 'fixes': [], 'bugs': []}),
            parse_args(cmd_commit(), ['--', '-file-with-dashes']))

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

    def test_option_help_global_hidden(self):
        """Hidden global options have no help strings."""
        out, err = self.run_bzr('help log')
        self.assertNotContainsRe(out, r'--message')

    def test_option_arg_help(self):
        """Help message shows option arguments."""
        out, err = self.run_bzr('help commit')
        self.assertEqual(err, '')
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
        self.assertEqual((['-']), parse_args(cmd_commit(), ['-'])[0])

    def parse(self, options, args):
        parser = option.get_optparser(options)
        return parser.parse_args(args)

    def test_conversion(self):
        options = [option.Option('hello')]
        opts, args = self.parse(options, ['--no-hello', '--hello'])
        self.assertEqual(True, opts.hello)
        opts, args = self.parse(options, [])
        self.assertFalse(hasattr(opts, 'hello'))
        opts, args = self.parse(options, ['--hello', '--no-hello'])
        self.assertEqual(False, opts.hello)
        options = [option.Option('number', type=int)]
        opts, args = self.parse(options, ['--number', '6'])
        self.assertEqual(6, opts.number)
        self.assertRaises(errors.CommandError, self.parse, options,
                          ['--number'])
        self.assertRaises(errors.CommandError, self.parse, options,
                          ['--no-number'])
        self.assertRaises(errors.CommandError, self.parse, options,
                          ['--number', 'a'])

    def test_is_hidden(self):
        self.assertTrue(option.Option('foo', hidden=True).is_hidden('foo'))
        self.assertFalse(option.Option('foo', hidden=False).is_hidden('foo'))

    def test_registry_conversion(self):
        registry = controldir.ControlDirFormatRegistry()
        bzr.register_metadir(registry, 'one', 'RepositoryFormat7', 'one help')
        bzr.register_metadir(
            registry, 'two', 'RepositoryFormatKnit1', 'two help')
        bzr.register_metadir(registry, 'hidden', 'RepositoryFormatKnit1',
                             'two help', hidden=True)
        registry.set_default('one')
        options = [option.RegistryOption('format', '', registry, str)]
        opts, args = self.parse(options, ['--format', 'one'])
        self.assertEqual({'format': 'one'}, opts)
        opts, args = self.parse(options, ['--format', 'two'])
        self.assertEqual({'format': 'two'}, opts)
        self.assertRaises(option.BadOptionValue, self.parse, options,
                          ['--format', 'three'])
        self.assertRaises(errors.CommandError, self.parse, options,
                          ['--two'])
        options = [option.RegistryOption('format', '', registry, str,
                                         value_switches=True)]
        opts, args = self.parse(options, ['--two'])
        self.assertEqual({'format': 'two'}, opts)
        opts, args = self.parse(options, ['--two', '--one'])
        self.assertEqual({'format': 'one'}, opts)
        opts, args = self.parse(options, ['--two', '--one',
                                          '--format', 'two'])
        self.assertEqual({'format': 'two'}, opts)
        options = [option.RegistryOption('format', '', registry, str,
                                         enum_switch=False)]
        self.assertRaises(errors.CommandError, self.parse, options,
                          ['--format', 'two'])

    def test_override(self):
        options = [option.Option('hello', type=str),
                   option.Option('hi', type=str, param_name='hello')]
        opts, args = self.parse(options, ['--hello', 'a', '--hello', 'b'])
        self.assertEqual('b', opts.hello)
        opts, args = self.parse(options, ['--hello', 'b', '--hello', 'a'])
        self.assertEqual('a', opts.hello)
        opts, args = self.parse(options, ['--hello', 'a', '--hi', 'b'])
        self.assertEqual('b', opts.hello)
        opts, args = self.parse(options, ['--hi', 'b', '--hello', 'a'])
        self.assertEqual('a', opts.hello)

    def test_registry_converter(self):
        options = [option.RegistryOption('format', '',
                                         controldir.format_registry, controldir.format_registry.make_controldir)]
        opts, args = self.parse(options, ['--format', 'knit'])
        self.assertIsInstance(opts.format.repository_format,
                              knitrepo.RepositoryFormatKnit1)

    def test_lazy_registry(self):
        options = [option.RegistryOption('format', '',
                                         lazy_registry=(
                                             'breezy.controldir', 'format_registry'),
                                         converter=str)]
        opts, args = self.parse(options, ['--format', 'knit'])
        self.assertEqual({'format': 'knit'}, opts)
        self.assertRaises(
            option.BadOptionValue, self.parse, options, ['--format', 'BAD'])

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
        self.assertEqual('test option', my_option.help)

    def test_help(self):
        registry = controldir.ControlDirFormatRegistry()
        bzr.register_metadir(registry, 'one', 'RepositoryFormat7', 'one help')
        bzr.register_metadir(registry, 'two',
                             'breezy.bzr.knitrepo.RepositoryFormatKnit1',
                             'two help',
                             )
        bzr.register_metadir(registry, 'hidden', 'RepositoryFormat7', 'hidden help',
                             hidden=True)
        registry.set_default('one')
        options = [option.RegistryOption('format', 'format help', registry,
                                         str, value_switches=True, title='Formats')]
        parser = option.get_optparser(options)
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
        registry = controldir.ControlDirFormatRegistry()
        bzr.register_metadir(registry, 'one', 'RepositoryFormat7', 'one help')
        bzr.register_metadir(registry, 'two',
                             'breezy.bzr.knitrepo.RepositoryFormatKnit1',
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

    def test_option_callback_bool(self):
        "Test booleans get True and False passed correctly to a callback."""
        cb_calls = []

        def cb(option, name, value, parser):
            cb_calls.append((option, name, value, parser))
        options = [option.Option('hello', custom_callback=cb)]
        opts, args = self.parse(options, ['--hello', '--no-hello'])
        self.assertEqual(2, len(cb_calls))
        opt, name, value, parser = cb_calls[0]
        self.assertEqual('hello', name)
        self.assertTrue(value)
        opt, name, value, parser = cb_calls[1]
        self.assertEqual('hello', name)
        self.assertFalse(value)

    def test_option_callback_str(self):
        """Test callbacks work for string options both long and short."""
        cb_calls = []

        def cb(option, name, value, parser):
            cb_calls.append((option, name, value, parser))
        options = [option.Option('hello', type=str, custom_callback=cb,
                                 short_name='h')]
        opts, args = self.parse(options, ['--hello', 'world', '-h', 'mars'])
        self.assertEqual(2, len(cb_calls))
        opt, name, value, parser = cb_calls[0]
        self.assertEqual('hello', name)
        self.assertEqual('world', value)
        opt, name, value, parser = cb_calls[1]
        self.assertEqual('hello', name)
        self.assertEqual('mars', value)


class TestListOptions(TestCase):
    """Tests for ListOption, used to specify lists on the command-line."""

    def parse(self, options, args):
        parser = option.get_optparser(options)
        return parser.parse_args(args)

    def test_list_option(self):
        options = [option.ListOption('hello', type=str)]
        opts, args = self.parse(options, ['--hello=world', '--hello=sailor'])
        self.assertEqual(['world', 'sailor'], opts.hello)

    def test_list_option_with_dash(self):
        options = [option.ListOption('with-dash', type=str)]
        opts, args = self.parse(options, ['--with-dash=world',
                                          '--with-dash=sailor'])
        self.assertEqual(['world', 'sailor'], opts.with_dash)

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

    def test_option_callback_list(self):
        """Test callbacks work for list options."""
        cb_calls = []

        def cb(option, name, value, parser):
            # Note that the value is a reference so copy to keep it
            cb_calls.append((option, name, value[:], parser))
        options = [option.ListOption('hello', type=str, custom_callback=cb)]
        opts, args = self.parse(options, ['--hello=world', '--hello=mars',
                                          '--hello=-'])
        self.assertEqual(3, len(cb_calls))
        opt, name, value, parser = cb_calls[0]
        self.assertEqual('hello', name)
        self.assertEqual(['world'], value)
        opt, name, value, parser = cb_calls[1]
        self.assertEqual('hello', name)
        self.assertEqual(['world', 'mars'], value)
        opt, name, value, parser = cb_calls[2]
        self.assertEqual('hello', name)
        self.assertEqual([], value)

    def test_list_option_param_name(self):
        """Test list options can have their param_name set."""
        options = [option.ListOption('hello', type=str, param_name='greeting')]
        opts, args = self.parse(
            options, ['--hello=world', '--hello=sailor'])
        self.assertEqual(['world', 'sailor'], opts.greeting)


class TestOptionDefinitions(TestCase):
    """Tests for options in the Bazaar codebase."""

    def get_builtin_command_options(self):
        g = []
        commands.install_bzr_command_hooks()
        for cmd_name in sorted(commands.builtin_command_names()):
            cmd = commands.get_cmd_object(cmd_name)
            for opt_name, opt in sorted(cmd.options().items()):
                g.append((cmd_name, opt))
        self.assertTrue(g)
        return g

    def test_option_grammar(self):
        msgs = []
        # Option help should be written in sentence form, and have a final
        # period with an optional bracketed suffix. All the text should be on
        # one line, because the display code will wrap it.
        option_re = re.compile(r'^[A-Z][^\n]+\.(?: \([^\n]+\))?$')
        for scope, opt in self.get_builtin_command_options():
            for name, _, _, helptxt in opt.iter_switches():
                if name != opt.name:
                    name = "/".join([opt.name, name])
                if not helptxt:
                    msgs.append('%-16s %-16s %s' %
                                ((scope or 'GLOBAL'), name, 'NO HELP'))
                elif not option_re.match(helptxt):
                    msgs.append('%-16s %-16s %s' %
                                ((scope or 'GLOBAL'), name, helptxt))
        if msgs:
            self.fail("The following options don't match the style guide:\n"
                      + '\n'.join(msgs))


class TestOptionMisc(TestCase):

    def test_is_hidden(self):
        registry = controldir.ControlDirFormatRegistry()
        bzr.register_metadir(registry, 'hidden', 'HiddenFormat',
                             'hidden help text', hidden=True)
        bzr.register_metadir(registry, 'visible', 'VisibleFormat',
                             'visible help text', hidden=False)
        format = option.RegistryOption('format', '', registry, str)
        self.assertTrue(format.is_hidden('hidden'))
        self.assertFalse(format.is_hidden('visible'))

    def test_short_name(self):
        registry = controldir.ControlDirFormatRegistry()
        opt = option.RegistryOption('format', help='', registry=registry)
        self.assertEqual(None, opt.short_name())
        opt = option.RegistryOption('format', short_name='F', help='',
                                    registry=registry)
        self.assertEqual('F', opt.short_name())

    def test_option_custom_help(self):
        the_opt = option.Option.OPTIONS['help']
        orig_help = the_opt.help[:]
        my_opt = option.custom_help('help', 'suggest lottery numbers')
        # Confirm that my_opt has my help and the original is unchanged
        self.assertEqual('suggest lottery numbers', my_opt.help)
        self.assertEqual(orig_help, the_opt.help)

    def test_short_value_switches(self):
        reg = registry.Registry()
        reg.register('short', 'ShortChoice')
        reg.register('long', 'LongChoice')
        ropt = option.RegistryOption('choice', '', reg, value_switches=True,
                                     short_value_switches={'short': 's'})
        opts, args = parse([ropt], ['--short'])
        self.assertEqual('ShortChoice', opts.choice)
        opts, args = parse([ropt], ['-s'])
        self.assertEqual('ShortChoice', opts.choice)


class TestVerboseQuietLinkage(TestCase):

    def check(self, parser, level, args):
        option._verbosity_level = 0
        opts, args = parser.parse_args(args)
        self.assertEqual(level, option._verbosity_level)

    def test_verbose_quiet_linkage(self):
        parser = option.get_optparser(
            [v for k, v in sorted(option.Option.STD_OPTIONS.items())])
        self.check(parser, 0, [])
        self.check(parser, 1, ['-v'])
        self.check(parser, 2, ['-v', '-v'])
        self.check(parser, -1, ['-q'])
        self.check(parser, -2, ['-qq'])
        self.check(parser, -1, ['-v', '-v', '-q'])
        self.check(parser, 2, ['-q', '-v', '-v'])
        self.check(parser, 0, ['--no-verbose'])
        self.check(parser, 0, ['-v', '-q', '--no-quiet'])
