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

"""Mapping upgrade tests."""

from bzrlib.bzrdir import BzrDir
from bzrlib.errors import InvalidRevisionId
from bzrlib.repository import Repository
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped

from errors import RebaseNotPresent
from fileids import generate_svn_file_id
from format import get_rich_root_format
from repository import MAPPING_VERSION
from tests import TestCaseWithSubversionRepository
from upgrade import (upgrade_repository, upgrade_branch,
                     upgrade_workingtree, UpgradeChangesContent, 
                     parse_legacy_revision_id, create_upgraded_revid, 
                     generate_upgrade_map)

class TestUpgradeChangesContent(TestCase):
    def test_init(self):
        x = UpgradeChangesContent("revisionx")
        self.assertEqual("revisionx", x.revid)


class ParserTests(TestCase):
    def test_current(self):
        self.assertEqual(("uuid", "trunk", 1, "trunk0", 3), 
                parse_legacy_revision_id("svn-v3-trunk0:uuid:trunk:1"))

    def test_current_undefined(self):
        self.assertEqual(("uuid", "trunk", 1, None, 3), 
                parse_legacy_revision_id("svn-v3-undefined:uuid:trunk:1"))

    def test_legacy2(self):
        self.assertEqual(("uuid", "trunk", 1, None, 2), 
                         parse_legacy_revision_id("svn-v2:1@uuid-trunk"))

    def test_legacy(self):
        self.assertEqual(("uuid", "trunk", 1, None, 1), 
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


def skip_no_rebase(unbound):
    def check_error(self, *args, **kwargs):
        try:
            return unbound(self, *args, **kwargs)
        except RebaseNotPresent, e:
            raise TestSkipped(e)
    check_error.__doc__ = unbound.__doc__
    check_error.__name__ = unbound.__name__
    return check_error


class UpgradeTests(TestCaseWithSubversionRepository):
    @skip_no_rebase
    def test_no_custom(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format=get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a","w").write("b")
        wt.add("a")
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)

        self.assertTrue(newrepos.has_revision("svn-v1:1@%s-" % oldrepos.uuid))

        upgrade_repository(newrepos, oldrepos, allow_changes=True)

        self.assertTrue(newrepos.has_revision(oldrepos.generate_revision_id(1, "", "none")))

    @skip_no_rebase
    def test_single_custom(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format=get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a", "w").write("b")
        wt.add("a")
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)
        file("f/a", 'w').write("moredata")
        wt.commit(message='fix moredata', rev_id="customrev")

        upgrade_repository(newrepos, oldrepos, allow_changes=True)

        self.assertTrue(newrepos.has_revision(oldrepos.generate_revision_id(1, "", "none")))
        self.assertTrue(newrepos.has_revision("customrev-svn%d-upgrade" % MAPPING_VERSION))
        self.assertTrue([oldrepos.generate_revision_id(1, "", "none")],
                        newrepos.revision_parents("customrev-svn%d-upgrade" % MAPPING_VERSION))

    @skip_no_rebase
    def test_single_keep_parent_fileid(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f", format=get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a", "w").write("b")
        wt.add(["a"], ["someid"])
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)
        wt.rename_one("a", "b")
        file("f/a", 'w').write("moredata")
        wt.add(["a"], ["specificid"])
        wt.commit(message='fix moredata', rev_id="customrev")

        upgrade_repository(newrepos, oldrepos, allow_changes=True)

        tree = newrepos.revision_tree("customrev-svn%d-upgrade" % MAPPING_VERSION)
        self.assertEqual("specificid", tree.inventory.path2id("a"))
        self.assertEqual(generate_svn_file_id(oldrepos.uuid, 1, "", "a"), 
                         tree.inventory.path2id("b"))

    @skip_no_rebase
    def test_single_custom_continue(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b', 'dc/b': 'c'})
        self.client_add("dc/a")
        self.client_add("dc/b")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format=get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a", "w").write("b")
        file("f/b", "w").write("c")
        wt.add("a")
        wt.add("b")
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)
        file("f/a", 'w').write("moredata")
        file("f/b", 'w').write("moredata")
        wt.commit(message='fix moredata', rev_id="customrev")

        tree = newrepos.revision_tree("svn-v1:1@%s-" % oldrepos.uuid)

        vf = newrepos.weave_store.get_weave_or_empty(tree.inventory.path2id("a"), newrepos.get_transaction())
        vf.clone_text("customrev-svn%d-upgrade" % MAPPING_VERSION,
                "svn-v1:1@%s-" % oldrepos.uuid, ["svn-v1:1@%s-" % oldrepos.uuid])

        upgrade_repository(newrepos, oldrepos, allow_changes=True)

        self.assertTrue(newrepos.has_revision(oldrepos.generate_revision_id(1, "", "none")))
        self.assertTrue(newrepos.has_revision("customrev-svn%d-upgrade" % MAPPING_VERSION))
        self.assertTrue([oldrepos.generate_revision_id(1, "", "none")],
                        newrepos.revision_parents("customrev-svn%d-upgrade" % MAPPING_VERSION))

    @skip_no_rebase
    def test_more_custom(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format=get_rich_root_format())
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

        renames = upgrade_repository(newrepos, oldrepos, allow_changes=True)
        self.assertEqual({
            'svn-v1:1@%s-' % oldrepos.uuid: 'svn-v3-none:%s::1' % oldrepos.uuid,
            "customrev": "customrev-svn%d-upgrade" % MAPPING_VERSION,
            "anotherrev": "anotherrev-svn%d-upgrade" % MAPPING_VERSION},
            renames)

        self.assertTrue(newrepos.has_revision(oldrepos.generate_revision_id(1, "", "none")))
        self.assertTrue(newrepos.has_revision("customrev-svn%d-upgrade" % MAPPING_VERSION))
        self.assertTrue(newrepos.has_revision("anotherrev-svn%d-upgrade" % MAPPING_VERSION))
        self.assertTrue([oldrepos.generate_revision_id(1, "", "none")],
                        newrepos.revision_parents("customrev-svn%d-upgrade" % MAPPING_VERSION))
        self.assertTrue(["customrev-svn%d-upgrade" % MAPPING_VERSION],
                        newrepos.revision_parents("anotherrev-svn%d-upgrade" % MAPPING_VERSION))

    @skip_no_rebase
    def test_more_custom_branch(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format=get_rich_root_format())
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

        upgrade_branch(b, oldrepos, allow_changes=True)
        self.assertEqual([oldrepos.generate_revision_id(0, "", "none"),
                          oldrepos.generate_revision_id(1, "", "none"),
                          "customrev-svn%d-upgrade" % MAPPING_VERSION,
                          "anotherrev-svn%d-upgrade" % MAPPING_VERSION
                          ], b.revision_history())

    @skip_no_rebase
    def test_workingtree(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format=get_rich_root_format())
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

        upgrade_workingtree(wt, oldrepos, allow_changes=True)
        self.assertEquals(wt.last_revision(), b.last_revision())
        self.assertEqual([oldrepos.generate_revision_id(0, "", "none"),
                          oldrepos.generate_revision_id(1, "", "none"),
                          "customrev-svn%d-upgrade" % MAPPING_VERSION,
                          "anotherrev-svn%d-upgrade" % MAPPING_VERSION
                          ], b.revision_history())

    @skip_no_rebase
    def test_branch_none(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/a': 'b'})
        self.client_add("dc/a")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format=get_rich_root_format())
        dir.create_repository()
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

    @skip_no_rebase
    def test_raise_incompat(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/d': 'e'})
        self.client_add("dc/d")
        self.client_commit("dc", "data")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format=get_rich_root_format())
        dir.create_repository()
        b = dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a", "w").write("c")
        wt.add("a")
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)

        self.assertRaises(UpgradeChangesContent, upgrade_branch, b, oldrepos)


class TestGenerateUpdateMapTests(TestCase):
    def test_nothing(self):
        self.assertEquals({}, generate_upgrade_map(["bla", "bloe"]))

    def test_v2(self):
        self.assertEquals({"svn-v2:12@65390229-12b7-0310-b90b-f21a5aa7ec8e-trunk": "svn-v3-trunk0:65390229-12b7-0310-b90b-f21a5aa7ec8e:trunk:12"}, generate_upgrade_map(["svn-v2:12@65390229-12b7-0310-b90b-f21a5aa7ec8e-trunk", "bloe", "blaaa"]))
