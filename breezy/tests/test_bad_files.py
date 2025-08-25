# Copyright (C) 2005, 2006, 2007, 2009, 2011 Canonical Ltd
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


"""Tests being able to ignore bad filetypes."""

import os
from io import StringIO

from .. import errors
from ..status import show_tree_status
from . import TestCaseWithTransport
from .features import OsFifoFeature


def verify_status(tester, tree, value):
    """Verify the output of show_tree_status."""
    tof = StringIO()
    show_tree_status(tree, to_file=tof)
    tof.seek(0)
    tester.assertEqual(value, tof.readlines())


class TestBadFiles(TestCaseWithTransport):
    """Tests for handling unsupported file types in the working tree."""

    def test_bad_files(self):
        """Test that bzr will ignore files it doesn't like."""
        self.requireFeature(OsFifoFeature)

        wt = self.make_branch_and_tree(".")

        files = ["one", "two", "three"]
        file_ids = [b"one-id", b"two-id", b"three-id"]
        self.build_tree(files)
        wt.add(files, ids=file_ids)
        wt.commit("Commit one", rev_id=b"a@u-0-0")

        # We should now have a few files, lets try to
        # put some bogus stuff in the tree

        # status with nothing changed
        verify_status(self, wt, [])

        os.mkfifo("a-fifo")
        self.build_tree(["six"])

        verify_status(self, wt, ["unknown:\n", "  a-fifo\n", "  six\n"])

        # We should raise an error if we are adding a bogus file
        self.assertRaises(errors.BadFileKindError, wt.smart_add, ["a-fifo"])

        # And the list of files shouldn't have been modified
        verify_status(self, wt, ["unknown:\n", "  a-fifo\n", "  six\n"])

        # Make sure smart_add can handle having a bogus
        # file in the way
        wt.smart_add([])
        verify_status(
            self,
            wt,
            [
                "added:\n",
                "  six\n",
                "unknown:\n",
                "  a-fifo\n",
            ],
        )
        wt.commit("Commit four", rev_id=b"a@u-0-3")

        verify_status(
            self,
            wt,
            [
                "unknown:\n",
                "  a-fifo\n",
            ],
        )
