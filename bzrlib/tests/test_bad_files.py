# Copyright (C) 2005 by Canonical Ltd

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


"""Tests being able to ignore mad filetypes.
"""

from bzrlib.tests import TestCaseInTempDir
from bzrlib.errors import BadFileKindError
import os

def verify_status(tester, branch, value):
    from bzrlib.status import show_status
    from cStringIO import StringIO

    tof = StringIO()
    show_status(branch, to_file=tof)
    tof.seek(0)
    tester.assertEquals(tof.readlines(), value)


class TestBadFiles(TestCaseInTempDir):
    
    def test_bad_files(self): 
        """Test that bzr will ignore files it doesn't like"""
        from bzrlib.commit import commit
        from bzrlib.add import smart_add
        from bzrlib.branch import Branch

        b = Branch.initialize('.')

        self.build_tree(['one', 'two', 'three'])
        smart_add('.')
        commit(b, "Commit one", rev_id="a@u-0-0")
        self.build_tree(['four'])
        smart_add('.')
        commit(b, "Commit two", rev_id="a@u-0-1")
        self.build_tree(['five'])
        smart_add('.')
        commit(b, "Commit three", rev_id="a@u-0-2")

        # We should now have a few files, lets try to
        # put some bogus stuff in the tree

        # We can only continue if we have mkfifo
        if not hasattr(os, 'mkfifo'):
            return

        # status with nothing
        verify_status(self, b, [])

        os.mkfifo('a-fifo')
        self.build_tree(['six'])

        verify_status(self, b,
                          ['unknown:\n',
                           '  a-fifo\n',
                           '  six\n'
                           ])
        
        # Make sure smart_add can handle having a bogus
        # file in the way
        smart_add('.')
        verify_status(self, b,
                          ['added:\n',
                           '  six\n',
                           'unknown:\n',
                           '  a-fifo\n',
                           ])
        commit(b, "Commit four", rev_id="a@u-0-3")

        verify_status(self, b,
                          ['unknown:\n',
                           '  a-fifo\n',
                           ])

        # We should raise an error if we are adding a bogus file
        # Is there a way to test the actual error that should be raised?
        self.run_bzr('add', 'a-fifo', retcode=3)

