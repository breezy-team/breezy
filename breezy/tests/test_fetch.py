# Copyright (C) 2005-2011, 2016 Canonical Ltd
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

from .. import errors, osutils
from .. import revision as _mod_revision
from ..branch import Branch
from ..bzr import bzrdir, knitrepo, versionedfile
from ..upgrade import Convert
from ..workingtree import WorkingTree
from . import TestCaseWithTransport
from .test_revision import make_branches

# These tests are a bit old; please instead add new tests into
# per_interrepository/ so they'll run on all relevant
# combinations.


def has_revision(branch, revision_id):
    return branch.repository.has_revision(revision_id)


def revision_history(branch):
    branch.lock_read()
    try:
        graph = branch.repository.get_graph()
        history = list(
            graph.iter_lefthand_ancestry(
                branch.last_revision(), [_mod_revision.NULL_REVISION]
            )
        )
    finally:
        branch.unlock()
    history.reverse()
    return history


def fetch_steps(self, br_a, br_b, writable_a):
    """A foreign test method for testing fetch locally and remotely."""
    # TODO RBC 20060201 make this a repository test.
    repo_b = br_b.repository
    self.assertFalse(repo_b.has_revision(revision_history(br_a)[3]))
    self.assertTrue(repo_b.has_revision(revision_history(br_a)[2]))
    self.assertEqual(len(revision_history(br_b)), 7)
    br_b.fetch(br_a, revision_history(br_a)[2])
    # branch.fetch is not supposed to alter the revision history
    self.assertEqual(len(revision_history(br_b)), 7)
    self.assertFalse(repo_b.has_revision(revision_history(br_a)[3]))

    # fetching the next revision up in sample data copies one revision
    br_b.fetch(br_a, revision_history(br_a)[3])
    self.assertTrue(repo_b.has_revision(revision_history(br_a)[3]))
    self.assertFalse(has_revision(br_a, revision_history(br_b)[6]))
    self.assertTrue(br_a.repository.has_revision(revision_history(br_b)[5]))

    # When a non-branch ancestor is missing, it should be unlisted...
    # as its not reference from the inventory weave.
    br_b4 = self.make_branch("br_4")
    br_b4.fetch(br_b)

    writable_a.fetch(br_b)
    self.assertTrue(has_revision(br_a, revision_history(br_b)[3]))
    self.assertTrue(has_revision(br_a, revision_history(br_b)[4]))

    br_b2 = self.make_branch("br_b2")
    br_b2.fetch(br_b)
    self.assertTrue(has_revision(br_b2, revision_history(br_b)[4]))
    self.assertTrue(has_revision(br_b2, revision_history(br_a)[2]))
    self.assertFalse(has_revision(br_b2, revision_history(br_a)[3]))

    br_a2 = self.make_branch("br_a2")
    br_a2.fetch(br_a)
    self.assertTrue(has_revision(br_a2, revision_history(br_b)[4]))
    self.assertTrue(has_revision(br_a2, revision_history(br_a)[3]))
    self.assertTrue(has_revision(br_a2, revision_history(br_a)[2]))

    br_a3 = self.make_branch("br_a3")
    # pulling a branch with no revisions grabs nothing, regardless of
    # whats in the inventory.
    br_a3.fetch(br_a2)
    for revno in range(4):
        self.assertFalse(br_a3.repository.has_revision(revision_history(br_a)[revno]))
    br_a3.fetch(br_a2, revision_history(br_a)[2])
    # pull the 3 revisions introduced by a@u-0-3
    br_a3.fetch(br_a2, revision_history(br_a)[3])
    # NoSuchRevision should be raised if the branch is missing the revision
    # that was requested.
    self.assertRaises(errors.NoSuchRevision, br_a3.fetch, br_a2, "pizza")

    # TODO: Test trying to fetch from a branch that points to a revision not
    # actually present in its repository.  Not every branch format allows you
    # to directly point to such revisions, so it's a bit complicated to
    # construct.  One way would be to uncommit and gc the revision, but not
    # every branch supports that.  -- mbp 20070814

    # TODO: test that fetch correctly does reweaving when needed. RBC 20051008
    # Note that this means - updating the weave when ghosts are filled in to
    # add the right parents.


