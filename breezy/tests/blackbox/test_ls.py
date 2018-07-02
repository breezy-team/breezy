# Copyright (C) 2006-2012 Canonical Ltd
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

"""External tests of 'brz ls'"""

from breezy import (
    ignores,
    tests,
    )
from breezy.tests.matchers import ContainsNoVfsCalls


class TestLS(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestLS, self).setUp()

        # Create a simple branch that can be used in testing
        ignores._set_user_ignores(['user-ignore'])

        self.wt = self.make_branch_and_tree('.')
        self.build_tree_contents([
                                 ('.bzrignore', b'*.pyo\n'),
                                 ('a', b'hello\n'),
                                 ])

    def ls_equals(self, value, args=None, recursive=True, working_dir=None):
        command = 'ls'
        if args is not None:
            command += ' ' + args
        if recursive:
            command += ' -R'
        out, err = self.run_bzr(command, working_dir=working_dir)
        self.assertEqual(b'', err)
        self.assertEqualDiff(value, out)

    def test_ls_null_verbose(self):
        # Can't supply both
        self.run_bzr_error([b'Cannot set both --verbose and --null'],
                           'ls --verbose --null')

    def test_ls_basic(self):
        """Test the abilities of 'brz ls'"""
        self.ls_equals(b'.bzrignore\na\n')
        self.ls_equals(b'.bzrignore\na\n', './')
        self.ls_equals(b'?        .bzrignore\n'
                       b'?        a\n',
                       b'--verbose')
        self.ls_equals(b'.bzrignore\n'
                       b'a\n',
                       b'--unknown')
        self.ls_equals(b'', '--ignored')
        self.ls_equals(b'', '--versioned')
        self.ls_equals(b'', '-V')
        self.ls_equals(b'.bzrignore\n'
                       b'a\n',
                       b'--unknown --ignored --versioned')
        self.ls_equals(b'.bzrignore\n'
                       b'a\n',
                       b'--unknown --ignored -V')
        self.ls_equals(b'', '--ignored --versioned')
        self.ls_equals(b'', '--ignored -V')
        self.ls_equals(b'.bzrignore\0a\0', '--null')

    def test_ls_added(self):
        self.wt.add(['a'])
        self.ls_equals(b'?        .bzrignore\n'
                       b'V        a\n',
                       b'--verbose')
        self.wt.commit('add')

        self.build_tree(['subdir/'])
        self.ls_equals(b'?        .bzrignore\n'
                       b'V        a\n'
                       b'?        subdir/\n'
                       , '--verbose')
        self.build_tree(['subdir/b'])
        self.wt.add(['subdir/', 'subdir/b', '.bzrignore'])
        self.ls_equals(b'V        .bzrignore\n'
                       b'V        a\n'
                       b'V        subdir/\n'
                       b'V        subdir/b\n'
                       , '--verbose')

    def test_show_ids(self):
        self.build_tree(['subdir/'])
        self.wt.add(['a', 'subdir'], [b'a-id', b'subdir-id'])
        self.ls_equals(
            b'.bzrignore                                         \n'
            b'a                                                  a-id\n'
            b'subdir/                                            subdir-id\n',
            b'--show-ids')
        self.ls_equals(
            b'?        .bzrignore\n'
            b'V        a                                         a-id\n'
            b'V        subdir/                                   subdir-id\n',
            b'--show-ids --verbose')
        self.ls_equals(b'.bzrignore\0\0'
                       b'a\0a-id\0'
                       b'subdir\0subdir-id\0', '--show-ids --null')

    def test_ls_no_recursive(self):
        self.build_tree(['subdir/', 'subdir/b'])
        self.wt.add(['a', 'subdir/', 'subdir/b', '.bzrignore'])

        self.ls_equals(b'.bzrignore\n'
                       b'a\n'
                       b'subdir/\n'
                       , recursive=False)

        self.ls_equals(b'V        .bzrignore\n'
                       b'V        a\n'
                       b'V        subdir/\n'
                       , '--verbose', recursive=False)

        # Check what happens in a sub-directory
        self.ls_equals(b'b\n', working_dir='subdir')
        self.ls_equals(b'b\0', '--null', working_dir='subdir')
        self.ls_equals(b'subdir/b\n', '--from-root', working_dir='subdir')
        self.ls_equals(b'subdir/b\0', '--from-root --null',
                       working_dir='subdir')
        self.ls_equals(b'subdir/b\n', '--from-root', recursive=False,
                       working_dir='subdir')

    def test_ls_path(self):
        """If a path is specified, files are listed with that prefix"""
        self.build_tree(['subdir/', 'subdir/b'])
        self.wt.add(['subdir', 'subdir/b'])
        self.ls_equals(b'subdir/b\n',
                       b'subdir')
        self.ls_equals(b'../.bzrignore\n'
                       b'../a\n'
                       b'../subdir/\n'
                       b'../subdir/b\n',
                       b'..', working_dir='subdir')
        self.ls_equals(b'../.bzrignore\0'
                       b'../a\0'
                       b'../subdir\0'
                       b'../subdir/b\0',
                       b'.. --null', working_dir='subdir')
        self.ls_equals(b'?        ../.bzrignore\n'
                       b'?        ../a\n'
                       b'V        ../subdir/\n'
                       b'V        ../subdir/b\n',
                       b'.. --verbose', working_dir='subdir')
        self.run_bzr_error([b'cannot specify both --from-root and PATH'],
                           'ls --from-root ..', working_dir='subdir')

    def test_ls_revision(self):
        self.wt.add(['a'])
        self.wt.commit('add')

        self.build_tree(['subdir/'])

        # Check what happens when we supply a specific revision
        self.ls_equals(b'a\n', '--revision 1')
        self.ls_equals(b'V        a\n'
                       , '--verbose --revision 1')

        self.ls_equals(b'', '--revision 1', working_dir='subdir')

    def test_ls_branch(self):
        """If a branch is specified, files are listed from it"""
        self.build_tree(['subdir/', 'subdir/b'])
        self.wt.add(['subdir', 'subdir/b'])
        self.wt.commit('committing')
        branch = self.make_branch('branchdir')
        branch.pull(self.wt.branch)
        self.ls_equals(b'branchdir/subdir/\n'
                       b'branchdir/subdir/b\n',
                       b'branchdir')
        self.ls_equals(b'branchdir/subdir/\n'
                       b'branchdir/subdir/b\n',
                       b'branchdir --revision 1')

    def test_ls_ignored(self):
        # Now try to do ignored files.
        self.wt.add(['a', '.bzrignore'])

        self.build_tree(['blah.py', 'blah.pyo', 'user-ignore'])
        self.ls_equals(b'.bzrignore\n'
                       b'a\n'
                       b'blah.py\n'
                       b'blah.pyo\n'
                       b'user-ignore\n'
                       )
        self.ls_equals(b'V        .bzrignore\n'
                       b'V        a\n'
                       b'?        blah.py\n'
                       b'I        blah.pyo\n'
                       b'I        user-ignore\n'
                       , '--verbose')
        self.ls_equals(b'blah.pyo\n'
                       b'user-ignore\n'
                       , '--ignored')
        self.ls_equals(b'blah.py\n'
                       , '--unknown')
        self.ls_equals(b'.bzrignore\n'
                       b'a\n'
                       , '--versioned')
        self.ls_equals(b'.bzrignore\n'
                       b'a\n'
                       , '-V')

    def test_kinds(self):
        self.build_tree(['subdir/'])
        self.ls_equals(b'.bzrignore\n'
                       b'a\n',
                       b'--kind=file')
        self.ls_equals(b'subdir/\n',
                       b'--kind=directory')
        self.ls_equals(b'',
                       b'--kind=symlink')
        self.run_bzr_error([b'invalid kind specified'], 'ls --kind=pile')

    def test_ls_path_nonrecursive(self):
        self.ls_equals(b'%s/.bzrignore\n'
                       b'%s/a\n'
                       % (self.test_dir, self.test_dir),
                       self.test_dir, recursive=False)

    def test_ls_directory(self):
        """Test --directory option"""
        self.wt = self.make_branch_and_tree('dir')
        self.build_tree(['dir/sub/', 'dir/sub/file'])
        self.wt.add(['sub', 'sub/file'])
        self.wt.commit('commit')
        self.ls_equals(b'sub/\nsub/file\n', '--directory=dir')
        self.ls_equals(b'sub/file\n', '-d dir sub')


class TestSmartServerLs(tests.TestCaseWithTransport):

    def test_simple_ls(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/foo', b'thecontents')])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(['ls', self.get_url('branch')])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(6, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
