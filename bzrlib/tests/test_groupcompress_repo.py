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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


from bzrlib import tests


class TestGroupCompressRepo(tests.TestCaseWithTransport):

    def test_inconsistency_fatal(self):
        repo = self.make_repository('repo', format='2a')
        self.assertTrue(repo.revisions._index._inconsistency_fatal)
        self.assertFalse(repo.texts._index._inconsistency_fatal)
        self.assertFalse(repo.inventories._index._inconsistency_fatal)
        self.assertFalse(repo.signatures._index._inconsistency_fatal)
        self.assertFalse(repo.chk_bytes._index._inconsistency_fatal)
