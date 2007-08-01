# Copyright (C) 2007 Canonical Ltd
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

from bzrlib.repository import Repository
from bzrlib.tests.repository_implementations import TestCaseWithRepository

class TestHasSameLocation(TestCaseWithRepository):

    def test_is_same_location(self):
        repo_a = self.make_repository('a')
        self.assertTrue(repo_a.has_same_location(repo_a))
        repo_a2 = Repository.open(self.get_url('a'))
        self.assertTrue(repo_a.has_same_location(repo_a2))
        repo_b = self.make_repository('b')
        self.assertFalse(repo_a.has_same_location(repo_b))
