# Copyright (C) 2007-2011 Canonical Ltd
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

"""Tests for repository write groups."""

from breezy import controldir, errors, memorytree, tests
from breezy.bzr import branch as bzrbranch
from breezy.bzr import remote, versionedfile
from breezy.bzr.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
)

from ....tests.scenarios import load_tests_apply_scenarios

load_tests = load_tests_apply_scenarios


class TestGetMissingParentInventories(TestCaseWithRepository):
    scenarios = all_repository_vf_format_scenarios()

    def test_empty_get_missing_parent_inventories(self):
        """A new write group has no missing parent inventories."""
        repo = self.make_repository(".")
        repo.lock_write()
        repo.start_write_group()
        try:
            self.assertEqual(set(), set(repo.get_missing_parent_inventories()))
        finally:
            repo.commit_write_group()
            repo.unlock()

    def branch_trunk_and_make_tree(self, trunk_repo, relpath):
        tree = self.make_branch_and_memory_tree("branch")
        trunk_repo.lock_read()
        self.addCleanup(trunk_repo.unlock)
        tree.branch.repository.fetch(trunk_repo, revision_id=b"rev-1")
        tree.set_parent_ids([b"rev-1"])
        return tree

    def make_first_commit(self, repo):
        trunk = repo.controldir.create_branch()
        tree = memorytree.MemoryTree.create_on_branch(trunk)
        tree.lock_write()
        tree.add([""], ["directory"], [b"TREE_ROOT"])
        tree.add(["dir"], ["directory"], [b"dir-id"])
        tree.add(
            ["filename"],
            ["file"],
            [b"file-id"],
        )
        tree.put_file_bytes_non_atomic("filename", b"content\n")
        tree.commit("Trunk commit", rev_id=b"rev-0")
        tree.commit("Trunk commit", rev_id=b"rev-1")
        tree.unlock()

    def make_new_commit_in_new_repo(self, trunk_repo, parents=None):
        tree = self.branch_trunk_and_make_tree(trunk_repo, "branch")
        tree.set_parent_ids(parents)
        tree.commit("Branch commit", rev_id=b"rev-2")
        branch_repo = tree.branch.repository
        branch_repo.lock_read()
        self.addCleanup(branch_repo.unlock)
        return branch_repo

    def make_stackable_repo(self, relpath="trunk"):
        if isinstance(self.repository_format, remote.RemoteRepositoryFormat):
            # RemoteRepository by default builds a default format real
            # repository, but the default format is unstackble.  So explicitly
            # make a stackable real repository and use that.
            repo = self.make_repository(relpath, format="1.9")
            dir = controldir.ControlDir.open(self.get_url(relpath))
            repo = dir.open_repository()
        else:
            repo = self.make_repository(relpath)
        if not repo._format.supports_external_lookups:
            raise tests.TestNotApplicable("format not stackable")
        repo.controldir._format.set_branch_format(bzrbranch.BzrBranchFormat7())
        return repo

    def reopen_repo_and_resume_write_group(self, repo):
        try:
            resume_tokens = repo.suspend_write_group()
        except errors.UnsuspendableWriteGroup:
            # If we got this far, and this repo does not support resuming write
            # groups, then get_missing_parent_inventories works in all
            # cases this repo supports.
            repo.unlock()
            return
        repo.unlock()
        reopened_repo = repo.controldir.open_repository()
        reopened_repo.lock_write()
        self.addCleanup(reopened_repo.unlock)
        reopened_repo.resume_write_group(resume_tokens)
        return reopened_repo

    def test_ghost_revision(self):
        """A parent inventory may be absent if all the needed texts are present.
        i.e., a ghost revision isn't (necessarily) considered to be a missing
        parent inventory.
        """
        # Make a trunk with one commit.
        trunk_repo = self.make_stackable_repo()
        self.make_first_commit(trunk_repo)
        trunk_repo.lock_read()
        self.addCleanup(trunk_repo.unlock)
        # Branch the trunk, add a new commit.
        branch_repo = self.make_new_commit_in_new_repo(
            trunk_repo, parents=[b"rev-1", b"ghost-rev"]
        )
        inv = branch_repo.get_inventory(b"rev-2")
        # Make a new repo stacked on trunk, and then copy into it:
        #  - all texts in rev-2
        #  - the new inventory (rev-2)
        #  - the new revision (rev-2)
        repo = self.make_stackable_repo("stacked")
        repo.lock_write()
        repo.start_write_group()
        # Add all texts from in rev-2 inventory.  Note that this has to exclude
        # the root if the repo format does not support rich roots.
        rich_root = branch_repo._format.rich_root_data
        all_texts = [
            (ie.file_id, ie.revision)
            for (_n, ie) in inv.iter_entries()
            if rich_root or inv.id2path(ie.file_id) != ""
        ]
        repo.texts.insert_record_stream(
            branch_repo.texts.get_record_stream(all_texts, "unordered", False)
        )
        # Add inventory and revision for rev-2.
        repo.add_inventory(b"rev-2", inv, [b"rev-1", b"ghost-rev"])
        repo.revisions.insert_record_stream(
            branch_repo.revisions.get_record_stream([(b"rev-2",)], "unordered", False)
        )
        # Now, no inventories are reported as missing, even though there is a
        # ghost.
        self.assertEqual(set(), repo.get_missing_parent_inventories())
        # Resuming the write group does not affect
        # get_missing_parent_inventories.
        reopened_repo = self.reopen_repo_and_resume_write_group(repo)
        self.assertEqual(set(), reopened_repo.get_missing_parent_inventories())
        reopened_repo.abort_write_group()

    def test_get_missing_parent_inventories(self):
        """A stacked repo with a single revision and inventory (no parent
        inventory) in it must have all the texts in its inventory (even if not
        changed w.r.t. to the absent parent), otherwise it will report missing
        texts/parent inventory.

        The core of this test is that a file was changed in rev-1, but in a
        stacked repo that only has rev-2
        """
        # Make a trunk with one commit.
        trunk_repo = self.make_stackable_repo()
        self.make_first_commit(trunk_repo)
        trunk_repo.lock_read()
        self.addCleanup(trunk_repo.unlock)
        # Branch the trunk, add a new commit.
        branch_repo = self.make_new_commit_in_new_repo(trunk_repo, parents=[b"rev-1"])
        inv = branch_repo.get_inventory(b"rev-2")
        # Make a new repo stacked on trunk, and copy the new commit's revision
        # and inventory records to it.
        repo = self.make_stackable_repo("stacked")
        repo.lock_write()
        repo.start_write_group()
        # Insert a single fulltext inv (using add_inventory because it's
        # simpler than insert_record_stream)
        repo.add_inventory(b"rev-2", inv, [b"rev-1"])
        repo.revisions.insert_record_stream(
            branch_repo.revisions.get_record_stream([(b"rev-2",)], "unordered", False)
        )
        # There should be no missing compression parents
        self.assertEqual(set(), repo.inventories.get_missing_compression_parent_keys())
        self.assertEqual(
            {("inventories", b"rev-1")}, repo.get_missing_parent_inventories()
        )
        # Resuming the write group does not affect
        # get_missing_parent_inventories.
        reopened_repo = self.reopen_repo_and_resume_write_group(repo)
        self.assertEqual(
            {("inventories", b"rev-1")}, reopened_repo.get_missing_parent_inventories()
        )
        # Adding the parent inventory satisfies get_missing_parent_inventories.
        reopened_repo.inventories.insert_record_stream(
            branch_repo.inventories.get_record_stream([(b"rev-1",)], "unordered", False)
        )
        self.assertEqual(set(), reopened_repo.get_missing_parent_inventories())
        reopened_repo.abort_write_group()

    def test_get_missing_parent_inventories_check(self):
        builder = self.make_branch_builder("test")
        builder.build_snapshot(
            [b"ghost-parent-id"],
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("file", b"file-id", "file", b"content\n")),
            ],
            allow_leftmost_as_ghost=True,
            revision_id=b"A-id",
        )
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        repo = self.make_repository("test-repo")
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.abort_write_group)
        # Now, add the objects manually
        text_keys = [(b"file-id", b"A-id")]
        if repo.supports_rich_root():
            text_keys.append((b"root-id", b"A-id"))
        # Directly add the texts, inventory, and revision object for b'A-id'
        repo.texts.insert_record_stream(
            b.repository.texts.get_record_stream(text_keys, "unordered", True)
        )
        repo.add_revision(
            b"A-id",
            b.repository.get_revision(b"A-id"),
            b.repository.get_inventory(b"A-id"),
        )
        get_missing = repo.get_missing_parent_inventories
        if repo._format.supports_external_lookups:
            self.assertEqual(
                {("inventories", b"ghost-parent-id")},
                get_missing(check_for_missing_texts=False),
            )
            self.assertEqual(set(), get_missing(check_for_missing_texts=True))
            self.assertEqual(set(), get_missing())
        else:
            # If we don't support external lookups, we always return empty
            self.assertEqual(set(), get_missing(check_for_missing_texts=False))
            self.assertEqual(set(), get_missing(check_for_missing_texts=True))
            self.assertEqual(set(), get_missing())

    def test_insert_stream_passes_resume_info(self):
        repo = self.make_repository("test-repo")
        if not repo._format.supports_external_lookups or isinstance(
            repo, remote.RemoteRepository
        ):
            raise tests.TestNotApplicable(
                "only valid for direct connections to resumable repos"
            )
        # log calls to get_missing_parent_inventories, so that we can assert it
        # is called with the correct parameters
        call_log = []
        orig = repo.get_missing_parent_inventories

        def get_missing(check_for_missing_texts=True):
            call_log.append(check_for_missing_texts)
            return orig(check_for_missing_texts=check_for_missing_texts)

        repo.get_missing_parent_inventories = get_missing
        repo.lock_write()
        self.addCleanup(repo.unlock)
        sink = repo._get_sink()
        sink.insert_stream((), repo._format, [])
        self.assertEqual([False], call_log)
        del call_log[:]
        repo.start_write_group()
        # We need to insert something, or suspend_write_group won't actually
        # create a token
        repo.texts.insert_record_stream(
            [
                versionedfile.FulltextContentFactory(
                    (b"file-id", b"rev-id"), (), None, b"lines\n"
                )
            ]
        )
        tokens = repo.suspend_write_group()
        self.assertNotEqual([], tokens)
        sink.insert_stream((), repo._format, tokens)
        self.assertEqual([True], call_log)

    def test_insert_stream_without_locking_fails_without_lock(self):
        repo = self.make_repository("test-repo")
        sink = repo._get_sink()
        stream = [
            (
                "texts",
                [
                    versionedfile.FulltextContentFactory(
                        (b"file-id", b"rev-id"), (), None, b"lines\n"
                    )
                ],
            )
        ]
        self.assertRaises(
            errors.ObjectNotLocked,
            sink.insert_stream_without_locking,
            stream,
            repo._format,
        )

    def test_insert_stream_without_locking_fails_without_write_group(self):
        repo = self.make_repository("test-repo")
        self.addCleanup(repo.lock_write().unlock)
        sink = repo._get_sink()
        stream = [
            (
                "texts",
                [
                    versionedfile.FulltextContentFactory(
                        (b"file-id", b"rev-id"), (), None, b"lines\n"
                    )
                ],
            )
        ]
        self.assertRaises(
            errors.BzrError, sink.insert_stream_without_locking, stream, repo._format
        )

    def test_insert_stream_without_locking(self):
        repo = self.make_repository("test-repo")
        self.addCleanup(repo.lock_write().unlock)
        repo.start_write_group()
        sink = repo._get_sink()
        stream = [
            (
                "texts",
                [
                    versionedfile.FulltextContentFactory(
                        (b"file-id", b"rev-id"), (), None, b"lines\n"
                    )
                ],
            )
        ]
        missing_keys = sink.insert_stream_without_locking(stream, repo._format)
        repo.commit_write_group()
        self.assertEqual(set(), missing_keys)


