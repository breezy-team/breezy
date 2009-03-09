# Copyright (C) 2005, 2009 Canonical Ltd
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
#

"""Tests of the 'bzr clean-tree' command."""

import os

from bzrlib.tests import TestCaseWithTransport


class TestBzrTools(TestCaseWithTransport):

    @staticmethod
    def touch(filename):
        my_file = open(filename, 'wb')
        try:
            my_file.write('')
        finally:
            my_file.close()

    def test_clean_tree(self):
        self.run_bzr('init')
        self.run_bzr('ignore *~')
        self.run_bzr('ignore *.pyc')
        self.touch('name')
        self.touch('name~')
        assert os.path.lexists('name~')
        self.touch('name.pyc')
        self.run_bzr('clean-tree --force')
        assert os.path.lexists('name~')
        assert not os.path.lexists('name')
        self.touch('name')
        self.run_bzr('clean-tree --detritus --force')
        assert os.path.lexists('name')
        assert not os.path.lexists('name~')
        assert os.path.lexists('name.pyc')
        self.run_bzr('clean-tree --ignored --force')
        assert os.path.lexists('name')
        assert not os.path.lexists('name.pyc')
        self.run_bzr('clean-tree --unknown --force')
        assert not os.path.lexists('name')
        self.touch('name')
        self.touch('name~')
        self.touch('name.pyc')
        self.run_bzr('clean-tree --unknown --ignored --force')
        assert not os.path.lexists('name')
        assert not os.path.lexists('name~')
        assert not os.path.lexists('name.pyc')
