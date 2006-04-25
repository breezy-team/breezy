# Copyright (C) 2005 by Canonical Ltd
# -*- coding: utf-8 -*-
# vim: encoding=utf-8

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
"""Black-box tests for bzr missing.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir


class TestMissing(TestCaseInTempDir):

    def test_missing(self):
        def bzr(*args, **kwargs):
            return self.run_bzr(*args, **kwargs)[0]
        missing = "You are missing 1 revision(s):"

        # create a source branch
        os.mkdir('a')
        os.chdir('a')
        bzr('init')
        open('a', 'wb').write('initial\n')
        bzr('add', 'a')
        bzr('commit', '-m', 'inital')

        # clone and add a differing revision
        bzr('branch', '.', '../b')
        os.chdir('../b')
        open('a', 'ab').write('more\n')
        bzr('commit', '-m', 'more')

        # run missing in a against b
        os.chdir('../a')
        # this should not require missing to take out a write lock on a 
        # or b. So we take a write lock on both to test that at the same
        # time. This may let the test pass while the default branch is an
        # os-locking branch, but it will trigger failures with lockdir based
        # branches.
        branch_a = Branch.open('.')
        branch_a.lock_write()
        branch_b = Branch.open('../b')
        branch_b.lock_write()
        out,err = self.run_bzr('missing', '../b', retcode=1)
        lines = out.splitlines()
        # we're missing the extra revision here
        self.assertEqual(missing, lines[0])
        # and we expect 8 lines of output which we trust at the moment to be
        # good.
        self.assertEqual(8, len(lines))
        # we do not expect any error output.
        self.assertEqual('', err)
        # unlock the branches for the rest of the test
        branch_a.unlock()
        branch_b.unlock()

        # get extra revision from b
        bzr('merge', '../b')
        bzr('commit', '-m', 'merge')

        # compare again, but now we have the 'merge' commit extra
        lines = bzr('missing', '../b', retcode=1).splitlines()
        self.assertEqual("You have 1 extra revision(s):", lines[0])
        self.assertEqual(8, len(lines))
        lines2 = bzr('missing', '../b', '--mine-only', retcode=1)
        lines2 = lines2.splitlines()
        self.assertEqual(lines, lines2)
        lines3 = bzr('missing', '../b', '--theirs-only', retcode=1)
        lines3 = lines3.splitlines()
        self.assertEqual(0, len(lines3))

        # relative to a, missing the 'merge' commit 
        os.chdir('../b')
        lines = bzr('missing', '../a', retcode=1).splitlines()
        self.assertEqual(missing, lines[0])
        self.assertEqual(8, len(lines))
        lines2 = bzr('missing', '../a', '--theirs-only', retcode=1)
        lines2 = lines2.splitlines()
        self.assertEqual(lines, lines2)
        lines3 = bzr('missing', '../a', '--mine-only', retcode=1)
        lines3 = lines3.splitlines()
        self.assertEqual(0, len(lines3))
        lines4 = bzr('missing', '../a', '--short', retcode=1)
        lines4 = lines4.splitlines()
        self.assertEqual(4, len(lines4))
        lines5 = bzr('missing', '../a', '--line', retcode=1)
        lines5 = lines5.splitlines()
        self.assertEqual(2, len(lines5))
        lines6 = bzr('missing', '../a', '--reverse', retcode=1)
        lines6 = lines6.splitlines()
        self.assertEqual(lines6, lines)
        lines7 = bzr('missing', '../a', '--show-ids', retcode=1)
        lines7 = lines7.splitlines()
        self.assertEqual(11, len(lines7))
        lines8 = bzr('missing', '../a', '--verbose', retcode=1)
        lines8 = lines8.splitlines()
        self.assertEqual("modified:", lines8[-2])
        self.assertEqual("  a", lines8[-1])

        
        # after a pull we're back on track
        bzr('pull')
        self.assertEqual("Branches are up to date.\n", 
                         bzr('missing', '../a'))

