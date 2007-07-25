# Copyright (C) 2006-2007 by Jelmer Vernooij
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
"""Tests for the rebase code."""

from bzrlib.errors import UnknownFormatError, NoSuchFile
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCase, TestCaseWithTransport

from rebase import (marshall_rebase_plan, unmarshall_rebase_plan, 
                    replay_snapshot, generate_simple_plan,
                    generate_transpose_plan, rebase_plan_exists,
                    rebase_todo, REBASE_PLAN_FILENAME, 
                    REBASE_CURRENT_REVID_FILENAME, read_rebase_plan, 
                    remove_rebase_plan, read_active_rebase_revid, 
                    write_active_rebase_revid, write_rebase_plan, MapTree,
                    ReplaySnapshotError, ReplayParentsInconsistent)


class RebasePlanReadWriterTests(TestCase):
    def test_simple_marshall_rebase_plan(self):
        self.assertEqualDiff(
"""# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
""", marshall_rebase_plan((1, "bla"), 
                          {"oldrev": ("newrev", ["newparent1", "newparent2"])}))

    def test_simple_unmarshall_rebase_plan(self):
        self.assertEquals(((1, "bla"), 
                          {"oldrev": ("newrev", ["newparent1", "newparent2"])}),
                         unmarshall_rebase_plan("""# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
"""))

    def test_unmarshall_rebase_plan_formatunknown(self):
        self.assertRaises(UnknownFormatError,
                         unmarshall_rebase_plan, """# Bazaar rebase plan x
1 bla
oldrev newrev newparent1 newparent2
""")


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
        
        newrev = replay_snapshot(wt.branch.repository, "bla2", "bla4", 
                ["bloe"], {"bla": "bloe"})
        self.assertEqual("bla4", newrev)
        self.assertTrue(wt.branch.repository.has_revision(newrev))
        self.assertEqual(["bloe"], 
                wt.branch.repository.revision_parents(newrev))
        self.assertEqual("bla2", 
            wt.branch.repository.get_revision(newrev).properties["rebase-of"])


class PlanCreatorTests(TestCaseWithTransport):
    def test_simple_plan_creator(self):
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

        self.assertEquals({'bla2': ('newbla2', ["bloe"])}, 
                generate_simple_plan(b.repository, b.revision_history(), "bla2", "bloe", 
                    lambda y: "new"+y.revision_id))
     
    def test_simple_plan_creator_extra_history(self):
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
        file('hello', 'w').write('universe')
        wt.commit(message='change hello again', rev_id="bla3")

        self.assertEquals({'bla2': ('newbla2', ["bloe"]), 'bla3': ('newbla3', ['newbla2'])}, 
                generate_simple_plan(b.repository, b.revision_history(), "bla2", "bloe", 
                    lambda y: "new"+y.revision_id))
 

    def test_generate_transpose_plan(self):
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
        file('hello', 'w').write('universe')
        wt.commit(message='change hello again', rev_id="bla3")
        wt.set_last_revision("bla")
        b.set_revision_history(["bla"])
        file('hello', 'w').write('somebar')
        wt.commit(message='change hello yet again', rev_id="blie")
        wt.set_last_revision(NULL_REVISION)
        b.set_revision_history([])
        wt.add('hello')
        wt.commit(message='add hello', rev_id="lala")

        self.assertEquals({
                'blie': ('newblie', ['lala']), },
                generate_transpose_plan(b.repository.get_revision_graph("blie"), 
                {"bla": "lala"}, b.repository.revision_parents, lambda y: "new"+y))
        self.assertEquals({
                'bla2': ('newbla2', ['lala']),
                'bla3': ('newbla3', ['newbla2']),
                'blie': ('newblie', ['lala']),
                'bloe': ('newbloe', ['lala'])},
                generate_transpose_plan(b.repository.get_revision_graph(), 
                {"bla": "lala"}, b.repository.revision_parents, lambda y: "new"+y))

    def test_generate_transpose_plan_one(self):
        self.assertEquals({"bla": ("newbla", ["lala"])},
                generate_transpose_plan({"bla": ["bloe"], "bloe": []},
                    {"bloe": "lala"}, {}.get, lambda y: "new"+y))

