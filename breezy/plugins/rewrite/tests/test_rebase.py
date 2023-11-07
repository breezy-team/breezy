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

from ....errors import ConflictsInTree, UnknownFormatError
from ....graph import DictParentsProvider, Graph
from ....revision import NULL_REVISION
from ....tests import TestCase, TestCaseWithTransport
from ....tests.matchers import RevisionHistoryMatches
from ....transport import NoSuchFile
from ..rebase import (
    REBASE_CURRENT_REVID_FILENAME,
    REBASE_PLAN_FILENAME,
    CommitBuilderRevisionRewriter,
    RebaseState1,
    ReplaySnapshotError,
    WorkingTreeRevisionRewriter,
    generate_simple_plan,
    generate_transpose_plan,
    marshall_rebase_plan,
    rebase_todo,
    unmarshall_rebase_plan,
)


class RebasePlanReadWriterTests(TestCase):
    def test_simple_marshall_rebase_plan(self):
        self.assertEqualDiff(
            b"""\
# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
""",
            marshall_rebase_plan(
                (1, b"bla"), {b"oldrev": (b"newrev", (b"newparent1", b"newparent2"))}
            ),
        )

    def test_simple_unmarshall_rebase_plan(self):
        self.assertEqual(
            ((1, b"bla"), {b"oldrev": (b"newrev", (b"newparent1", b"newparent2"))}),
            unmarshall_rebase_plan(
                b"""# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
"""
            ),
        )

    def test_unmarshall_rebase_plan_formatunknown(self):
        self.assertRaises(
            UnknownFormatError,
            unmarshall_rebase_plan,
            b"""# Bazaar rebase plan x
1 bla
oldrev newrev newparent1 newparent2
""",
        )


class ConversionTests(TestCaseWithTransport):
    def test_simple(self):
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        wt.commit(message="add hello", rev_id=b"bla")
        with open("hello", "w") as f:
            f.write("world")
        wt.commit(message="change hello", rev_id=b"bloe")
        wt.set_last_revision(b"bla")
        b.generate_revision_history(b"bla")
        with open("hello", "w") as f:
            f.write("world")
        wt.commit(message="change hello", rev_id=b"bla2")

        wt.branch.repository.lock_write()
        newrev = CommitBuilderRevisionRewriter(wt.branch.repository)(
            b"bla2", b"bla4", (b"bloe",)
        )
        self.assertEqual(b"bla4", newrev)
        self.assertTrue(wt.branch.repository.has_revision(newrev))
        self.assertEqual(
            (b"bloe",), wt.branch.repository.get_parent_map([newrev])[newrev]
        )
        self.assertEqual(
            "bla2", wt.branch.repository.get_revision(newrev).properties["rebase-of"]
        )
        wt.branch.repository.unlock()


