# Copyright (C) 2009 Canonical Ltd
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

"""Test the helper functions."""

from bzrlib import tests

from bzrlib.plugins.fastimport import (
    helpers,
    )


class TestCommonDirectory(tests.TestCase):

    def test_no_paths(self):
        c = helpers.common_directory(None)
        self.assertEqual(c, None)
        c = helpers.common_directory([])
        self.assertEqual(c, None)

    def test_one_path(self):
        c = helpers.common_directory(['foo'])
        self.assertEqual(c, '')
        c = helpers.common_directory(['foo/'])
        self.assertEqual(c, 'foo/')
        c = helpers.common_directory(['foo/bar'])
        self.assertEqual(c, 'foo/')

    def test_two_paths(self):
        c = helpers.common_directory(['foo', 'bar'])
        self.assertEqual(c, '')
        c = helpers.common_directory(['foo/', 'bar'])
        self.assertEqual(c, '')
        c = helpers.common_directory(['foo/', 'foo/bar'])
        self.assertEqual(c, 'foo/')
        c = helpers.common_directory(['foo/bar/x', 'foo/bar/y'])
        self.assertEqual(c, 'foo/bar/')
        c = helpers.common_directory(['foo/bar/aa_x', 'foo/bar/aa_y'])
        self.assertEqual(c, 'foo/bar/')

    def test_lots_of_paths(self):
        c = helpers.common_directory(['foo/bar/x', 'foo/bar/y', 'foo/bar/z'])
        self.assertEqual(c, 'foo/bar/')
