# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.errors import NoSuchRevision
from bzrlib.repository import Repository

from revids import RevidMap
from tests import TestCaseWithSubversionRepository

class TestRevidMap(TestCaseWithSubversionRepository):
    def test_create(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        revidmap = RevidMap(repos)

    def test_lookup_revid_nonexistant(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        revidmap = RevidMap(repos)
        self.assertRaises(NoSuchRevision, lambda: revidmap.lookup_revid("bla"))

