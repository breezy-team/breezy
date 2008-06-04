# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.errors import NoSuchRevision, InvalidRevisionId
from bzrlib.repository import Repository
from bzrlib.tests import TestCase

from bzrlib.plugins.svn.revids import RevisionIdMapCache
from bzrlib.plugins.svn.tests import TestCaseWithSubversionRepository

class TestRevidMapCache(TestCase):
    def test_create(self):
        revidmap = RevisionIdMapCache()

    def test_lookup_revids_seen(self):
        revidmap = RevisionIdMapCache()
        self.assertEquals(0, revidmap.last_revnum_checked("trunk"))
        revidmap.set_last_revnum_checked("trunk", 45)
        self.assertEquals(45, revidmap.last_revnum_checked("trunk"))

    def test_lookup_revid_nonexistant(self):
        revidmap = RevisionIdMapCache()
        self.assertRaises(NoSuchRevision, lambda: revidmap.lookup_revid("bla"))

    def test_lookup_revid(self):
        revidmap = RevisionIdMapCache()
        revidmap.insert_revid("bla", "mypath", 42, 42, "brainslug")
        self.assertEquals(("mypath", 42, 42, "brainslug"), 
                revidmap.lookup_revid("bla"))

    def test_lookup_branch(self):
        revidmap = RevisionIdMapCache()
        revidmap.insert_revid("bla", "mypath", 42, 42, "brainslug")
        self.assertEquals("bla", 
                revidmap.lookup_branch_revnum(42, "mypath", "brainslug"))

    def test_lookup_branch_nonexistant(self):
        revidmap = RevisionIdMapCache()
        self.assertIs(None,
                revidmap.lookup_branch_revnum(42, "mypath", "foo"))

    def test_lookup_branch_incomplete(self):
        revidmap = RevisionIdMapCache()
        revidmap.insert_revid("bla", "mypath", 200, 42, "brainslug")
        self.assertEquals(None, 
                revidmap.lookup_branch_revnum(42, "mypath", "brainslug"))
