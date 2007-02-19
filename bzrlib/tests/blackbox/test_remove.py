# Copyright (C) 2005, 2006 Canonical Ltd
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


import os

from bzrlib.tests.blackbox.test_unversion import TestUnversion
from bzrlib.workingtree import WorkingTree


class TestRemove(TestUnversion):

    def __init__(self, methodName='runTest'):
        super(TestRemove, self).__init__(methodName)
        self.cmd = 'remove'
        self.shape = None

    def assertCommandPerformedOnFiles(self,files):
        for f in files:
            self.failIfExists(f)
            self.assertNotInWorkingTree(f)

    def test_command_on_unversioned_files(self):
        self.build_tree(['a'])
        tree = self.make_branch_and_tree('.')

        (out,err) = self.runbzr(self.cmd + ' a')
        self.assertEquals(out.strip(), "")
        self.assertEquals(err.strip(), "deleted a")

    def test_command_on_non_existing_files(self):
        tree = self._make_add_and_assert_tree([])
        (out,err) = self.runbzr(self.cmd + ' b')
        self.assertEquals(out.strip(), "")
        self.assertEquals(err.strip(), "b does not exist.")
