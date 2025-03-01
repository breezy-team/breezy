# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tests for fetch between repositories of the same type."""

from breezy import controldir, errors, gpg, repository
from breezy.bzr import remote
from breezy.bzr.inventory import ROOT_ID
from breezy.tests import TestNotApplicable, TestSkipped
from breezy.tests.per_repository import TestCaseWithRepository


class TestFetchSameRepository(TestCaseWithRepository):
    def test_fetch(self):
        # smoke test fetch to ensure that the convenience function works.
        # it is defined as a convenience function with the underlying
        # functionality provided by an InterRepository
        tree_a = self.make_branch_and_tree("a")
        self.build_tree(["a/foo"])
        tree_a.add("foo")
        tree_a.commit("rev1")
        # fetch with a default limit (grab everything)
        repo = self.make_repository("b")
        if (
            tree_a.branch.repository.supports_rich_root()
            and not repo.supports_rich_root()
        ):
            raise TestSkipped("Cannot fetch from model2 to model1")
        repo.fetch(tree_a.branch.repository, revision_id=None)

    def test_fetch_fails_in_write_group(self):
        # fetch() manages a write group itself, fetching within one isn't safe.
        repo = self.make_repository("a")
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.abort_write_group)
        # Don't need a specific class - not expecting flow control based on
        # this.
        self.assertRaises(errors.BzrError, repo.fetch, repo)

    def test_fetch_to_knit3(self):
        # create a repository of the sort we are testing.
        tree_a = self.make_branch_and_tree("a")
        self.build_tree(["a/foo"])
        tree_a.add("foo")
        rev1 = tree_a.commit("rev1")
        # create a knit-3 based format to fetch into
        f = controldir.format_registry.make_controldir("development-subtree")
        try:
            format = tree_a.branch.repository._format
            format.check_conversion_target(f.repository_format)
            # if we cannot convert data to knit3, skip the test.
        except errors.BadConversionTarget as e:
            raise TestSkipped(str(e))
        self.get_transport().mkdir("b")
        b_bzrdir = f.initialize(self.get_url("b"))
        knit3_repo = b_bzrdir.create_repository()
        # fetch with a default limit (grab everything)
        knit3_repo.fetch(tree_a.branch.repository, revision_id=None)
        # Reopen to avoid any in-memory caching - ensure its reading from
        # disk.
        knit3_repo = b_bzrdir.open_repository()
        rev1_tree = knit3_repo.revision_tree(rev1)
        with rev1_tree.lock_read():
            lines = rev1_tree.get_file_lines("")
        self.assertEqual([], lines)
        b_branch = b_bzrdir.create_branch()
        b_branch.pull(tree_a.branch)
        try:
            tree_b = b_bzrdir.create_workingtree()
        except errors.NotLocalUrl:
            try:
                tree_b = b_branch.create_checkout("b", lightweight=True)
            except errors.NotLocalUrl:
                raise TestSkipped(
                    "cannot make working tree with transport {!r}".format(b_bzrdir.transport)
                )
        rev2 = tree_b.commit("no change")
        rev2_tree = knit3_repo.revision_tree(rev2)
        self.assertEqual(rev1, rev2_tree.get_file_revision(""))

    def do_test_fetch_to_rich_root_sets_parents_correctly(
        self, result, snapshots, root_id=ROOT_ID, allow_lefthand_ghost=False
    ):
        """Assert that result is the parents of b'tip' after fetching snapshots.

        This helper constructs a 1.9 format source, and a test-format target
        and fetches the result of building snapshots in the source, then
        asserts that the parents of tip are result.

        :param result: A parents list for the inventories.get_parent_map call.
        :param snapshots: An iterable of snapshot parameters for
            BranchBuilder.build_snapshot.
        '
        """
        # This overlaps slightly with the tests for commit builder about graph
        # consistency.
        # Cases:
        repo = self.make_repository("target")
        remote_format = isinstance(repo, remote.RemoteRepository)
        if not repo._format.rich_root_data and not remote_format:
            return  # not relevant
        if not repo._format.supports_full_versioned_files:
            raise TestNotApplicable("format does not support full versioned files")
        builder = self.make_branch_builder("source", format="1.9")
        builder.start_series()
        for revision_id, parent_ids, actions in snapshots:
            builder.build_snapshot(
                parent_ids,
                actions,
                allow_leftmost_as_ghost=allow_lefthand_ghost,
                revision_id=revision_id,
            )
        builder.finish_series()
        source = builder.get_branch()
        if remote_format and not repo._format.rich_root_data:
            # use a manual rich root format to ensure the code path is tested.
            repo = self.make_repository("remote-target", format="1.9-rich-root")
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.fetch(source.repository)
        graph = repo.get_file_graph()
        self.assertEqual(
            result, graph.get_parent_map([(root_id, b"tip")])[(root_id, b"tip")]
        )

    def test_fetch_to_rich_root_set_parent_no_parents(self):
        # No parents rev -> No parents
        self.do_test_fetch_to_rich_root_sets_parents_correctly(
            (),
            [
                (b"tip", None, [("add", ("", ROOT_ID, "directory", ""))]),
            ],
        )

    def test_fetch_to_rich_root_set_parent_1_parent(self):
        # 1 parent rev -> 1 parent
        self.do_test_fetch_to_rich_root_sets_parents_correctly(
            ((ROOT_ID, b"base"),),
            [
                (b"base", None, [("add", ("", ROOT_ID, "directory", ""))]),
                (b"tip", None, []),
            ],
        )

    def test_fetch_to_rich_root_set_parent_1_ghost_parent(self):
        # 1 ghost parent -> No parents
        if not self.repository_format.supports_ghosts:
            raise TestNotApplicable("repository format does not support ghosts")
        self.do_test_fetch_to_rich_root_sets_parents_correctly(
            (),
            [
                (b"tip", [b"ghost"], [("add", ("", ROOT_ID, "directory", ""))]),
            ],
            allow_lefthand_ghost=True,
        )

    def test_fetch_to_rich_root_set_parent_2_head_parents(self):
        # 2 parents both heads -> 2 parents
        self.do_test_fetch_to_rich_root_sets_parents_correctly(
            ((ROOT_ID, b"left"), (ROOT_ID, b"right")),
            [
                (b"base", None, [("add", ("", ROOT_ID, "directory", ""))]),
                (b"left", None, []),
                (b"right", [b"base"], []),
                (b"tip", [b"left", b"right"], []),
            ],
        )

    def test_fetch_to_rich_root_set_parent_2_parents_1_head(self):
        # 2 parents one head -> 1 parent
        self.do_test_fetch_to_rich_root_sets_parents_correctly(
            ((ROOT_ID, b"right"),),
            [
                (b"left", None, [("add", ("", ROOT_ID, "directory", ""))]),
                (b"right", None, []),
                (b"tip", [b"left", b"right"], []),
            ],
        )

    def test_fetch_to_rich_root_set_parent_1_parent_different_id_gone(self):
        # 1 parent different fileid, ours missing -> no parents
        self.do_test_fetch_to_rich_root_sets_parents_correctly(
            (),
            [
                (b"base", None, [("add", ("", ROOT_ID, "directory", ""))]),
                (
                    b"tip",
                    None,
                    [
                        ("unversion", ""),
                        ("add", ("", b"my-root", "directory", "")),
                    ],
                ),
            ],
            root_id=b"my-root",
        )

    def test_fetch_to_rich_root_set_parent_1_parent_different_id_moved(self):
        # 1 parent different fileid, ours moved -> 1 parent
        # (and that parent honours the changing revid of the other location)
        self.do_test_fetch_to_rich_root_sets_parents_correctly(
            ((b"my-root", b"origin"),),
            [
                (
                    b"origin",
                    None,
                    [
                        ("add", ("", ROOT_ID, "directory", "")),
                        ("add", ("child", b"my-root", "directory", "")),
                    ],
                ),
                (b"base", None, []),
                (
                    b"tip",
                    None,
                    [
                        ("unversion", "child"),
                        ("unversion", ""),
                        ("flush", None),
                        ("add", ("", b"my-root", "directory", "")),
                    ],
                ),
            ],
            root_id=b"my-root",
        )

    def test_fetch_to_rich_root_set_parent_2_parent_1_different_id_gone(self):
        # 2 parents, 1 different fileid, our second missing -> 1 parent
        self.do_test_fetch_to_rich_root_sets_parents_correctly(
            ((b"my-root", b"right"),),
            [
                (b"base", None, [("add", ("", ROOT_ID, "directory", ""))]),
                (
                    b"right",
                    None,
                    [("unversion", ""), ("add", ("", b"my-root", "directory", ""))],
                ),
                (
                    b"tip",
                    [b"base", b"right"],
                    [
                        ("unversion", ""),
                        ("add", ("", b"my-root", "directory", "")),
                    ],
                ),
            ],
            root_id=b"my-root",
        )

    def test_fetch_to_rich_root_set_parent_2_parent_2_different_id_moved(self):
        # 2 parents, 1 different fileid, our second moved -> 2 parent
        # (and that parent honours the changing revid of the other location)
        self.do_test_fetch_to_rich_root_sets_parents_correctly(
            ((b"my-root", b"right"),),
            # b'my-root' at 'child'.
            [
                (
                    b"origin",
                    None,
                    [
                        ("add", ("", ROOT_ID, "directory", "")),
                        ("add", ("child", b"my-root", "directory", "")),
                    ],
                ),
                (b"base", None, []),
                # b'my-root' at root
                (
                    b"right",
                    None,
                    [
                        ("unversion", "child"),
                        ("unversion", ""),
                        ("flush", None),
                        ("add", ("", b"my-root", "directory", "")),
                    ],
                ),
                (
                    b"tip",
                    [b"base", b"right"],
                    [
                        ("unversion", ""),
                        ("unversion", "child"),
                        ("flush", None),
                        ("add", ("", b"my-root", "directory", "")),
                    ],
                ),
            ],
            root_id=b"my-root",
        )

    def test_fetch_all_from_self(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("one")
        # This needs to be a new copy of the repository, if this changes, the
        # test needs to be rewritten
        repo = tree.branch.repository.controldir.open_repository()
        # This fetch should be a no-op see bug #158333
        tree.branch.repository.fetch(repo, None)

    def test_fetch_from_self(self):
        tree = self.make_branch_and_tree(".")
        rev_id = tree.commit("one")
        repo = tree.branch.repository.controldir.open_repository()
        # This fetch should be a no-op see bug #158333
        tree.branch.repository.fetch(repo, rev_id)

    def test_fetch_missing_from_self(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("one")
        # Even though the fetch() is a NO-OP it should assert the revision id
        # is present
        repo = tree.branch.repository.controldir.open_repository()
        self.assertRaises(
            errors.NoSuchRevision,
            tree.branch.repository.fetch,
            repo,
            b"no-such-revision",
        )

    def makeARepoWithSignatures(self):
        wt = self.make_branch_and_tree("a-repo-with-sigs")
        rev1 = wt.commit("rev1", allow_pointless=True)
        repo = wt.branch.repository
        repo.lock_write()
        repo.start_write_group()
        try:
            repo.sign_revision(rev1, gpg.LoopbackGPGStrategy(None))
        except errors.UnsupportedOperation:
            self.assertFalse(repo._format.supports_revision_signatures)
            raise TestNotApplicable("repository format does not support signatures")
        repo.commit_write_group()
        repo.unlock()
        return repo, rev1

    def test_fetch_copies_signatures(self):
        source_repo, rev1 = self.makeARepoWithSignatures()
        target_repo = self.make_repository("target")
        target_repo.fetch(source_repo, revision_id=None)
        self.assertEqual(
            source_repo.get_signature_text(rev1), target_repo.get_signature_text(rev1)
        )

    def make_repository_with_one_revision(self):
        wt = self.make_branch_and_tree("source")
        rev1 = wt.commit("rev1", allow_pointless=True)
        return wt.branch.repository, rev1

    def test_fetch_revision_already_exists(self):
        # Make a repository with one revision.
        source_repo, rev1 = self.make_repository_with_one_revision()
        # Fetch that revision into a second repository.
        target_repo = self.make_repository("target")
        target_repo.fetch(source_repo, revision_id=rev1)
        # Now fetch again; there will be nothing to do.  This should work
        # without causing any errors.
        target_repo.fetch(source_repo, revision_id=rev1)

    def test_fetch_all_same_revisions_twice(self):
        # Blind-fetching all the same revisions twice should succeed and be a
        # no-op the second time.
        repo = self.make_repository("repo")
        tree = self.make_branch_and_tree("tree")
        tree.commit("test")
        repo.fetch(tree.branch.repository)
        repo.fetch(tree.branch.repository)

    def make_simple_branch_with_ghost(self):
        if not self.repository_format.supports_ghosts:
            raise TestNotApplicable("repository format does not support ghosts")
        builder = self.make_branch_builder("source")
        builder.start_series()
        a_revid = builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("file", b"file-id", "file", b"content\n")),
            ],
        )
        b_revid = builder.build_snapshot([a_revid, b"ghost-id"], [])
        builder.finish_series()
        source_b = builder.get_branch()
        source_b.lock_read()
        self.addCleanup(source_b.unlock)
        return source_b, b_revid

    def test_fetch_with_ghost(self):
        source_b, b_revid = self.make_simple_branch_with_ghost()
        target = self.make_repository("target")
        target.lock_write()
        self.addCleanup(target.unlock)
        target.fetch(source_b.repository, revision_id=b_revid)

    def test_fetch_into_smart_with_ghost(self):
        trans = self.make_smart_server("target")
        source_b, b_revid = self.make_simple_branch_with_ghost()
        if not source_b.controldir._format.supports_transport(trans):
            raise TestNotApplicable("format does not support transport")
        target = self.make_repository("target")
        # Re-open the repository over the smart protocol
        target = repository.Repository.open(trans.base)
        target.lock_write()
        self.addCleanup(target.unlock)
        try:
            target.fetch(source_b.repository, revision_id=b_revid)
        except errors.TokenLockingNotSupported:
            # The code inside fetch() that tries to lock and then fails, also
            # causes weird problems with 'lock_not_held' later on...
            target.lock_read()
            self.knownFailure(
                "some repositories fail to fetch"
                " via the smart server because of locking issues."
            )

    def test_fetch_from_smart_with_ghost(self):
        trans = self.make_smart_server("source")
        source_b, b_revid = self.make_simple_branch_with_ghost()
        if not source_b.controldir._format.supports_transport(trans):
            raise TestNotApplicable("format does not support transport")
        target = self.make_repository("target")
        target.lock_write()
        self.addCleanup(target.unlock)
        # Re-open the repository over the smart protocol
        source = repository.Repository.open(trans.base)
        source.lock_read()
        self.addCleanup(source.unlock)
        target.fetch(source, revision_id=b_revid)