class PlanCreatorTests(TestCaseWithTransport):
    def test_simple_plan_creator(self):
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        wt.commit(message="add hello", rev_id=b"bla")
        with open("hello", "w") as f:
            f.write("world")
        wt.commit(message="change hello", rev_id=b"bloe")
        wt.set_last_revision(b"bla")
        b.generate_revision_history(b"bla")
        with open("hello", "w") as f:
            f.write("world")
        wt.commit(message="change hello", rev_id=b"bla2")

        b.repository.lock_read()
        graph = b.repository.get_graph()
        self.assertEqual(
            {b"bla2": (b"newbla2", (b"bloe",))},
            generate_simple_plan(
                graph.find_difference(b.last_revision(), b"bla")[0],
                b"bla2",
                None,
                b"bloe",
                graph,
                lambda y, _: b"new" + y,
            ),
        )
        b.repository.unlock()

    def test_simple_plan_creator_extra_history(self):
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        wt.commit(message="add hello", rev_id=b"bla")
        with open("hello", "w") as f:
            f.write("world")
        wt.commit(message="change hello", rev_id=b"bloe")
        wt.set_last_revision(b"bla")
        b.generate_revision_history(b"bla")
        with open("hello", "w") as f:
            f.write("world")
        wt.commit(message="change hello", rev_id=b"bla2")
        with open("hello", "w") as f:
            f.write("universe")
        wt.commit(message="change hello again", rev_id=b"bla3")

        with b.repository.lock_read():
            graph = b.repository.get_graph()
            self.assertEqual(
                {
                    b"bla2": (b"newbla2", (b"bloe",)),
                    b"bla3": (b"newbla3", (b"newbla2",)),
                },
                generate_simple_plan(
                    graph.find_difference(b.last_revision(), b"bloe")[0],
                    b"bla2",
                    None,
                    b"bloe",
                    graph,
                    lambda y, _: b"new" + y,
                ),
            )

    def test_generate_transpose_plan(self):
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        wt.commit(message="add hello", rev_id=b"bla")
        with open("hello", "w") as f:
            f.write("world")
        wt.commit(message="change hello", rev_id=b"bloe")
        wt.set_last_revision(b"bla")
        b.generate_revision_history(b"bla")
        with open("hello", "w") as f:
            f.write("world")
        wt.commit(message="change hello", rev_id=b"bla2")
        with open("hello", "w") as f:
            f.write("universe")
        wt.commit(message="change hello again", rev_id=b"bla3")
        wt.set_last_revision(b"bla")
        b.generate_revision_history(b"bla")
        with open("hello", "w") as f:
            f.write("somebar")
        wt.commit(message="change hello yet again", rev_id=b"blie")
        wt.set_last_revision(NULL_REVISION)
        b.generate_revision_history(NULL_REVISION)
        wt.add("hello")
        wt.commit(message="add hello", rev_id=b"lala")

        b.repository.lock_read()
        graph = b.repository.get_graph()
        self.assertEqual(
            {b"blie": (b"newblie", (b"lala",))},
            generate_transpose_plan(
                graph.iter_ancestry([b"blie"]),
                {b"bla": b"lala"},
                graph,
                lambda y, _: b"new" + y,
            ),
        )
        self.assertEqual(
            {
                b"bla2": (b"newbla2", (b"lala",)),
                b"bla3": (b"newbla3", (b"newbla2",)),
                b"blie": (b"newblie", (b"lala",)),
                b"bloe": (b"newbloe", (b"lala",)),
            },
            generate_transpose_plan(
                graph.iter_ancestry(b.repository._all_revision_ids()),
                {b"bla": b"lala"},
                graph,
                lambda y, _: b"new" + y,
            ),
        )
        b.repository.unlock()

    def test_generate_transpose_plan_one(self):
        graph = Graph(DictParentsProvider({"bla": ("bloe",), "bloe": (), "lala": ()}))
        self.assertEqual(
            {"bla": ("newbla", ("lala",))},
            generate_transpose_plan(
                graph.iter_ancestry(["bla", "bloe"]),
                {"bloe": "lala"},
                graph,
                lambda y, _: "new" + y,
            ),
        )

    def test_plan_with_already_merged(self):
        r"""We need to use a merge base that makes sense.

        A
        | \
        B  D
        | \|
        C  E

        Rebasing E on C should result in:

        A -> B -> C -> D -> E

        with a plan of:

        D -> (D', [C])
        E -> (E', [D', C])
        """
        parents_map = {"A": (), "B": ("A",), "C": ("B",), "D": ("A",), "E": ("D", "B")}
        graph = Graph(DictParentsProvider(parents_map))
        self.assertEqual(
            {"D": ("D'", ("C",)), "E": ("E'", ("D'",))},
            generate_simple_plan(
                ["D", "E"], "D", None, "C", graph, lambda y, _: y + "'"
            ),
        )

    def test_plan_with_already_merged_skip_merges(self):
        r"""We need to use a merge base that makes sense.

        A
        | \
        B  D
        | \|
        C  E

        Rebasing E on C should result in:

        A -> B -> C -> D'

        with a plan of:

        D -> (D', [C])
        """
        parents_map = {"A": (), "B": ("A",), "C": ("B",), "D": ("A",), "E": ("D", "B")}
        graph = Graph(DictParentsProvider(parents_map))
        self.assertEqual(
            {"D": ("D'", ("C",))},
            generate_simple_plan(
                ["D", "E"], "D", None, "C", graph, lambda y, _: y + "'", True
            ),
        )


class RebaseStateTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.wt = self.make_branch_and_tree(".")
        self.state = RebaseState1(self.wt)

    def test_rebase_plan_exists_false(self):
        self.assertFalse(self.state.has_plan())

    def test_rebase_plan_exists_empty(self):
        self.wt._transport.put_bytes(REBASE_PLAN_FILENAME, b"")
        self.assertFalse(self.state.has_plan())

    def test_rebase_plan_exists(self):
        self.wt._transport.put_bytes(REBASE_PLAN_FILENAME, b"foo")
        self.assertTrue(self.state.has_plan())

    def test_remove_rebase_plan(self):
        self.wt._transport.put_bytes(REBASE_PLAN_FILENAME, b"foo")
        self.state.remove_plan()
        self.assertFalse(self.state.has_plan())

    def test_remove_rebase_plan_twice(self):
        self.state.remove_plan()
        self.assertFalse(self.state.has_plan())

    def test_write_rebase_plan(self):
        with open("hello", "w") as f:
            f.write("hello world")
        self.wt.add("hello")
        self.wt.commit(message="add hello", rev_id=b"bla")
        self.state.write_plan({b"oldrev": (b"newrev", [b"newparent1", b"newparent2"])})
        self.assertEqualDiff(
            b"""# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
""",
            self.wt._transport.get_bytes(REBASE_PLAN_FILENAME),
        )

    def test_read_rebase_plan_nonexistant(self):
        self.assertRaises(NoSuchFile, self.state.read_plan)

    def test_read_rebase_plan_empty(self):
        self.wt._transport.put_bytes(REBASE_PLAN_FILENAME, b"")
        self.assertRaises(NoSuchFile, self.state.read_plan)

    def test_read_rebase_plan(self):
        self.wt._transport.put_bytes(
            REBASE_PLAN_FILENAME,
            b"""# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
""",
        )
        self.assertEqual(
            ((1, b"bla"), {b"oldrev": (b"newrev", (b"newparent1", b"newparent2"))}),
            self.state.read_plan(),
        )

    def test_read_nonexistant(self):
        self.assertIs(None, self.state.read_active_revid())

    def test_read_null(self):
        self.wt._transport.put_bytes(REBASE_CURRENT_REVID_FILENAME, NULL_REVISION)
        self.assertIs(None, self.state.read_active_revid())

    def test_read(self):
        self.wt._transport.put_bytes(REBASE_CURRENT_REVID_FILENAME, b"bla")
        self.assertEqual(b"bla", self.state.read_active_revid())

    def test_write(self):
        self.state.write_active_revid(b"bloe")
        self.assertEqual(b"bloe", self.state.read_active_revid())

    def test_write_null(self):
        self.state.write_active_revid(None)
        self.assertIs(None, self.state.read_active_revid())


class RebaseTodoTests(TestCase):
    def test_done(self):
        class Repository:
            def has_revision(self, revid):
                return revid == "bloe"

        self.assertEqual([], list(rebase_todo(Repository(), {"bla": ("bloe", [])})))

    def test_notstarted(self):
        class Repository:
            def has_revision(self, revid):
                return False

        self.assertEqual(
            ["bla"], list(rebase_todo(Repository(), {"bla": ("bloe", [])}))
        )

    def test_halfway(self):
        class Repository:
            def has_revision(self, revid):
                return revid == "bloe"

        self.assertEqual(
            ["ha"],
            list(rebase_todo(Repository(), {"bla": ("bloe", []), "ha": ("hee", [])})),
        )


