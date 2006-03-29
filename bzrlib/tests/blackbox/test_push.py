# Copyright (C) 2005 by Canonical Ltd
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Black-box tests for bzr push.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.osutils import abspath


class TestPush(ExternalBase):

    def example_branch(test):
        test.runbzr('init')
        file('hello', 'wt').write('foo')
        test.runbzr('add hello')
        test.runbzr('commit -m setup hello')
        file('goodbye', 'wt').write('baz')
        test.runbzr('add goodbye')
        test.runbzr('commit -m setup goodbye')

    def test_push_remember(self):
        """Push changes from one branch to another and test push location."""
        os.mkdir('a')
        os.chdir('a')

        self.example_branch()
        self.runbzr('init ../b')
        self.runbzr('init ../c')
        os.chdir('../b')
        file('bottles', 'wt').write('99 bottles of beer on the wall')
        self.runbzr('add bottles')
        self.runbzr('commit -m 99_bottles')
        os.chdir('../a')
        b = Branch.open('')
        # initial push location must be empty
        self.assertEqual(None, b.get_push_location())
        # test push for failure without push location set
        out = self.runbzr('push', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: No push location known or specified.\n'))
        # test implicit --remember when no push location set, push fails
        out = self.runbzr('push ../b', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: These branches have diverged.  '
                    'Try a merge then push with overwrite.\n'))
        self.assertEquals(abspath(b.get_push_location()), abspath('../b'))
        # test implicit --remember after resolving previous failure
        os.chdir('../b')
        self.runbzr('uncommit --force')
        os.chdir('../a')
        self.runbzr('push')
        self.assertEquals(abspath(b.get_push_location()), abspath('../b'))
        # test explicit --remember
        self.runbzr('push ../c --remember')
        self.assertEquals(abspath(b.get_push_location()), abspath('../c'))