class PlanFileTests(TestCaseWithTransport):
   def test_rebase_plan_exists_false(self):
        wt = self.make_branch_and_tree('.')
        self.assertFalse(rebase_plan_exists(wt))

   def test_rebase_plan_exists_empty(self):
        wt = self.make_branch_and_tree('.')
        wt._control_files.put_utf8(REBASE_PLAN_FILENAME, "")
        self.assertFalse(rebase_plan_exists(wt))

   def test_rebase_plan_exists(self):
        wt = self.make_branch_and_tree('.')
        wt._control_files.put_utf8(REBASE_PLAN_FILENAME, "foo")
        self.assertTrue(rebase_plan_exists(wt))

   def test_remove_rebase_plan(self):
        wt = self.make_branch_and_tree('.')
        wt._control_files.put_utf8(REBASE_PLAN_FILENAME, "foo")
        remove_rebase_plan(wt)
        self.assertFalse(rebase_plan_exists(wt))

   def test_remove_rebase_plan_twice(self):
        wt = self.make_branch_and_tree('.')
        remove_rebase_plan(wt)
        self.assertFalse(rebase_plan_exists(wt))

   def test_write_rebase_plan(self):
        wt = self.make_branch_and_tree('.')
        file('hello', 'w').write('hello world')
        wt.add('hello')
        wt.commit(message='add hello', rev_id="bla")
        write_rebase_plan(wt, 
                {"oldrev": ("newrev", ["newparent1", "newparent2"])})
        self.assertEqualDiff("""# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
""", wt._control_files.get(REBASE_PLAN_FILENAME).read())

   def test_read_rebase_plan_nonexistant(self):
        wt = self.make_branch_and_tree('.')
        self.assertRaises(NoSuchFile, read_rebase_plan, wt)

   def test_read_rebase_plan_empty(self):
        wt = self.make_branch_and_tree('.')
        wt._control_files.put_utf8(REBASE_PLAN_FILENAME, "")
        self.assertRaises(NoSuchFile, read_rebase_plan, wt)
        
   def test_read_rebase_plan(self):
        wt = self.make_branch_and_tree('.')
        wt._control_files.put_utf8(REBASE_PLAN_FILENAME, """# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
""")
        self.assertEquals(((1, "bla"), {"oldrev": ("newrev", ["newparent1", "newparent2"])}),
                read_rebase_plan(wt))


class CurrentRevidFileTests(TestCaseWithTransport):
    def test_read_nonexistant(self):
        wt = self.make_branch_and_tree('.')
        self.assertIs(None, read_active_rebase_revid(wt))

    def test_read_null(self):
        wt = self.make_branch_and_tree('.')
        wt._control_files.put_utf8(REBASE_CURRENT_REVID_FILENAME, NULL_REVISION)
        self.assertIs(None, read_active_rebase_revid(wt))

    def test_read(self):
        wt = self.make_branch_and_tree('.')
        wt._control_files.put_utf8(REBASE_CURRENT_REVID_FILENAME, "bla")
        self.assertEquals("bla", read_active_rebase_revid(wt))

    def test_write(self):
        wt = self.make_branch_and_tree('.')
        write_active_rebase_revid(wt, "bloe")
        self.assertEquals("bloe", read_active_rebase_revid(wt))

    def test_write_null(self):
        wt = self.make_branch_and_tree('.')
        write_active_rebase_revid(wt, None)
        self.assertIs(None, read_active_rebase_revid(wt))


