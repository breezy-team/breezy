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

from bzrlib import (
    builtins,
    bzrdir,
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
           ([], {'help': True}))
        eq(parse_args(cmd_commit(), ['--message=biter']),
           ([], {'message': 'biter'}))
        ## eq(parse_args(cmd_log(),  '-r 500'.split()),
        ##   ([], {'revision': RevisionSpec_int(500)}))

    def test_no_more_opts(self):
        """Terminated options"""
        self.assertEquals(parse_args(cmd_commit(), ['--', '-file-with-dashes']),
                          (['-file-with-dashes'], {}))

    def test_option_help(self):
        """Options have help strings."""
        out, err = self.run_bzr_captured(['commit', '--help'])
        self.assertContainsRe(out, r'--file(.|\n)*file containing commit'
                                   ' message')
        self.assertContainsRe(out, r'-h.*--help')

    def test_option_help_global(self):
        """Global options have help strings."""
        out, err = self.run_bzr_captured(['help', 'status'])
        self.assertContainsRe(out, r'--show-ids.*show internal object')

    def test_option_arg_help(self):
        """Help message shows option arguments."""
        out, err = self.run_bzr_captured(['help', 'commit'])
        self.assertEquals(err, '')
        self.assertContainsRe(out, r'--file[ =]MSGFILE')

    def test_unknown_short_opt(self):
        out, err = self.run_bzr_captured(['help', '-r'], retcode=3)
        self.assertContainsRe(err, r'no such option')

    def test_get_short_name(self):
        file_opt = option.Option.OPTIONS['file']
        self.assertEquals(file_opt.short_name(), 'F')
        force_opt = option.Option.OPTIONS['force']
        self.assertEquals(force_opt.short_name(), None)

    def test_set_short_name(self):
        o = option.Option('wiggle')
        o.set_short_name('w')
        self.assertEqual(o.short_name(), 'w')

    def test_old_short_names(self):
        # test the deprecated method for getting and setting short option
        # names
        expected_warning = (
            "access to SHORT_OPTIONS was deprecated in version 0.14."
            " Set the short option name when constructing the Option.",
            DeprecationWarning, 2)
        _warnings = []
        def capture_warning(message, category, stacklevel=None):
            _warnings.append((message, category, stacklevel))
        old_warning_method = symbol_versioning.warn
        try:
            # an example of the kind of thing plugins might want to do through
            # the old interface - make a new option and then give it a short
            # name.
            symbol_versioning.set_warning_method(capture_warning)
            example_opt = option.Option('example', help='example option')
            option.Option.SHORT_OPTIONS['w'] = example_opt
            self.assertEqual(example_opt.short_name(), 'w')
            self.assertEqual([expected_warning], _warnings)
            # now check that it can actually be parsed with the registered
            # value
            opts, args = parse([example_opt], ['-w', 'foo'])
            self.assertEqual(opts.example, True)
            self.assertEqual(args, ['foo'])
        finally:
            symbol_versioning.set_warning_method(old_warning_method)

    def test_allow_dash(self):
        """Test that we can pass a plain '-' as an argument."""
        self.assertEqual((['-'], {}), parse_args(cmd_commit(), ['-']))

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

#     >>> parse_args('log -r 500'.split())
#     (['log'], {'revision': [<RevisionSpec_int 500>]})
#     >>> parse_args('log -r500..600'.split())
#     (['log'], {'revision': [<RevisionSpec_int 500>, <RevisionSpec_int 600>]})
#     >>> parse_args('log -vr500..600'.split())
#     (['log'], {'verbose': True, 'revision': [<RevisionSpec_int 500>, <RevisionSpec_int 600>]})
#     >>> parse_args('log -rrevno:500..600'.split()) #the r takes an argument
#     (['log'], {'revision': [<RevisionSpec_revno revno:500>, <RevisionSpec_int 600>]})


class ListOptions(TestCase):
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
