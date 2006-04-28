# (C) 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

from cStringIO import StringIO
import os

import bzrlib
import bzrlib.branch
from bzrlib.branch import Branch
import bzrlib.bzrdir as bzrdir
from bzrlib.bzrdir import BzrDir
import bzrlib.errors as errors
from bzrlib.errors import NotBranchError, NotVersionedError
from bzrlib.osutils import basename
from bzrlib.tests import TestSkipped
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
import bzrlib.workingtree as workingtree
from bzrlib.workingtree import (TreeEntry, TreeDirectory, TreeFile, TreeLink,
                                WorkingTree)


class TestIsControlFilename(TestCaseWithWorkingTree):

    def validate_tree_is_controlfilename(self, tree):
        """check that 'tree' obeys the contract for is_control_filename."""
        bzrdirname = basename(tree.bzrdir.transport.base[:-1])
        self.assertTrue(tree.is_control_filename(bzrdirname))
        self.assertTrue(tree.is_control_filename(bzrdirname + '/subdir'))
        self.assertFalse(tree.is_control_filename('dir/' + bzrdirname))
        self.assertFalse(tree.is_control_filename('dir/' + bzrdirname + '/sub'))

    def test_dotbzr_is_control_in_cwd(self):
        tree = self.make_branch_and_tree('.')
        self.validate_tree_is_controlfilename(tree)
        
    def test_dotbzr_is_control_in_subdir(self):
        tree = self.make_branch_and_tree('subdir')
        self.validate_tree_is_controlfilename(tree)
        
