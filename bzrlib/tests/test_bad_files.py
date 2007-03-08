# Copyright (C) 2005, 2007 Canonical Ltd
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


"""Tests being able to ignore bad filetypes."""

from cStringIO import StringIO
import os

from bzrlib import (
    add,
    errors,
    )
from bzrlib.status import show_tree_status
from bzrlib.tests import TestCaseWithTransport


def verify_status(tester, tree, value):
    """Verify the output of show_tree_status"""
    tof = StringIO()
    show_tree_status(tree, to_file=tof)
    tof.seek(0)
    tester.assertEqual(value, tof.readlines())


class TestBadFiles(TestCaseWithTransport):

    def test_bad_files(self):
        """Test that bzr will ignore files it doesn't like"""
        if getattr(os, 'mkfifo', None) is None:
            # TODO: Ultimately this should be TestSkipped
            # or PlatformDeficiency
            return

        wt = self.make_branch_and_tree('.')
        b = wt.branch

        files = ['one', 'two', 'three']
        file_ids = ['one-id', 'two-id', 'three-id']
        self.build_tree(files)
        wt.add(files, file_ids)
        wt.commit("Commit one", rev_id="a@u-0-0")

        # We should now have a few files, lets try to
        # put some bogus stuff in the tree

        # status with nothing changed
        verify_status(self, wt, [])

        os.mkfifo('a-fifo')
        self.build_tree(['six'])

        verify_status(self, wt,
                          ['unknown:\n',
                           '  a-fifo\n',
                           '  six\n'
                           ])

        # We should raise an error if we are adding a bogus file
        self.assertRaises(errors.BadFileKindError,
                          add.smart_add_tree, wt, ['a-fifo'])

        # And the list of files shouldn't have been modified
        verify_status(self, wt,
                          ['unknown:\n',
                           '  a-fifo\n',
                           '  six\n'
                           ])

        # Make sure smart_add can handle having a bogus
        # file in the way
        add.smart_add_tree(wt, ['.'])
        verify_status(self, wt,
                          ['added:\n',
                           '  six\n',
                           'unknown:\n',
                           '  a-fifo\n',
                           ])
        wt.commit("Commit four", rev_id="a@u-0-3")

        verify_status(self, wt,
                          ['unknown:\n',
                           '  a-fifo\n',
                           ])
