# Copyright (C) 2006 by Canonical Ltd
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

"""External tests of 'bzr ls'"""

import os

from bzrlib import ignores
from bzrlib.tests import TestCaseWithTransport


class TestLS(TestCaseWithTransport):

    def setUp(self):
        super(TestLS, self).setUp()
        
        # Create a simple branch that can be used in testing
        ignores._set_user_ignores(['user-ignore'])

        self.wt = self.make_branch_and_tree('.')
        self.build_tree_contents([
                                 ('.bzrignore', '*.pyo\n'),
                                 ('a', 'hello\n'),
                                 ])

    def ls_equals(self, value, *args):
        out, err = self.run_bzr('ls', *args)
        self.assertEqual('', err)
        self.assertEqual(value, out)

    def test_ls_null_verbose(self):
        # Can't supply both
        self.run_bzr_error(['Cannot set both --verbose and --null'],
                           'ls', '--verbose', '--null')

    def test_ls_basic(self):
        """Test the abilities of 'bzr ls'"""
        self.ls_equals('.bzrignore\na\n')
        self.ls_equals('?        .bzrignore\n'
                       '?        a\n',
                       '--verbose')
        self.ls_equals('.bzrignore\n'
                       'a\n',
                       '--unknown')
        self.ls_equals('', '--ignored')
        self.ls_equals('', '--versioned')
        self.ls_equals('.bzrignore\n'
                       'a\n',
                       '--unknown', '--ignored', '--versioned')
        self.ls_equals('', '--ignored', '--versioned')
        self.ls_equals('.bzrignore\0a\0', '--null')

    def test_ls_added(self):
        self.wt.add(['a'])
        self.ls_equals('?        .bzrignore\n'
                       'V        a\n',
                       '--verbose')
        self.wt.commit('add')
        
        self.build_tree(['subdir/'])
        self.ls_equals('?        .bzrignore\n'
                       'V        a\n'
                       '?        subdir/\n'
                       , '--verbose')
        self.build_tree(['subdir/b'])
        self.wt.add(['subdir/', 'subdir/b', '.bzrignore'])
        self.ls_equals('V        .bzrignore\n'
                       'V        a\n'
                       'V        subdir/\n'
                       'V        subdir/b\n'
                       , '--verbose')

    def test_ls_recursive(self):
        self.build_tree(['subdir/', 'subdir/b'])
        self.wt.add(['a', 'subdir/', 'subdir/b', '.bzrignore'])

        self.ls_equals('.bzrignore\n'
                       'a\n'
                       'subdir\n'
                       , '--non-recursive')

        self.ls_equals('V        .bzrignore\n'
                       'V        a\n'
                       'V        subdir/\n'
                       , '--verbose', '--non-recursive')

        # Check what happens in a sub-directory
        os.chdir('subdir')
        self.ls_equals('b\n')
        self.ls_equals('b\0'
                  , '--null')
        self.ls_equals('.bzrignore\n'
                       'a\n'
                       'subdir\n'
                       'subdir/b\n'
                       , '--from-root')
        self.ls_equals('.bzrignore\0'
                       'a\0'
                       'subdir\0'
                       'subdir/b\0'
                       , '--from-root', '--null')
        self.ls_equals('.bzrignore\n'
                       'a\n'
                       'subdir\n'
                       , '--from-root', '--non-recursive')

    def test_ls_revision(self):
        self.wt.add(['a'])
        self.wt.commit('add')

        self.build_tree(['subdir/'])

        # Check what happens when we supply a specific revision
        self.ls_equals('a\n', '--revision', '1')
        self.ls_equals('V        a\n'
                       , '--verbose', '--revision', '1')

        os.chdir('subdir')
        self.ls_equals('', '--revision', '1')

    def test_ls_ignored(self):
        # Now try to do ignored files.
        self.wt.add(['a', '.bzrignore'])

        self.build_tree(['blah.py', 'blah.pyo', 'user-ignore'])
        self.ls_equals('.bzrignore\n'
                       'a\n'
                       'blah.py\n'
                       'blah.pyo\n'
                       'user-ignore\n'
                       )
        self.ls_equals('V        .bzrignore\n'
                       'V        a\n'
                       '?        blah.py\n'
                       'I        blah.pyo\n'
                       'I        user-ignore\n'
                       , '--verbose')
        self.ls_equals('blah.pyo\n'
                       'user-ignore\n'
                       , '--ignored')
        self.ls_equals('blah.py\n'
                       , '--unknown')
        self.ls_equals('.bzrignore\n'
                       'a\n'
                       , '--versioned')

