# Copyright (C) 2005 by Canonical Ltd
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


"""Black-box tests for bzr cat.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir

class TestCat(TestCaseInTempDir):

    def test_cat(self):

        def bzr(*args, **kwargs):
            return self.run_bzr(*args, **kwargs)[0]

        bzr('init')
        open('a', 'wb').write('foo\n')
        bzr('add', 'a')

        # 'bzr cat' without an option should cat the last revision
        bzr('cat', 'a', retcode=3)

        bzr('commit', '-m', '1')
        open('a', 'wb').write('baz\n')

        self.assertEquals(bzr('cat', 'a'), 'foo\n')

        bzr('commit', '-m', '2')
        self.assertEquals(bzr('cat', 'a'), 'baz\n')
        self.assertEquals(bzr('cat', 'a', '-r', '1'), 'foo\n')
        self.assertEquals(bzr('cat', 'a', '-r', '-1'), 'baz\n')

        rev_id = bzr('revision-history').strip().split('\n')[-1]

        self.assertEquals(bzr('cat', 'a', '-r', 'revid:%s' % rev_id), 'baz\n')

