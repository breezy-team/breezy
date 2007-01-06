# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NoRepositoryPresent, InvalidRevisionId
from bzrlib.repository import Repository
from bzrlib.tests import TestCase, TestCaseWithTransport

import repository
from repository import SvnRepository, MAPPING_VERSION, REVISION_ID_PREFIX
from tests import TestCaseWithSubversionRepository
from upgrade import (change_revision_parent, upgrade_repository, 
                     UpgradeChangesContent, parse_legacy_revision_id,
                     create_upgraded_revid)

class TestUpgradeChangesContent(TestCase):
    def test_init(self):
        x = UpgradeChangesContent("revisionx")
        self.assertEqual("revisionx", x.revid)


class ParserTests(TestCase):
    def test_current(self):
        self.assertEqual(("uuid", "trunk", 1, 2), 
                         parse_legacy_revision_id("svn-v2:1@uuid-trunk"))

    def test_legacy(self):
        self.assertEqual(("uuid", "trunk", 1, 1), 
                         parse_legacy_revision_id("svn-v1:1@uuid-trunk"))

    def test_except(self):
        self.assertRaises(InvalidRevisionId, 
                         parse_legacy_revision_id, "svn-v0:1@uuid-trunk")

    def test_except_nonsvn(self):
        self.assertRaises(InvalidRevisionId, 
                         parse_legacy_revision_id, "blah")

    def test_create_upgraded_revid_new(self):
        self.assertEqual("bla-svn%d-upgrade" % MAPPING_VERSION,
                         create_upgraded_revid("bla"))

    def test_create_upgraded_revid_upgrade(self):
        self.assertEqual("bla-svn%d-upgrade" % MAPPING_VERSION,
                         create_upgraded_revid("bla-svn1-upgrade"))


class ConversionTests(TestCaseWithTransport):
    def test_simple(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        wt.commit(message='add hello', rev_id="bla")
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bloe")
        wt.set_last_revision("bla")
        b.set_revision_history(["bla"])
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bla2")
        
        newrev = change_revision_parent(wt.branch.repository, "bla2", "bla4", 
                                        ["bloe"])
        self.assertEqual("bla4", newrev)
        self.assertTrue(wt.branch.repository.has_revision(newrev))
        self.assertEqual(["bloe"], wt.branch.repository.revision_parents(newrev))


class UpgradeTests(TestCaseWithSubversionRepository):
    def test_no_custom(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a","w").write("b")
        wt.add("a")
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)

        self.assertTrue(newrepos.has_revision("svn-v1:1@%s-" % oldrepos.uuid))

        upgrade_repository(newrepos, oldrepos)

        self.assertTrue(newrepos.has_revision("svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))

    def test_single_custom(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a", "w").write("b")
        wt.add("a")
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)
        file("dc/a", 'w').write("moredata")
        wt.commit(message='fix moredata', rev_id="customrev")

        upgrade_repository(newrepos, oldrepos)

        self.assertTrue(newrepos.has_revision("svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision("customrev-svn%d-upgrade" % MAPPING_VERSION))
        self.assertTrue(["svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)],
                        newrepos.revision_parents("customrev-svn%d-upgrade" % MAPPING_VERSION))
