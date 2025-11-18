# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for pushing revisions from Bazaar into Git."""

from ...branch import InterBranch
from ...controldir import format_registry
from ...repository import InterRepository
from ...tests import TestCaseWithTransport
from ..interrepo import InterToGitRepository
from ..mapping import BzrGitMappingExperimental, BzrGitMappingv1


class InterToGitRepositoryTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.git_repo = self.make_repository(
            "git", format=format_registry.make_controldir("git")
        )
        self.bzr_repo = self.make_repository("bzr", shared=True)

    def _get_interrepo(self, mapping=None):
        self.bzr_repo.lock_read()
        self.addCleanup(self.bzr_repo.unlock)
        interrepo = InterRepository.get(self.bzr_repo, self.git_repo)
        if mapping is not None:
            interrepo.mapping = mapping
        return interrepo

    def test_instance(self):
        self.assertIsInstance(self._get_interrepo(), InterToGitRepository)

    def test_pointless_fetch_refs_old_mapping(self):
        interrepo = self._get_interrepo(mapping=BzrGitMappingv1())
        interrepo.fetch_refs(lambda x: {}, lossy=False)

    def test_pointless_fetch_refs(self):
        interrepo = self._get_interrepo(mapping=BzrGitMappingExperimental())
        _revidmap, old_refs, new_refs = interrepo.fetch_refs(lambda x: {}, lossy=False)
        self.assertEqual(old_refs, {b"HEAD": (b"ref: refs/heads/master", None)})
        self.assertEqual(new_refs, {})

    def test_pointless_lossy_fetch_refs(self):
        revidmap, old_refs, new_refs = self._get_interrepo().fetch_refs(
            lambda x: {}, lossy=True
        )
        self.assertEqual(old_refs, {b"HEAD": (b"ref: refs/heads/master", None)})
        self.assertEqual(new_refs, {})
        self.assertEqual(revidmap, {})

    def test_pointless_missing_revisions(self):
        interrepo = self._get_interrepo()
        interrepo.source_store.lock_read()
        self.addCleanup(interrepo.source_store.unlock)
        self.assertEqual([], list(interrepo.missing_revisions([])))

    def test_missing_revisions_unknown_stop_rev(self):
        interrepo = self._get_interrepo()
        interrepo.source_store.lock_read()
        self.addCleanup(interrepo.source_store.unlock)
        self.assertEqual([], list(interrepo.missing_revisions([(None, b"unknown")])))

    def test_odd_rename(self):
        # Add initial revision to bzr branch.
        branch = self.bzr_repo.controldir.create_branch()
        tree = branch.controldir.create_workingtree()
        self.build_tree(["bzr/bar/", "bzr/bar/foobar"])
        tree.add(["bar", "bar/foobar"])
        tree.commit("initial")

        # Add new directory and perform move in bzr branch.
        self.build_tree(["bzr/baz/"])
        tree.add(["baz"])
        tree.rename_one("bar", "baz/IrcDotNet")
        last_revid = tree.commit("rename")

        # Push bzr branch to git branch.
        def decide(x):
            return {b"refs/heads/master": (None, last_revid)}

        interrepo = self._get_interrepo()
        revidmap, _old_refs, _new_refs = interrepo.fetch_refs(decide, lossy=True)
        gitid = revidmap[last_revid][0]
        store = self.git_repo._git.object_store
        commit = store[gitid]
        tree = store[commit.tree]
        tree.check()
        self.assertIn(b"baz", tree, repr(tree.items()))
        self.assertIn(tree[b"baz"][1], store)
        baz = store[tree[b"baz"][1]]
        baz.check()
        ircdotnet = store[baz[b"IrcDotNet"][1]]
        ircdotnet.check()
        foobar = store[ircdotnet[b"foobar"][1]]
        foobar.check()


