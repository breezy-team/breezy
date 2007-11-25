# Copyright (C) 2005 Canonical Ltd
# -*- coding: utf-8 -*-
# vim: encoding=utf-8
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

"""Black-box tests for bzr missing."""

import os

from bzrlib import osutils

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseWithTransport


class TestMissing(TestCaseWithTransport):

    def test_missing(self):
        missing = "You are missing 1 revision(s):"

        # create a source branch
        a_tree = self.make_branch_and_tree('a')
        self.build_tree_contents([('a/a', 'initial\n')])
        a_tree.add('a')
        a_tree.commit(message='initial')

        # clone and add a differing revision
        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()
        self.build_tree_contents([('b/a', 'initial\nmore\n')])
        b_tree.commit(message='more')

        # run missing in a against b
        # this should not require missing to take out a write lock on a 
        # or b. So we take a write lock on both to test that at the same
        # time. This may let the test pass while the default branch is an
        # os-locking branch, but it will trigger failures with lockdir based
        # branches.
        a_branch = a_tree.branch
        a_branch.lock_write()
        b_branch = b_tree.branch
        b_branch.lock_write()
        os.chdir('a')
        out,err = self.run_bzr('missing ../b', retcode=1)
        lines = out.splitlines()
        # we're missing the extra revision here
        self.assertEqual(missing, lines[0])
        # and we expect 8 lines of output which we trust at the moment to be
        # good.
        self.assertEqual(8, len(lines))
        # we do not expect any error output.
        self.assertEqual('', err)
        # unlock the branches for the rest of the test
        a_branch.unlock()
        b_branch.unlock()

        # get extra revision from b
        a_tree.merge_from_branch(b_branch)
        a_tree.commit(message='merge')

        # compare again, but now we have the 'merge' commit extra
        lines = self.run_bzr('missing ../b', retcode=1)[0].splitlines()
        self.assertEqual("You have 1 extra revision(s):", lines[0])
        self.assertEqual(8, len(lines))
        lines2 = self.run_bzr('missing ../b --mine-only', retcode=1)[0]
        lines2 = lines2.splitlines()
        self.assertEqual(lines, lines2)
        lines3 = self.run_bzr('missing ../b --theirs-only', retcode=1)[0]
        lines3 = lines3.splitlines()
        self.assertEqual(0, len(lines3))

        # relative to a, missing the 'merge' commit 
        os.chdir('../b')
        lines = self.run_bzr('missing ../a', retcode=1)[0].splitlines()
        self.assertEqual(missing, lines[0])
        self.assertEqual(8, len(lines))
        lines2 = self.run_bzr('missing ../a --theirs-only', retcode=1)[0]
        lines2 = lines2.splitlines()
        self.assertEqual(lines, lines2)
        lines3 = self.run_bzr('missing ../a --mine-only', retcode=1)[0]
        lines3 = lines3.splitlines()
        self.assertEqual(0, len(lines3))
        lines4 = self.run_bzr('missing ../a --short', retcode=1)[0]
        lines4 = lines4.splitlines()
        self.assertEqual(4, len(lines4))
        lines5 = self.run_bzr('missing ../a --line', retcode=1)[0]
        lines5 = lines5.splitlines()
        self.assertEqual(2, len(lines5))
        lines6 = self.run_bzr('missing ../a --reverse', retcode=1)[0]
        lines6 = lines6.splitlines()
        self.assertEqual(lines6, lines)
        lines7 = self.run_bzr('missing ../a --show-ids', retcode=1)[0]
        lines7 = lines7.splitlines()
        self.assertEqual(11, len(lines7))
        lines8 = self.run_bzr('missing ../a --verbose', retcode=1)[0]
        lines8 = lines8.splitlines()
        self.assertEqual("modified:", lines8[-2])
        self.assertEqual("  a", lines8[-1])

        # after a pull we're back on track
        b_tree.pull(a_branch)
        self.assertEqual("Branches are up to date.\n", self.run_bzr('missing ../a')[0])

    def test_missing_check_last_location(self):
        # check that last location shown as filepath not file URL

        # create a source branch
        wt = self.make_branch_and_tree('a')
        b = wt.branch
        self.build_tree(['a/foo'])
        wt.add('foo')
        wt.commit('initial')

        os.chdir('a')
        location = osutils.getcwd() + '/'

        # clone
        b.bzrdir.sprout('../b')

        # check last location
        lines, err = self.run_bzr('missing', working_dir='../b')
        self.assertEquals('Using last location: %s\n'
                          'Branches are up to date.\n' % location,
                          lines)
        self.assertEquals('', err)
