# Copyright (C) 2008-2012, 2016 Canonical Ltd
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

"""Tests for Branch.get_stacked_on_url and set_stacked_on_url."""

import contextlib

from breezy import branch as _mod_branch
from breezy import check, controldir, errors
from breezy.tests import TestNotApplicable, fixtures, transport_util
from breezy.tests.per_branch import TestCaseWithBranch

from ...revision import NULL_REVISION

unstackable_format_errors = (
    _mod_branch.UnstackableBranchFormat,
    errors.UnstackableRepositoryFormat,
)


class TestStacking(TestCaseWithBranch):
    def check_lines_added_or_present(self, stacked_branch, revid):
        # similar to a failure seen in bug 288751 by mbp 20081120
        stacked_repo = stacked_branch.repository
        with stacked_repo.lock_read():
            list(
                stacked_repo.inventories.iter_lines_added_or_present_in_keys([(revid,)])
            )

    def test_get_set_stacked_on_url(self):
        # branches must either:
        # raise UnstackableBranchFormat or
        # raise UnstackableRepositoryFormat or
        # permit stacking to be done and then return the stacked location.
        branch = self.make_branch("branch")
        target = self.make_branch("target")
        try:
            branch.set_stacked_on_url(target.base)
        except unstackable_format_errors:
            # if the set failed, so must the get
            self.assertRaises(unstackable_format_errors, branch.get_stacked_on_url)
            self.assertFalse(branch._format.supports_stacking())
            return
        self.assertTrue(branch._format.supports_stacking())
        # now we have a stacked branch:
        self.assertEqual(target.base, branch.get_stacked_on_url())
        branch.set_stacked_on_url(None)
        self.assertRaises(errors.NotStacked, branch.get_stacked_on_url)

    def test_get_set_stacked_on_relative(self):
        # Branches can be stacked on other branches using relative paths.
        branch = self.make_branch("branch")
        self.make_branch("target")
        try:
            branch.set_stacked_on_url("../target")
        except unstackable_format_errors:
            # if the set failed, so must the get
            self.assertRaises(unstackable_format_errors, branch.get_stacked_on_url)
            return
        self.assertEqual("../target", branch.get_stacked_on_url())

    def test_set_stacked_on_same_branch_raises(self):
        # Stacking on the same branch silently raises and doesn't execute the
        # change. Reported in bug 376243.
        branch = self.make_branch("branch")
        try:
            self.assertRaises(
                errors.UnstackableLocationError, branch.set_stacked_on_url, "../branch"
            )
        except unstackable_format_errors:
            # if the set failed, so must the get
            self.assertRaises(unstackable_format_errors, branch.get_stacked_on_url)
            return
        self.assertRaises(errors.NotStacked, branch.get_stacked_on_url)

    def test_set_stacked_on_same_branch_after_being_stacked_raises(self):
        # Stacking on the same branch silently raises and doesn't execute the
        # change.
        branch = self.make_branch("branch")
        self.make_branch("target")
        try:
            branch.set_stacked_on_url("../target")
        except unstackable_format_errors:
            # if the set failed, so must the get
            self.assertRaises(unstackable_format_errors, branch.get_stacked_on_url)
            return
        self.assertRaises(
            errors.UnstackableLocationError, branch.set_stacked_on_url, "../branch"
        )
        self.assertEqual("../target", branch.get_stacked_on_url())

    def assertRevisionInRepository(self, repo_path, revid):
        """Check that a revision is in a repository, disregarding stacking."""
        repo = controldir.ControlDir.open(repo_path).open_repository()
        self.assertTrue(repo.has_revision(revid))

    def assertRevisionNotInRepository(self, repo_path, revid):
        """Check that a revision is not in a repository, disregarding stacking."""
        repo = controldir.ControlDir.open(repo_path).open_repository()
        self.assertFalse(repo.has_revision(revid))

    def test_get_graph_stacked(self):
        """A stacked repository shows the graph of its parent."""
        trunk_tree = self.make_branch_and_tree("mainline")
        trunk_revid = trunk_tree.commit("mainline")
        # make a new branch, and stack on the existing one.  we don't use
        # sprout(stacked=True) here because if that is buggy and copies data
        # it would cause a false pass of this test.
        new_branch = self.make_branch("new_branch")
        try:
            new_branch.set_stacked_on_url(trunk_tree.branch.base)
        except unstackable_format_errors as e:
            raise TestNotApplicable(e) from e
        # reading the graph from the stacked branch's repository should see
        # data from the stacked-on branch
        new_repo = new_branch.repository
        with new_repo.lock_read():
            self.assertEqual(
                new_repo.get_parent_map([trunk_revid]), {trunk_revid: (NULL_REVISION,)}
            )

    def test_sprout_stacked(self):
        # We have a mainline
        trunk_tree = self.make_branch_and_tree("mainline")
        trunk_revid = trunk_tree.commit("mainline")
        # and make branch from it which is stacked
        try:
            new_dir = trunk_tree.controldir.sprout("newbranch", stacked=True)
        except unstackable_format_errors as e:
            raise TestNotApplicable(e) from e
        # stacked repository
        self.assertRevisionNotInRepository("newbranch", trunk_revid)
        tree = new_dir.open_branch().create_checkout("local")
        new_branch_revid = tree.commit("something local")
        self.assertRevisionNotInRepository(trunk_tree.branch.base, new_branch_revid)
        self.assertRevisionInRepository("newbranch", new_branch_revid)

    def test_sprout_stacked_from_smart_server(self):
        # We have a mainline
        trunk_tree = self.make_branch_and_tree("mainline")
        trunk_revid = trunk_tree.commit("mainline")
        # Make sure that we can make a stacked branch from it
        try:
            trunk_tree.controldir.sprout("testbranch", stacked=True)
        except unstackable_format_errors as e:
            raise TestNotApplicable(e) from e
        # Now serve the original mainline from a smart server
        remote_transport = self.make_smart_server("mainline")
        remote_bzrdir = controldir.ControlDir.open_from_transport(remote_transport)
        # and make branch from the smart server which is stacked
        new_dir = remote_bzrdir.sprout("newbranch", stacked=True)
        # stacked repository
        self.assertRevisionNotInRepository("newbranch", trunk_revid)
        tree = new_dir.open_branch().create_checkout("local")
        new_branch_revid = tree.commit("something local")
        self.assertRevisionNotInRepository(trunk_tree.branch.user_url, new_branch_revid)
        self.assertRevisionInRepository("newbranch", new_branch_revid)

    def test_unstack_fetches(self):
        """Removing the stacked-on branch pulls across all data."""
        try:
            builder = self.make_branch_builder("trunk")
        except errors.UninitializableFormat as e:
            raise TestNotApplicable("uninitializeable format") from e
        # We have a mainline
        trunk, mainline_revid, rev2 = fixtures.build_branch_with_non_ancestral_rev(
            builder
        )
        # and make branch from it which is stacked (with no tags)
        try:
            new_dir = trunk.controldir.sprout(self.get_url("newbranch"), stacked=True)
        except unstackable_format_errors as e:
            raise TestNotApplicable(e) from e
        # stacked repository
        self.assertRevisionNotInRepository("newbranch", mainline_revid)
        # TODO: we'd like to commit in the stacked repository; that requires
        # some care (maybe a BranchBuilder) if it's remote and has no
        # workingtree
        # newbranch_revid = new_dir.open_workingtree().commit('revision in '
        # 'newbranch')
        # now when we unstack that should implicitly fetch, to make sure that
        # the branch will still work
        new_branch = new_dir.open_branch()
        try:
            new_branch.tags.set_tag("tag-a", rev2)
        except errors.TagsNotSupported:
            tags_supported = False
        else:
            tags_supported = True
        new_branch.set_stacked_on_url(None)
        self.assertRevisionInRepository("newbranch", mainline_revid)
        # of course it's still in the mainline
        self.assertRevisionInRepository("trunk", mainline_revid)
        if tags_supported:
            # the tagged revision in trunk is now in newbranch too
            self.assertRevisionInRepository("newbranch", rev2)
        # and now we're no longer stacked
        self.assertRaises(errors.NotStacked, new_branch.get_stacked_on_url)

    def test_unstack_already_locked(self):
        """Removing the stacked-on branch with an already write-locked branch
        works.

        This was bug 551525.
        """
        try:
            stacked_bzrdir = self.make_stacked_bzrdir()
        except unstackable_format_errors as e:
            raise TestNotApplicable(e) from e
        stacked_branch = stacked_bzrdir.open_branch()
        stacked_branch.lock_write()
        stacked_branch.set_stacked_on_url(None)
        stacked_branch.unlock()

    def test_unstack_already_multiple_locked(self):
        """Unstacking a branch preserves the lock count (even though it
        replaces the br.repository object).

        This is a more extreme variation of test_unstack_already_locked.
        """
        try:
            stacked_bzrdir = self.make_stacked_bzrdir()
        except unstackable_format_errors as e:
            raise TestNotApplicable(e) from e
        stacked_branch = stacked_bzrdir.open_branch()
        stacked_branch.lock_write()
        stacked_branch.lock_write()
        stacked_branch.lock_write()
        stacked_branch.set_stacked_on_url(None)
        stacked_branch.unlock()
        stacked_branch.unlock()
        stacked_branch.unlock()

    def make_stacked_bzrdir(self, in_directory=None):
        """Create a stacked branch and return its bzrdir.

        :param in_directory: If not None, create a directory of this
            name and create the stacking and stacked-on bzrdirs in
            this directory.
        """
        if in_directory is not None:
            self.get_transport().mkdir(in_directory)
            prefix = in_directory + "/"
        else:
            prefix = ""
        tree = self.make_branch_and_tree(prefix + "stacked-on")
        tree.commit("Added foo")
        stacked_bzrdir = tree.branch.controldir.sprout(
            self.get_url(prefix + "stacked"), tree.branch.last_revision(), stacked=True
        )
        return stacked_bzrdir

    def test_clone_from_stacked_branch_preserve_stacking(self):
        # We can clone from the bzrdir of a stacked branch. If
        # preserve_stacking is True, the cloned branch is stacked on the
        # same branch as the original.
        try:
            stacked_bzrdir = self.make_stacked_bzrdir()
        except unstackable_format_errors as e:
            raise TestNotApplicable(e) from e
        cloned_bzrdir = stacked_bzrdir.clone("cloned", preserve_stacking=True)
        with contextlib.suppress(unstackable_format_errors):
            self.assertEqual(
                stacked_bzrdir.open_branch().get_stacked_on_url(),
                cloned_bzrdir.open_branch().get_stacked_on_url(),
            )

    def test_clone_from_branch_stacked_on_relative_url_preserve_stacking(self):
        # If a branch's stacked-on url is relative, we can still clone
        # from it with preserve_stacking True and get a branch stacked
        # on an appropriately adjusted relative url.
        try:
            stacked_bzrdir = self.make_stacked_bzrdir(in_directory="dir")
        except unstackable_format_errors as e:
            raise TestNotApplicable(e) from e
        stacked_bzrdir.open_branch().set_stacked_on_url("../stacked-on")
        cloned_bzrdir = stacked_bzrdir.clone(
            self.get_url("cloned"), preserve_stacking=True
        )
        self.assertEqual(
            "../dir/stacked-on", cloned_bzrdir.open_branch().get_stacked_on_url()
        )

    def test_clone_from_stacked_branch_no_preserve_stacking(self):
        try:
            stacked_bzrdir = self.make_stacked_bzrdir()
        except unstackable_format_errors as e:
            # not a testable combination.
            raise TestNotApplicable(e) from e
        cloned_unstacked_bzrdir = stacked_bzrdir.clone(
            "cloned-unstacked", preserve_stacking=False
        )
        unstacked_branch = cloned_unstacked_bzrdir.open_branch()
        self.assertRaises(
            (errors.NotStacked, _mod_branch.UnstackableBranchFormat),
            unstacked_branch.get_stacked_on_url,
        )

    def test_no_op_preserve_stacking(self):
        """With no stacking, preserve_stacking should be a no-op."""
        branch = self.make_branch("source")
        cloned_bzrdir = branch.controldir.clone("cloned", preserve_stacking=True)
        self.assertRaises(
            (errors.NotStacked, _mod_branch.UnstackableBranchFormat),
            cloned_bzrdir.open_branch().get_stacked_on_url,
        )

    def make_stacked_on_matching(self, source):
        if source.repository.supports_rich_root():
            if source.repository._format.supports_chks:
                format = "2a"
            else:
                format = "1.9-rich-root"
        else:
            format = "1.9"
        return self.make_branch("stack-on", format)

    def test_sprout_stacking_policy_handling(self):
        """Obey policy where possible, ignore otherwise."""
        if self.bzrdir_format.fixed_components:
            raise TestNotApplicable("Branch format 4 does not autoupgrade.")
        source = self.make_branch("source")
        stack_on = self.make_stacked_on_matching(source)
        parent_bzrdir = self.make_controldir(".", format="default")
        parent_bzrdir.get_config().set_default_stack_on("stack-on")
        target = source.controldir.sprout("target").open_branch()
        # When we sprout we upgrade the branch when there is a default stack_on
        # set by a config *and* the targeted branch supports stacking.
        if stack_on._format.supports_stacking():
            self.assertEqual("../stack-on", target.get_stacked_on_url())
        else:
            self.assertRaises(branch.UnstackableBranchFormat, target.get_stacked_on_url)

    def test_clone_stacking_policy_handling(self):
        """Obey policy where possible, ignore otherwise."""
        if self.bzrdir_format.fixed_components:
            raise TestNotApplicable("Branch format 4 does not autoupgrade.")
        source = self.make_branch("source")
        stack_on = self.make_stacked_on_matching(source)
        parent_bzrdir = self.make_controldir(".", format="default")
        parent_bzrdir.get_config().set_default_stack_on("stack-on")
        target = source.controldir.clone("target").open_branch()
        # When we clone we upgrade the branch when there is a default stack_on
        # set by a config *and* the targeted branch supports stacking.
        if stack_on._format.supports_stacking():
            self.assertEqual("../stack-on", target.get_stacked_on_url())
        else:
            self.assertRaises(
                _mod_branch.UnstackableBranchFormat, target.get_stacked_on_url
            )

    def test_sprout_to_smart_server_stacking_policy_handling(self):
        """Obey policy where possible, ignore otherwise."""
        if not self.branch_format.supports_leaving_lock():
            raise TestNotApplicable("Branch format is not usable via HPSS.")
        source = self.make_branch("source")
        stack_on = self.make_stacked_on_matching(source)
        parent_bzrdir = self.make_controldir(".", format="default")
        parent_bzrdir.get_config().set_default_stack_on("stack-on")
        url = self.make_smart_server("target").base
        target = source.controldir.sprout(url).open_branch()
        # When we sprout we upgrade the branch when there is a default stack_on
        # set by a config *and* the targeted branch supports stacking.
        if stack_on._format.supports_stacking():
            self.assertEqual("../stack-on", target.get_stacked_on_url())
        else:
            self.assertRaises(
                _mod_branch.UnstackableBranchFormat, target.get_stacked_on_url
            )

    def prepare_stacked_on_fetch(self):
        stack_on = self.make_branch_and_tree("stack-on")
        rev1 = stack_on.commit("first commit")
        try:
            stacked_dir = stack_on.controldir.sprout("stacked", stacked=True)
        except unstackable_format_errors as e:
            raise TestNotApplicable("Format does not support stacking.") from e
        unstacked = self.make_repository("unstacked")
        return stacked_dir.open_workingtree(), unstacked, rev1

    def test_fetch_copies_from_stacked_on(self):
        stacked, unstacked, rev1 = self.prepare_stacked_on_fetch()
        unstacked.fetch(stacked.branch.repository, rev1)
        unstacked.get_revision(rev1)

    def test_fetch_copies_from_stacked_on_and_stacked(self):
        stacked, unstacked, rev1 = self.prepare_stacked_on_fetch()
        tree = stacked.branch.create_checkout("local")
        rev2 = tree.commit("second commit")
        unstacked.fetch(stacked.branch.repository, rev2)
        unstacked.get_revision(rev1)
        unstacked.get_revision(rev2)
        self.check_lines_added_or_present(stacked.branch, rev1)
        self.check_lines_added_or_present(stacked.branch, rev2)

    def test_autopack_when_stacked(self):
        # in bzr.dev as of 20080730, autopack was reported to fail in stacked
        # repositories because of problems with text deltas spanning physical
        # repository boundaries.  however, i didn't actually get this test to
        # fail on that code. -- mbp
        # see https://bugs.launchpad.net/bzr/+bug/252821
        stack_on = self.make_branch_and_tree("stack-on")
        if not stack_on.branch._format.supports_stacking():
            raise TestNotApplicable(f"{self.branch_format!r} does not support stacking")
        text_lines = [b"line %d blah blah blah\n" % i for i in range(20)]
        self.build_tree_contents([("stack-on/a", b"".join(text_lines))])
        stack_on.add("a")
        stack_on.commit("base commit")
        stacked_dir = stack_on.controldir.sprout("stacked", stacked=True)
        stacked_branch = stacked_dir.open_branch()
        local_tree = stack_on.controldir.sprout("local").open_workingtree()
        for i in range(20):
            text_lines[0] = b"changed in %d\n" % i
            self.build_tree_contents([("local/a", b"".join(text_lines))])
            local_tree.commit("commit %d" % i)
            local_tree.branch.push(stacked_branch)
        stacked_branch.repository.pack()
        check.check_dwim(stacked_branch.base, False, True, True)

    def test_pull_delta_when_stacked(self):
        if not self.branch_format.supports_stacking():
            raise TestNotApplicable(f"{self.branch_format!r} does not support stacking")
        stack_on = self.make_branch_and_tree("stack-on")
        text_lines = [b"line %d blah blah blah\n" % i for i in range(20)]
        self.build_tree_contents([("stack-on/a", b"".join(text_lines))])
        stack_on.add("a")
        stack_on.commit("base commit")
        # make a stacked branch from the mainline
        stacked_dir = stack_on.controldir.sprout("stacked", stacked=True)
        stacked_tree = stacked_dir.open_workingtree()
        # make a second non-stacked branch from the mainline
        other_dir = stack_on.controldir.sprout("other")
        other_tree = other_dir.open_workingtree()
        text_lines[9] = b"changed in other\n"
        self.build_tree_contents([("other/a", b"".join(text_lines))])
        stacked_revid = other_tree.commit("commit in other")
        # this should have generated a delta; try to pull that across
        # bug 252821 caused a RevisionNotPresent here...
        stacked_tree.pull(other_tree.branch)
        stacked_tree.branch.repository.pack()
        check.check_dwim(stacked_tree.branch.base, False, True, True)
        self.check_lines_added_or_present(stacked_tree.branch, stacked_revid)

    def test_fetch_revisions_with_file_changes(self):
        # Fetching revisions including file changes into a stacked branch
        # works without error.
        # Make the source tree.
        src_tree = self.make_branch_and_tree("src")
        self.build_tree_contents([("src/a", b"content")])
        src_tree.add("a")
        src_tree.commit("first commit")

        # Make the stacked-on branch.
        src_tree.controldir.sprout("stacked-on")

        # Make a branch stacked on it.
        target = self.make_branch("target")
        try:
            target.set_stacked_on_url("../stacked-on")
        except unstackable_format_errors as e:
            raise TestNotApplicable("Format does not support stacking.") from e

        # Change the source branch.
        self.build_tree_contents([("src/a", b"new content")])
        rev2 = src_tree.commit("second commit")

        # Fetch changes to the target.
        target.fetch(src_tree.branch)
        rtree = target.repository.revision_tree(rev2)
        rtree.lock_read()
        self.addCleanup(rtree.unlock)
        self.assertEqual(b"new content", rtree.get_file_text("a"))
        self.check_lines_added_or_present(target, rev2)

    def test_transform_fallback_location_hook(self):
        # The 'transform_fallback_location' branch hook allows us to inspect
        # and transform the URL of the fallback location for the branch.
        self.make_branch("stack-on")
        stacked = self.make_branch("stacked")
        try:
            stacked.set_stacked_on_url("../stack-on")
        except unstackable_format_errors as e:
            raise TestNotApplicable("Format does not support stacking.") from e
        self.get_transport().rename("stack-on", "new-stack-on")
        hook_calls = []

        def hook(stacked_branch, url):
            hook_calls.append(url)
            return "../new-stack-on"

        _mod_branch.Branch.hooks.install_named_hook(
            "transform_fallback_location", hook, None
        )
        _mod_branch.Branch.open("stacked")
        self.assertEqual(["../stack-on"], hook_calls)

    def test_stack_on_repository_branch(self):
        # Stacking should work when the repo isn't co-located with the
        # stack-on branch.
        try:
            repo = self.make_repository("repo", shared=True)
        except errors.IncompatibleFormat as e:
            raise TestNotApplicable() from e
        if not repo._format.supports_nesting_repositories:
            raise TestNotApplicable()
        # Avoid make_branch, which produces standalone branches.
        bzrdir = self.make_controldir("repo/stack-on")
        try:
            b = bzrdir.create_branch()
        except errors.UninitializableFormat as e:
            raise TestNotApplicable() from e
        transport = self.get_transport("stacked")
        b.controldir.clone_on_transport(transport, stacked_on=b.base)
        # Ensure that opening the branch doesn't raise.
        _mod_branch.Branch.open(transport.base)

    def test_revision_history_of_stacked(self):
        # See <https://launchpad.net/bugs/380314>.
        stack_on = self.make_branch_and_tree("stack-on")
        rev1 = stack_on.commit("first commit")
        try:
            stacked_dir = stack_on.controldir.sprout(
                self.get_url("stacked"), stacked=True
            )
        except unstackable_format_errors as e:
            raise TestNotApplicable("Format does not support stacking.") from e
        try:
            stacked = stacked_dir.open_workingtree()
        except errors.NoWorkingTree:
            stacked = stacked_dir.open_branch().create_checkout(
                "stacked-checkout", lightweight=True
            )
        tree = stacked.branch.create_checkout("local")
        rev2 = tree.commit("second commit")
        # Sanity check: stacked's repo should not contain rev1, otherwise this
        # test isn't testing what it's supposed to.
        repo = stacked.branch.repository.controldir.open_repository()
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual({}, repo.get_parent_map([rev1]))
        # revision_history should work, even though the history is spread over
        # multiple repositories.
        self.assertEqual((2, rev2), stacked.branch.last_revision_info())


