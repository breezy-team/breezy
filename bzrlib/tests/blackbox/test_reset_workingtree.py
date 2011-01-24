# Copyright (C) 2011 Canonical Ltd
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


from bzrlib import (
    workingtree,
    )
from bzrlib.tests import TestCaseWithTransport


def _get_dirstate_path(tree):
    """Get the path to the dirstate file."""
    # This is a bit ugly, but the alternative was hard-coding the path
    tree.lock_read()
    try:
        ds = tree.current_dirstate()
        return ds._filename
    finally:
        tree.unlock()


class TestResetWorkingTree(TestCaseWithTransport):

    def test_reset_noop(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo', 'tree/dir/', 'tree/dir/bar'])
        tree.add(['foo', 'dir', 'dir/bar'])
        tree.commit('first')
        self.run_bzr('reset-workingtree')

    def test_reset_broken_dirstate(self):
        tree = self.make_branch_and_tree('tree')
        # This test assumes that the format uses a DirState file, which we then
        # manually corrupt. If we change the way to get at that dirstate file,
        # then we can update how this is done
        self.assertIsNot(None, getattr(tree, 'current_dirstate', None))
        path = _get_dirstate_path(tree)
        f = open(path, 'ab')
        try:
            f.write('broken-trailing-garbage\n')
        finally:
            f.close()
        self.run_bzr('reset-workingtree')
        tree = workingtree.WorkingTree.open('tree')
        # At this point, check should be happy
        tree.check_state()
