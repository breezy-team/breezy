# Copyright (C) 2004, 2005, 2006 by Canonical Ltd
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


"""Tests for versioning of bzrlib."""

from bzrlib import version, workingtree
from bzrlib.tests import TestCase, TestSkipped

class TestBzrlibVersioning(TestCase):

    def test_get_bzr_source_tree(self):
        """Get tree for bzr source, if any."""
        # We don't know if these tests are being run from a checkout or branch
        # of bzr, from an installed copy, or from source unpacked from a
        # tarball.  We don't construct a branch just for testing this, so we
        # just assert that it must either return None or the tree.
        src_tree = version._get_bzr_source_tree()
        if src_tree is None:
            raise TestSkipped("bzr tests aren't run from a bzr working tree")
        else:
            # ensure that what we got was in fact a working tree instance.
            self.assertIsInstance(src_tree, workingtree.WorkingTree)
