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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
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
        self.failUnlessExists('name~')
        self.touch('name.pyc')
        self.run_bzr('clean-tree --force')
        self.failUnlessExists('name~')
        self.failIfExists('name')
        self.touch('name')
        self.run_bzr('clean-tree --detritus --force')
        self.failUnlessExists('name')
        self.failIfExists('name~')
        self.failUnlessExists('name.pyc')
        self.run_bzr('clean-tree --ignored --force')
        self.failUnlessExists('name')
        self.failIfExists('name.pyc')
        self.run_bzr('clean-tree --unknown --force')
        self.failIfExists('name')
        self.touch('name')
        self.touch('name~')
        self.touch('name.pyc')
        self.run_bzr('clean-tree --unknown --ignored --force')
        self.failIfExists('name')
        self.failIfExists('name~')
        self.failIfExists('name.pyc')