class TestFetch(TestCaseWithTransport):
    def test_fetch(self):
        # highest indices a: 5, b: 7
        br_a, br_b = make_branches(self, format="dirstate-tags")
        fetch_steps(self, br_a, br_b, br_a)

    def test_fetch_self(self):
        wt = self.make_branch_and_tree("br")
        wt.branch.fetch(wt.branch)

    def test_fetch_root_knit(self):
        """Ensure that knit2.fetch() updates the root knit.

        This tests the case where the root has a new revision, but there are no
        corresponding filename, parent, contents or other changes.
        """
        knit1_format = bzrdir.BzrDirMetaFormat1()
        knit1_format.repository_format = knitrepo.RepositoryFormatKnit1()
        knit2_format = bzrdir.BzrDirMetaFormat1()
        knit2_format.repository_format = knitrepo.RepositoryFormatKnit3()
        # we start with a knit1 repository because that causes the
        # root revision to change for each commit, even though the content,
        # parent, name, and other attributes are unchanged.
        tree = self.make_branch_and_tree("tree", knit1_format)
        tree.set_root_id(b"tree-root")
        tree.commit("rev1", rev_id=b"rev1")
        tree.commit("rev2", rev_id=b"rev2")

        # Now we convert it to a knit2 repository so that it has a root knit
        Convert(tree.basedir, knit2_format)
        tree = WorkingTree.open(tree.basedir)
        branch = self.make_branch("branch", format=knit2_format)
        branch.pull(tree.branch, stop_revision=b"rev1")
        repo = branch.repository
        repo.lock_read()
        try:
            # Make sure fetch retrieved only what we requested
            self.assertEqual(
                {(b"tree-root", b"rev1"): ()},
                repo.texts.get_parent_map(
                    [(b"tree-root", b"rev1"), (b"tree-root", b"rev2")]
                ),
            )
        finally:
            repo.unlock()
        branch.pull(tree.branch)
        # Make sure that the next revision in the root knit was retrieved,
        # even though the text, name, parent_id, etc., were unchanged.
        repo.lock_read()
        try:
            # Make sure fetch retrieved only what we requested
            self.assertEqual(
                {(b"tree-root", b"rev2"): ((b"tree-root", b"rev1"),)},
                repo.texts.get_parent_map([(b"tree-root", b"rev2")]),
            )
        finally:
            repo.unlock()

    def test_fetch_incompatible(self):
        knit_tree = self.make_branch_and_tree("knit", format="knit")
        knit3_tree = self.make_branch_and_tree("knit3", format="dirstate-with-subtree")
        knit3_tree.commit("blah")
        e = self.assertRaises(
            errors.IncompatibleRepositories, knit_tree.branch.fetch, knit3_tree.branch
        )
        self.assertContainsRe(
            str(e),
            r"(?m).*/knit.*\nis not compatible with\n.*/knit3/.*\n"
            r"different rich-root support",
        )


class TestMergeFetch(TestCaseWithTransport):
    def test_merge_fetches_unrelated(self):
        """Merge brings across history from unrelated source."""
        wt1 = self.make_branch_and_tree("br1")
        br1 = wt1.branch
        wt1.commit(message="rev 1-1", rev_id=b"1-1")
        wt1.commit(message="rev 1-2", rev_id=b"1-2")
        wt2 = self.make_branch_and_tree("br2")
        br2 = wt2.branch
        wt2.commit(message="rev 2-1", rev_id=b"2-1")
        wt2.merge_from_branch(br1, from_revision=b"null:")
        self._check_revs_present(br2)

    def test_merge_fetches(self):
        """Merge brings across history from source."""
        wt1 = self.make_branch_and_tree("br1")
        br1 = wt1.branch
        wt1.commit(message="rev 1-1", rev_id=b"1-1")
        dir_2 = br1.controldir.sprout("br2")
        br2 = dir_2.open_branch()
        wt1.commit(message="rev 1-2", rev_id=b"1-2")
        wt2 = dir_2.open_workingtree()
        wt2.commit(message="rev 2-1", rev_id=b"2-1")
        wt2.merge_from_branch(br1)
        self._check_revs_present(br2)

    def _check_revs_present(self, br2):
        for rev_id in [b"1-1", b"1-2", b"2-1"]:
            self.assertTrue(br2.repository.has_revision(rev_id))
            rev = br2.repository.get_revision(rev_id)
            self.assertEqual(rev.revision_id, rev_id)
            self.assertTrue(br2.repository.get_inventory(rev_id))