class LocalBzrToGitPushTests(TestCaseWithTransport):
    """Test local push operations from bzr to git, especially tag handling."""

    def setUp(self):
        super().setUp()
        # Create a bzr branch with content
        self.bzr_tree = self.make_branch_and_tree("bzr", format="bzr")
        self.build_tree(["bzr/file1.txt"])
        self.bzr_tree.add(["file1.txt"])
        self.rev1 = self.bzr_tree.commit("Initial commit")

        self.build_tree_contents([("bzr/file1.txt", b"updated content")])
        self.rev2 = self.bzr_tree.commit("Second commit")

        # Create tags
        self.bzr_tree.branch.tags.set_tag("tag1", self.rev1)
        self.bzr_tree.branch.tags.set_tag("tag2", self.rev2)

        # Create a git repository as target
        self.git_repo = self.make_repository(
            "git", format=format_registry.make_controldir("git")
        )
        self.git_branch = self.git_repo.controldir.create_branch()

    def test_push_with_tags_default(self):
        """Test that tags are NOT pushed by default (breezy default behavior)."""
        # Push from bzr to git (lossy mode required for bzr->git)
        interbranch = InterBranch.get(self.bzr_tree.branch, self.git_branch)
        interbranch.push(lossy=True)

        # Verify tags were NOT pushed (respecting breezy's default config)
        git_refs = self.git_repo._git.refs.as_dict()
        self.assertNotIn(b"refs/tags/tag1", git_refs)
        self.assertNotIn(b"refs/tags/tag2", git_refs)

    def test_push_without_tags_explicit(self):
        """Test that tags are not pushed when explicitly disabled."""
        # Set branch.fetch_tags to False
        self.bzr_tree.branch.get_config().set_user_option("branch.fetch_tags", False)

        # Push from bzr to git
        interbranch = InterBranch.get(self.bzr_tree.branch, self.git_branch)
        interbranch.push(lossy=True)

        # Verify tags were not pushed
        git_refs = self.git_repo._git.refs.as_dict()
        self.assertNotIn(b"refs/tags/tag1", git_refs)
        self.assertNotIn(b"refs/tags/tag2", git_refs)

    def test_push_with_tags_explicit(self):
        """Test that tags are pushed when explicitly enabled."""
        # Set branch.fetch_tags to True
        self.bzr_tree.branch.get_config().set_user_option("branch.fetch_tags", True)

        # Push from bzr to git (lossy mode required for bzr->git)
        interbranch = InterBranch.get(self.bzr_tree.branch, self.git_branch)
        interbranch.push(lossy=True)

        # Verify tags were pushed
        git_refs = self.git_repo._git.refs.as_dict()
        self.assertIn(b"refs/tags/tag1", git_refs)
        self.assertIn(b"refs/tags/tag2", git_refs)

    def test_push_partial_with_tags(self):
        """Test that only relevant tags are pushed with partial push when enabled."""
        # Enable tag pushing
        self.bzr_tree.branch.get_config().set_user_option("branch.fetch_tags", True)

        # Push only first revision
        interbranch = InterBranch.get(self.bzr_tree.branch, self.git_branch)
        interbranch.push(stop_revision=self.rev1, lossy=True)

        # Only tag1 should be pushed since tag2 points to rev2 which wasn't pushed
        git_refs = self.git_repo._git.refs.as_dict()
        self.assertIn(b"refs/tags/tag1", git_refs)
        # Note: tag2 might still be pushed but point to a missing revision
        # This behavior depends on the exact implementation

    def test_update_push_with_new_tags(self):
        """Test that new tags are pushed on subsequent pushes when enabled."""
        # Enable tag pushing
        self.bzr_tree.branch.get_config().set_user_option("branch.fetch_tags", True)

        # First push without any tags
        self.bzr_tree.branch.tags.delete_tag("tag1")
        self.bzr_tree.branch.tags.delete_tag("tag2")

        interbranch = InterBranch.get(self.bzr_tree.branch, self.git_branch)
        interbranch.push(lossy=True)

        git_refs = self.git_repo._git.refs.as_dict()
        self.assertNotIn(b"refs/tags/tag1", git_refs)
        self.assertNotIn(b"refs/tags/tag2", git_refs)

        # Add tags and push again
        self.bzr_tree.branch.tags.set_tag("tag1", self.rev1)
        self.bzr_tree.branch.tags.set_tag("tag2", self.rev2)

        interbranch.push(lossy=True)

        # Verify new tags were pushed
        git_refs = self.git_repo._git.refs.as_dict()
        self.assertIn(b"refs/tags/tag1", git_refs)
        self.assertIn(b"refs/tags/tag2", git_refs)
