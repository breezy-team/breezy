# Copyright (C) 2005 by Canonical Ltd
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

"""Black-box tests for bzr revert."""

import os

from bzrlib.tests.blackbox import ExternalBase
from bzrlib.trace import mutter


class TestRevert(ExternalBase):

    def _prepare_tree(self):
        self.runbzr('init')
        self.runbzr('mkdir dir')

        f = file('dir/file', 'wb')
        f.write('spam')
        f.close()
        self.runbzr('add dir/file')

        self.runbzr('commit -m1')

        # modify file
        f = file('dir/file', 'wb')
        f.write('eggs')
        f.close()

        # check status
        self.assertEquals('modified:\n  dir/file\n', self.capture('status'))

    def helper(self, param=''):
        self._prepare_tree()
        # change dir
        # revert to default revision for file in subdir does work
        os.chdir('dir')
        mutter('cd dir\n')

        self.assertEquals('1\n', self.capture('revno'))
        self.runbzr('revert %s file' % param)
        self.assertEquals('spam', open('file', 'rb').read())

    def test_revert_in_subdir(self):
        self.helper()

    def test_revert_to_revision_in_subdir(self):
        # test case for bug #29424:
        # revert to specific revision for file in subdir does not work
        self.helper('-r 1')