class RebaseTodoTests(TestCase):
    def test_done(self):
        class Repository:
            def has_revision(self, revid):
                return revid == "bloe"
        self.assertEquals([], 
                list(rebase_todo(Repository(), { "bla": ("bloe", [])})))

    def test_notstarted(self):
        class Repository:
            def has_revision(self, revid):
                return False
        self.assertEquals(["bla"], 
                list(rebase_todo(Repository(), { "bla": ("bloe", [])})))

    def test_halfway(self):
        class Repository:
            def has_revision(self, revid):
                return revid == "bloe"
        self.assertEquals(["ha"], 
                list(rebase_todo(Repository(), { "bla": ("bloe", []), 
                                                 "ha": ("hee", [])})))

class ReplaySnapshotTests(TestCaseWithTransport):
    def test_single_revision(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(['afile'])
        wt.add(["afile"])
        wt.commit("bla", rev_id="oldcommit")
        replay_snapshot(wt.branch.repository, "oldcommit", "newcommit", [],
                        {})
        oldrev = wt.branch.repository.get_revision("oldcommit")
        newrev = wt.branch.repository.get_revision("newcommit")
        self.assertEquals([], newrev.parent_ids)
        self.assertEquals("newcommit", newrev.revision_id)
        self.assertEquals(oldrev.committer, newrev.committer)
        self.assertEquals(oldrev.timestamp, newrev.timestamp)
        self.assertEquals(oldrev.timezone, newrev.timezone)
        inv = wt.branch.repository.get_inventory("newcommit")
        self.assertEquals("newcommit", inv[inv.path2id("afile")].revision)

    def test_parents_different(self):
        """replay_snapshot() relies on the fact that the contents of 
        the old and new parents is equal (at least concerning tree shape). If 
        it turns out it isn't, an exception should be raised."""
        wt = self.make_branch_and_tree(".")
        wt.commit("bloe", rev_id="base")
        self.build_tree(['afile', 'notherfile'])
        wt.add(["afile"])
        wt.commit("bla", rev_id="oldparent")
        wt.add(["notherfile"])
        wt.commit("bla", rev_id="oldcommit")
        # this should raise an exception since oldcommit is being rewritten 
        # but 'afile' is present in the old parents but not in the new ones.
        self.assertRaises(
                ReplayParentsInconsistent, replay_snapshot, 
                wt.branch.repository, "oldcommit", "newcommit", 
                ["base"], {"oldparent": "base"})

    def test_two_revisions(self):
        wt = self.make_branch_and_tree("old")
        self.build_tree(['old/afile', 'old/notherfile'])
        wt.add(["afile"], ["somefileid"])
        wt.commit("bla", rev_id="oldparent")
        wt.add(["notherfile"])
        wt.commit("bla", rev_id="oldcommit")
        oldrepos = wt.branch.repository
        wt = self.make_branch_and_tree("new")
        self.build_tree(['new/afile', 'new/notherfile'])
        wt.add(["afile"], ["afileid"])
        wt.commit("bla", rev_id="newparent")
        wt.branch.repository.fetch(oldrepos)
        replay_snapshot(wt.branch.repository, "oldcommit", "newcommit", 
                ["newparent"], {"oldparent": "newparent"})
        oldrev = wt.branch.repository.get_revision("oldcommit")
        newrev = wt.branch.repository.get_revision("newcommit")
        self.assertEquals(["newparent"], newrev.parent_ids)
        self.assertEquals("newcommit", newrev.revision_id)
        self.assertEquals(oldrev.committer, newrev.committer)
        self.assertEquals(oldrev.timestamp, newrev.timestamp)
        self.assertEquals(oldrev.timezone, newrev.timezone)
        inv = wt.branch.repository.get_inventory("newcommit")
        self.assertEquals("afileid", inv.path2id("afile"))
        self.assertEquals("newcommit", inv[inv.path2id("notherfile")].revision)

    def test_two_revisions_no_renames(self):
        wt = self.make_branch_and_tree("old")
        self.build_tree(['old/afile', 'old/notherfile'])
        wt.add(["afile"], ["somefileid"])
        wt.commit("bla", rev_id="oldparent")
        wt.add(["notherfile"])
        wt.commit("bla", rev_id="oldcommit")
        oldrepos = wt.branch.repository
        wt = self.make_branch_and_tree("new")
        self.build_tree(['new/afile', 'new/notherfile'])
        wt.add(["afile"], ["afileid"])
        wt.commit("bla", rev_id="newparent")
        wt.branch.repository.fetch(oldrepos)
        self.assertRaises(ReplayParentsInconsistent, 
                          replay_snapshot, wt.branch.repository, 
                          "oldcommit", "newcommit", 
                        ["newparent"], revid_renames={})

    def test_multi_revisions(self):
        wt = self.make_branch_and_tree("old")
        self.build_tree(['old/afile', 'old/sfile', 'old/notherfile'])
        wt.add(['sfile'])
        wt.add(["afile"], ["somefileid"])
        wt.commit("bla", rev_id="oldgrandparent")
        open("old/afile", "w").write("data")
        wt.commit("bla", rev_id="oldparent")
        wt.add(["notherfile"])
        wt.commit("bla", rev_id="oldcommit")
        oldrepos = wt.branch.repository
        wt = self.make_branch_and_tree("new")
        self.build_tree(['new/afile', 'new/sfile', 'new/notherfile'])
        wt.add(['sfile'])
        wt.add(["afile"], ["afileid"])
        wt.commit("bla", rev_id="newgrandparent")
        open("new/afile", "w").write("data")
        wt.commit("bla", rev_id="newparent")
        wt.branch.repository.fetch(oldrepos)
        replay_snapshot(wt.branch.repository, "oldcommit", "newcommit", 
                ["newparent"], {"oldgrandparent": "newgrandparent", 
                                "oldparent": "newparent"})
        oldrev = wt.branch.repository.get_revision("oldcommit")
        newrev = wt.branch.repository.get_revision("newcommit")
        self.assertEquals(["newparent"], newrev.parent_ids)
        self.assertEquals("newcommit", newrev.revision_id)
        self.assertEquals(oldrev.committer, newrev.committer)
        self.assertEquals(oldrev.timestamp, newrev.timestamp)
        self.assertEquals(oldrev.timezone, newrev.timezone)
        inv = wt.branch.repository.get_inventory("newcommit")
        self.assertEquals("afileid", inv.path2id("afile"))
        self.assertEquals("newcommit", inv[inv.path2id("notherfile")].revision)
        self.assertEquals("newgrandparent", inv[inv.path2id("sfile")].revision)

    def test_maps_ids(self):
        wt = self.make_branch_and_tree("old")
        wt.commit("base", rev_id="base")
        self.build_tree(['old/afile'])
        wt.add(["afile"], ids=["originalid"])
        wt.commit("bla", rev_id="oldparent")
        file("old/afile", "w").write("bloe")
        wt.commit("bla", rev_id="oldcommit")
        oldrepos = wt.branch.repository
        wt = self.make_branch_and_tree("new")
        self.build_tree(['new/afile'])
        wt.add(["afile"], ids=["newid"])
        wt.commit("bla", rev_id="newparent")
        wt.branch.repository.fetch(oldrepos)
        replay_snapshot(wt.branch.repository, "oldcommit", "newcommit", 
                ["newparent"], {"oldparent": "newparent"})
        oldrev = wt.branch.repository.get_revision("oldcommit")
        newrev = wt.branch.repository.get_revision("newcommit")
        self.assertEquals(["newparent"], newrev.parent_ids)
        self.assertEquals("newcommit", newrev.revision_id)
        self.assertEquals(oldrev.committer, newrev.committer)
        self.assertEquals(oldrev.timestamp, newrev.timestamp)
        self.assertEquals(oldrev.timezone, newrev.timezone)
        inv = wt.branch.repository.get_inventory("newcommit")
        self.assertEquals("newid", inv.path2id("afile"))
        self.assertEquals("newcommit", inv[inv.path2id("afile")].revision)

class TestReplaySnapshotError(TestCase):
    def test_create(self):
        ReplaySnapshotError("message")


class TestReplayParentsInconsistent(TestCase):
    def test_create(self):
        ReplayParentsInconsistent("afileid", "arevid")
