# Copyright (C) 2006-2010 Canonical Ltd
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

from io import StringIO

from .. import config
from .. import status as _mod_status
from ..revisionspec import RevisionSpec
from ..status import show_pending_merges, show_tree_status
from . import TestCaseWithTransport


class TestStatus(TestCaseWithTransport):
    def test_pending_none(self):
        # Test whether show_pending_merges works in a tree with no commits
        tree = self.make_branch_and_tree("a")
        tree.commit("empty commit")
        tree2 = self.make_branch_and_tree("b")
        # set a left most parent that is not a present commit
        tree2.add_parent_tree_id(b"some-ghost", allow_leftmost_as_ghost=True)
        # do a merge
        tree2.merge_from_branch(tree.branch)
        output = StringIO()
        with tree2.lock_read():
            show_pending_merges(tree2, output)
        self.assertContainsRe(output.getvalue(), "empty commit")

    def make_multiple_pending_tree(self):
        config.GlobalStack().set("email", "Joe Foo <joe@foo.com>")
        tree = self.make_branch_and_tree("a")
        tree.commit("commit 1", timestamp=1196796819, timezone=0)
        tree2 = tree.controldir.clone("b").open_workingtree()
        tree.commit("commit 2", timestamp=1196796819, timezone=0)
        tree2.commit("commit 2b", timestamp=1196796819, timezone=0)
        tree3 = tree2.controldir.clone("c").open_workingtree()
        tree2.commit("commit 3b", timestamp=1196796819, timezone=0)
        tree3.commit("commit 3c", timestamp=1196796819, timezone=0)
        tree.merge_from_branch(tree2.branch)
        tree.merge_from_branch(tree3.branch, force=True)
        return tree

    def test_multiple_pending(self):
        tree = self.make_multiple_pending_tree()
        output = StringIO()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        show_pending_merges(tree, output)
        # 2b doesn't appear because it's an ancestor of 3b
        self.assertEqualDiff(
            "pending merge tips: (use -v to see all merge revisions)\n"
            "  Joe Foo 2007-12-04 commit 3b\n"
            "  Joe Foo 2007-12-04 commit 3c\n",
            output.getvalue(),
        )

    def test_multiple_pending_verbose(self):
        tree = self.make_multiple_pending_tree()
        output = StringIO()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        show_pending_merges(tree, output, verbose=True)
        # Even though 2b is in the ancestry of 3c, it should only be displayed
        # under the first merge parent.
        self.assertEqualDiff(
            "pending merges:\n"
            "  Joe Foo 2007-12-04 commit 3b\n"
            "    Joe Foo 2007-12-04 commit 2b\n"
            "  Joe Foo 2007-12-04 commit 3c\n",
            output.getvalue(),
        )

    def test_with_pending_ghost(self):
        """Test when a pending merge is itself a ghost."""
        tree = self.make_branch_and_tree("a")
        tree.commit("first")
        tree.add_parent_tree_id(b"a-ghost-revision")
        tree.lock_read()
        self.addCleanup(tree.unlock)
        output = StringIO()
        show_pending_merges(tree, output)
        self.assertEqualDiff(
            "pending merge tips: (use -v to see all merge revisions)\n"
            "  (ghost) a-ghost-revision\n",
            output.getvalue(),
        )

    def test_pending_with_ghosts(self):
        """Test when a pending merge's ancestry includes ghosts."""
        config.GlobalStack().set("email", "Joe Foo <joe@foo.com>")
        tree = self.make_branch_and_tree("a")
        tree.commit("empty commit")
        tree2 = tree.controldir.clone("b").open_workingtree()
        tree2.commit("a non-ghost", timestamp=1196796819, timezone=0)
        tree2.add_parent_tree_id(b"a-ghost-revision")
        tree2.commit("commit with ghost", timestamp=1196796819, timezone=0)
        tree2.commit("another non-ghost", timestamp=1196796819, timezone=0)
        tree.merge_from_branch(tree2.branch)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        output = StringIO()
        show_pending_merges(tree, output, verbose=True)
        self.assertEqualDiff(
            "pending merges:\n"
            "  Joe Foo 2007-12-04 another non-ghost\n"
            "    Joe Foo 2007-12-04 [merge] commit with ghost\n"
            "    (ghost) a-ghost-revision\n"
            "    Joe Foo 2007-12-04 a non-ghost\n",
            output.getvalue(),
        )

    def tests_revision_to_revision(self):
        """Doing a status between two revision trees should work."""
        tree = self.make_branch_and_tree(".")
        r1_id = tree.commit("one", allow_pointless=True)
        r2_id = tree.commit("two", allow_pointless=True)
        output = StringIO()
        show_tree_status(
            tree,
            to_file=output,
            revision=[
                RevisionSpec.from_string(f"revid:{r1_id.decode('utf-8')}"),
                RevisionSpec.from_string(f"revid:{r2_id.decode('utf-8')}"),
            ],
        )
        # return does not matter as long as it did not raise.