class TestMergeFileHistory(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        wt1 = self.make_branch_and_tree("br1")
        br1 = wt1.branch
        self.build_tree_contents([("br1/file", b"original contents\n")])
        wt1.add("file", ids=b"this-file-id")
        wt1.commit(message="rev 1-1", rev_id=b"1-1")
        dir_2 = br1.controldir.sprout("br2")
        dir_2.open_branch()
        wt2 = dir_2.open_workingtree()
        self.build_tree_contents([("br1/file", b"original from 1\n")])
        wt1.commit(message="rev 1-2", rev_id=b"1-2")
        self.build_tree_contents([("br1/file", b"agreement\n")])
        wt1.commit(message="rev 1-3", rev_id=b"1-3")
        self.build_tree_contents([("br2/file", b"contents in 2\n")])
        wt2.commit(message="rev 2-1", rev_id=b"2-1")
        self.build_tree_contents([("br2/file", b"agreement\n")])
        wt2.commit(message="rev 2-2", rev_id=b"2-2")

    def test_merge_fetches_file_history(self):
        """Merge brings across file histories."""
        br2 = Branch.open("br2")
        br1 = Branch.open("br1")
        WorkingTree.open("br2").merge_from_branch(br1)
        br2.lock_read()
        self.addCleanup(br2.unlock)
        for rev_id, text in [
            (b"1-2", b"original from 1\n"),
            (b"1-3", b"agreement\n"),
            (b"2-1", b"contents in 2\n"),
            (b"2-2", b"agreement\n"),
        ]:
            self.assertEqualDiff(
                br2.repository.revision_tree(rev_id).get_file_text("file"), text
            )


class TestKnitToPackFetch(TestCaseWithTransport):
    def find_get_record_stream(self, calls, expected_count=1):
        """In a list of calls, find the last 'get_record_stream'.

        :param expected_count: The number of calls we should exepect to find.
            If a different number is found, an assertion is raised.
        """
        get_record_call = None
        call_count = 0
        for call in calls:
            if call[0] == "get_record_stream":
                call_count += 1
                get_record_call = call
        self.assertEqual(expected_count, call_count)
        return get_record_call

    def test_fetch_with_deltas_no_delta_closure(self):
        tree = self.make_branch_and_tree("source", format="dirstate")
        target = self.make_repository("target", format="pack-0.92")
        self.build_tree(["source/file"])
        tree.set_root_id(b"root-id")
        tree.add("file", ids=b"file-id")
        tree.commit("one", rev_id=b"rev-one")
        source = tree.branch.repository
        source.texts = versionedfile.RecordingVersionedFilesDecorator(source.texts)
        source.signatures = versionedfile.RecordingVersionedFilesDecorator(
            source.signatures
        )
        source.revisions = versionedfile.RecordingVersionedFilesDecorator(
            source.revisions
        )
        source.inventories = versionedfile.RecordingVersionedFilesDecorator(
            source.inventories
        )
        # precondition
        self.assertTrue(target._format._fetch_uses_deltas)
        target.fetch(source, revision_id=b"rev-one")
        self.assertEqual(
            (
                "get_record_stream",
                [(b"file-id", b"rev-one")],
                target._format._fetch_order,
                False,
            ),
            self.find_get_record_stream(source.texts.calls),
        )
        self.assertEqual(
            ("get_record_stream", [(b"rev-one",)], target._format._fetch_order, False),
            self.find_get_record_stream(source.inventories.calls, 2),
        )
        self.assertEqual(
            ("get_record_stream", [(b"rev-one",)], target._format._fetch_order, False),
            self.find_get_record_stream(source.revisions.calls),
        )
        # XXX: Signatures is special, and slightly broken. The
        # standard item_keys_introduced_by actually does a lookup for every
        # signature to see if it exists, rather than waiting to do them all at
        # once at the end. The fetch code then does an all-at-once and just
        # allows for some of them to be missing.
        # So we know there will be extra calls, but the *last* one is the one
        # we care about.
        signature_calls = source.signatures.calls[-1:]
        self.assertEqual(
            ("get_record_stream", [(b"rev-one",)], target._format._fetch_order, False),
            self.find_get_record_stream(signature_calls),
        )

    def test_fetch_no_deltas_with_delta_closure(self):
        tree = self.make_branch_and_tree("source", format="dirstate")
        target = self.make_repository("target", format="pack-0.92")
        self.build_tree(["source/file"])
        tree.set_root_id(b"root-id")
        tree.add("file", ids=b"file-id")
        tree.commit("one", rev_id=b"rev-one")
        source = tree.branch.repository
        source.texts = versionedfile.RecordingVersionedFilesDecorator(source.texts)
        source.signatures = versionedfile.RecordingVersionedFilesDecorator(
            source.signatures
        )
        source.revisions = versionedfile.RecordingVersionedFilesDecorator(
            source.revisions
        )
        source.inventories = versionedfile.RecordingVersionedFilesDecorator(
            source.inventories
        )
        # XXX: This won't work in general, but for the dirstate format it does.
        self.overrideAttr(target._format, "_fetch_uses_deltas", False)
        target.fetch(source, revision_id=b"rev-one")
        self.assertEqual(
            (
                "get_record_stream",
                [(b"file-id", b"rev-one")],
                target._format._fetch_order,
                True,
            ),
            self.find_get_record_stream(source.texts.calls),
        )
        self.assertEqual(
            ("get_record_stream", [(b"rev-one",)], target._format._fetch_order, True),
            self.find_get_record_stream(source.inventories.calls, 2),
        )
        self.assertEqual(
            ("get_record_stream", [(b"rev-one",)], target._format._fetch_order, True),
            self.find_get_record_stream(source.revisions.calls),
        )
        # XXX: Signatures is special, and slightly broken. The
        # standard item_keys_introduced_by actually does a lookup for every
        # signature to see if it exists, rather than waiting to do them all at
        # once at the end. The fetch code then does an all-at-once and just
        # allows for some of them to be missing.
        # So we know there will be extra calls, but the *last* one is the one
        # we care about.
        signature_calls = source.signatures.calls[-1:]
        self.assertEqual(
            ("get_record_stream", [(b"rev-one",)], target._format._fetch_order, True),
            self.find_get_record_stream(signature_calls),
        )

    def test_fetch_revisions_with_deltas_into_pack(self):
        # See BUG #261339, dev versions of bzr could accidentally create deltas
        # in revision texts in knit branches (when fetching from packs). So we
        # ensure that *if* a knit repository has a delta in revisions, that it
        # gets properly expanded back into a fulltext when stored in the pack
        # file.
        tree = self.make_branch_and_tree("source", format="dirstate")
        target = self.make_repository("target", format="pack-0.92")
        self.build_tree(["source/file"])
        tree.set_root_id(b"root-id")
        tree.add("file", ids=b"file-id")
        tree.commit("one", rev_id=b"rev-one")
        # Hack the KVF for revisions so that it "accidentally" allows a delta
        tree.branch.repository.revisions._max_delta_chain = 200
        tree.commit("two", rev_id=b"rev-two")
        source = tree.branch.repository
        # Ensure that we stored a delta
        source.lock_read()
        self.addCleanup(source.unlock)
        record = next(
            source.revisions.get_record_stream([(b"rev-two",)], "unordered", False)
        )
        self.assertEqual("knit-delta-gz", record.storage_kind)
        target.fetch(tree.branch.repository, revision_id=b"rev-two")
        # The record should get expanded back to a fulltext
        target.lock_read()
        self.addCleanup(target.unlock)
        record = next(
            target.revisions.get_record_stream([(b"rev-two",)], "unordered", False)
        )
        self.assertEqual("knit-ft-gz", record.storage_kind)

    def test_fetch_with_fallback_and_merge(self):
        builder = self.make_branch_builder("source", format="pack-0.92")
        builder.start_series()
        # graph
        #   A
        #   |\
        #   B C
        #   | |
        #   | D
        #   | |
        #   | E
        #    \|
        #     F
        # A & B are present in the base (stacked-on) repository, A-E are
        # present in the source.
        # This reproduces bug #304841
        # We need a large enough inventory that total size of compressed deltas
        # is shorter than the size of a compressed fulltext. We have to use
        # random ids because otherwise the inventory fulltext compresses too
        # well and the deltas get bigger.
        to_add = [("add", ("", b"TREE_ROOT", "directory", None))]
        for i in range(10):
            fname = "file%03d" % (i,)
            fileid = ("{}-{}".format(fname, osutils.rand_chars(64))).encode("ascii")
            to_add.append(("add", (fname, fileid, "file", b"content\n")))
        builder.build_snapshot(None, to_add, revision_id=b"A")
        builder.build_snapshot([b"A"], [], revision_id=b"B")
        builder.build_snapshot([b"A"], [], revision_id=b"C")
        builder.build_snapshot([b"C"], [], revision_id=b"D")
        builder.build_snapshot([b"D"], [], revision_id=b"E")
        builder.build_snapshot([b"E", b"B"], [], revision_id=b"F")
        builder.finish_series()
        source_branch = builder.get_branch()
        source_branch.controldir.sprout("base", revision_id=b"B")
        target_branch = self.make_branch("target", format="1.6")
        target_branch.set_stacked_on_url("../base")
        source = source_branch.repository
        source.lock_read()
        self.addCleanup(source.unlock)
        source.inventories = versionedfile.OrderingVersionedFilesDecorator(
            source.inventories,
            key_priority={(b"E",): 1, (b"D",): 2, (b"C",): 4, (b"F",): 3},
        )
        # Ensure that the content is yielded in the proper order, and given as
        # the expected kinds
        records = [
            (record.key, record.storage_kind)
            for record in source.inventories.get_record_stream(
                [(b"D",), (b"C",), (b"E",), (b"F",)], "unordered", False
            )
        ]
        self.assertEqual(
            [
                ((b"E",), "knit-delta-gz"),
                ((b"D",), "knit-delta-gz"),
                ((b"F",), "knit-delta-gz"),
                ((b"C",), "knit-delta-gz"),
            ],
            records,
        )

        target_branch.lock_write()
        self.addCleanup(target_branch.unlock)
        target = target_branch.repository
        target.fetch(source, revision_id=b"F")
        # 'C' should be expanded to a fulltext, but D and E should still be
        # deltas
        stream = target.inventories.get_record_stream(
            [(b"C",), (b"D",), (b"E",), (b"F",)], "unordered", False
        )
        kinds = {record.key: record.storage_kind for record in stream}
        self.assertEqual(
            {
                (b"C",): "knit-ft-gz",
                (b"D",): "knit-delta-gz",
                (b"E",): "knit-delta-gz",
                (b"F",): "knit-delta-gz",
            },
            kinds,
        )


class Test1To2Fetch(TestCaseWithTransport):
    """Tests for Model1To2 failure modes."""

    def make_tree_and_repo(self):
        self.tree = self.make_branch_and_tree("tree", format="pack-0.92")
        self.repo = self.make_repository("rich-repo", format="rich-root-pack")
        self.repo.lock_write()
        self.addCleanup(self.repo.unlock)

    def do_fetch_order_test(self, first, second):
        """Test that fetch works no matter what the set order of revision is.

        This test depends on the order of items in a set, which is
        implementation-dependant, so we test A, B and then B, A.
        """
        self.make_tree_and_repo()
        self.tree.commit("Commit 1", rev_id=first)
        self.tree.commit("Commit 2", rev_id=second)
        self.repo.fetch(self.tree.branch.repository, second)

    def test_fetch_order_AB(self):
        """See do_fetch_order_test."""
        self.do_fetch_order_test(b"A", b"B")

    def test_fetch_order_BA(self):
        """See do_fetch_order_test."""
        self.do_fetch_order_test(b"B", b"A")

    def get_parents(self, file_id, revision_id):
        self.repo.lock_read()
        try:
            parent_map = self.repo.texts.get_parent_map([(file_id, revision_id)])
            return parent_map[(file_id, revision_id)]
        finally:
            self.repo.unlock()

    def test_fetch_ghosts(self):
        self.make_tree_and_repo()
        self.tree.commit("first commit", rev_id=b"left-parent")
        self.tree.add_parent_tree_id(b"ghost-parent")
        fork = self.tree.controldir.sprout("fork", b"null:").open_workingtree()
        fork.commit("not a ghost", rev_id=b"not-ghost-parent")
        self.tree.branch.repository.fetch(fork.branch.repository, b"not-ghost-parent")
        self.tree.add_parent_tree_id(b"not-ghost-parent")
        self.tree.commit("second commit", rev_id=b"second-id")
        self.repo.fetch(self.tree.branch.repository, b"second-id")
        root_id = self.tree.path2id("")
        self.assertEqual(
            ((root_id, b"left-parent"), (root_id, b"not-ghost-parent")),
            self.get_parents(root_id, b"second-id"),
        )

    def make_two_commits(self, change_root, fetch_twice):
        self.make_tree_and_repo()
        self.tree.commit("first commit", rev_id=b"first-id")
        if change_root:
            self.tree.set_root_id(b"unique-id")
        self.tree.commit("second commit", rev_id=b"second-id")
        if fetch_twice:
            self.repo.fetch(self.tree.branch.repository, b"first-id")
        self.repo.fetch(self.tree.branch.repository, b"second-id")

    def test_fetch_changed_root(self):
        self.make_two_commits(change_root=True, fetch_twice=False)
        self.assertEqual((), self.get_parents(b"unique-id", b"second-id"))

    def test_two_fetch_changed_root(self):
        self.make_two_commits(change_root=True, fetch_twice=True)
        self.assertEqual((), self.get_parents(b"unique-id", b"second-id"))

    def test_two_fetches(self):
        self.make_two_commits(change_root=False, fetch_twice=True)
        self.assertEqual(
            ((b"TREE_ROOT", b"first-id"),), self.get_parents(b"TREE_ROOT", b"second-id")
        )