class ReplaySnapshotTests(TestCaseWithTransport):
    def test_single_revision(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(["afile"])
        wt.add(["afile"])
        wt.commit("bla", rev_id=b"oldcommit")
        wt.branch.repository.lock_write()
        CommitBuilderRevisionRewriter(wt.branch.repository)(
            b"oldcommit", b"newcommit", ()
        )
        wt.branch.repository.unlock()
        oldrev = wt.branch.repository.get_revision(b"oldcommit")
        newrev = wt.branch.repository.get_revision(b"newcommit")
        self.assertEqual([], newrev.parent_ids)
        self.assertEqual(b"newcommit", newrev.revision_id)
        self.assertEqual(oldrev.committer, newrev.committer)
        self.assertEqual(oldrev.timestamp, newrev.timestamp)
        self.assertEqual(oldrev.timezone, newrev.timezone)
        tree = wt.branch.repository.revision_tree(b"newcommit")
        self.assertEqual(b"newcommit", tree.get_file_revision("afile"))

    def test_two_revisions(self):
        wt = self.make_branch_and_tree("old")
        self.build_tree_contents(
            [("old/afile", "afilecontents"), ("old/notherfile", "notherfilecontents")]
        )
        wt.add(["afile"], ids=[b"somefileid"])
        wt.commit("bla", rev_id=b"oldparent")
        wt.add(["notherfile"])
        wt.commit("bla", rev_id=b"oldcommit")
        oldrepos = wt.branch.repository
        wt = self.make_branch_and_tree("new")
        self.build_tree_contents(
            [("new/afile", "afilecontents"), ("new/notherfile", "notherfilecontents")]
        )
        wt.add(["afile"], ids=[b"afileid"])
        wt.commit("bla", rev_id=b"newparent")
        wt.branch.repository.fetch(oldrepos)
        wt.branch.repository.lock_write()
        CommitBuilderRevisionRewriter(wt.branch.repository)(
            b"oldcommit", b"newcommit", (b"newparent",)
        )
        wt.branch.repository.unlock()
        oldrev = wt.branch.repository.get_revision(b"oldcommit")
        newrev = wt.branch.repository.get_revision(b"newcommit")
        self.assertEqual([b"newparent"], newrev.parent_ids)
        self.assertEqual(b"newcommit", newrev.revision_id)
        self.assertEqual(oldrev.committer, newrev.committer)
        self.assertEqual(oldrev.timestamp, newrev.timestamp)
        self.assertEqual(oldrev.timezone, newrev.timezone)
        tree = wt.branch.repository.revision_tree(b"newcommit")
        self.assertEqual(b"afileid", tree.path2id("afile"))
        self.assertEqual(b"newcommit", tree.get_file_revision("notherfile"))

    def test_two_revisions_no_renames(self):
        wt = self.make_branch_and_tree("old")
        self.build_tree(["old/afile", "old/notherfile"])
        wt.add(["afile"], ids=[b"somefileid"])
        wt.commit("bla", rev_id=b"oldparent")
        wt.add(["notherfile"])
        wt.commit("bla", rev_id=b"oldcommit")
        oldrepos = wt.branch.repository
        wt = self.make_branch_and_tree("new")
        self.build_tree(["new/afile", "new/notherfile"])
        wt.add(["afile"], ids=[b"afileid"])
        wt.commit("bla", rev_id=b"newparent")
        wt.branch.repository.fetch(oldrepos)
        wt.branch.repository.lock_write()
        CommitBuilderRevisionRewriter(wt.branch.repository)(
            b"oldcommit", b"newcommit", (b"newparent",)
        )
        wt.branch.repository.unlock()

    def test_multi_revisions(self):
        wt = self.make_branch_and_tree("old")
        self.build_tree_contents(
            [
                ("old/afile", "afilecontent"),
                ("old/sfile", "sfilecontent"),
                ("old/notherfile", "notherfilecontent"),
            ]
        )
        wt.add(["sfile"])
        wt.add(["afile"], ids=[b"somefileid"])
        wt.commit("bla", rev_id=b"oldgrandparent")
        with open("old/afile", "w") as f:
            f.write("data")
        wt.commit("bla", rev_id=b"oldparent")
        wt.add(["notherfile"])
        wt.commit("bla", rev_id=b"oldcommit")
        oldrepos = wt.branch.repository
        wt = self.make_branch_and_tree("new")
        self.build_tree_contents(
            [
                ("new/afile", "afilecontent"),
                ("new/sfile", "sfilecontent"),
                ("new/notherfile", "notherfilecontent"),
            ]
        )
        wt.add(["sfile"])
        wt.add(["afile"], ids=[b"afileid"])
        wt.commit("bla", rev_id=b"newgrandparent")
        with open("new/afile", "w") as f:
            f.write("data")
        wt.commit("bla", rev_id=b"newparent")
        wt.branch.repository.fetch(oldrepos)
        wt.branch.repository.lock_write()
        CommitBuilderRevisionRewriter(wt.branch.repository)(
            b"oldcommit", b"newcommit", (b"newparent",)
        )
        wt.branch.repository.unlock()
        oldrev = wt.branch.repository.get_revision(b"oldcommit")
        newrev = wt.branch.repository.get_revision(b"newcommit")
        self.assertEqual([b"newparent"], newrev.parent_ids)
        self.assertEqual(b"newcommit", newrev.revision_id)
        self.assertEqual(oldrev.committer, newrev.committer)
        self.assertEqual(oldrev.timestamp, newrev.timestamp)
        self.assertEqual(oldrev.timezone, newrev.timezone)
        tree = wt.branch.repository.revision_tree(b"newcommit")
        self.assertEqual(b"afileid", tree.path2id("afile"))
        self.assertEqual(b"newcommit", tree.get_file_revision("notherfile"))
        self.assertEqual(b"newgrandparent", tree.get_file_revision("sfile"))

    def test_maps_ids(self):
        wt = self.make_branch_and_tree("old")
        wt.commit("base", rev_id=b"base")
        self.build_tree(["old/afile"])
        wt.add(["afile"], ids=[b"originalid"])
        wt.commit("bla", rev_id=b"oldparent")
        with open("old/afile", "w") as f:
            f.write("bloe")
        wt.commit("bla", rev_id=b"oldcommit")
        oldrepos = wt.branch.repository
        wt = self.make_branch_and_tree("new")
        self.build_tree(["new/afile"])
        wt.add(["afile"], ids=[b"newid"])
        wt.commit("bla", rev_id=b"newparent")
        wt.branch.repository.fetch(oldrepos)
        wt.branch.repository.lock_write()
        CommitBuilderRevisionRewriter(wt.branch.repository)(
            b"oldcommit", b"newcommit", (b"newparent",)
        )
        wt.branch.repository.unlock()
        oldrev = wt.branch.repository.get_revision(b"oldcommit")
        newrev = wt.branch.repository.get_revision(b"newcommit")
        self.assertEqual([b"newparent"], newrev.parent_ids)
        self.assertEqual(b"newcommit", newrev.revision_id)
        self.assertEqual(oldrev.committer, newrev.committer)
        self.assertEqual(oldrev.timestamp, newrev.timestamp)
        self.assertEqual(oldrev.timezone, newrev.timezone)
        tree = wt.branch.repository.revision_tree(b"newcommit")
        self.assertEqual(b"newid", tree.path2id("afile"))
        self.assertEqual(b"newcommit", tree.get_file_revision("afile"))


class TestReplayWorkingtree(TestCaseWithTransport):
    def test_conflicts(self):
        wt = self.make_branch_and_tree("old")
        wt.commit("base", rev_id=b"base")
        self.build_tree(["old/afile"])
        wt.add(["afile"], ids=[b"originalid"])
        wt.commit("bla", rev_id=b"oldparent")
        with open("old/afile", "w") as f:
            f.write("bloe")
        wt.commit("bla", rev_id=b"oldcommit")
        oldrepos = wt.branch.repository
        wt = self.make_branch_and_tree("new")
        self.build_tree(["new/afile"])
        wt.add(["afile"], ids=[b"newid"])
        wt.commit("bla", rev_id=b"newparent")
        wt.branch.repository.fetch(oldrepos)
        with wt.lock_write():
            replayer = WorkingTreeRevisionRewriter(wt, RebaseState1(wt))
            self.assertRaises(
                ConflictsInTree,
                replayer,
                b"oldcommit",
                b"newcommit",
                [b"newparent"],
            )

    def test_simple(self):
        wt = self.make_branch_and_tree("old")
        wt.commit("base", rev_id=b"base")
        self.build_tree(["old/afile"])
        wt.add(["afile"], ids=[b"originalid"])
        wt.commit("bla", rev_id=b"oldparent")
        with open("old/afile", "w") as f:
            f.write("bloe")
        wt.commit("bla", rev_id=b"oldcommit")
        wt = wt.controldir.sprout("new").open_workingtree()
        self.build_tree(["new/bfile"])
        wt.add(["bfile"], ids=[b"newid"])
        wt.commit("bla", rev_id=b"newparent")
        replayer = WorkingTreeRevisionRewriter(wt, RebaseState1(wt))
        replayer(b"oldcommit", b"newcommit", [b"newparent"])
        oldrev = wt.branch.repository.get_revision(b"oldcommit")
        newrev = wt.branch.repository.get_revision(b"newcommit")
        self.assertEqual([b"newparent"], newrev.parent_ids)
        self.assertEqual(b"newcommit", newrev.revision_id)
        self.assertEqual(oldrev.timestamp, newrev.timestamp)
        self.assertEqual(oldrev.timezone, newrev.timezone)

    def test_multiple(self):
        # rebase from
        # base: []
        # oldparent: [base]
        # newparent: [base]
        # oldcommit: [oldparent, ghost]
        # create newcommit by rebasing oldcommit from oldparent to newparent,
        # keeping the merge of ghost.
        # Common base:
        wt = self.make_branch_and_tree("old")
        wt.commit("base", rev_id=b"base")
        # oldparent:
        self.build_tree_contents([("old/afile", "base content")])
        wt.add(["afile"], ids=[b"originalid"])
        wt.commit("bla", rev_id=b"oldparent")
        # oldcommit (the delta getting rebased)
        #  - change the content of afile to be 'bloe'
        with open("old/afile", "w") as f:
            f.write("bloe")
        wt.add_pending_merge(b"ghost")
        wt.commit("bla", rev_id=b"oldcommit")
        # newparent (the new base for the rebased commit)
        new_tree = wt.controldir.sprout("new", revision_id=b"base").open_workingtree()
        new_tree.branch.repository.fetch(wt.branch.repository)
        wt = new_tree
        self.build_tree_contents([("new/afile", "base content")])
        wt.add(["afile"], ids=[b"originalid"])
        wt.commit("bla", rev_id=b"newparent")
        # And do it!
        wt.lock_write()
        replayer = WorkingTreeRevisionRewriter(wt, RebaseState1(wt))
        replayer(b"oldcommit", b"newcommit", (b"newparent", b"ghost"))
        wt.unlock()
        oldrev = wt.branch.repository.get_revision(b"oldcommit")
        newrev = wt.branch.repository.get_revision(b"newcommit")
        self.assertEqual([b"oldparent", b"ghost"], oldrev.parent_ids)
        self.assertEqual([b"newparent", b"ghost"], newrev.parent_ids)
        self.assertEqual(b"newcommit", newrev.revision_id)
        self.assertEqual(oldrev.timestamp, newrev.timestamp)
        self.assertEqual(oldrev.timezone, newrev.timezone)

    def test_already_merged(self):
        r"""We need to use a merge base that makes sense.

        A
        | \
        B  D
        | \|
        C  E

        Rebasing E on C should result in:

        A -> B -> C -> D' -> E'

        Ancestry:
        A:
        B: A
        C: A, B
        D: A
        E: A, B, D
        D': A, B, C
        E': A, B, C, D'

        """
        oldwt = self.make_branch_and_tree("old")
        self.build_tree(["old/afile"])
        with open("old/afile", "w") as f:
            f.write("A\n" * 10)
        oldwt.add(["afile"])
        oldwt.commit("base", rev_id=b"A")
        newwt = oldwt.controldir.sprout("new").open_workingtree()
        with open("old/afile", "w") as f:
            f.write("A\n" * 10 + "B\n")
        oldwt.commit("bla", rev_id=b"B")
        with open("old/afile", "w") as f:
            f.write("A\n" * 10 + "C\n")
        oldwt.commit("bla", rev_id=b"C")
        self.build_tree(["new/bfile"])
        newwt.add(["bfile"])
        with open("new/bfile", "w") as f:
            f.write("D\n")
        newwt.commit("bla", rev_id=b"D")
        with open("new/afile", "w") as f:
            f.write("E\n" + "A\n" * 10 + "B\n")
        with open("new/bfile", "w") as f:
            f.write("D\nE\n")
        newwt.add_pending_merge(b"B")
        newwt.commit("bla", rev_id=b"E")
        newwt.branch.repository.fetch(oldwt.branch.repository)
        newwt.lock_write()
        replayer = WorkingTreeRevisionRewriter(newwt, RebaseState1(newwt))
        replayer(b"D", b"D'", [b"C"])
        newwt.unlock()
        oldrev = newwt.branch.repository.get_revision(b"D")
        newrev = newwt.branch.repository.get_revision(b"D'")
        self.assertEqual([b"C"], newrev.parent_ids)
        newwt.lock_write()
        replayer = WorkingTreeRevisionRewriter(newwt, RebaseState1(newwt))
        self.assertRaises(ConflictsInTree, replayer, b"E", b"E'", [b"D'"])
        newwt.unlock()
        with open("new/afile") as f:
            self.assertEqual("E\n" + "A\n" * 10 + "C\n", f.read())
        newwt.set_conflicts([])
        oldrev = newwt.branch.repository.get_revision(b"E")
        replayer.commit_rebase(oldrev, b"E'")
        newrev = newwt.branch.repository.get_revision(b"E'")
        self.assertEqual([b"D'"], newrev.parent_ids)
        self.assertThat(
            newwt.branch, RevisionHistoryMatches([b"A", b"B", b"C", b"D'", b"E'"])
        )


class TestReplaySnapshotError(TestCase):
    def test_create(self):
        ReplaySnapshotError("message")
