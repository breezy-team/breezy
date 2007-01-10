# Copyright (C) 2005, 2006 Canonical Ltd
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

from bzrlib.builtins import cmd_commit, cmd_log, cmd_status
from bzrlib.commands import Command, parse_args
from bzrlib import errors
from bzrlib import option
from bzrlib.tests import TestCase

# TODO: might be nice to just parse them into a structured form and test
# against that, rather than running the whole command.

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

    def test_allow_dash(self):
        """Test that we can pass a plain '-' as an argument."""
        self.assertEqual((['-'], {}), parse_args(cmd_commit(), ['-']))

    def test_conversion(self):
        def parse(options, args):
            parser = option.get_optparser(dict((o.name, o) for o in options))
            return parser.parse_args(args)
        options = [option.Option('hello')]
        opts, args = parse(options, ['--no-hello', '--hello'])
        self.assertEqual(True, opts.hello)
        opts, args = parse(options, [])
        self.assertEqual(option.OptionParser.DEFAULT_VALUE, opts.hello)
        opts, args = parse(options, ['--hello', '--no-hello'])
        self.assertEqual(False, opts.hello)
        options = [option.Option('number', type=int)]
        opts, args = parse(options, ['--number', '6'])
        self.assertEqual(6, opts.number)
        self.assertRaises(errors.BzrCommandError, parse, options, ['--number'])
        self.assertRaises(errors.BzrCommandError, parse, options, 
                          ['--no-number'])

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

#     >>> parse_args('log -r 500'.split())
#     (['log'], {'revision': [<RevisionSpec_int 500>]})
#     >>> parse_args('log -r500..600'.split())
#     (['log'], {'revision': [<RevisionSpec_int 500>, <RevisionSpec_int 600>]})
#     >>> parse_args('log -vr500..600'.split())
#     (['log'], {'verbose': True, 'revision': [<RevisionSpec_int 500>, <RevisionSpec_int 600>]})
#     >>> parse_args('log -rrevno:500..600'.split()) #the r takes an argument
#     (['log'], {'revision': [<RevisionSpec_revno revno:500>, <RevisionSpec_int 600>]})
