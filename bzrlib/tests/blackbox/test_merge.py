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


"""Black-box tests for bzr merge.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.osutils import abspath


class TestMerge(ExternalBase):

    def example_branch(test):
        test.runbzr('init')
        file('hello', 'wt').write('foo')
        test.runbzr('add hello')
        test.runbzr('commit -m setup hello')
        file('goodbye', 'wt').write('baz')
        test.runbzr('add goodbye')
        test.runbzr('commit -m setup goodbye')

    def test_merge_remember(self):
        """Merge changes from one branch to another and test parent location."""
        os.mkdir('a')
        os.chdir('a')

        self.example_branch()
        self.runbzr('branch . ../b')
        self.runbzr('branch . ../c')
        file('bottles', 'wt').write('99 bottles of beer on the wall')
        self.runbzr('add bottles')
        self.runbzr('commit -m 99_bottles')
        os.chdir('../b')
        b = Branch.open('')
        parent = b.get_parent()
        # reset parent
        b.set_parent(None)
        self.assertEqual(None, b.get_parent())
        # test merge for failure without parent set
        out = self.runbzr('merge', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: No merge branch known or specified.\n'))
        # test implicit --remember when no parent set, this merge conflicts
        file('bottles', 'wt').write('98 bottles of beer on the wall')
        self.runbzr('add bottles')
        out = self.runbzr('merge ../a', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: Working tree has uncommitted changes.\n'))
        self.assertEquals(abspath(b.get_parent()), abspath(parent))
        # test implicit --remember after resolving conflict
        self.runbzr('revert')
        os.unlink('bottles')
        self.runbzr('merge')
        self.assertEquals(abspath(b.get_parent()), abspath(parent))
        self.runbzr('commit -m merge_a')
        # test explicit --remember
        self.runbzr('merge ../c --remember')
        self.assertEquals(abspath(b.get_parent()), abspath('../c'))
        self.runbzr('commit -m merge_c --unchanged')