class TestHooks(TestCaseWithTransport):
    def test_constructor(self):
        """Check that creating a StatusHooks instance has the right defaults."""
        hooks = _mod_status.StatusHooks()
        self.assertIn("post_status", hooks, f"post_status not in {hooks}")
        self.assertIn("pre_status", hooks, f"pre_status not in {hooks}")

    def test_installed_hooks_are_StatusHooks(self):
        """The installed hooks object should be a StatusHooks."""
        # the installed hooks are saved in self._preserved_hooks.
        self.assertIsInstance(
            self._preserved_hooks[_mod_status][1], _mod_status.StatusHooks
        )

    def test_post_status_hook(self):
        """Ensure that post_status hook is invoked with the right args."""
        calls = []
        _mod_status.hooks.install_named_hook("post_status", calls.append, None)
        self.assertLength(0, calls)
        tree = self.make_branch_and_tree(".")
        r1_id = tree.commit("one", allow_pointless=True)
        r2_id = tree.commit("two", allow_pointless=True)
        output = StringIO()
        show_tree_status(
            tree,
            to_file=output,
            revision=[
                RevisionSpec.from_string(f"revid:{r1_id.decode('utf-8')}"),
                RevisionSpec.from_string(f"revid:{r2_id.decode('utf-8')}"),
            ],
        )
        self.assertLength(1, calls)
        params = calls[0]
        self.assertIsInstance(params, _mod_status.StatusHookParams)
        attrs = [
            "old_tree",
            "new_tree",
            "to_file",
            "versioned",
            "show_ids",
            "short",
            "verbose",
            "specific_files",
        ]
        for a in attrs:
            self.assertTrue(
                hasattr(params, a), f'Attribute "{a}" not found in StatusHookParam'
            )

    def test_pre_status_hook(self):
        """Ensure that pre_status hook is invoked with the right args."""
        calls = []
        _mod_status.hooks.install_named_hook("pre_status", calls.append, None)
        self.assertLength(0, calls)
        tree = self.make_branch_and_tree(".")
        r1_id = tree.commit("one", allow_pointless=True)
        r2_id = tree.commit("two", allow_pointless=True)
        output = StringIO()
        show_tree_status(
            tree,
            to_file=output,
            revision=[
                RevisionSpec.from_string(f"revid:{r1_id.decode('utf-8')}"),
                RevisionSpec.from_string(f"revid:{r2_id.decode('utf-8')}"),
            ],
        )
        self.assertLength(1, calls)
        params = calls[0]
        self.assertIsInstance(params, _mod_status.StatusHookParams)
        attrs = [
            "old_tree",
            "new_tree",
            "to_file",
            "versioned",
            "show_ids",
            "short",
            "verbose",
            "specific_files",
        ]
        for a in attrs:
            self.assertTrue(
                hasattr(params, a), f'Attribute "{a}" not found in StatusHookParam'
            )
