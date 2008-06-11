# Copyright (C) 2006 Canonical Ltd
# -*- coding: utf-8 -*-
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


"""Black-box tests for 'bzr modified', which shows modified files."""

import os

from bzrlib.branch import Branch
from bzrlib.tests.blackbox import ExternalBase

class TestModified(ExternalBase):

    def test_modified(self):
        """Test that 'modified' command reports modified files"""
        self._test_modified('a', 'a')

    def test_modified_with_spaces(self):
        """Test that 'modified' command reports modified files with spaces in their names quoted"""
        self._test_modified('a filename with spaces', '"a filename with spaces"')

    def _test_modified(self, name, output):

        def check_modified(expected, null=False):
            command = 'modified'
            if null:
                command += ' --null'
            out, err = self.run_bzr(command)
            self.assertEquals(out, expected)
            self.assertEquals(err, '')

        # in empty directory, nothing modified
        tree = self.make_branch_and_tree('.')
        check_modified('')

        # with unknown file, still nothing modified
        self.build_tree_contents([(name, 'contents of %s\n' % (name))])
        check_modified('')
        
        # after add, not modified
        tree.add(name)
        check_modified('')

        # after commit, not modified
        tree.commit(message='add %s' % output)
        check_modified('')

        # modify the file
        self.build_tree_contents([(name, 'changed\n')]) 
        check_modified(output + '\n')
        
        # check null seps - use the unquoted raw name here
        check_modified(name + '\0', null=True)

        # now commit the file and it's no longer modified
        tree.commit(message='modified %s' %(name))
        check_modified('')

