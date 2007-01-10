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
from bzrlib.trace import mutter

import repository
from repository import SvnRepository, MAPPING_VERSION, REVISION_ID_PREFIX
from tests import TestCaseWithSubversionRepository
from upgrade import (change_revision_parent, upgrade_repository, upgrade_branch,
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

        upgrade_repository(newrepos, oldrepos, allow_change=True)

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
        file("f/a", 'w').write("moredata")
        wt.commit(message='fix moredata', rev_id="customrev")

        upgrade_repository(newrepos, oldrepos, allow_change=True)

        self.assertTrue(newrepos.has_revision(oldrepos.generate_revision_id(1, "")))
        self.assertTrue(newrepos.has_revision("customrev-svn%d-upgrade" % MAPPING_VERSION))
        self.assertTrue([oldrepos.generate_revision_id(1, "")],
                        newrepos.revision_parents("customrev-svn%d-upgrade" % MAPPING_VERSION))

    def test_more_custom(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a", "w").write("b")
        wt.add("a")
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)
        file("f/a", 'w').write("moredata")
        wt.commit(message='fix moredata', rev_id="customrev")
        file("f/a", 'w').write("blackfield")
        wt.commit(message='fix it again', rev_id="anotherrev")

        renames = upgrade_repository(newrepos, oldrepos, allow_change=True)
        self.assertEqual({
            "svn-v1:1@%s-" % oldrepos.uuid:"svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid),
            "customrev": "customrev-svn%d-upgrade" % MAPPING_VERSION,
            "anotherrev": "anotherrev-svn%d-upgrade" % MAPPING_VERSION},
            renames)

        self.assertTrue(newrepos.has_revision(oldrepos.generate_revision_id(1, "")))
        self.assertTrue(newrepos.has_revision("customrev-svn%d-upgrade" % MAPPING_VERSION))
        self.assertTrue(newrepos.has_revision("anotherrev-svn%d-upgrade" % MAPPING_VERSION))
        self.assertTrue([oldrepos.generate_revision_id(1, "")],
                        newrepos.revision_parents("customrev-svn%d-upgrade" % MAPPING_VERSION))
        self.assertTrue(["customrev-svn%d-upgrade" % MAPPING_VERSION],
                        newrepos.revision_parents("anotherrev-svn%d-upgrade" % MAPPING_VERSION))

    def test_more_custom_branch(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        b = dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a", "w").write("b")
        wt.add("a")
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)
        file("f/a", 'w').write("moredata")
        wt.commit(message='fix moredata', rev_id="customrev")
        file("f/a", 'w').write("blackfield")
        wt.commit(message='fix it again', rev_id="anotherrev")

        upgrade_branch(b, oldrepos, allow_change=True)
        self.assertEqual(["svn-v2:1@%s-" % oldrepos.uuid,
                          "customrev-svn%d-upgrade" % MAPPING_VERSION,
                          "anotherrev-svn%d-upgrade" % MAPPING_VERSION
                          ], b.revision_history())

    def test_branch_none(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        b = dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a", "w").write("b")
        wt.add("a")
        wt.commit(message="data", rev_id="blarev")
        file("f/a", 'w').write("moredata")
        wt.commit(message='fix moredata', rev_id="customrev")
        file("f/a", 'w').write("blackfield")
        wt.commit(message='fix it again', rev_id="anotherrev")

        upgrade_branch(b, oldrepos)
        self.assertEqual(["blarev", "customrev", "anotherrev"],
                b.revision_history())

    def test_raise_incompat(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/d': 'e'})
        self.client_add("dc/d")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        b = dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a", "w").write("c")
        wt.add("a")
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)

        self.assertRaises(UpgradeChangesContent, upgrade_branch, b, oldrepos)