class TestStackingConnections(transport_util.TestCaseWithConnectionHookedTransport):
    def setUp(self):
        super().setUp()
        try:
            base_tree = self.make_branch_and_tree("base", format=self.bzrdir_format)
        except errors.UninitializableFormat as e:
            raise TestNotApplicable(e) from e
        stacked = self.make_branch("stacked", format=self.bzrdir_format)
        try:
            stacked.set_stacked_on_url(base_tree.branch.base)
        except unstackable_format_errors as e:
            raise TestNotApplicable(e) from e
        self.rev_base = base_tree.commit("first")
        stacked.set_last_revision_info(1, self.rev_base)
        stacked_relative = self.make_branch(
            "stacked_relative", format=self.bzrdir_format
        )
        stacked_relative.set_stacked_on_url(base_tree.branch.user_url)
        stacked.set_last_revision_info(1, self.rev_base)
        self.start_logging_connections()

    def test_open_stacked(self):
        b = _mod_branch.Branch.open(self.get_url("stacked"))
        b.repository.get_revision(self.rev_base)
        self.assertEqual(1, len(self.connections))

    def test_open_stacked_relative(self):
        b = _mod_branch.Branch.open(self.get_url("stacked_relative"))
        b.repository.get_revision(self.rev_base)
        self.assertEqual(1, len(self.connections))
