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


"""Black-box tests for bzr revno.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir

class TestRevno(TestCaseInTempDir):

    def test_revno(self):

        def bzr(*args, **kwargs):
            return self.run_bzr(*args, **kwargs)[0]

        os.mkdir('a')
        os.chdir('a')
        bzr('init')
        self.assertEquals(int(bzr('revno')), 0)

        open('foo', 'wb').write('foo\n')
        bzr('add', 'foo')
        bzr('commit', '-m', 'foo')
        self.assertEquals(int(bzr('revno')), 1)

        os.mkdir('baz')
        bzr('add', 'baz')
        bzr('commit', '-m', 'baz')
        self.assertEquals(int(bzr('revno')), 2)

        os.chdir('..')
        self.assertEquals(int(bzr('revno', 'a')), 2)
        self.assertEquals(int(bzr('revno', 'a/baz')), 2)