class TestResumeableWriteGroup(TestCaseWithRepository):
    scenarios = all_repository_vf_format_scenarios()

    def make_write_locked_repo(self, relpath="repo"):
        repo = self.make_repository(relpath)
        repo.lock_write()
        self.addCleanup(repo.unlock)
        return repo

    def reopen_repo(self, repo):
        same_repo = repo.controldir.open_repository()
        same_repo.lock_write()
        self.addCleanup(same_repo.unlock)
        return same_repo

    def require_suspendable_write_groups(self, reason):
        repo = self.make_repository("__suspend_test")
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        try:
            repo.suspend_write_group()
        except errors.UnsuspendableWriteGroup as e:
            repo.abort_write_group()
            raise tests.TestNotApplicable(reason) from e

    def test_suspend_write_group(self):
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        repo.texts.add_lines((b"file-id", b"revid"), (), [b"lines"])
        try:
            wg_tokens = repo.suspend_write_group()
        except errors.UnsuspendableWriteGroup:
            # The contract for repos that don't support suspending write groups
            # is that suspend_write_group raises UnsuspendableWriteGroup, but
            # is otherwise a no-op.  So we can still e.g. abort the write group
            # as usual.
            self.assertTrue(repo.is_in_write_group())
            repo.abort_write_group()
        else:
            # After suspending a write group we are no longer in a write group
            self.assertFalse(repo.is_in_write_group())
            # suspend_write_group returns a list of tokens, which are strs.  If
            # no other write groups were resumed, there will only be one token.
            self.assertEqual(1, len(wg_tokens))
            self.assertIsInstance(wg_tokens[0], str)
            # See also test_pack_repository's test of the same name.

    def test_resume_write_group_then_abort(self):
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = (b"file-id", b"revid")
        repo.texts.add_lines(text_key, (), [b"lines"])
        try:
            wg_tokens = repo.suspend_write_group()
        except errors.UnsuspendableWriteGroup:
            # If the repo does not support suspending write groups, it doesn't
            # support resuming them either.
            repo.abort_write_group()
            self.assertRaises(
                errors.UnsuspendableWriteGroup, repo.resume_write_group, []
            )
        else:
            # self.assertEqual([], list(repo.texts.keys()))
            same_repo = self.reopen_repo(repo)
            same_repo.resume_write_group(wg_tokens)
            self.assertEqual([text_key], list(same_repo.texts.keys()))
            self.assertTrue(same_repo.is_in_write_group())
            same_repo.abort_write_group()
            self.assertEqual([], list(repo.texts.keys()))
            # See also test_pack_repository's test of the same name.

    def test_multiple_resume_write_group(self):
        self.require_suspendable_write_groups(
            "Cannot test resume on repo that does not support suspending"
        )
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        first_key = (b"file-id", b"revid")
        repo.texts.add_lines(first_key, (), [b"lines"])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        self.assertTrue(same_repo.is_in_write_group())
        second_key = (b"file-id", b"second-revid")
        same_repo.texts.add_lines(second_key, (first_key,), [b"more lines"])
        try:
            new_wg_tokens = same_repo.suspend_write_group()
        except:
            same_repo.abort_write_group(suppress_errors=True)
            raise
        self.assertEqual(2, len(new_wg_tokens))
        self.assertSubset(wg_tokens, new_wg_tokens)
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(new_wg_tokens)
        both_keys = {first_key, second_key}
        self.assertEqual(both_keys, same_repo.texts.keys())
        same_repo.abort_write_group()

    def test_no_op_suspend_resume(self):
        self.require_suspendable_write_groups(
            "Cannot test resume on repo that does not support suspending"
        )
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = (b"file-id", b"revid")
        repo.texts.add_lines(text_key, (), [b"lines"])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        new_wg_tokens = same_repo.suspend_write_group()
        self.assertEqual(wg_tokens, new_wg_tokens)
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        self.assertEqual([text_key], list(same_repo.texts.keys()))
        same_repo.abort_write_group()

    def test_read_after_suspend_fails(self):
        self.require_suspendable_write_groups(
            "Cannot test suspend on repo that does not support suspending"
        )
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = (b"file-id", b"revid")
        repo.texts.add_lines(text_key, (), [b"lines"])
        repo.suspend_write_group()
        self.assertEqual([], list(repo.texts.keys()))

    def test_read_after_second_suspend_fails(self):
        self.require_suspendable_write_groups(
            "Cannot test suspend on repo that does not support suspending"
        )
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = (b"file-id", b"revid")
        repo.texts.add_lines(text_key, (), [b"lines"])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.suspend_write_group()
        self.assertEqual([], list(same_repo.texts.keys()))

    def test_read_after_resume_abort_fails(self):
        self.require_suspendable_write_groups(
            "Cannot test suspend on repo that does not support suspending"
        )
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = (b"file-id", b"revid")
        repo.texts.add_lines(text_key, (), [b"lines"])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.abort_write_group()
        self.assertEqual([], list(same_repo.texts.keys()))

    def test_cannot_resume_aborted_write_group(self):
        self.require_suspendable_write_groups(
            "Cannot test resume on repo that does not support suspending"
        )
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = (b"file-id", b"revid")
        repo.texts.add_lines(text_key, (), [b"lines"])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.abort_write_group()
        same_repo = self.reopen_repo(repo)
        self.assertRaises(
            errors.UnresumableWriteGroup, same_repo.resume_write_group, wg_tokens
        )

    def test_commit_resumed_write_group_no_new_data(self):
        self.require_suspendable_write_groups(
            "Cannot test resume on repo that does not support suspending"
        )
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = (b"file-id", b"revid")
        repo.texts.add_lines(text_key, (), [b"lines"])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.commit_write_group()
        self.assertEqual([text_key], list(same_repo.texts.keys()))
        self.assertEqual(
            b"lines",
            next(
                same_repo.texts.get_record_stream([text_key], "unordered", True)
            ).get_bytes_as("fulltext"),
        )
        self.assertRaises(
            errors.UnresumableWriteGroup, same_repo.resume_write_group, wg_tokens
        )

    def test_commit_resumed_write_group_plus_new_data(self):
        self.require_suspendable_write_groups(
            "Cannot test resume on repo that does not support suspending"
        )
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        first_key = (b"file-id", b"revid")
        repo.texts.add_lines(first_key, (), [b"lines"])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        second_key = (b"file-id", b"second-revid")
        same_repo.texts.add_lines(second_key, (first_key,), [b"more lines"])
        same_repo.commit_write_group()
        self.assertEqual({first_key, second_key}, set(same_repo.texts.keys()))
        self.assertEqual(
            b"lines",
            next(
                same_repo.texts.get_record_stream([first_key], "unordered", True)
            ).get_bytes_as("fulltext"),
        )
        self.assertEqual(
            b"more lines",
            next(
                same_repo.texts.get_record_stream([second_key], "unordered", True)
            ).get_bytes_as("fulltext"),
        )

    def make_source_with_delta_record(self):
        # Make a source repository with a delta record in it.
        source_repo = self.make_write_locked_repo("source")
        source_repo.start_write_group()
        key_base = (b"file-id", b"base")
        key_delta = (b"file-id", b"delta")

        def text_stream():
            yield versionedfile.FulltextContentFactory(key_base, (), None, b"lines\n")
            yield versionedfile.FulltextContentFactory(
                key_delta, (key_base,), None, b"more\nlines\n"
            )

        source_repo.texts.insert_record_stream(text_stream())
        source_repo.commit_write_group()
        return source_repo

    def test_commit_resumed_write_group_with_missing_parents(self):
        self.require_suspendable_write_groups(
            "Cannot test resume on repo that does not support suspending"
        )
        source_repo = self.make_source_with_delta_record()
        key_delta = (b"file-id", b"delta")
        # Start a write group, insert just a delta.
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        stream = source_repo.texts.get_record_stream([key_delta], "unordered", False)
        repo.texts.insert_record_stream(stream)
        # It's either not commitable due to the missing compression parent, or
        # the stacked location has already filled in the fulltext.
        try:
            repo.commit_write_group()
        except errors.BzrCheckError:
            # It refused to commit because we have a missing parent
            pass
        else:
            same_repo = self.reopen_repo(repo)
            same_repo.lock_read()
            record = next(
                same_repo.texts.get_record_stream([key_delta], "unordered", True)
            )
            self.assertEqual(b"more\nlines\n", record.get_bytes_as("fulltext"))
            return
        # Merely suspending and resuming doesn't make it commitable either.
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        self.assertRaises(errors.BzrCheckError, same_repo.commit_write_group)
        same_repo.abort_write_group()

    def test_commit_resumed_write_group_adding_missing_parents(self):
        self.require_suspendable_write_groups(
            "Cannot test resume on repo that does not support suspending"
        )
        source_repo = self.make_source_with_delta_record()
        key_delta = (b"file-id", b"delta")
        # Start a write group.
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = (b"file-id", b"revid")
        repo.texts.add_lines(text_key, (), [b"lines"])
        # Suspend it, then resume it.
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        # Add a record with a missing compression parent
        stream = source_repo.texts.get_record_stream([key_delta], "unordered", False)
        same_repo.texts.insert_record_stream(stream)
        # Just like if we'd added that record without a suspend/resume cycle,
        # commit_write_group fails.
        try:
            same_repo.commit_write_group()
        except errors.BzrCheckError:
            pass
        else:
            # If the commit_write_group didn't fail, that is because the
            # insert_record_stream already gave it a fulltext.
            same_repo = self.reopen_repo(repo)
            same_repo.lock_read()
            record = next(
                same_repo.texts.get_record_stream([key_delta], "unordered", True)
            )
            self.assertEqual(b"more\nlines\n", record.get_bytes_as("fulltext"))
            return
        same_repo.abort_write_group()

    def test_add_missing_parent_after_resume(self):
        self.require_suspendable_write_groups(
            "Cannot test resume on repo that does not support suspending"
        )
        source_repo = self.make_source_with_delta_record()
        key_base = (b"file-id", b"base")
        key_delta = (b"file-id", b"delta")
        # Start a write group, insert just a delta.
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        stream = source_repo.texts.get_record_stream([key_delta], "unordered", False)
        repo.texts.insert_record_stream(stream)
        # Suspend it, then resume it.
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        # Fill in the missing compression parent.
        stream = source_repo.texts.get_record_stream([key_base], "unordered", False)
        same_repo.texts.insert_record_stream(stream)
        same_repo.commit_write_group()

    def test_suspend_empty_initial_write_group(self):
        """Suspending a write group with no writes returns an empty token
        list.
        """
        self.require_suspendable_write_groups(
            "Cannot test suspend on repo that does not support suspending"
        )
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        wg_tokens = repo.suspend_write_group()
        self.assertEqual([], wg_tokens)

    def test_resume_empty_initial_write_group(self):
        """Resuming an empty token list is equivalent to start_write_group."""
        self.require_suspendable_write_groups(
            "Cannot test resume on repo that does not support suspending"
        )
        repo = self.make_write_locked_repo()
        repo.resume_write_group([])
        repo.abort_write_group()
