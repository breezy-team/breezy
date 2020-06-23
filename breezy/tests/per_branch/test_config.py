# Copyright (C) 2010, 2011, 2012, 2016 Canonical Ltd
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

"""Tests for branch.get_config behaviour."""

from breezy import (
    branch,
    errors,
    tests,
    )
from breezy.tests import per_branch


class TestGetConfig(per_branch.TestCaseWithBranch):

    def test_set_user_option_with_dict(self):
        b = self.make_branch('b')
        config = b.get_config()
        value_dict = {
            'ascii': 'abcd', u'unicode \N{WATCH}': u'foo \N{INTERROBANG}'}
        config.set_user_option('name', value_dict.copy())
        self.assertEqual(value_dict, config.get_user_option('name'))

    def test_set_submit_branch(self):
        # Make sure setting a config option persists on disk
        b = self.make_branch('.')
        b.set_submit_branch('foo')
        # Refresh the branch
        b = branch.Branch.open('.')
        self.assertEqual('foo', b.get_submit_branch())
