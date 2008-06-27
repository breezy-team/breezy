# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>

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

"""Mapping upgrade tests."""

from bzrlib.bzrdir import BzrDir
from bzrlib.errors import InvalidRevisionId
from bzrlib.repository import Repository
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped

from bzrlib.plugins.svn.errors import RebaseNotPresent
from bzrlib.plugins.svn.format import get_rich_root_format
from bzrlib.plugins.svn.mapping import (BzrSvnMappingv2, BzrSvnMappingv1)
from bzrlib.plugins.svn.mapping3 import BzrSvnMappingv3FileProps
from bzrlib.plugins.svn.mapping3.scheme import TrunkBranchingScheme
from bzrlib.plugins.svn.tests import TestCaseWithSubversionRepository
from bzrlib.plugins.svn.upgrade import (upgrade_repository, upgrade_branch,
                     upgrade_workingtree, UpgradeChangesContent, 
                     create_upgraded_revid, generate_upgrade_map)

class TestUpgradeChangesContent(TestCase):
    def test_init(self):
        x = UpgradeChangesContent("revisionx")
        self.assertEqual("revisionx", x.revid)


class ParserTests(TestCase):
    def test_create_upgraded_revid_new(self):
        self.assertEqual("bla-svn3-upgrade",
                         create_upgraded_revid("bla", "-svn3"))

    def test_create_upgraded_revid_upgrade(self):
        self.assertEqual("bla-svn3-upgrade",
                         create_upgraded_revid("bla-svn1-upgrade", "-svn3"))


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
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("a").modify("b")
        dc.close()

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f", format=get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a","w").write("b")
        wt.add("a")
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)

        self.assertTrue(newrepos.has_revision("svn-v1:1@%s-" % oldrepos.uuid))

        upgrade_repository(newrepos, oldrepos, allow_changes=True)

        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(oldrepos.generate_revision_id(1, "", mapping)))

    @skip_no_rebase
    def test_single_custom(self):
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("a").modify("b")
        dc.close()

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f", format=get_rich_root_format())
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

        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(oldrepos.generate_revision_id(1, "", mapping)))
        self.assertTrue(newrepos.has_revision("customrev%s-upgrade" % mapping.upgrade_suffix))
        newrepos.lock_read()
        self.assertTrue((oldrepos.generate_revision_id(1, "", mapping),),
                        tuple(newrepos.get_revision("customrev%s-upgrade" % mapping.upgrade_suffix).parent_ids))
        newrepos.unlock()

    @skip_no_rebase
    def test_single_keep_parent_fileid(self):
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("a").modify("b")
        dc.close()

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
        mapping = oldrepos.get_mapping()
        tree = newrepos.revision_tree("customrev%s-upgrade" % mapping.upgrade_suffix)
        self.assertEqual("specificid", tree.inventory.path2id("a"))
        self.assertEqual(mapping.generate_file_id(oldrepos.uuid, 1, "", u"a"), 
                         tree.inventory.path2id("b"))

    @skip_no_rebase
    def test_single_custom_continue(self):
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("a").modify("b")
        dc.add_file("b").modify("c")
        dc.close()

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f", format=get_rich_root_format())
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

        newrepos.lock_write()
        newrepos.start_write_group()

        mapping = oldrepos.get_mapping()
        fileid = tree.inventory.path2id("a")
        revid = "customrev%s-upgrade" % mapping.upgrade_suffix
        newrepos.texts.add_lines((fileid, revid), 
                [(fileid, "svn-v1:1@%s-" % oldrepos.uuid)],
                tree.get_file(fileid).readlines())

        newrepos.commit_write_group()
        newrepos.unlock()

        upgrade_repository(newrepos, oldrepos, allow_changes=True)

        self.assertTrue(newrepos.has_revision(oldrepos.generate_revision_id(1, "", mapping)))
        self.assertTrue(newrepos.has_revision("customrev%s-upgrade" % mapping.upgrade_suffix))
        newrepos.lock_read()
        self.assertTrue((oldrepos.generate_revision_id(1, "", mapping),),
                        tuple(newrepos.get_revision("customrev%s-upgrade" % mapping.upgrade_suffix).parent_ids))
        newrepos.unlock()

    @skip_no_rebase
    def test_more_custom(self):
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("a").modify("b")
        dc.close()

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f", format=get_rich_root_format())
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

        mapping = oldrepos.get_mapping()
        renames = upgrade_repository(newrepos, oldrepos, allow_changes=True)
        self.assertEqual({
            'svn-v1:1@%s-' % oldrepos.uuid: 'svn-v3-none:%s::1' % oldrepos.uuid,
            "customrev": "customrev%s-upgrade" % mapping.upgrade_suffix,
            "anotherrev": "anotherrev%s-upgrade" % mapping.upgrade_suffix},
            renames)

        self.assertTrue(newrepos.has_revision(oldrepos.generate_revision_id(1, "", mapping)))
        self.assertTrue(newrepos.has_revision("customrev%s-upgrade" % mapping.upgrade_suffix))
        self.assertTrue(newrepos.has_revision("anotherrev%s-upgrade" % mapping.upgrade_suffix))
        newrepos.lock_read()
        self.assertTrue((oldrepos.generate_revision_id(1, "", mapping),),
                        tuple(newrepos.get_revision("customrev%s-upgrade" % mapping.upgrade_suffix).parent_ids))
        self.assertTrue(("customrev-%s-upgrade" % mapping.upgrade_suffix,),
                        tuple(newrepos.get_revision("anotherrev%s-upgrade" % mapping.upgrade_suffix).parent_ids))
        newrepos.unlock()

    @skip_no_rebase
    def test_more_custom_branch(self):
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("a").modify("b")
        dc.close()

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f", format=get_rich_root_format())
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
        mapping = oldrepos.get_mapping()
        self.assertEqual([oldrepos.generate_revision_id(0, "", mapping),
                          oldrepos.generate_revision_id(1, "", mapping),
                          "customrev%s-upgrade" % mapping.upgrade_suffix,
                          "anotherrev%s-upgrade" % mapping.upgrade_suffix
                          ], b.revision_history())

    @skip_no_rebase
    def test_workingtree(self):
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("a").modify("b")
        dc.close()

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f", format=get_rich_root_format())
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

        mapping = oldrepos.get_mapping()
        upgrade_workingtree(wt, oldrepos, allow_changes=True)
        self.assertEquals(wt.last_revision(), b.last_revision())
        self.assertEqual([oldrepos.generate_revision_id(0, "", mapping),
                          oldrepos.generate_revision_id(1, "", mapping),
                          "customrev%s-upgrade" % mapping.upgrade_suffix,
                          "anotherrev%s-upgrade" % mapping.upgrade_suffix
                          ], b.revision_history())

    @skip_no_rebase
    def test_branch_none(self):
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("a").modify("b")
        dc.close()

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f", format=get_rich_root_format())
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
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("d").modify("e")
        dc.close()

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f", format=get_rich_root_format())
        dir.create_repository()
        b = dir.create_branch()
        wt = dir.create_workingtree()
        file("f/a", "w").write("c")
        wt.add("a")
        wt.commit(message="data", rev_id="svn-v1:1@%s-" % oldrepos.uuid)

        self.assertRaises(UpgradeChangesContent, upgrade_branch, b, oldrepos)


class TestGenerateUpdateMapTests(TestCase):
    def test_nothing(self):
        self.assertEquals({}, generate_upgrade_map(BzrSvnMappingv3FileProps(TrunkBranchingScheme()), ["bla", "bloe"]))

    def test_v2_to_v3(self):
        self.assertEquals({"svn-v2:12@65390229-12b7-0310-b90b-f21a5aa7ec8e-trunk": "svn-v3-trunk0:65390229-12b7-0310-b90b-f21a5aa7ec8e:trunk:12"}, generate_upgrade_map(BzrSvnMappingv3FileProps(TrunkBranchingScheme()), ["svn-v2:12@65390229-12b7-0310-b90b-f21a5aa7ec8e-trunk", "bloe", "blaaa"]))
