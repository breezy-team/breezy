# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

"""Tests for branch implementations - tests a branch format."""

import contextlib

from breezy import branch as _mod_branch
from breezy import (
    config,
    controldir,
    errors,
    lock,
    osutils,
    repository,
    revision,
    shelf,
    tests,
    transport,
    urlutils,
)
from breezy import tree as _mod_tree
from breezy.bzr import remote
from breezy.tests import per_branch
from breezy.transport import memory

from ..http_server import HttpServer


class TestTestCaseWithBranch(per_branch.TestCaseWithBranch):
    def test_branch_format_matches_bzrdir_branch_format(self):
        bzrdir_branch_format = self.bzrdir_format.get_branch_format()
        self.assertIs(self.branch_format.__class__, bzrdir_branch_format.__class__)

    def test_make_branch_gets_expected_format(self):
        branch = self.make_branch(".")
        self.assertIs(self.branch_format.__class__, branch._format.__class__)


class TestBranch(per_branch.TestCaseWithBranch):
    def test_create_tree_with_merge(self):
        tree, revmap = self.create_tree_with_merge()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        graph = tree.branch.repository.get_graph()
        ancestry_graph = graph.get_parent_map(tree.branch.repository.all_revision_ids())
        self.assertEqual(
            {
                revmap["1"]: (b"null:",),
                revmap["2"]: (revmap["1"],),
                revmap["1.1.1"]: (revmap["1"],),
                revmap["3"]: (
                    revmap["2"],
                    revmap["1.1.1"],
                ),
            },
            ancestry_graph,
        )

    def test_revision_ids_are_utf8(self):
        wt = self.make_branch_and_tree("tree")
        rev1 = wt.commit("f")
        rev2 = wt.commit("f")
        rev3 = wt.commit("f")

        br = self.get_branch()
        br.fetch(wt.branch)
        br.generate_revision_history(rev3)
        for revision_id in [rev3, rev2, rev1]:
            self.assertIsInstance(revision_id, bytes)
        last = br.last_revision()
        self.assertEqual(rev3, last)
        self.assertIsInstance(last, bytes)
        revno, last = br.last_revision_info()
        self.assertEqual(3, revno)
        self.assertEqual(rev3, last)
        self.assertIsInstance(last, bytes)

    def test_fetch_revisions(self):
        """Test fetch-revision operation."""
        wt = self.make_branch_and_tree("b1")
        b1 = wt.branch
        self.build_tree_contents([("b1/foo", b"hello")])
        wt.add(["foo"])
        rev1 = wt.commit("lala!", allow_pointless=False)

        b2 = self.make_branch("b2")
        result = b2.fetch(b1)
        self.assertIsInstance(result, repository.FetchResult)

        b2.repository.get_revision(rev1)
        tree = b2.repository.revision_tree(rev1)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(tree.get_file_text("foo"), b"hello")

    def get_unbalanced_tree_pair(self):
        """Return two branches, a and b, with one file in a."""
        tree_a = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/b", b"b")])
        tree_a.add("b")
        tree_a.commit("silly commit")

        tree_b = self.make_branch_and_tree("b")
        return tree_a, tree_b

    def get_balanced_branch_pair(self):
        """Returns br_a, br_b as with one commit in a, and b has a's stores."""
        tree_a, tree_b = self.get_unbalanced_tree_pair()
        tree_b.branch.repository.fetch(tree_a.branch.repository)
        return tree_a, tree_b

    def test_clone_partial(self):
        """Copy only part of the history of a branch."""
        # TODO: RBC 20060208 test with a revision not on revision-history.
        #       what should that behaviour be ? Emailed the list.
        # First, make a branch with two commits.
        wt_a = self.make_branch_and_tree("a")
        self.build_tree(["a/one"])
        wt_a.add(["one"])
        rev1 = wt_a.commit("commit one")
        self.build_tree(["a/two"])
        wt_a.add(["two"])
        wt_a.commit("commit two")
        # Now make a copy of the repository.
        repo_b = self.make_repository("b")
        wt_a.branch.repository.copy_content_into(repo_b)
        # wt_a might be a lightweight checkout, so get a hold of the actual
        # branch (because you can't do a partial clone of a lightweight
        # checkout).
        branch = wt_a.branch.controldir.open_branch()
        # Then make a branch where the new repository is, but specify a revision
        # ID.  The new branch's history will stop at the specified revision.
        br_b = branch.clone(repo_b.controldir, revision_id=rev1)
        self.assertEqual(rev1, br_b.last_revision())

    def get_parented_branch(self):
        wt_a = self.make_branch_and_tree("a")
        self.build_tree(["a/one"])
        wt_a.add(["one"])
        rev1 = wt_a.commit("commit one")

        branch_b = wt_a.branch.controldir.sprout("b", revision_id=rev1).open_branch()
        self.assertEqual(
            urlutils.strip_segment_parameters(wt_a.branch.user_url),
            urlutils.strip_segment_parameters(branch_b.get_parent()),
        )
        return branch_b

    def test_clone_branch_nickname(self):
        # test the nick name is preserved always
        raise tests.TestSkipped("XXX branch cloning is not yet tested.")

    def test_clone_branch_parent(self):
        # test the parent is preserved always
        branch_b = self.get_parented_branch()
        repo_c = self.make_repository("c")
        branch_b.repository.copy_content_into(repo_c)
        branch_c = branch_b.clone(repo_c.controldir)
        self.assertNotEqual(None, branch_c.get_parent())
        self.assertEqual(branch_b.get_parent(), branch_c.get_parent())

        # We can also set a specific parent, and it should be honored
        random_parent = "http://example.com/path/to/branch"
        branch_b.set_parent(random_parent)
        repo_d = self.make_repository("d")
        branch_b.repository.copy_content_into(repo_d)
        branch_d = branch_b.clone(repo_d.controldir)
        self.assertEqual(random_parent, branch_d.get_parent())

    def test_submit_branch(self):
        """Submit location can be queried and set."""
        branch = self.make_branch("branch")
        self.assertEqual(branch.get_submit_branch(), None)
        branch.set_submit_branch("sftp://example.com")
        self.assertEqual(branch.get_submit_branch(), "sftp://example.com")
        branch.set_submit_branch("sftp://example.net")
        self.assertEqual(branch.get_submit_branch(), "sftp://example.net")

    def test_public_branch(self):
        """Public location can be queried and set."""
        branch = self.make_branch("branch")
        self.assertEqual(branch.get_public_branch(), None)
        branch.set_public_branch("sftp://example.com")
        self.assertEqual(branch.get_public_branch(), "sftp://example.com")
        branch.set_public_branch("sftp://example.net")
        self.assertEqual(branch.get_public_branch(), "sftp://example.net")
        branch.set_public_branch(None)
        self.assertEqual(branch.get_public_branch(), None)

    def test_record_initial_ghost(self):
        """Branches should support having ghosts."""
        wt = self.make_branch_and_tree(".")
        if not wt.branch.repository._format.supports_ghosts:
            raise tests.TestNotApplicable("repository format does not support ghosts")
        wt.set_parent_ids(
            [b"non:existent@rev--ision--0--2"], allow_leftmost_as_ghost=True
        )
        self.assertEqual([b"non:existent@rev--ision--0--2"], wt.get_parent_ids())
        rev_id = wt.commit("commit against a ghost first parent.")
        rev = wt.branch.repository.get_revision(rev_id)
        self.assertEqual(rev.parent_ids, [b"non:existent@rev--ision--0--2"])

    def test_record_two_ghosts(self):
        """Recording with all ghosts works."""
        wt = self.make_branch_and_tree(".")
        if not wt.branch.repository._format.supports_ghosts:
            raise tests.TestNotApplicable("repository format does not support ghosts")
        wt.set_parent_ids(
            [
                b"foo@azkhazan-123123-abcabc",
                b"wibble@fofof--20050401--1928390812",
            ],
            allow_leftmost_as_ghost=True,
        )
        rev_id = wt.commit("commit from ghost base with one merge")
        # the revision should have been committed with two parents
        rev = wt.branch.repository.get_revision(rev_id)
        self.assertEqual(
            [b"foo@azkhazan-123123-abcabc", b"wibble@fofof--20050401--1928390812"],
            rev.parent_ids,
        )

    def test_bad_revision(self):
        self.assertRaises(
            errors.InvalidRevisionId, self.get_branch().repository.get_revision, None
        )

    def test_nicks_bzr(self):
        """Test the behaviour of branch nicks specific to bzr branches.

        Nicknames are implicitly the name of the branch's directory, unless an
        explicit nickname is set.  That is, an explicit nickname always
        overrides the implicit one.

        """
        t = self.get_transport()
        branch = self.make_branch("bzr.dev")
        if not branch.repository._format.supports_storing_branch_nick:
            raise tests.TestNotApplicable("not a bzr branch format")
        # The nick will be 'bzr.dev', because there is no explicit nick set.
        self.assertEqual(branch.nick, "bzr.dev")
        # Move the branch to a different directory, 'bzr.ab'.  Now that branch
        # will report its nick as 'bzr.ab'.
        t.move("bzr.dev", "bzr.ab")
        branch = _mod_branch.Branch.open(self.get_url("bzr.ab"))
        self.assertEqual(branch.nick, "bzr.ab")
        # Set the branch nick explicitly.  This will ensure there's a branch
        # config file in the branch.
        branch.nick = "Aaron's branch"
        if not isinstance(branch, remote.RemoteBranch):
            self.assertTrue(branch._transport.has("branch.conf"))
        # Because the nick has been set explicitly, the nick is now always
        # "Aaron's branch", regardless of directory name.
        self.assertEqual(branch.nick, "Aaron's branch")
        t.move("bzr.ab", "integration")
        branch = _mod_branch.Branch.open(self.get_url("integration"))
        self.assertEqual(branch.nick, "Aaron's branch")
        branch.nick = "\u1234"
        self.assertEqual(branch.nick, "\u1234")

    def test_nicks(self):
        """Test explicit and implicit branch nicknames.

        A nickname is always available, whether set explicitly or not.
        """
        self.get_transport()
        branch = self.make_branch("bzr.dev")
        # An implicit nick name is set; what it is exactly depends on the
        # format.
        self.assertIsInstance(branch.nick, str)
        # Set the branch nick explicitly.
        branch.nick = "Aaron's branch"
        # Because the nick has been set explicitly, the nick is now always
        # "Aaron's branch".
        self.assertEqual(branch.nick, "Aaron's branch")
        branch.nick = "\u1234"
        self.assertEqual(branch.nick, "\u1234")

    def test_commit_nicks(self):
        """Nicknames are committed to the revision."""
        wt = self.make_branch_and_tree("bzr.dev")
        branch = wt.branch
        branch.nick = "My happy branch"
        wt.commit("My commit respect da nick.")
        committed = branch.repository.get_revision(branch.last_revision())
        if branch.repository._format.supports_storing_branch_nick:
            self.assertEqual(committed.properties["branch-nick"], "My happy branch")
        else:
            self.assertNotIn("branch-nick", committed.properties)

    def test_create_colocated(self):
        try:
            repo = self.make_repository(".", shared=True)
        except errors.IncompatibleFormat:
            return
        if repo.controldir._format.colocated_branches:
            raise tests.TestNotApplicable(
                "control dir does not support colocated branches"
            )
        self.assertEqual(0, len(repo.controldir.list_branches()))
        if not self.bzrdir_format.colocated_branches:
            raise tests.TestNotApplicable(
                "control dir format does not support colocated branches"
            )
        try:
            self.branch_format.initialize(repo.controldir, name="branch1")
        except errors.UninitializableFormat:
            # branch references are not default init'able and
            # not all bzrdirs support colocated branches.
            return
        self.assertEqual(1, len(repo.controldir.list_branches()))
        self.branch_format.initialize(repo.controldir, name="branch2")
        self.assertEqual(2, len(repo.controldir.list_branches()))

    def test_create_append_revisions_only(self):
        try:
            repo = self.make_repository(".", shared=True)
        except errors.IncompatibleFormat:
            return
        for _val in (True, False):
            try:
                branch = self.branch_format.initialize(
                    repo.controldir, append_revisions_only=True
                )
            except (errors.UninitializableFormat, errors.UpgradeRequired):
                # branch references are not default init'able and
                # not all branches support append_revisions_only
                return
            self.assertEqual(True, branch.get_append_revisions_only())
            repo.controldir.destroy_branch()

    def test_get_set_append_revisions_only(self):
        branch = self.make_branch(".")
        if branch._format.supports_set_append_revisions_only():
            branch.set_append_revisions_only(True)
            self.assertTrue(branch.get_append_revisions_only())
            branch.set_append_revisions_only(False)
            self.assertFalse(branch.get_append_revisions_only())
        else:
            self.assertRaises(
                errors.UpgradeRequired, branch.set_append_revisions_only, True
            )
            self.assertFalse(branch.get_append_revisions_only())

    def test_create_open_branch_uses_repository(self):
        try:
            repo = self.make_repository(".", shared=True)
        except errors.IncompatibleFormat as err:
            raise tests.TestNotApplicable("requires shared repository support") from err
        child_transport = repo.controldir.root_transport.clone("child")
        child_transport.mkdir(".")
        try:
            child_dir = self.bzrdir_format.initialize_on_transport(child_transport)
        except errors.UninitializableFormat as err:
            raise tests.TestNotApplicable(
                "control dir format not initializable"
            ) from err
        try:
            child_branch = self.branch_format.initialize(child_dir)
        except errors.UninitializableFormat:
            # branch references are not default init'able.
            return
        self.assertEqual(
            repo.controldir.root_transport.base,
            child_branch.repository.controldir.root_transport.base,
        )
        child_branch = _mod_branch.Branch.open(self.get_url("child"))
        self.assertEqual(
            repo.controldir.root_transport.base,
            child_branch.repository.controldir.root_transport.base,
        )

    def test_format_description(self):
        tree = self.make_branch_and_tree("tree")
        text = tree.branch._format.get_format_description()
        self.assertTrue(len(text))

    def test_get_commit_builder(self):
        branch = self.make_branch(".")
        branch.lock_write()
        builder = branch.get_commit_builder([])
        self.assertIsInstance(builder, repository.CommitBuilder)
        branch.repository.commit_write_group()
        branch.unlock()

    def test_generate_revision_history(self):
        """Create a fake revision history easily."""
        tree = self.make_branch_and_tree(".")
        rev1 = tree.commit("foo")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        graph = tree.branch.repository.get_graph()
        orig_history = list(
            graph.iter_lefthand_ancestry(
                tree.branch.last_revision(), [revision.NULL_REVISION]
            )
        )
        tree.commit("bar", allow_pointless=True)
        tree.branch.generate_revision_history(rev1)
        self.assertEqual(
            orig_history,
            list(
                graph.iter_lefthand_ancestry(
                    tree.branch.last_revision(), [revision.NULL_REVISION]
                )
            ),
        )

    def test_generate_revision_history_NULL_REVISION(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("foo")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.branch.generate_revision_history(revision.NULL_REVISION)
        self.assertEqual(revision.NULL_REVISION, tree.branch.last_revision())

    def test_create_checkout(self):
        tree_a = self.make_branch_and_tree("a")
        branch_a = tree_a.branch
        checkout_b = branch_a.create_checkout("b")
        self.assertEqual(b"null:", checkout_b.last_revision())
        try:
            rev1 = checkout_b.commit("rev1")
        except errors.NoRoundtrippingSupport as err:
            raise tests.TestNotApplicable(
                f"roundtripping between {checkout_b.branch!r} and {checkout_b.branch.get_master_branch()!r} not supported"
            ) from err
        self.assertEqual(rev1, branch_a.last_revision())
        self.assertNotEqual(checkout_b.branch.base, branch_a.base)

        checkout_c = branch_a.create_checkout("c", lightweight=True)
        self.assertEqual(rev1, checkout_c.last_revision())
        rev2 = checkout_c.commit("rev2")
        self.assertEqual(rev2, branch_a.last_revision())
        self.assertEqual(checkout_c.branch.base, branch_a.base)

        checkout_d = branch_a.create_checkout("d", lightweight=True)
        self.assertEqual(rev2, checkout_d.last_revision())
        checkout_e = branch_a.create_checkout("e")
        self.assertEqual(rev2, checkout_e.last_revision())

    def test_create_anonymous_lightweight_checkout(self):
        """A lightweight checkout from a readonly branch should succeed."""
        tree_a = self.make_branch_and_tree("a")
        rev_id = tree_a.commit("put some content in the branch")
        # open the branch via a readonly transport
        url = self.get_readonly_url(urlutils.basename(tree_a.branch.base))
        t = transport.get_transport_from_url(url)
        if not tree_a.branch.controldir._format.supports_transport(t):
            raise tests.TestNotApplicable("format does not support transport")
        source_branch = _mod_branch.Branch.open(url)
        # sanity check that the test will be valid
        self.assertRaises(
            (errors.LockError, errors.TransportNotPossible), source_branch.lock_write
        )
        checkout = source_branch.create_checkout("c", lightweight=True)
        self.assertEqual(rev_id, checkout.last_revision())

    def test_create_anonymous_heavyweight_checkout(self):
        """A regular checkout from a readonly branch should succeed."""
        tree_a = self.make_branch_and_tree("a")
        rev_id = tree_a.commit("put some content in the branch")
        # open the branch via a readonly transport
        url = self.get_readonly_url(osutils.basename(tree_a.branch.base.rstrip("/")))
        t = transport.get_transport_from_url(url)
        if not tree_a.branch.controldir._format.supports_transport(t):
            raise tests.TestNotApplicable("format does not support transport")
        source_branch = _mod_branch.Branch.open(url)
        # sanity check that the test will be valid
        self.assertRaises(
            (errors.LockError, errors.TransportNotPossible), source_branch.lock_write
        )
        checkout = source_branch.create_checkout("c")
        self.assertEqual(rev_id, checkout.last_revision())

    def test_heads_to_fetch(self):
        # heads_to_fetch is a method that returns a collection of revids that
        # need to be fetched to copy this branch into another repo.  At a
        # minimum this will include the tip.
        # (In native formats, this is the tip + tags, but other formats may
        # have other revs needed)
        tree = self.make_branch_and_tree("a")
        tree.commit("first commit")
        rev2 = tree.commit("second commit")
        must_fetch, _should_fetch = tree.branch.heads_to_fetch()
        self.assertIn(rev2, must_fetch)

    def test_heads_to_fetch_not_null_revision(self):
        # NULL_REVISION does not appear in the result of heads_to_fetch, even
        # for an empty branch.
        tree = self.make_branch_and_tree("a")
        must_fetch, should_fetch = tree.branch.heads_to_fetch()
        self.assertNotIn(revision.NULL_REVISION, must_fetch)
        self.assertNotIn(revision.NULL_REVISION, should_fetch)

    def test_create_memorytree(self):
        tree = self.make_branch_and_tree("a")
        self.assertIsInstance(tree.branch.create_memorytree(), _mod_tree.Tree)


class TestBranchFormat(per_branch.TestCaseWithBranch):
    def test_branch_format_network_name(self):
        br = self.make_branch(".")
        format = br._format
        network_name = format.network_name()
        self.assertIsInstance(network_name, bytes)
        # We want to test that the network_name matches the actual format on
        # disk. For local branches that means that using network_name as a key
        # in the registry gives back the same format. For remote branches we
        # check that the network_name of the RemoteBranchFormat we have locally
        # matches the actual format present on disk.
        if isinstance(format, remote.RemoteBranchFormat):
            br._ensure_real()
            real_branch = br._real_branch
            self.assertEqual(real_branch._format.network_name(), network_name)
        else:
            registry = _mod_branch.network_format_registry
            looked_up_format = registry.get(network_name)
            self.assertEqual(format.__class__, looked_up_format.__class__)

    def test_get_config_calls(self):
        # Smoke test that all branch succeed getting a config
        br = self.make_branch(".")
        br.get_config()
        br.get_config_stack()


class ChrootedTests(per_branch.TestCaseWithBranch):
    """A support class that provides readonly urls outside the local namespace.

    This is done by checking if self.transport_server is a MemoryServer. if it
    is then we are chrooted already, if it is not then an HttpServer is used
    for readonly urls.
    """

    def setUp(self):
        super().setUp()
        if self.vfs_transport_factory != memory.MemoryServer:
            self.transport_readonly_server = HttpServer

    def test_open_containing(self):
        self.assertRaises(
            errors.NotBranchError,
            _mod_branch.Branch.open_containing,
            self.get_readonly_url(""),
        )
        self.assertRaises(
            errors.NotBranchError,
            _mod_branch.Branch.open_containing,
            self.get_readonly_url("g/p/q"),
        )
        branch = self.make_branch(".")
        if not branch.controldir._format.supports_transport(
            transport.get_transport_from_url(self.get_readonly_url("."))
        ):
            raise tests.TestNotApplicable("format does not support transport")
        branch, relpath = _mod_branch.Branch.open_containing(self.get_readonly_url(""))
        self.assertEqual("", relpath)
        branch, relpath = _mod_branch.Branch.open_containing(
            self.get_readonly_url("g/p/q")
        )
        self.assertEqual("g/p/q", relpath)


class InstrumentedTransaction:
    def finish(self):
        self.calls.append("finish")

    def __init__(self):
        self.calls = []


class TestDecorator:
    def __init__(self):
        self._calls = []

    def lock_read(self):
        self._calls.append("lr")
        return lock.LogicalLockResult(self.unlock)

    def lock_write(self):
        self._calls.append("lw")
        return lock.LogicalLockResult(self.unlock)

    def unlock(self):
        self._calls.append("ul")

    def do_with_read(self):
        with self.lock_read():
            return 1

    def except_with_read(self):
        with self.lock_read():
            raise RuntimeError


class TestBranchPushLocations(per_branch.TestCaseWithBranch):
    def test_get_push_location_unset(self):
        self.assertEqual(None, self.get_branch().get_push_location())

    def test_get_push_location_exact(self):
        b = self.get_branch()
        config.LocationConfig.from_string(
            f"[{b.base}]\npush_location=foo\n", b.base, save=True
        )
        self.assertEqual("foo", self.get_branch().get_push_location())

    def test_set_push_location(self):
        branch = self.get_branch()
        branch.set_push_location("foo")
        self.assertEqual("foo", branch.get_push_location())


class TestChildSubmitFormats(per_branch.TestCaseWithBranch):
    def test_get_child_submit_format_default(self):
        submit_format = self.get_branch().get_child_submit_format()
        self.assertTrue(submit_format is None or isinstance(submit_format, str))

    def test_get_child_submit_format(self):
        branch = self.get_branch()
        branch.get_config_stack().set("child_submit_format", "10")
        branch = self.get_branch()
        self.assertEqual("10", branch.get_child_submit_format())


class TestFormat(per_branch.TestCaseWithBranch):
    """Tests for the format itself."""

    def test_get_reference(self):
        """get_reference on all regular branches should return None."""
        if not self.branch_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        made_controldir = self.make_controldir(".")
        made_controldir.create_repository()
        if made_controldir._format.colocated_branches:
            # Formats that support colocated branches sometimes have a default
            # branch that is a reference branch (such as Git). Cope with
            # those by creating a different colocated branch.
            name = "foo"
        else:
            name = None
        try:
            made_branch = made_controldir.create_branch(name)
        except errors.UninitializableFormat as err:
            raise tests.TestNotApplicable("Uninitializable branch format") from err

        self.assertEqual(
            None, made_branch._format.get_reference(made_branch.controldir, name)
        )

    def test_set_reference(self):
        """set_reference on all regular branches should be callable."""
        if not self.branch_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        this_branch = self.make_branch("this")
        other_branch = self.make_branch("other")
        try:
            this_branch._format.set_reference(
                this_branch.controldir, None, other_branch
            )
        except (NotImplementedError, errors.IncompatibleFormat):
            # that's ok
            pass
        else:
            ref = this_branch._format.get_reference(this_branch.controldir)
            self.assertEqual(ref, other_branch.user_url)

    def test_format_initialize_find_open(self):
        # loopback test to check the current format initializes to itself.
        if not self.branch_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # supported formats must be able to init and open
        self.get_transport()
        readonly_t = transport.get_transport_from_url(self.get_readonly_url())
        made_branch = self.make_branch(".")
        self.assertIsInstance(made_branch, _mod_branch.Branch)

        # find it via bzrdir opening:
        opened_control = controldir.ControlDir.open(readonly_t.base)
        direct_opened_branch = opened_control.open_branch()
        self.assertEqual(direct_opened_branch.__class__, made_branch.__class__)
        self.assertEqual(opened_control, direct_opened_branch.controldir)
        self.assertIsInstance(
            direct_opened_branch._format, self.branch_format.__class__
        )

        # find it via Branch.open
        opened_branch = _mod_branch.Branch.open(readonly_t.base)
        self.assertIsInstance(opened_branch, made_branch.__class__)
        self.assertEqual(made_branch._format.__class__, opened_branch._format.__class__)
        # if it has a unique id string, can we probe for it ?
        try:
            self.branch_format.get_format_string()
        except NotImplementedError:
            return
        self.assertEqual(self.branch_format, opened_control.find_branch_format())


class TestBound(per_branch.TestCaseWithBranch):
    def test_bind_unbind(self):
        branch = self.make_branch("1")
        branch2 = self.make_branch("2")
        try:
            branch.bind(branch2)
        except _mod_branch.BindingUnsupported as err:
            raise tests.TestNotApplicable("Format does not support binding") from err
        self.assertTrue(branch.unbind())
        self.assertFalse(branch.unbind())
        self.assertIs(None, branch.get_bound_location())

    def test_old_bound_location(self):
        branch = self.make_branch("branch1")
        try:
            self.assertIs(None, branch.get_old_bound_location())
        except errors.UpgradeRequired as e:
            raise tests.TestNotApplicable(
                "Format does not store old bound locations"
            ) from e
        branch2 = self.make_branch("branch2")
        branch.bind(branch2)
        self.assertIs(None, branch.get_old_bound_location())
        branch.unbind()
        self.assertContainsRe(branch.get_old_bound_location(), "\\/branch2\\/$")

    def test_bind_diverged(self):
        tree_a = self.make_branch_and_tree("tree_a")
        tree_a.commit("rev1a")
        tree_b = tree_a.controldir.sprout("tree_b").open_workingtree()
        tree_a.commit("rev2a")
        tree_b.commit("rev2b")
        try:
            tree_b.branch.bind(tree_a.branch)
        except _mod_branch.BindingUnsupported as e:
            raise tests.TestNotApplicable("Format does not support binding") from e

    def test_unbind_clears_cached_master_branch(self):
        """b.unbind clears any cached value of b.get_master_branch."""
        master = self.make_branch("master")
        branch = self.make_branch("branch")
        try:
            branch.bind(master)
        except _mod_branch.BindingUnsupported as e:
            raise tests.TestNotApplicable("Format does not support binding") from e
        self.addCleanup(branch.lock_write().unlock)
        self.assertNotEqual(None, branch.get_master_branch())
        branch.unbind()
        self.assertEqual(None, branch.get_master_branch())

    def test_bind_clears_cached_master_branch(self):
        """b.bind clears any cached value of b.get_master_branch."""
        master1 = self.make_branch("master1")
        master2 = self.make_branch("master2")
        branch = self.make_branch("branch")
        try:
            branch.bind(master1)
        except _mod_branch.BindingUnsupported as e:
            raise tests.TestNotApplicable("Format does not support binding") from e
        self.addCleanup(branch.lock_write().unlock)
        self.assertNotEqual(None, branch.get_master_branch())
        branch.bind(master2)
        self.assertEqual(
            ".",
            urlutils.relative_url(
                self.get_url("master2"), branch.get_master_branch().base
            ),
        )

    def test_set_bound_location_clears_cached_master_branch(self):
        """b.set_bound_location clears any cached value of b.get_master_branch."""
        master1 = self.make_branch("master1")
        self.make_branch("master2")
        branch = self.make_branch("branch")
        try:
            branch.bind(master1)
        except _mod_branch.BindingUnsupported as e:
            raise tests.TestNotApplicable("Format does not support binding") from e
        self.addCleanup(branch.lock_write().unlock)
        self.assertNotEqual(None, branch.get_master_branch())
        branch.set_bound_location(self.get_url("master2"))
        self.assertEqual(
            ".",
            urlutils.relative_url(
                self.get_url("master2"), branch.get_master_branch().base
            ),
        )


class TestStrict(per_branch.TestCaseWithBranch):
    def test_strict_history(self):
        tree1 = self.make_branch_and_tree("tree1")
        try:
            tree1.branch.set_append_revisions_only(True)
        except errors.UpgradeRequired as e:
            raise tests.TestSkipped("Format does not support strict history") from e
        tree1.commit("empty commit")
        tree2 = tree1.controldir.sprout("tree2").open_workingtree()
        tree2.commit("empty commit 2")
        tree1.pull(tree2.branch)
        tree1.commit("empty commit 3")
        tree2.commit("empty commit 4")
        self.assertRaises(errors.DivergedBranches, tree1.pull, tree2.branch)
        tree2.merge_from_branch(tree1.branch)
        tree2.commit("empty commit 5")
        self.assertRaises(errors.AppendRevisionsOnlyViolation, tree1.pull, tree2.branch)
        tree3 = tree1.controldir.sprout("tree3").open_workingtree()
        tree3.merge_from_branch(tree2.branch)
        tree3.commit("empty commit 6")
        tree2.pull(tree3.branch)


class TestIgnoreFallbacksParameter(per_branch.TestCaseWithBranch):
    def make_branch_with_fallback(self):
        fallback = self.make_branch("fallback")
        if not fallback._format.supports_stacking():
            raise tests.TestNotApplicable("format does not support stacking")
        stacked = self.make_branch("stacked")
        stacked.set_stacked_on_url(fallback.base)
        return stacked

    def test_fallbacks_not_opened(self):
        stacked = self.make_branch_with_fallback()
        self.get_transport("").rename("fallback", "moved")
        reopened_dir = controldir.ControlDir.open(stacked.base)
        reopened = reopened_dir.open_branch(ignore_fallbacks=True)
        self.assertEqual([], reopened.repository._fallback_repositories)

    def test_fallbacks_are_opened(self):
        stacked = self.make_branch_with_fallback()
        reopened_dir = controldir.ControlDir.open(stacked.base)
        reopened = reopened_dir.open_branch(ignore_fallbacks=False)
        self.assertLength(1, reopened.repository._fallback_repositories)


class TestBranchControlComponent(per_branch.TestCaseWithBranch):
    """Branch implementations adequately implement ControlComponent."""

    def test_urls(self):
        br = self.make_branch("branch")
        self.assertIsInstance(br.user_url, str)
        self.assertEqual(br.user_url, br.user_transport.base)
        self.assertEqual(br.control_url, br.control_transport.base)


class FakeShelfCreator:
    def __init__(self, branch):
        self.branch = branch

    def write_shelf(self, shelf_file, message=None):
        tree = self.branch.repository.revision_tree(revision.NULL_REVISION)
        with tree.preview_transform() as tt:
            shelf.ShelfCreator._write_shelf(shelf_file, tt, revision.NULL_REVISION)


@contextlib.contextmanager
def skip_if_storing_uncommitted_unsupported():
    try:
        yield
    except errors.StoringUncommittedNotSupported as e:
        raise tests.TestNotApplicable("Cannot store uncommitted changes.") from e


class TestUncommittedChanges(per_branch.TestCaseWithBranch):
    def setUp(self):
        super().setUp()
        if not self.branch_format.supports_store_uncommitted():
            raise tests.TestNotApplicable(
                "Branch format does not support store_uncommitted"
            )

    def bind(self, branch, master):
        try:
            branch.bind(master)
        except _mod_branch.BindingUnsupported as e:
            raise tests.TestNotApplicable("Branch cannot be bound.") from e

    def test_store_uncommitted(self):
        tree = self.make_branch_and_tree("b")
        branch = tree.branch
        creator = FakeShelfCreator(branch)
        with skip_if_storing_uncommitted_unsupported():
            self.assertIs(None, branch.get_unshelver(tree))
        branch.store_uncommitted(creator)
        self.assertIsNot(None, branch.get_unshelver(tree))

    def test_store_uncommitted_bound(self):
        tree = self.make_branch_and_tree("b")
        branch = tree.branch
        master = self.make_branch("master")
        self.bind(branch, master)
        creator = FakeShelfCreator(tree.branch)
        self.assertIs(None, tree.branch.get_unshelver(tree))
        self.assertIs(None, master.get_unshelver(tree))
        tree.branch.store_uncommitted(creator)
        self.assertIsNot(None, master.get_unshelver(tree))

    def test_store_uncommitted_already_stored(self):
        branch = self.make_branch("b")
        with skip_if_storing_uncommitted_unsupported():
            branch.store_uncommitted(FakeShelfCreator(branch))
        self.assertRaises(
            errors.ChangesAlreadyStored,
            branch.store_uncommitted,
            FakeShelfCreator(branch),
        )

    def test_store_uncommitted_none(self):
        branch = self.make_branch("b")
        with skip_if_storing_uncommitted_unsupported():
            branch.store_uncommitted(FakeShelfCreator(branch))
        branch.store_uncommitted(None)
        self.assertIs(None, branch.get_unshelver(None))

    def test_get_unshelver(self):
        tree = self.make_branch_and_tree("tree")
        tree.commit("")
        self.build_tree_contents([("tree/file", b"contents1")])
        tree.add("file")
        with skip_if_storing_uncommitted_unsupported():
            tree.store_uncommitted()
        unshelver = tree.branch.get_unshelver(tree)
        self.assertIsNot(None, unshelver)

    def test_get_unshelver_bound(self):
        tree = self.make_branch_and_tree("tree")
        tree.commit("")
        self.build_tree_contents([("tree/file", b"contents1")])
        tree.add("file")
        with skip_if_storing_uncommitted_unsupported():
            tree.store_uncommitted()
        branch = self.make_branch("branch")
        self.bind(branch, tree.branch)
        unshelver = branch.get_unshelver(tree)
        self.assertIsNot(None, unshelver)


class TestFormatMetadata(per_branch.TestCaseWithBranch):
    def test_stores_revno(self):
        self.assertIn(self.branch_format.stores_revno(), (True, False))
