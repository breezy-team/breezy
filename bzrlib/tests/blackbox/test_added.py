# Copyright (C) 2006 by Canonical Ltd
# -*- coding: utf-8 -*-

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


"""Black-box tests for 'bzr added', which shows newly-added files.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir
from bzrlib.tests.treeshape import build_tree_contents

class TestAdded(TestCaseInTempDir):

    def test_added(self):
        """Test that 'added' command reports added files"""

        def check_added(expected):
            out, err = self.run_bzr_captured(['added'])
            self.assertEquals(out, expected)
            self.assertEquals(err, '')

        def bzr(*args):
            self.run_bzr(*args)

        # in empty directory, nothing added
        bzr('init')
        check_added('')

        # with unknown file, still nothing added
        build_tree_contents([('a', 'contents of a\n')])
        check_added('')

        # after add, shows up in list
        # bug report 20060119 by Nathan McCallum -- 'bzr added' causes
        # NameError
        bzr('add', 'a')
        check_added('a\n')

        # after commit, now no longer listed
        bzr('commit', '-m', 'add a')
        check_added('')
