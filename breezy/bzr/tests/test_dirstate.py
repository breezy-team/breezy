# Copyright (C) 2006-2011 Canonical Ltd
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

"""Tests of the dirstate functionality being built for WorkingTreeFormat4."""

import os
import tempfile

from ... import controldir, errors, memorytree, osutils, tests
from ... import revision as _mod_revision
from ...tests import features, test_osutils
from ...tests.scenarios import load_tests_apply_scenarios
from .. import dirstate, inventory, inventorytree, workingtree_4

# TODO:
# TESTS to write:
# general checks for NOT_IN_MEMORY error conditions.
# set_path_id on a NOT_IN_MEMORY dirstate
# set_path_id  unicode support
# set_path_id  setting id of a path not root
# set_path_id  setting id when there are parents without the id in the parents
# set_path_id  setting id when there are parents with the id in the parents
# set_path_id  setting id when state is not in memory
# set_path_id  setting id when state is in memory unmodified
# set_path_id  setting id when state is in memory modified


class TestErrors(tests.TestCase):
    def test_dirstate_corrupt(self):
        error = dirstate.DirstateCorrupt(
            ".bzr/checkout/dirstate", 'trailing garbage: "x"'
        )
        self.assertEqualDiff(
            "The dirstate file (.bzr/checkout/dirstate)"
            ' appears to be corrupt: trailing garbage: "x"',
            str(error),
        )


load_tests = load_tests_apply_scenarios


class TestCaseWithDirState(tests.TestCaseWithTransport):
    """Helper functions for creating DirState objects with various content."""

    scenarios = test_osutils.dir_reader_scenarios()

    # Set by load_tests
    _dir_reader_class = None
    _native_to_unicode = None  # Not used yet

    def setUp(self):
        super().setUp()
        self.overrideAttr(osutils, "_selected_dir_reader", self._dir_reader_class())

    def create_empty_dirstate(self):
        """Return a locked but empty dirstate."""
        state = dirstate.DirState.initialize("dirstate")
        return state

    def create_dirstate_with_root(self):
        """Return a write-locked state with a single root entry."""
        packed_stat = b"AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk"
        root_entry_direntry = (
            (b"", b"", b"a-root-value"),
            [
                (b"d", b"", 0, False, packed_stat),
            ],
        )
        dirblocks = []
        dirblocks.append((b"", [root_entry_direntry]))
        dirblocks.append((b"", []))
        state = self.create_empty_dirstate()
        try:
            state._set_data([], dirblocks)
            state._validate()
        except:
            state.unlock()
            raise
        return state

    def create_dirstate_with_root_and_subdir(self):
        """Return a locked DirState with a root and a subdir."""
        packed_stat = b"AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk"
        subdir_entry = (
            (b"", b"subdir", b"subdir-id"),
            [
                (b"d", b"", 0, False, packed_stat),
            ],
        )
        state = self.create_dirstate_with_root()
        try:
            dirblocks = list(state._dirblocks)
            dirblocks[1][1].append(subdir_entry)
            state._set_data([], dirblocks)
        except:
            state.unlock()
            raise
        return state

    def create_complex_dirstate(self):
        r"""This dirstate contains multiple files and directories.

         /        a-root-value
         a/       a-dir
         b/       b-dir
         c        c-file
         d        d-file
         a/e/     e-dir
         a/f      f-file
         b/g      g-file
         b/h\xc3\xa5  h-\xc3\xa5-file  #This is u'\xe5' encoded into utf-8

        Notice that a/e is an empty directory.

        :return: The dirstate, still write-locked.
        """
        packed_stat = b"AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk"
        null_sha = b"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        root_entry = (
            (b"", b"", b"a-root-value"),
            [
                (b"d", b"", 0, False, packed_stat),
            ],
        )
        a_entry = (
            (b"", b"a", b"a-dir"),
            [
                (b"d", b"", 0, False, packed_stat),
            ],
        )
        b_entry = (
            (b"", b"b", b"b-dir"),
            [
                (b"d", b"", 0, False, packed_stat),
            ],
        )
        c_entry = (
            (b"", b"c", b"c-file"),
            [
                (b"f", null_sha, 10, False, packed_stat),
            ],
        )
        d_entry = (
            (b"", b"d", b"d-file"),
            [
                (b"f", null_sha, 20, False, packed_stat),
            ],
        )
        e_entry = (
            (b"a", b"e", b"e-dir"),
            [
                (b"d", b"", 0, False, packed_stat),
            ],
        )
        f_entry = (
            (b"a", b"f", b"f-file"),
            [
                (b"f", null_sha, 30, False, packed_stat),
            ],
        )
        g_entry = (
            (b"b", b"g", b"g-file"),
            [
                (b"f", null_sha, 30, False, packed_stat),
            ],
        )
        h_entry = (
            (b"b", b"h\xc3\xa5", b"h-\xc3\xa5-file"),
            [
                (b"f", null_sha, 40, False, packed_stat),
            ],
        )
        dirblocks = []
        dirblocks.append((b"", [root_entry]))
        dirblocks.append((b"", [a_entry, b_entry, c_entry, d_entry]))
        dirblocks.append((b"a", [e_entry, f_entry]))
        dirblocks.append((b"b", [g_entry, h_entry]))
        state = dirstate.DirState.initialize("dirstate")
        state._validate()
        try:
            state._set_data([], dirblocks)
        except:
            state.unlock()
            raise
        return state

    def check_state_with_reopen(self, expected_result, state):
        """Check that state has current state expected_result.

        This will check the current state, open the file anew and check it
        again.
        This function expects the current state to be locked for writing, and
        will unlock it before re-opening.
        This is required because we can't open a lock_read() while something
        else has a lock_write().
            write => mutually exclusive lock
            read => shared lock
        """
        # The state should already be write locked, since we just had to do
        # some operation to get here.
        self.assertTrue(state._lock_token is not None)
        try:
            self.assertEqual(expected_result[0], state.get_parent_ids())
            # there should be no ghosts in this tree.
            self.assertEqual([], state.get_ghosts())
            # there should be one fileid in this tree - the root of the tree.
            self.assertEqual(expected_result[1], list(state._iter_entries()))
            state.save()
        finally:
            state.unlock()
        del state
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        try:
            self.assertEqual(expected_result[1], list(state._iter_entries()))
        finally:
            state.unlock()

    def create_basic_dirstate(self):
        """Create a dirstate with a few files and directories.

        a
        b/
          c
          d/
            e
        b-c
        f
        """
        tree = self.make_branch_and_tree("tree")
        paths = ["a", "b/", "b/c", "b/d/", "b/d/e", "b-c", "f"]
        file_ids = [b"a-id", b"b-id", b"c-id", b"d-id", b"e-id", b"b-c-id", b"f-id"]
        self.build_tree(["tree/" + p for p in paths])
        tree.set_root_id(b"TREE_ROOT")
        tree.add([p.rstrip("/") for p in paths], ids=file_ids)
        tree.commit("initial", rev_id=b"rev-1")
        revision_id = b"rev-1"
        # a_packed_stat = dirstate.pack_stat(os.stat('tree/a'))
        t = self.get_transport("tree")
        a_text = t.get_bytes("a")
        a_sha = osutils.sha_string(a_text)
        a_len = len(a_text)
        # b_packed_stat = dirstate.pack_stat(os.stat('tree/b'))
        # c_packed_stat = dirstate.pack_stat(os.stat('tree/b/c'))
        c_text = t.get_bytes("b/c")
        c_sha = osutils.sha_string(c_text)
        c_len = len(c_text)
        # d_packed_stat = dirstate.pack_stat(os.stat('tree/b/d'))
        # e_packed_stat = dirstate.pack_stat(os.stat('tree/b/d/e'))
        e_text = t.get_bytes("b/d/e")
        e_sha = osutils.sha_string(e_text)
        e_len = len(e_text)
        b_c_text = t.get_bytes("b-c")
        b_c_sha = osutils.sha_string(b_c_text)
        b_c_len = len(b_c_text)
        # f_packed_stat = dirstate.pack_stat(os.stat('tree/f'))
        f_text = t.get_bytes("f")
        f_sha = osutils.sha_string(f_text)
        f_len = len(f_text)
        null_stat = dirstate.DirState.NULLSTAT
        expected = {
            b"": (
                (b"", b"", b"TREE_ROOT"),
                [
                    (b"d", b"", 0, False, null_stat),
                    (b"d", b"", 0, False, revision_id),
                ],
            ),
            b"a": (
                (b"", b"a", b"a-id"),
                [
                    (b"f", b"", 0, False, null_stat),
                    (b"f", a_sha, a_len, False, revision_id),
                ],
            ),
            b"b": (
                (b"", b"b", b"b-id"),
                [
                    (b"d", b"", 0, False, null_stat),
                    (b"d", b"", 0, False, revision_id),
                ],
            ),
            b"b/c": (
                (b"b", b"c", b"c-id"),
                [
                    (b"f", b"", 0, False, null_stat),
                    (b"f", c_sha, c_len, False, revision_id),
                ],
            ),
            b"b/d": (
                (b"b", b"d", b"d-id"),
                [
                    (b"d", b"", 0, False, null_stat),
                    (b"d", b"", 0, False, revision_id),
                ],
            ),
            b"b/d/e": (
                (b"b/d", b"e", b"e-id"),
                [
                    (b"f", b"", 0, False, null_stat),
                    (b"f", e_sha, e_len, False, revision_id),
                ],
            ),
            b"b-c": (
                (b"", b"b-c", b"b-c-id"),
                [
                    (b"f", b"", 0, False, null_stat),
                    (b"f", b_c_sha, b_c_len, False, revision_id),
                ],
            ),
            b"f": (
                (b"", b"f", b"f-id"),
                [
                    (b"f", b"", 0, False, null_stat),
                    (b"f", f_sha, f_len, False, revision_id),
                ],
            ),
        }
        state = dirstate.DirState.from_tree(tree, "dirstate")
        try:
            state.save()
        finally:
            state.unlock()
        # Use a different object, to make sure nothing is pre-cached in memory.
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        self.addCleanup(state.unlock)
        self.assertEqual(dirstate.DirState.NOT_IN_MEMORY, state._dirblock_state)
        # This is code is only really tested if we actually have to make more
        # than one read, so set the page size to something smaller.
        # We want it to contain about 2.2 records, so that we have a couple
        # records that we can read per attempt
        state._bisect_page_size = 200
        return tree, state, expected

    def create_duplicated_dirstate(self):
        """Create a dirstate with a deleted and added entries.

        This grabs a basic_dirstate, and then removes and re adds every entry
        with a new file id.
        """
        tree, state, expected = self.create_basic_dirstate()
        # Now we will just remove and add every file so we get an extra entry
        # per entry. Unversion in reverse order so we handle subdirs
        tree.unversion(["f", "b-c", "b/d/e", "b/d", "b/c", "b", "a"])
        tree.add(
            ["a", "b", "b/c", "b/d", "b/d/e", "b-c", "f"],
            ids=[
                b"a-id2",
                b"b-id2",
                b"c-id2",
                b"d-id2",
                b"e-id2",
                b"b-c-id2",
                b"f-id2",
            ],
        )

        # Update the expected dictionary.
        for path in [b"a", b"b", b"b/c", b"b/d", b"b/d/e", b"b-c", b"f"]:
            orig = expected[path]
            path2 = path + b"2"
            # This record was deleted in the current tree
            expected[path] = (
                orig[0],
                [dirstate.DirState.NULL_PARENT_DETAILS, orig[1][1]],
            )
            new_key = (orig[0][0], orig[0][1], orig[0][2] + b"2")
            # And didn't exist in the basis tree
            expected[path2] = (
                new_key,
                [orig[1][0], dirstate.DirState.NULL_PARENT_DETAILS],
            )

        # We will replace the 'dirstate' file underneath 'state', but that is
        # okay as lock as we unlock 'state' first.
        state.unlock()
        try:
            new_state = dirstate.DirState.from_tree(tree, "dirstate")
            try:
                new_state.save()
            finally:
                new_state.unlock()
        finally:
            # But we need to leave state in a read-lock because we already have
            # a cleanup scheduled
            state.lock_read()
        return tree, state, expected

    def create_renamed_dirstate(self):
        """Create a dirstate with a few internal renames.

        This takes the basic dirstate, and moves the paths around.
        """
        tree, state, expected = self.create_basic_dirstate()
        # Rename a file
        tree.rename_one("a", "b/g")
        # And a directory
        tree.rename_one("b/d", "h")

        old_a = expected[b"a"]
        expected[b"a"] = (old_a[0], [(b"r", b"b/g", 0, False, b""), old_a[1][1]])
        expected[b"b/g"] = (
            (b"b", b"g", b"a-id"),
            [old_a[1][0], (b"r", b"a", 0, False, b"")],
        )
        old_d = expected[b"b/d"]
        expected[b"b/d"] = (old_d[0], [(b"r", b"h", 0, False, b""), old_d[1][1]])
        expected[b"h"] = (
            (b"", b"h", b"d-id"),
            [old_d[1][0], (b"r", b"b/d", 0, False, b"")],
        )

        old_e = expected[b"b/d/e"]
        expected[b"b/d/e"] = (old_e[0], [(b"r", b"h/e", 0, False, b""), old_e[1][1]])
        expected[b"h/e"] = (
            (b"h", b"e", b"e-id"),
            [old_e[1][0], (b"r", b"b/d/e", 0, False, b"")],
        )

        state.unlock()
        try:
            new_state = dirstate.DirState.from_tree(tree, "dirstate")
            try:
                new_state.save()
            finally:
                new_state.unlock()
        finally:
            state.lock_read()
        return tree, state, expected


class TestTreeToDirState(TestCaseWithDirState):
    def test_empty_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are no files on disk and no parents
        tree = self.make_branch_and_tree("tree")
        expected_result = (
            [],
            [
                (
                    (b"", b"", tree.path2id("")),  # common details
                    [
                        (
                            b"d",
                            b"",
                            0,
                            False,
                            dirstate.DirState.NULLSTAT,
                        ),  # current tree
                    ],
                )
            ],
        )
        state = dirstate.DirState.from_tree(tree, "dirstate")
        state._validate()
        self.check_state_with_reopen(expected_result, state)

    def test_1_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree("tree")
        rev_id = tree.commit("first post")
        dirstate.pack_stat(os.stat(tree.basedir))
        expected_result = (
            [rev_id],
            [
                (
                    (b"", b"", tree.path2id("")),  # common details
                    [
                        (
                            b"d",
                            b"",
                            0,
                            False,
                            dirstate.DirState.NULLSTAT,
                        ),  # current tree
                        (b"d", b"", 0, False, rev_id),  # first parent details
                    ],
                )
            ],
        )
        state = dirstate.DirState.from_tree(tree, "dirstate")
        self.check_state_with_reopen(expected_result, state)
        state.lock_read()
        try:
            state._validate()
        finally:
            state.unlock()

    def test_2_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree("tree")
        rev_id = tree.commit("first post")
        tree2 = tree.controldir.sprout("tree2").open_workingtree()
        rev_id2 = tree2.commit("second post", allow_pointless=True)
        tree.merge_from_branch(tree2.branch)
        expected_result = (
            [rev_id, rev_id2],
            [
                (
                    (b"", b"", tree.path2id("")),  # common details
                    [
                        (
                            b"d",
                            b"",
                            0,
                            False,
                            dirstate.DirState.NULLSTAT,
                        ),  # current tree
                        (b"d", b"", 0, False, rev_id),  # first parent details
                        (b"d", b"", 0, False, rev_id),  # second parent details
                    ],
                )
            ],
        )
        state = dirstate.DirState.from_tree(tree, "dirstate")
        self.check_state_with_reopen(expected_result, state)
        state.lock_read()
        try:
            state._validate()
        finally:
            state.unlock()

    def test_empty_unknowns_are_ignored_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are no files on disk and no parents
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/unknown"])
        expected_result = (
            [],
            [
                (
                    (b"", b"", tree.path2id("")),  # common details
                    [
                        (
                            b"d",
                            b"",
                            0,
                            False,
                            dirstate.DirState.NULLSTAT,
                        ),  # current tree
                    ],
                )
            ],
        )
        state = dirstate.DirState.from_tree(tree, "dirstate")
        self.check_state_with_reopen(expected_result, state)

    def get_tree_with_a_file(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a file"])
        tree.add("a file", ids=b"a-file-id")
        return tree

    def test_non_empty_no_parents_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are files on disk and no parents
        tree = self.get_tree_with_a_file()
        expected_result = (
            [],
            [
                (
                    (b"", b"", tree.path2id("")),  # common details
                    [
                        (
                            b"d",
                            b"",
                            0,
                            False,
                            dirstate.DirState.NULLSTAT,
                        ),  # current tree
                    ],
                ),
                (
                    (b"", b"a file", b"a-file-id"),  # common
                    [
                        (b"f", b"", 0, False, dirstate.DirState.NULLSTAT),  # current
                    ],
                ),
            ],
        )
        state = dirstate.DirState.from_tree(tree, "dirstate")
        self.check_state_with_reopen(expected_result, state)

    def test_1_parents_not_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.get_tree_with_a_file()
        rev_id = tree.commit("first post")
        # change the current content to be different this will alter stat, sha
        # and length:
        self.build_tree_contents([("tree/a file", b"new content\n")])
        expected_result = (
            [rev_id],
            [
                (
                    (b"", b"", tree.path2id("")),  # common details
                    [
                        (
                            b"d",
                            b"",
                            0,
                            False,
                            dirstate.DirState.NULLSTAT,
                        ),  # current tree
                        (b"d", b"", 0, False, rev_id),  # first parent details
                    ],
                ),
                (
                    (b"", b"a file", b"a-file-id"),  # common
                    [
                        (b"f", b"", 0, False, dirstate.DirState.NULLSTAT),  # current
                        (
                            b"f",
                            b"c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8",
                            24,
                            False,
                            rev_id,
                        ),  # first parent
                    ],
                ),
            ],
        )
        state = dirstate.DirState.from_tree(tree, "dirstate")
        self.check_state_with_reopen(expected_result, state)

    def test_2_parents_not_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.get_tree_with_a_file()
        rev_id = tree.commit("first post")
        tree2 = tree.controldir.sprout("tree2").open_workingtree()
        # change the current content to be different this will alter stat, sha
        # and length:
        self.build_tree_contents([("tree2/a file", b"merge content\n")])
        rev_id2 = tree2.commit("second post")
        tree.merge_from_branch(tree2.branch)
        # change the current content to be different this will alter stat, sha
        # and length again, giving us three distinct values:
        self.build_tree_contents([("tree/a file", b"new content\n")])
        expected_result = (
            [rev_id, rev_id2],
            [
                (
                    (b"", b"", tree.path2id("")),  # common details
                    [
                        (
                            b"d",
                            b"",
                            0,
                            False,
                            dirstate.DirState.NULLSTAT,
                        ),  # current tree
                        (b"d", b"", 0, False, rev_id),  # first parent details
                        (b"d", b"", 0, False, rev_id),  # second parent details
                    ],
                ),
                (
                    (b"", b"a file", b"a-file-id"),  # common
                    [
                        (b"f", b"", 0, False, dirstate.DirState.NULLSTAT),  # current
                        (
                            b"f",
                            b"c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8",
                            24,
                            False,
                            rev_id,
                        ),  # first parent
                        (
                            b"f",
                            b"314d796174c9412647c3ce07dfb5d36a94e72958",
                            14,
                            False,
                            rev_id2,
                        ),  # second parent
                    ],
                ),
            ],
        )
        state = dirstate.DirState.from_tree(tree, "dirstate")
        self.check_state_with_reopen(expected_result, state)

    def test_colliding_fileids(self):
        # test insertion of parents creating several entries at the same path.
        # we used to have a bug where they could cause the dirstate to break
        # its ordering invariants.
        # create some trees to test from
        parents = []
        for i in range(7):
            tree = self.make_branch_and_tree(f"tree{i}")
            self.build_tree(
                [
                    f"tree{i}/name",
                ]
            )
            tree.add(["name"], ids=[b"file-id%d" % i])
            revision_id = b"revid-%d" % i
            tree.commit("message", rev_id=revision_id)
            parents.append(
                (revision_id, tree.branch.repository.revision_tree(revision_id))
            )
        # now fold these trees into a dirstate
        state = dirstate.DirState.initialize("dirstate")
        try:
            state.set_parent_trees(parents, [])
            state._validate()
        finally:
            state.unlock()


class TestDirStateOnFile(TestCaseWithDirState):
    def create_updated_dirstate(self):
        self.build_tree(["a-file"])
        tree = self.make_branch_and_tree(".")
        tree.add(["a-file"], ids=[b"a-id"])
        tree.commit("add a-file")
        # Save and unlock the state, re-open it in readonly mode
        state = dirstate.DirState.from_tree(tree, "dirstate")
        state.save()
        state.unlock()
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        return state

    def test_construct_with_path(self):
        tree = self.make_branch_and_tree("tree")
        state = dirstate.DirState.from_tree(tree, "dirstate.from_tree")
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        state.unlock()
        self.build_tree_contents([("dirstate", b"".join(lines))])
        # get a state object
        # no parents, default tree content
        expected_result = (
            [],
            [
                (
                    (b"", b"", tree.path2id("")),  # common details
                    # current tree details, but new from_tree skips statting, it
                    # uses set_state_from_inventory, and thus depends on the
                    # inventory state.
                    [
                        (b"d", b"", 0, False, dirstate.DirState.NULLSTAT),
                    ],
                )
            ],
        )
        state = dirstate.DirState.on_file("dirstate")
        state.lock_write()  # check_state_with_reopen will save() and unlock it
        self.check_state_with_reopen(expected_result, state)

    def test_can_save_clean_on_file(self):
        tree = self.make_branch_and_tree("tree")
        state = dirstate.DirState.from_tree(tree, "dirstate")
        try:
            # doing a save should work here as there have been no changes.
            state.save()
            # TODO: stat it and check it hasn't changed; may require waiting
            # for the state accuracy window.
        finally:
            state.unlock()

    def test_can_save_in_read_lock(self):
        state = self.create_updated_dirstate()
        try:
            entry = state._get_entry(0, path_utf8=b"a-file")
            # The current size should be 0 (default)
            self.assertEqual(0, entry[1][0][2])
            # We should have a real entry.
            self.assertNotEqual((None, None), entry)
            # Set the cutoff-time into the future, so things look cacheable
            state._sha_cutoff_time()
            state._cutoff_time += 10.0
            st = os.lstat("a-file")
            sha1sum = dirstate.update_entry(state, entry, "a-file", st)
            # We updated the current sha1sum because the file is cacheable
            self.assertEqual(b"ecc5374e9ed82ad3ea3b4d452ea995a5fd3e70e3", sha1sum)

            # The dirblock has been updated
            self.assertEqual(st.st_size, entry[1][0][2])
            self.assertEqual(
                dirstate.DirState.IN_MEMORY_HASH_MODIFIED, state._dirblock_state
            )

            del entry
            # Now, since we are the only one holding a lock, we should be able
            # to save and have it written to disk
            state.save()
        finally:
            state.unlock()

        # Re-open the file, and ensure that the state has been updated.
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        try:
            entry = state._get_entry(0, path_utf8=b"a-file")
            self.assertEqual(st.st_size, entry[1][0][2])
        finally:
            state.unlock()

    def test_save_fails_quietly_if_locked(self):
        """If dirstate is locked, save will fail without complaining."""
        state = self.create_updated_dirstate()
        try:
            entry = state._get_entry(0, path_utf8=b"a-file")
            # No cached sha1 yet.
            self.assertEqual(b"", entry[1][0][1])
            # Set the cutoff-time into the future, so things look cacheable
            state._sha_cutoff_time()
            state._cutoff_time += 10.0
            st = os.lstat("a-file")
            sha1sum = dirstate.update_entry(state, entry, "a-file", st)
            self.assertEqual(b"ecc5374e9ed82ad3ea3b4d452ea995a5fd3e70e3", sha1sum)
            self.assertEqual(
                dirstate.DirState.IN_MEMORY_HASH_MODIFIED, state._dirblock_state
            )

            # Now, before we try to save, grab another dirstate, and take out a
            # read lock.
            # TODO: jam 20070315 Ideally this would be locked by another
            #       process. To make sure the file is really OS locked.
            state2 = dirstate.DirState.on_file("dirstate")
            state2.lock_read()
            try:
                # This won't actually write anything, because it couldn't grab
                # a write lock. But it shouldn't raise an error, either.
                # TODO: jam 20070315 We should probably distinguish between
                #       being dirty because of 'update_entry'. And dirty
                #       because of real modification. So that save() *does*
                #       raise a real error if it fails when we have real
                #       modifications.
                state.save()
            finally:
                state2.unlock()
        finally:
            state.unlock()

        # The file on disk should not be modified.
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        try:
            entry = state._get_entry(0, path_utf8=b"a-file")
            self.assertEqual(b"", entry[1][0][1])
        finally:
            state.unlock()

    def test_save_refuses_if_changes_aborted(self):
        self.build_tree(["a-file", "a-dir/"])
        state = dirstate.DirState.initialize("dirstate")
        try:
            # No stat and no sha1 sum.
            state.add("a-file", b"a-file-id", "file", None, b"")
            state.save()
        finally:
            state.unlock()

        # The dirstate should include TREE_ROOT and 'a-file' and nothing else
        expected_blocks = [
            (
                b"",
                [
                    (
                        (b"", b"", b"TREE_ROOT"),
                        [(b"d", b"", 0, False, dirstate.DirState.NULLSTAT)],
                    )
                ],
            ),
            (
                b"",
                [
                    (
                        (b"", b"a-file", b"a-file-id"),
                        [(b"f", b"", 0, False, dirstate.DirState.NULLSTAT)],
                    )
                ],
            ),
        ]

        state = dirstate.DirState.on_file("dirstate")
        state.lock_write()
        try:
            state._read_dirblocks_if_needed()
            self.assertEqual(expected_blocks, state._dirblocks)

            # Now modify the state, but mark it as inconsistent
            state.add("a-dir", b"a-dir-id", "directory", None, b"")
            state._changes_aborted = True
            state.save()
        finally:
            state.unlock()

        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        try:
            state._read_dirblocks_if_needed()
            self.assertEqual(expected_blocks, state._dirblocks)
        finally:
            state.unlock()


class TestDirStateInitialize(TestCaseWithDirState):
    def test_initialize(self):
        expected_result = (
            [],
            [
                (
                    (b"", b"", b"TREE_ROOT"),  # common details
                    [
                        (
                            b"d",
                            b"",
                            0,
                            False,
                            dirstate.DirState.NULLSTAT,
                        ),  # current tree
                    ],
                )
            ],
        )
        state = dirstate.DirState.initialize("dirstate")
        try:
            self.assertIsInstance(state, dirstate.DirState)
            lines = state.get_lines()
        finally:
            state.unlock()
        # On win32 you can't read from a locked file, even within the same
        # process. So we have to unlock and release before we check the file
        # contents.
        self.assertFileEqual(b"".join(lines), "dirstate")
        state.lock_read()  # check_state_with_reopen will unlock
        self.check_state_with_reopen(expected_result, state)


class TestDirStateManipulations(TestCaseWithDirState):
    def make_minimal_tree(self):
        tree1 = self.make_branch_and_memory_tree("tree1")
        tree1.lock_write()
        self.addCleanup(tree1.unlock)
        tree1.add("")
        revid1 = tree1.commit("foo")
        return tree1, revid1

    def test_update_minimal_updates_id_index(self):
        state = self.create_dirstate_with_root_and_subdir()
        self.addCleanup(state.unlock)
        id_index = state._get_id_index()
        self.assertEqual([b"a-root-value", b"subdir-id"], sorted(id_index))
        state.add("file-name", b"file-id", "file", None, "")
        self.assertEqual([b"a-root-value", b"file-id", b"subdir-id"], sorted(id_index))
        state.update_minimal(
            (b"", b"new-name", b"file-id"), b"f", path_utf8=b"new-name"
        )
        self.assertEqual([b"a-root-value", b"file-id", b"subdir-id"], sorted(id_index))
        self.assertEqual([(b"", b"new-name", b"file-id")], sorted(id_index[b"file-id"]))
        state._validate()

    def test_set_state_from_inventory_no_content_no_parents(self):
        # setting the current inventory is a slow but important api to support.
        tree1, _revid1 = self.make_minimal_tree()
        inv = tree1.root_inventory
        root_id = inv.path2id("")
        expected_result = (
            [],
            [
                (
                    (b"", b"", root_id),
                    [(b"d", b"", 0, False, dirstate.DirState.NULLSTAT)],
                )
            ],
        )
        state = dirstate.DirState.initialize("dirstate")
        try:
            state.set_state_from_inventory(inv)
            self.assertEqual(
                dirstate.DirState.IN_MEMORY_UNMODIFIED, state._header_state
            )
            self.assertEqual(
                dirstate.DirState.IN_MEMORY_MODIFIED, state._dirblock_state
            )
        except:
            state.unlock()
            raise
        else:
            # This will unlock it
            self.check_state_with_reopen(expected_result, state)

    def test_set_state_from_scratch_no_parents(self):
        tree1, _revid1 = self.make_minimal_tree()
        inv = tree1.root_inventory
        root_id = inv.path2id("")
        expected_result = (
            [],
            [
                (
                    (b"", b"", root_id),
                    [(b"d", b"", 0, False, dirstate.DirState.NULLSTAT)],
                )
            ],
        )
        state = dirstate.DirState.initialize("dirstate")
        try:
            state.set_state_from_scratch(inv, [], [])
            self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED, state._header_state)
            self.assertEqual(
                dirstate.DirState.IN_MEMORY_MODIFIED, state._dirblock_state
            )
        except:
            state.unlock()
            raise
        else:
            # This will unlock it
            self.check_state_with_reopen(expected_result, state)

    def test_set_state_from_scratch_identical_parent(self):
        tree1, revid1 = self.make_minimal_tree()
        inv = tree1.root_inventory
        root_id = inv.path2id("")
        rev_tree1 = tree1.branch.repository.revision_tree(revid1)
        d_entry = (b"d", b"", 0, False, dirstate.DirState.NULLSTAT)
        parent_entry = (b"d", b"", 0, False, revid1)
        expected_result = [revid1], [((b"", b"", root_id), [d_entry, parent_entry])]
        state = dirstate.DirState.initialize("dirstate")
        try:
            state.set_state_from_scratch(inv, [(revid1, rev_tree1)], [])
            self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED, state._header_state)
            self.assertEqual(
                dirstate.DirState.IN_MEMORY_MODIFIED, state._dirblock_state
            )
        except:
            state.unlock()
            raise
        else:
            # This will unlock it
            self.check_state_with_reopen(expected_result, state)

    def test_set_state_from_inventory_preserves_hashcache(self):
        # https://bugs.launchpad.net/bzr/+bug/146176
        # set_state_from_inventory should preserve the stat and hash value for
        # workingtree files that are not changed by the inventory.

        tree = self.make_branch_and_tree(".")
        # depends on the default format using dirstate...
        with tree.lock_write():
            # make a dirstate with some valid hashcache data
            # file on disk, but that's not needed for this test
            foo_contents = b"contents of foo"
            self.build_tree_contents([("foo", foo_contents)])
            tree.add("foo", ids=b"foo-id")

            foo_stat = os.stat("foo")
            foo_packed = dirstate.pack_stat(foo_stat)
            foo_sha = osutils.sha_string(foo_contents)
            foo_size = len(foo_contents)

            # should not be cached yet, because the file's too fresh
            self.assertEqual(
                (
                    (
                        b"",
                        b"foo",
                        b"foo-id",
                    ),
                    [(b"f", b"", 0, False, dirstate.DirState.NULLSTAT)],
                ),
                tree._dirstate._get_entry(0, b"foo-id"),
            )
            # poke in some hashcache information - it wouldn't normally be
            # stored because it's too fresh
            tree._dirstate.update_minimal(
                (b"", b"foo", b"foo-id"),
                b"f",
                False,
                foo_sha,
                foo_packed,
                foo_size,
                b"foo",
            )
            # now should be cached
            self.assertEqual(
                (
                    (
                        b"",
                        b"foo",
                        b"foo-id",
                    ),
                    [(b"f", foo_sha, foo_size, False, foo_packed)],
                ),
                tree._dirstate._get_entry(0, b"foo-id"),
            )

            # extract the inventory, and add something to it
            inv = tree._get_root_inventory()
            # should see the file we poked in...
            self.assertTrue(inv.has_id(b"foo-id"))
            self.assertTrue(inv.has_filename("foo"))
            inv.add_path("bar", "file", b"bar-id")
            tree._dirstate._validate()
            # this used to cause it to lose its hashcache
            tree._dirstate.set_state_from_inventory(inv)
            tree._dirstate._validate()

        with tree.lock_read():
            # now check that the state still has the original hashcache value
            state = tree._dirstate
            state._validate()
            foo_tuple = state._get_entry(0, path_utf8=b"foo")
            self.assertEqual(
                (
                    (
                        b"",
                        b"foo",
                        b"foo-id",
                    ),
                    [
                        (
                            b"f",
                            foo_sha,
                            len(foo_contents),
                            False,
                            dirstate.pack_stat(foo_stat),
                        )
                    ],
                ),
                foo_tuple,
            )

    def test_set_state_from_inventory_mixed_paths(self):
        tree1 = self.make_branch_and_tree("tree1")
        self.build_tree(
            ["tree1/a/", "tree1/a/b/", "tree1/a-b/", "tree1/a/b/foo", "tree1/a-b/bar"]
        )
        tree1.lock_write()
        try:
            tree1.add(
                ["a", "a/b", "a-b", "a/b/foo", "a-b/bar"],
                ids=[b"a-id", b"b-id", b"a-b-id", b"foo-id", b"bar-id"],
            )
            tree1.commit("rev1", rev_id=b"rev1")
            root_id = tree1.path2id("")
            inv = tree1.root_inventory
        finally:
            tree1.unlock()
        expected_result1 = [
            (b"", b"", root_id, b"d"),
            (b"", b"a", b"a-id", b"d"),
            (b"", b"a-b", b"a-b-id", b"d"),
            (b"a", b"b", b"b-id", b"d"),
            (b"a/b", b"foo", b"foo-id", b"f"),
            (b"a-b", b"bar", b"bar-id", b"f"),
        ]
        expected_result2 = [
            (b"", b"", root_id, b"d"),
            (b"", b"a", b"a-id", b"d"),
            (b"", b"a-b", b"a-b-id", b"d"),
            (b"a-b", b"bar", b"bar-id", b"f"),
        ]
        state = dirstate.DirState.initialize("dirstate")
        try:
            state.set_state_from_inventory(inv)
            values = []
            for entry in state._iter_entries():
                values.append(entry[0] + entry[1][0][:1])
            self.assertEqual(expected_result1, values)
            inv.delete(b"b-id")
            state.set_state_from_inventory(inv)
            values = []
            for entry in state._iter_entries():
                values.append(entry[0] + entry[1][0][:1])
            self.assertEqual(expected_result2, values)
        finally:
            state.unlock()

    def test_set_path_id_no_parents(self):
        """The id of a path can be changed trivally with no parents."""
        state = dirstate.DirState.initialize("dirstate")
        try:
            # check precondition to be sure the state does change appropriately.
            root_entry = ((b"", b"", b"TREE_ROOT"), [(b"d", b"", 0, False, b"x" * 32)])
            self.assertEqual([root_entry], list(state._iter_entries()))
            self.assertEqual(root_entry, state._get_entry(0, path_utf8=b""))
            self.assertEqual(root_entry, state._get_entry(0, fileid_utf8=b"TREE_ROOT"))
            self.assertEqual(
                (None, None), state._get_entry(0, fileid_utf8=b"second-root-id")
            )
            state.set_path_id(b"", b"second-root-id")
            new_root_entry = (
                (b"", b"", b"second-root-id"),
                [(b"d", b"", 0, False, b"x" * 32)],
            )
            expected_rows = [new_root_entry]
            self.assertEqual(expected_rows, list(state._iter_entries()))
            self.assertEqual(new_root_entry, state._get_entry(0, path_utf8=b""))
            self.assertEqual(
                new_root_entry, state._get_entry(0, fileid_utf8=b"second-root-id")
            )
            self.assertEqual(
                (None, None), state._get_entry(0, fileid_utf8=b"TREE_ROOT")
            )
            # should work across save too
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        try:
            state._validate()
            self.assertEqual(expected_rows, list(state._iter_entries()))
        finally:
            state.unlock()

    def test_set_path_id_with_parents(self):
        """Set the root file id in a dirstate with parents."""
        mt = self.make_branch_and_tree("mt")
        # in case the default tree format uses a different root id
        mt.set_root_id(b"TREE_ROOT")
        mt.commit("foo", rev_id=b"parent-revid")
        rt = mt.branch.repository.revision_tree(b"parent-revid")
        state = dirstate.DirState.initialize("dirstate")
        state._validate()
        try:
            state.set_parent_trees([(b"parent-revid", rt)], ghosts=[])
            root_entry = (
                (b"", b"", b"TREE_ROOT"),
                [
                    (b"d", b"", 0, False, b"x" * 32),
                    (b"d", b"", 0, False, b"parent-revid"),
                ],
            )
            self.assertEqual(root_entry, state._get_entry(0, path_utf8=b""))
            self.assertEqual(root_entry, state._get_entry(0, fileid_utf8=b"TREE_ROOT"))
            self.assertEqual(
                (None, None), state._get_entry(0, fileid_utf8=b"Asecond-root-id")
            )
            state.set_path_id(b"", b"Asecond-root-id")
            state._validate()
            # now see that it is what we expected
            old_root_entry = (
                (b"", b"", b"TREE_ROOT"),
                [(b"a", b"", 0, False, b""), (b"d", b"", 0, False, b"parent-revid")],
            )
            new_root_entry = (
                (b"", b"", b"Asecond-root-id"),
                [(b"d", b"", 0, False, b""), (b"a", b"", 0, False, b"")],
            )
            expected_rows = [new_root_entry, old_root_entry]
            state._validate()
            self.assertEqual(expected_rows, list(state._iter_entries()))
            self.assertEqual(new_root_entry, state._get_entry(0, path_utf8=b""))
            self.assertEqual(old_root_entry, state._get_entry(1, path_utf8=b""))
            self.assertEqual(
                (None, None), state._get_entry(0, fileid_utf8=b"TREE_ROOT")
            )
            self.assertEqual(
                old_root_entry, state._get_entry(1, fileid_utf8=b"TREE_ROOT")
            )
            self.assertEqual(
                new_root_entry, state._get_entry(0, fileid_utf8=b"Asecond-root-id")
            )
            self.assertEqual(
                (None, None), state._get_entry(1, fileid_utf8=b"Asecond-root-id")
            )
            # should work across save too
            state.save()
        finally:
            state.unlock()
        # now flush & check we get the same
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        try:
            state._validate()
            self.assertEqual(expected_rows, list(state._iter_entries()))
        finally:
            state.unlock()
        # now change within an existing file-backed state
        state.lock_write()
        try:
            state._validate()
            state.set_path_id(b"", b"tree-root-2")
            state._validate()
        finally:
            state.unlock()

    def test_set_parent_trees_no_content(self):
        # set_parent_trees is a slow but important api to support.
        tree1 = self.make_branch_and_memory_tree("tree1")
        tree1.lock_write()
        try:
            tree1.add("")
            revid1 = tree1.commit("foo")
        finally:
            tree1.unlock()
        branch2 = tree1.branch.controldir.clone("tree2").open_branch()
        tree2 = memorytree.MemoryTree.create_on_branch(branch2)
        tree2.lock_write()
        try:
            revid2 = tree2.commit("foo")
            root_id = tree2.path2id("")
        finally:
            tree2.unlock()
        state = dirstate.DirState.initialize("dirstate")
        try:
            state.set_path_id(b"", root_id)
            state.set_parent_trees(
                (
                    (revid1, tree1.branch.repository.revision_tree(revid1)),
                    (revid2, tree2.branch.repository.revision_tree(revid2)),
                    (b"ghost-rev", None),
                ),
                [b"ghost-rev"],
            )
            # check we can reopen and use the dirstate after setting parent
            # trees.
            state._validate()
            state.save()
            state._validate()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file("dirstate")
        state.lock_write()
        try:
            self.assertEqual([revid1, revid2, b"ghost-rev"], state.get_parent_ids())
            # iterating the entire state ensures that the state is parsable.
            list(state._iter_entries())
            # be sure that it sets not appends - change it
            state.set_parent_trees(
                (
                    (revid1, tree1.branch.repository.revision_tree(revid1)),
                    (b"ghost-rev", None),
                ),
                [b"ghost-rev"],
            )
            # and now put it back.
            state.set_parent_trees(
                (
                    (revid1, tree1.branch.repository.revision_tree(revid1)),
                    (revid2, tree2.branch.repository.revision_tree(revid2)),
                    (
                        b"ghost-rev",
                        tree2.branch.repository.revision_tree(
                            _mod_revision.NULL_REVISION
                        ),
                    ),
                ),
                [b"ghost-rev"],
            )
            self.assertEqual([revid1, revid2, b"ghost-rev"], state.get_parent_ids())
            # the ghost should be recorded as such by set_parent_trees.
            self.assertEqual([b"ghost-rev"], state.get_ghosts())
            self.assertEqual(
                [
                    (
                        (b"", b"", root_id),
                        [
                            (b"d", b"", 0, False, dirstate.DirState.NULLSTAT),
                            (b"d", b"", 0, False, revid1),
                            (b"d", b"", 0, False, revid1),
                        ],
                    )
                ],
                list(state._iter_entries()),
            )
        finally:
            state.unlock()

    def test_set_parent_trees_file_missing_from_tree(self):
        # Adding a parent tree may reference files not in the current state.
        # they should get listed just once by id, even if they are in two
        # separate trees.
        # set_parent_trees is a slow but important api to support.
        tree1 = self.make_branch_and_memory_tree("tree1")
        tree1.lock_write()
        try:
            tree1.add("")
            tree1.add(["a file"], ["file"], [b"file-id"])
            tree1.put_file_bytes_non_atomic("a file", b"file-content")
            revid1 = tree1.commit("foo")
        finally:
            tree1.unlock()
        branch2 = tree1.branch.controldir.clone("tree2").open_branch()
        tree2 = memorytree.MemoryTree.create_on_branch(branch2)
        tree2.lock_write()
        try:
            tree2.put_file_bytes_non_atomic("a file", b"new file-content")
            revid2 = tree2.commit("foo")
            root_id = tree2.path2id("")
        finally:
            tree2.unlock()
        # check the layout in memory
        expected_result = (
            [revid1, revid2],
            [
                (
                    (b"", b"", root_id),
                    [
                        (b"d", b"", 0, False, dirstate.DirState.NULLSTAT),
                        (b"d", b"", 0, False, revid1),
                        (b"d", b"", 0, False, revid1),
                    ],
                ),
                (
                    (b"", b"a file", b"file-id"),
                    [
                        (b"a", b"", 0, False, b""),
                        (
                            b"f",
                            b"2439573625385400f2a669657a7db6ae7515d371",
                            12,
                            False,
                            revid1,
                        ),
                        (
                            b"f",
                            b"542e57dc1cda4af37cb8e55ec07ce60364bb3c7d",
                            16,
                            False,
                            revid2,
                        ),
                    ],
                ),
            ],
        )
        state = dirstate.DirState.initialize("dirstate")
        try:
            state.set_path_id(b"", root_id)
            state.set_parent_trees(
                (
                    (revid1, tree1.branch.repository.revision_tree(revid1)),
                    (revid2, tree2.branch.repository.revision_tree(revid2)),
                ),
                [],
            )
        except:
            state.unlock()
            raise
        else:
            # check_state_with_reopen will unlock
            self.check_state_with_reopen(expected_result, state)

    # add a path via _set_data - so we dont need delta work, just
    # raw data in, and ensure that it comes out via get_lines happily.

    def test_add_path_to_root_no_parents_all_data(self):
        # The most trivial addition of a path is when there are no parents and
        # its in the root and all data about the file is supplied
        self.build_tree(["a file"])
        stat = os.lstat("a file")
        # the 1*20 is the sha1 pretend value.
        state = dirstate.DirState.initialize("dirstate")
        expected_entries = [
            (
                (b"", b"", b"TREE_ROOT"),
                [
                    (b"d", b"", 0, False, dirstate.DirState.NULLSTAT),  # current tree
                ],
            ),
            (
                (b"", b"a file", b"a-file-id"),
                [
                    (
                        b"f",
                        b"1" * 20,
                        19,
                        False,
                        dirstate.pack_stat(stat),
                    ),  # current tree
                ],
            ),
        ]
        try:
            state.add("a file", b"a-file-id", "file", stat, b"1" * 20)
            # having added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        self.addCleanup(state.unlock)
        self.assertEqual(expected_entries, list(state._iter_entries()))

    def test_add_path_to_unversioned_directory(self):
        """Adding a path to an unversioned directory should error.

        This is a duplicate of TestWorkingTree.test_add_in_unversioned,
        once dirstate is stable and if it is merged with WorkingTree3, consider
        removing this copy of the test.
        """
        self.build_tree(["unversioned/", "unversioned/a file"])
        state = dirstate.DirState.initialize("dirstate")
        self.addCleanup(state.unlock)
        self.assertRaises(
            errors.NotVersionedError,
            state.add,
            "unversioned/a file",
            b"a-file-id",
            "file",
            None,
            None,
        )

    def test_add_directory_to_root_no_parents_all_data(self):
        # The most trivial addition of a dir is when there are no parents and
        # its in the root and all data about the file is supplied
        self.build_tree(["a dir/"])
        stat = os.lstat("a dir")
        expected_entries = [
            (
                (b"", b"", b"TREE_ROOT"),
                [
                    (b"d", b"", 0, False, dirstate.DirState.NULLSTAT),  # current tree
                ],
            ),
            (
                (b"", b"a dir", b"a dir id"),
                [
                    (b"d", b"", 0, False, dirstate.pack_stat(stat)),  # current tree
                ],
            ),
        ]
        state = dirstate.DirState.initialize("dirstate")
        try:
            state.add("a dir", b"a dir id", "directory", stat, None)
            # having added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        self.addCleanup(state.unlock)
        state._validate()
        self.assertEqual(expected_entries, list(state._iter_entries()))

    def _test_add_symlink_to_root_no_parents_all_data(self, link_name, target):
        # The most trivial addition of a symlink when there are no parents and
        # its in the root and all data about the file is supplied
        # bzr doesn't support fake symlinks on windows, yet.
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        os.symlink(target, link_name)
        stat = os.lstat(link_name)
        expected_entries = [
            (
                (b"", b"", b"TREE_ROOT"),
                [
                    (b"d", b"", 0, False, dirstate.DirState.NULLSTAT),  # current tree
                ],
            ),
            (
                (b"", link_name.encode("UTF-8"), b"a link id"),
                [
                    (
                        b"l",
                        target.encode("UTF-8"),
                        stat[6],
                        False,
                        dirstate.pack_stat(stat),
                    ),  # current tree
                ],
            ),
        ]
        state = dirstate.DirState.initialize("dirstate")
        try:
            state.add(link_name, b"a link id", "symlink", stat, target.encode("UTF-8"))
            # having added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        self.addCleanup(state.unlock)
        self.assertEqual(expected_entries, list(state._iter_entries()))

    def test_add_symlink_to_root_no_parents_all_data(self):
        self._test_add_symlink_to_root_no_parents_all_data("a link", "target")

    def test_add_symlink_unicode_to_root_no_parents_all_data(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_add_symlink_to_root_no_parents_all_data(
            "\N{EURO SIGN}link", "targ\N{EURO SIGN}et"
        )

    def test_add_directory_and_child_no_parents_all_data(self):
        # after adding a directory, we should be able to add children to it.
        self.build_tree(["a dir/", "a dir/a file"])
        dirstat = os.lstat("a dir")
        filestat = os.lstat("a dir/a file")
        expected_entries = [
            (
                (b"", b"", b"TREE_ROOT"),
                [
                    (b"d", b"", 0, False, dirstate.DirState.NULLSTAT),  # current tree
                ],
            ),
            (
                (b"", b"a dir", b"a dir id"),
                [
                    (b"d", b"", 0, False, dirstate.pack_stat(dirstat)),  # current tree
                ],
            ),
            (
                (b"a dir", b"a file", b"a-file-id"),
                [
                    (
                        b"f",
                        b"1" * 20,
                        25,
                        False,
                        dirstate.pack_stat(filestat),
                    ),  # current tree details
                ],
            ),
        ]
        state = dirstate.DirState.initialize("dirstate")
        try:
            state.add("a dir", b"a dir id", "directory", dirstat, None)
            state.add("a dir/a file", b"a-file-id", "file", filestat, b"1" * 20)
            # added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        self.addCleanup(state.unlock)
        self.assertEqual(expected_entries, list(state._iter_entries()))

    def test_add_tree_reference(self):
        # make a dirstate and add a tree reference
        state = dirstate.DirState.initialize("dirstate")
        expected_entry = (
            (b"", b"subdir", b"subdir-id"),
            [(b"t", b"subtree-123123", 0, False, b"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")],
        )
        try:
            state.add("subdir", b"subdir-id", "tree-reference", None, b"subtree-123123")
            entry = state._get_entry(0, b"subdir-id", b"subdir")
            self.assertEqual(entry, expected_entry)
            state._validate()
            state.save()
        finally:
            state.unlock()
        # now check we can read it back
        state.lock_read()
        self.addCleanup(state.unlock)
        state._validate()
        entry2 = state._get_entry(0, b"subdir-id", b"subdir")
        self.assertEqual(entry, entry2)
        self.assertEqual(entry, expected_entry)
        # and lookup by id should work too
        entry2 = state._get_entry(0, fileid_utf8=b"subdir-id")
        self.assertEqual(entry, expected_entry)

    def test_add_forbidden_names(self):
        state = dirstate.DirState.initialize("dirstate")
        self.addCleanup(state.unlock)
        self.assertRaises(
            errors.BzrError, state.add, ".", b"ass-id", "directory", None, None
        )
        self.assertRaises(
            errors.BzrError, state.add, "..", b"ass-id", "directory", None, None
        )

    def test_set_state_with_rename_b_a_bug_395556(self):
        # bug 395556 uncovered a bug where the dirstate ends up with a false
        # relocation record - in a tree with no parents there should be no
        # absent or relocated records. This then leads to further corruption
        # when a commit occurs, as the incorrect relocation gathers an
        # incorrect absent in tree 1, and future changes go to pot.
        tree1 = self.make_branch_and_tree("tree1")
        self.build_tree(["tree1/b"])
        with tree1.lock_write():
            tree1.add(["b"], ids=[b"b-id"])
            root_id = tree1.path2id("")
            inv = tree1.root_inventory
            state = dirstate.DirState.initialize("dirstate")
            try:
                # Set the initial state with 'b'
                state.set_state_from_inventory(inv)
                inv.rename(b"b-id", root_id, "a")
                # Set the new state with 'a', which currently corrupts.
                state.set_state_from_inventory(inv)
                expected_result1 = [
                    (b"", b"", root_id, b"d"),
                    (b"", b"a", b"b-id", b"f"),
                ]
                values = []
                for entry in state._iter_entries():
                    values.append(entry[0] + entry[1][0][:1])
                self.assertEqual(expected_result1, values)
            finally:
                state.unlock()


class TestDirStateHashUpdates(TestCaseWithDirState):
    def do_update_entry(self, state, path):
        entry = state._get_entry(0, path_utf8=path)
        stat = os.lstat(path)
        return dirstate.update_entry(state, entry, os.path.abspath(path), stat)

    def _read_state_content(self, state):
        """Read the content of the dirstate file.

        On Windows when one process locks a file, you can't even open() the
        file in another process (to read it). So we go directly to
        state._state_file. This should always be the exact disk representation,
        so it is reasonable to do so.
        DirState also always seeks before reading, so it doesn't matter if we
        bump the file pointer.
        """
        state._state_file.seek(0)
        return state._state_file.read()

    def test_worth_saving_limit_avoids_writing(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["c", "d"])
        tree.lock_write()
        tree.add(["c", "d"], ids=[b"c-id", b"d-id"])
        tree.commit("add c and d")
        state = InstrumentedDirState.on_file(
            tree.current_dirstate()._filename, worth_saving_limit=2
        )
        tree.unlock()
        state.lock_write()
        self.addCleanup(state.unlock)
        state._read_dirblocks_if_needed()
        state.adjust_time(+20)  # Allow things to be cached
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)
        content = self._read_state_content(state)
        self.do_update_entry(state, b"c")
        self.assertEqual(1, len(state._known_hash_changes))
        self.assertEqual(
            dirstate.DirState.IN_MEMORY_HASH_MODIFIED, state._dirblock_state
        )
        state.save()
        # It should not have set the state to IN_MEMORY_UNMODIFIED because the
        # hash values haven't been written out.
        self.assertEqual(
            dirstate.DirState.IN_MEMORY_HASH_MODIFIED, state._dirblock_state
        )
        self.assertEqual(content, self._read_state_content(state))
        self.assertEqual(
            dirstate.DirState.IN_MEMORY_HASH_MODIFIED, state._dirblock_state
        )
        self.do_update_entry(state, b"d")
        self.assertEqual(2, len(state._known_hash_changes))
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED, state._dirblock_state)
        self.assertEqual(0, len(state._known_hash_changes))


class TestGetLines(TestCaseWithDirState):
    def test_get_line_with_2_rows(self):
        state = self.create_dirstate_with_root_and_subdir()
        try:
            self.assertEqual(
                [
                    b"#bazaar dirstate flat format 3\n",
                    b"crc32: 41262208\n",
                    b"num_entries: 2\n",
                    b"0\x00\n\x00"
                    b"0\x00\n\x00"
                    b"\x00\x00a-root-value\x00"
                    b"d\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00\n\x00"
                    b"\x00subdir\x00subdir-id\x00"
                    b"d\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00\n\x00",
                ],
                state.get_lines(),
            )
        finally:
            state.unlock()

    def test_entry_to_line(self):
        state = self.create_dirstate_with_root()
        try:
            self.assertEqual(
                b"\x00\x00a-root-value\x00d\x00\x000\x00n"
                b"\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk",
                state._entry_to_line(state._dirblocks[0][1][0]),
            )
        finally:
            state.unlock()

    def test_entry_to_line_with_parent(self):
        packed_stat = b"AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk"
        root_entry = (
            (b"", b"", b"a-root-value"),
            [
                (b"d", b"", 0, False, packed_stat),  # current tree details
                # first: a pointer to the current location
                (b"a", b"dirname/basename", 0, False, b""),
            ],
        )
        state = dirstate.DirState.initialize("dirstate")
        try:
            self.assertEqual(
                b"\x00\x00a-root-value\x00"
                b"d\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00"
                b"a\x00dirname/basename\x000\x00n\x00",
                state._entry_to_line(root_entry),
            )
        finally:
            state.unlock()

    def test_entry_to_line_with_two_parents_at_different_paths(self):
        # / in the tree, at / in one parent and /dirname/basename in the other.
        packed_stat = b"AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk"
        root_entry = (
            (b"", b"", b"a-root-value"),
            [
                (b"d", b"", 0, False, packed_stat),  # current tree details
                (b"d", b"", 0, False, b"rev_id"),  # first parent details
                # second: a pointer to the current location
                (b"a", b"dirname/basename", 0, False, b""),
            ],
        )
        state = dirstate.DirState.initialize("dirstate")
        try:
            self.assertEqual(
                b"\x00\x00a-root-value\x00"
                b"d\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00"
                b"d\x00\x000\x00n\x00rev_id\x00"
                b"a\x00dirname/basename\x000\x00n\x00",
                state._entry_to_line(root_entry),
            )
        finally:
            state.unlock()

    def test_iter_entries(self):
        # we should be able to iterate the dirstate entries from end to end
        # this is for get_lines to be easy to read.
        packed_stat = b"AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk"
        dirblocks = []
        root_entries = [
            (
                (b"", b"", b"a-root-value"),
                [
                    (b"d", b"", 0, False, packed_stat),  # current tree details
                ],
            )
        ]
        dirblocks.append(("", root_entries))
        # add two files in the root
        subdir_entry = (
            (b"", b"subdir", b"subdir-id"),
            [
                (b"d", b"", 0, False, packed_stat),  # current tree details
            ],
        )
        afile_entry = (
            (b"", b"afile", b"afile-id"),
            [
                (b"f", b"sha1value", 34, False, packed_stat),  # current tree details
            ],
        )
        dirblocks.append(("", [subdir_entry, afile_entry]))
        # and one in subdir
        file_entry2 = (
            (b"subdir", b"2file", b"2file-id"),
            [
                (b"f", b"sha1value", 23, False, packed_stat),  # current tree details
            ],
        )
        dirblocks.append(("subdir", [file_entry2]))
        state = dirstate.DirState.initialize("dirstate")
        try:
            state._set_data([], dirblocks)
            expected_entries = [root_entries[0], subdir_entry, afile_entry, file_entry2]
            self.assertEqual(expected_entries, list(state._iter_entries()))
        finally:
            state.unlock()


class TestGetBlockRowIndex(TestCaseWithDirState):
    def assertBlockRowIndexEqual(
        self,
        block_index,
        row_index,
        dir_present,
        file_present,
        state,
        dirname,
        basename,
        tree_index,
    ):
        self.assertEqual(
            (block_index, row_index, dir_present, file_present),
            state._get_block_entry_index(dirname, basename, tree_index),
        )
        if dir_present:
            block = state._dirblocks[block_index]
            self.assertEqual(dirname, block[0])
        if dir_present and file_present:
            row = state._dirblocks[block_index][1][row_index]
            self.assertEqual(dirname, row[0][0])
            self.assertEqual(basename, row[0][1])

    def test_simple_structure(self):
        state = self.create_dirstate_with_root_and_subdir()
        self.addCleanup(state.unlock)
        self.assertBlockRowIndexEqual(1, 0, True, True, state, b"", b"subdir", 0)
        self.assertBlockRowIndexEqual(1, 0, True, False, state, b"", b"bdir", 0)
        self.assertBlockRowIndexEqual(1, 1, True, False, state, b"", b"zdir", 0)
        self.assertBlockRowIndexEqual(2, 0, False, False, state, b"a", b"foo", 0)
        self.assertBlockRowIndexEqual(2, 0, False, False, state, b"subdir", b"foo", 0)

    def test_complex_structure_exists(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        # Make sure we can find everything that exists
        self.assertBlockRowIndexEqual(0, 0, True, True, state, b"", b"", 0)
        self.assertBlockRowIndexEqual(1, 0, True, True, state, b"", b"a", 0)
        self.assertBlockRowIndexEqual(1, 1, True, True, state, b"", b"b", 0)
        self.assertBlockRowIndexEqual(1, 2, True, True, state, b"", b"c", 0)
        self.assertBlockRowIndexEqual(1, 3, True, True, state, b"", b"d", 0)
        self.assertBlockRowIndexEqual(2, 0, True, True, state, b"a", b"e", 0)
        self.assertBlockRowIndexEqual(2, 1, True, True, state, b"a", b"f", 0)
        self.assertBlockRowIndexEqual(3, 0, True, True, state, b"b", b"g", 0)
        self.assertBlockRowIndexEqual(3, 1, True, True, state, b"b", b"h\xc3\xa5", 0)

    def test_complex_structure_missing(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        # Make sure things would be inserted in the right locations
        # '_' comes before 'a'
        self.assertBlockRowIndexEqual(0, 0, True, True, state, b"", b"", 0)
        self.assertBlockRowIndexEqual(1, 0, True, False, state, b"", b"_", 0)
        self.assertBlockRowIndexEqual(1, 1, True, False, state, b"", b"aa", 0)
        self.assertBlockRowIndexEqual(1, 4, True, False, state, b"", b"h\xc3\xa5", 0)
        self.assertBlockRowIndexEqual(2, 0, False, False, state, b"_", b"a", 0)
        self.assertBlockRowIndexEqual(3, 0, False, False, state, b"aa", b"a", 0)
        self.assertBlockRowIndexEqual(4, 0, False, False, state, b"bb", b"a", 0)
        # This would be inserted between a/ and b/
        self.assertBlockRowIndexEqual(3, 0, False, False, state, b"a/e", b"a", 0)
        # Put at the end
        self.assertBlockRowIndexEqual(4, 0, False, False, state, b"e", b"a", 0)


class TestGetEntry(TestCaseWithDirState):
    def assertEntryEqual(self, dirname, basename, file_id, state, path, index):
        """Check that the right entry is returned for a request to getEntry."""
        entry = state._get_entry(index, path_utf8=path)
        if file_id is None:
            self.assertEqual((None, None), entry)
        else:
            cur = entry[0]
            self.assertEqual((dirname, basename, file_id), cur[:3])

    def test_simple_structure(self):
        state = self.create_dirstate_with_root_and_subdir()
        self.addCleanup(state.unlock)
        self.assertEntryEqual(b"", b"", b"a-root-value", state, b"", 0)
        self.assertEntryEqual(b"", b"subdir", b"subdir-id", state, b"subdir", 0)
        self.assertEntryEqual(None, None, None, state, b"missing", 0)
        self.assertEntryEqual(None, None, None, state, b"missing/foo", 0)
        self.assertEntryEqual(None, None, None, state, b"subdir/foo", 0)

    def test_complex_structure_exists(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        self.assertEntryEqual(b"", b"", b"a-root-value", state, b"", 0)
        self.assertEntryEqual(b"", b"a", b"a-dir", state, b"a", 0)
        self.assertEntryEqual(b"", b"b", b"b-dir", state, b"b", 0)
        self.assertEntryEqual(b"", b"c", b"c-file", state, b"c", 0)
        self.assertEntryEqual(b"", b"d", b"d-file", state, b"d", 0)
        self.assertEntryEqual(b"a", b"e", b"e-dir", state, b"a/e", 0)
        self.assertEntryEqual(b"a", b"f", b"f-file", state, b"a/f", 0)
        self.assertEntryEqual(b"b", b"g", b"g-file", state, b"b/g", 0)
        self.assertEntryEqual(
            b"b", b"h\xc3\xa5", b"h-\xc3\xa5-file", state, b"b/h\xc3\xa5", 0
        )

    def test_complex_structure_missing(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        self.assertEntryEqual(None, None, None, state, b"_", 0)
        self.assertEntryEqual(None, None, None, state, b"_\xc3\xa5", 0)
        self.assertEntryEqual(None, None, None, state, b"a/b", 0)
        self.assertEntryEqual(None, None, None, state, b"c/d", 0)

    def test_get_entry_uninitialized(self):
        """Calling get_entry will load data if it needs to."""
        state = self.create_dirstate_with_root()
        try:
            state.save()
        finally:
            state.unlock()
        del state
        state = dirstate.DirState.on_file("dirstate")
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY, state._header_state)
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY, state._dirblock_state)
            self.assertEntryEqual(b"", b"", b"a-root-value", state, b"", 0)
        finally:
            state.unlock()


class TestIterChildEntries(TestCaseWithDirState):
    def create_dirstate_with_two_trees(self):
        r"""This dirstate contains multiple files and directories.

         /        a-root-value
         a/       a-dir
         b/       b-dir
         c        c-file
         d        d-file
         a/e/     e-dir
         a/f      f-file
         b/g      g-file
         b/h\xc3\xa5  h-\xc3\xa5-file  #This is u'\xe5' encoded into utf-8

        Notice that a/e is an empty directory.

        There is one parent tree, which has the same shape with the following variations:
        b/g in the parent is gone.
        b/h in the parent has a different id
        b/i is new in the parent
        c is renamed to b/j in the parent

        :return: The dirstate, still write-locked.
        """
        packed_stat = b"AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk"
        null_sha = b"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        NULL_PARENT_DETAILS = dirstate.DirState.NULL_PARENT_DETAILS
        root_entry = (
            (b"", b"", b"a-root-value"),
            [
                (b"d", b"", 0, False, packed_stat),
                (b"d", b"", 0, False, b"parent-revid"),
            ],
        )
        a_entry = (
            (b"", b"a", b"a-dir"),
            [
                (b"d", b"", 0, False, packed_stat),
                (b"d", b"", 0, False, b"parent-revid"),
            ],
        )
        b_entry = (
            (b"", b"b", b"b-dir"),
            [
                (b"d", b"", 0, False, packed_stat),
                (b"d", b"", 0, False, b"parent-revid"),
            ],
        )
        c_entry = (
            (b"", b"c", b"c-file"),
            [
                (b"f", null_sha, 10, False, packed_stat),
                (b"r", b"b/j", 0, False, b""),
            ],
        )
        d_entry = (
            (b"", b"d", b"d-file"),
            [
                (b"f", null_sha, 20, False, packed_stat),
                (b"f", b"d", 20, False, b"parent-revid"),
            ],
        )
        e_entry = (
            (b"a", b"e", b"e-dir"),
            [
                (b"d", b"", 0, False, packed_stat),
                (b"d", b"", 0, False, b"parent-revid"),
            ],
        )
        f_entry = (
            (b"a", b"f", b"f-file"),
            [
                (b"f", null_sha, 30, False, packed_stat),
                (b"f", b"f", 20, False, b"parent-revid"),
            ],
        )
        g_entry = (
            (b"b", b"g", b"g-file"),
            [
                (b"f", null_sha, 30, False, packed_stat),
                NULL_PARENT_DETAILS,
            ],
        )
        h_entry1 = (
            (b"b", b"h\xc3\xa5", b"h-\xc3\xa5-file1"),
            [
                (b"f", null_sha, 40, False, packed_stat),
                NULL_PARENT_DETAILS,
            ],
        )
        h_entry2 = (
            (b"b", b"h\xc3\xa5", b"h-\xc3\xa5-file2"),
            [
                NULL_PARENT_DETAILS,
                (b"f", b"h", 20, False, b"parent-revid"),
            ],
        )
        i_entry = (
            (b"b", b"i", b"i-file"),
            [
                NULL_PARENT_DETAILS,
                (b"f", b"h", 20, False, b"parent-revid"),
            ],
        )
        j_entry = (
            (b"b", b"j", b"c-file"),
            [
                (b"r", b"c", 0, False, b""),
                (b"f", b"j", 20, False, b"parent-revid"),
            ],
        )
        dirblocks = []
        dirblocks.append((b"", [root_entry]))
        dirblocks.append((b"", [a_entry, b_entry, c_entry, d_entry]))
        dirblocks.append((b"a", [e_entry, f_entry]))
        dirblocks.append((b"b", [g_entry, h_entry1, h_entry2, i_entry, j_entry]))
        state = dirstate.DirState.initialize("dirstate")
        state._validate()
        try:
            state._set_data([b"parent"], dirblocks)
        except:
            state.unlock()
            raise
        return state, dirblocks

    def test_iter_children_b(self):
        state, dirblocks = self.create_dirstate_with_two_trees()
        self.addCleanup(state.unlock)
        expected_result = []
        expected_result.append(dirblocks[3][1][2])  # h2
        expected_result.append(dirblocks[3][1][3])  # i
        expected_result.append(dirblocks[3][1][4])  # j
        self.assertEqual(expected_result, list(state._iter_child_entries(1, b"b")))

    def test_iter_child_root(self):
        state, dirblocks = self.create_dirstate_with_two_trees()
        self.addCleanup(state.unlock)
        expected_result = []
        expected_result.append(dirblocks[1][1][0])  # a
        expected_result.append(dirblocks[1][1][1])  # b
        expected_result.append(dirblocks[1][1][3])  # d
        expected_result.append(dirblocks[2][1][0])  # e
        expected_result.append(dirblocks[2][1][1])  # f
        expected_result.append(dirblocks[3][1][2])  # h2
        expected_result.append(dirblocks[3][1][3])  # i
        expected_result.append(dirblocks[3][1][4])  # j
        self.assertEqual(expected_result, list(state._iter_child_entries(1, b"")))


class TestDirstateSortOrder(tests.TestCaseWithTransport):
    """Test that DirState adds entries in the right order."""

    def test_add_sorting(self):
        """Add entries in lexicographical order, we get path sorted order.

        This tests it to a depth of 4, to make sure we don't just get it right
        at a single depth. 'a/a' should come before 'a-a', even though it
        doesn't lexicographically.
        """
        dirs = [
            "a",
            "a/a",
            "a/a/a",
            "a/a/a/a",
            "a-a",
            "a/a-a",
            "a/a/a-a",
            "a/a/a/a-a",
        ]
        null_sha = b""
        state = dirstate.DirState.initialize("dirstate")
        self.addCleanup(state.unlock)

        fake_stat = os.stat("dirstate")
        for d in dirs:
            d_id = d.encode("utf-8").replace(b"/", b"_") + b"-id"
            file_path = d + "/f"
            file_id = file_path.encode("utf-8").replace(b"/", b"_") + b"-id"
            state.add(d, d_id, "directory", fake_stat, null_sha)
            state.add(file_path, file_id, "file", fake_stat, null_sha)

        expected = [
            b"",
            b"",
            b"a",
            b"a/a",
            b"a/a/a",
            b"a/a/a/a",
            b"a/a/a/a-a",
            b"a/a/a-a",
            b"a/a-a",
            b"a-a",
        ]

        def split(p):
            return p.split(b"/")

        self.assertEqual(sorted(expected, key=split), expected)
        dirblock_names = [d[0] for d in state._dirblocks]
        self.assertEqual(expected, dirblock_names)

    def test_set_parent_trees_correct_order(self):
        """After calling set_parent_trees() we should maintain the order."""
        dirs = ["a", "a-a", "a/a"]
        null_sha = b""
        state = dirstate.DirState.initialize("dirstate")
        self.addCleanup(state.unlock)

        fake_stat = os.stat("dirstate")
        for d in dirs:
            d_id = d.encode("utf-8").replace(b"/", b"_") + b"-id"
            file_path = d + "/f"
            file_id = file_path.encode("utf-8").replace(b"/", b"_") + b"-id"
            state.add(d, d_id, "directory", fake_stat, null_sha)
            state.add(file_path, file_id, "file", fake_stat, null_sha)

        expected = [b"", b"", b"a", b"a/a", b"a-a"]
        dirblock_names = [d[0] for d in state._dirblocks]
        self.assertEqual(expected, dirblock_names)

        # *really* cheesy way to just get an empty tree
        repo = self.make_repository("repo")
        empty_tree = repo.revision_tree(_mod_revision.NULL_REVISION)
        state.set_parent_trees([("null:", empty_tree)], [])

        dirblock_names = [d[0] for d in state._dirblocks]
        self.assertEqual(expected, dirblock_names)


class InstrumentedDirState(dirstate.DirState):
    """An DirState with instrumented sha1 functionality."""

    def __init__(
        self, path, sha1_provider, worth_saving_limit=0, use_filesystem_for_exec=True
    ):
        super().__init__(
            path,
            sha1_provider,
            worth_saving_limit=worth_saving_limit,
            use_filesystem_for_exec=use_filesystem_for_exec,
        )
        self._time_offset = 0
        self._log = []
        # member is dynamically set in DirState.__init__ to turn on trace
        self._sha1_provider = sha1_provider
        self._sha1_file = self._sha1_file_and_log

    def _sha_cutoff_time(self):
        timestamp = super()._sha_cutoff_time()
        self._cutoff_time = timestamp + self._time_offset

    def _sha1_file_and_log(self, abspath):
        self._log.append(("sha1", abspath))
        return self._sha1_provider.sha1(abspath)

    def _read_link(self, abspath, old_link):
        self._log.append(("read_link", abspath, old_link))
        return super()._read_link(abspath, old_link)

    def _lstat(self, abspath, entry):
        self._log.append(("lstat", abspath))
        return super()._lstat(abspath, entry)

    def _is_executable(self, mode, old_executable):
        self._log.append(("is_exec", mode, old_executable))
        return super()._is_executable(mode, old_executable)

    def adjust_time(self, secs):
        """Move the clock forward or back.

        :param secs: The amount to adjust the clock by. Positive values make it
        seem as if we are in the future, negative values make it seem like we
        are in the past.
        """
        self._time_offset += secs
        self._cutoff_time = None


class _FakeStat:
    """A class with the same attributes as a real stat result."""

    def __init__(self, size, mtime, ctime, dev, ino, mode):
        self.st_size = size
        self.st_mtime = mtime
        self.st_ctime = ctime
        self.st_dev = dev
        self.st_ino = ino
        self.st_mode = mode

    @staticmethod
    def from_stat(st):
        return _FakeStat(
            st.st_size, st.st_mtime, st.st_ctime, st.st_dev, st.st_ino, st.st_mode
        )


class TestPackStat(tests.TestCaseWithTransport):
    def assertPackStat(self, expected, stat_value):
        """Check the packed and serialized form of a stat value."""
        self.assertEqual(expected, dirstate.pack_stat(stat_value))

    def test_pack_stat_int(self):
        st = _FakeStat(6859, 1172758614, 1172758617, 777, 6499538, 0o100644)
        # Make sure that all parameters have an impact on the packed stat.
        self.assertPackStat(b"AAAay0Xm4FZF5uBZAAADCQBjLNIAAIGk", st)
        st.st_size = 7000
        #                ay0 => bWE
        self.assertPackStat(b"AAAbWEXm4FZF5uBZAAADCQBjLNIAAIGk", st)
        st.st_mtime = 1172758620
        #                     4FZ => 4Fx
        self.assertPackStat(b"AAAbWEXm4FxF5uBZAAADCQBjLNIAAIGk", st)
        st.st_ctime = 1172758630
        #                          uBZ => uBm
        self.assertPackStat(b"AAAbWEXm4FxF5uBmAAADCQBjLNIAAIGk", st)
        st.st_dev = 888
        #                                DCQ => DeA
        self.assertPackStat(b"AAAbWEXm4FxF5uBmAAADeABjLNIAAIGk", st)
        st.st_ino = 6499540
        #                                     LNI => LNQ
        self.assertPackStat(b"AAAbWEXm4FxF5uBmAAADeABjLNQAAIGk", st)
        st.st_mode = 0o100744
        #                                          IGk => IHk
        self.assertPackStat(b"AAAbWEXm4FxF5uBmAAADeABjLNQAAIHk", st)

    def test_pack_stat_float(self):
        """On some platforms mtime and ctime are floats.

        Make sure we don't get warnings or errors, and that we ignore changes <
        1s
        """
        st = _FakeStat(7000, 1172758614.0, 1172758617.0, 777, 6499538, 0o100644)
        # These should all be the same as the integer counterparts
        self.assertPackStat(b"AAAbWEXm4FZF5uBZAAADCQBjLNIAAIGk", st)
        st.st_mtime = 1172758620.0
        #                     FZF5 => FxF5
        self.assertPackStat(b"AAAbWEXm4FxF5uBZAAADCQBjLNIAAIGk", st)
        st.st_ctime = 1172758630.0
        #                          uBZ => uBm
        self.assertPackStat(b"AAAbWEXm4FxF5uBmAAADCQBjLNIAAIGk", st)
        # fractional seconds are discarded, so no change from above
        st.st_mtime = 1172758620.453
        self.assertPackStat(b"AAAbWEXm4FxF5uBmAAADCQBjLNIAAIGk", st)
        st.st_ctime = 1172758630.228
        self.assertPackStat(b"AAAbWEXm4FxF5uBmAAADCQBjLNIAAIGk", st)


class TestBisect(TestCaseWithDirState):
    """Test the ability to bisect into the disk format."""

    def assertBisect(self, expected_map, map_keys, state, paths):
        """Assert that bisecting for paths returns the right result.

        :param expected_map: A map from key => entry value
        :param map_keys: The keys to expect for each path
        :param state: The DirState object.
        :param paths: A list of paths, these will automatically be split into
                      (dir, name) tuples, and sorted according to how _bisect
                      requires.
        """
        result = state._bisect(paths)
        # For now, results are just returned in whatever order we read them.
        # We could sort by (dir, name, file_id) or something like that, but in
        # the end it would still be fairly arbitrary, and we don't want the
        # extra overhead if we can avoid it. So sort everything to make sure
        # equality is true
        self.assertEqual(len(map_keys), len(paths))
        expected = {}
        for path, keys in zip(paths, map_keys, strict=False):
            if keys is None:
                # This should not be present in the output
                continue
            expected[path] = sorted(expected_map[k] for k in keys)

        # The returned values are just arranged randomly based on when they
        # were read, for testing, make sure it is properly sorted.
        for path in result:
            result[path].sort()

        self.assertEqual(expected, result)

    def assertBisectDirBlocks(self, expected_map, map_keys, state, paths):
        """Assert that bisecting for dirbblocks returns the right result.

        :param expected_map: A map from key => expected values
        :param map_keys: A nested list of paths we expect to be returned.
            Something like [['a', 'b', 'f'], ['b/c', 'b/d']]
        :param state: The DirState object.
        :param paths: A list of directories
        """
        result = state._bisect_dirblocks(paths)
        self.assertEqual(len(map_keys), len(paths))
        expected = {}
        for path, keys in zip(paths, map_keys, strict=False):
            if keys is None:
                # This should not be present in the output
                continue
            expected[path] = sorted(expected_map[k] for k in keys)
        for path in result:
            result[path].sort()

        self.assertEqual(expected, result)

    def assertBisectRecursive(self, expected_map, map_keys, state, paths):
        """Assert the return value of a recursive bisection.

        :param expected_map: A map from key => entry value
        :param map_keys: A list of paths we expect to be returned.
            Something like ['a', 'b', 'f', 'b/d', 'b/d2']
        :param state: The DirState object.
        :param paths: A list of files and directories. It will be broken up
            into (dir, name) pairs and sorted before calling _bisect_recursive.
        """
        expected = {}
        for key in map_keys:
            entry = expected_map[key]
            dir_name_id, trees_info = entry
            expected[dir_name_id] = trees_info

        result = state._bisect_recursive(paths)

        self.assertEqual(expected, result)

    def test_bisect_each(self):
        """Find a single record using bisect."""
        _tree, state, expected = self.create_basic_dirstate()

        # Bisect should return the rows for the specified files.
        self.assertBisect(expected, [[b""]], state, [b""])
        self.assertBisect(expected, [[b"a"]], state, [b"a"])
        self.assertBisect(expected, [[b"b"]], state, [b"b"])
        self.assertBisect(expected, [[b"b/c"]], state, [b"b/c"])
        self.assertBisect(expected, [[b"b/d"]], state, [b"b/d"])
        self.assertBisect(expected, [[b"b/d/e"]], state, [b"b/d/e"])
        self.assertBisect(expected, [[b"b-c"]], state, [b"b-c"])
        self.assertBisect(expected, [[b"f"]], state, [b"f"])

    def test_bisect_multi(self):
        """Bisect can be used to find multiple records at the same time."""
        _tree, state, expected = self.create_basic_dirstate()
        # Bisect should be capable of finding multiple entries at the same time
        self.assertBisect(expected, [[b"a"], [b"b"], [b"f"]], state, [b"a", b"b", b"f"])
        self.assertBisect(
            expected, [[b"f"], [b"b/d"], [b"b/d/e"]], state, [b"f", b"b/d", b"b/d/e"]
        )
        self.assertBisect(
            expected, [[b"b"], [b"b-c"], [b"b/c"]], state, [b"b", b"b-c", b"b/c"]
        )

    def test_bisect_one_page(self):
        """Test bisect when there is only 1 page to read."""
        _tree, state, expected = self.create_basic_dirstate()
        state._bisect_page_size = 5000
        self.assertBisect(expected, [[b""]], state, [b""])
        self.assertBisect(expected, [[b"a"]], state, [b"a"])
        self.assertBisect(expected, [[b"b"]], state, [b"b"])
        self.assertBisect(expected, [[b"b/c"]], state, [b"b/c"])
        self.assertBisect(expected, [[b"b/d"]], state, [b"b/d"])
        self.assertBisect(expected, [[b"b/d/e"]], state, [b"b/d/e"])
        self.assertBisect(expected, [[b"b-c"]], state, [b"b-c"])
        self.assertBisect(expected, [[b"f"]], state, [b"f"])
        self.assertBisect(expected, [[b"a"], [b"b"], [b"f"]], state, [b"a", b"b", b"f"])
        self.assertBisect(
            expected, [[b"b/d"], [b"b/d/e"], [b"f"]], state, [b"b/d", b"b/d/e", b"f"]
        )
        self.assertBisect(
            expected, [[b"b"], [b"b/c"], [b"b-c"]], state, [b"b", b"b/c", b"b-c"]
        )

    def test_bisect_duplicate_paths(self):
        """When bisecting for a path, handle multiple entries."""
        _tree, state, expected = self.create_duplicated_dirstate()

        # Now make sure that both records are properly returned.
        self.assertBisect(expected, [[b""]], state, [b""])
        self.assertBisect(expected, [[b"a", b"a2"]], state, [b"a"])
        self.assertBisect(expected, [[b"b", b"b2"]], state, [b"b"])
        self.assertBisect(expected, [[b"b/c", b"b/c2"]], state, [b"b/c"])
        self.assertBisect(expected, [[b"b/d", b"b/d2"]], state, [b"b/d"])
        self.assertBisect(expected, [[b"b/d/e", b"b/d/e2"]], state, [b"b/d/e"])
        self.assertBisect(expected, [[b"b-c", b"b-c2"]], state, [b"b-c"])
        self.assertBisect(expected, [[b"f", b"f2"]], state, [b"f"])

    def test_bisect_page_size_too_small(self):
        """If the page size is too small, we will auto increase it."""
        _tree, state, expected = self.create_basic_dirstate()
        state._bisect_page_size = 50
        self.assertBisect(expected, [None], state, [b"b/e"])
        self.assertBisect(expected, [[b"a"]], state, [b"a"])
        self.assertBisect(expected, [[b"b"]], state, [b"b"])
        self.assertBisect(expected, [[b"b/c"]], state, [b"b/c"])
        self.assertBisect(expected, [[b"b/d"]], state, [b"b/d"])
        self.assertBisect(expected, [[b"b/d/e"]], state, [b"b/d/e"])
        self.assertBisect(expected, [[b"b-c"]], state, [b"b-c"])
        self.assertBisect(expected, [[b"f"]], state, [b"f"])

    def test_bisect_missing(self):
        """Test that bisect return None if it cannot find a path."""
        _tree, state, expected = self.create_basic_dirstate()
        self.assertBisect(expected, [None], state, [b"foo"])
        self.assertBisect(expected, [None], state, [b"b/foo"])
        self.assertBisect(expected, [None], state, [b"bar/foo"])
        self.assertBisect(expected, [None], state, [b"b-c/foo"])

        self.assertBisect(
            expected, [[b"a"], None, [b"b/d"]], state, [b"a", b"foo", b"b/d"]
        )

    def test_bisect_rename(self):
        """Check that we find a renamed row."""
        _tree, state, expected = self.create_renamed_dirstate()

        # Search for the pre and post renamed entries
        self.assertBisect(expected, [[b"a"]], state, [b"a"])
        self.assertBisect(expected, [[b"b/g"]], state, [b"b/g"])
        self.assertBisect(expected, [[b"b/d"]], state, [b"b/d"])
        self.assertBisect(expected, [[b"h"]], state, [b"h"])

        # What about b/d/e? shouldn't that also get 2 directory entries?
        self.assertBisect(expected, [[b"b/d/e"]], state, [b"b/d/e"])
        self.assertBisect(expected, [[b"h/e"]], state, [b"h/e"])

    def test_bisect_dirblocks(self):
        _tree, state, expected = self.create_duplicated_dirstate()
        self.assertBisectDirBlocks(
            expected,
            [[b"", b"a", b"a2", b"b", b"b2", b"b-c", b"b-c2", b"f", b"f2"]],
            state,
            [b""],
        )
        self.assertBisectDirBlocks(
            expected, [[b"b/c", b"b/c2", b"b/d", b"b/d2"]], state, [b"b"]
        )
        self.assertBisectDirBlocks(expected, [[b"b/d/e", b"b/d/e2"]], state, [b"b/d"])
        self.assertBisectDirBlocks(
            expected,
            [
                [b"", b"a", b"a2", b"b", b"b2", b"b-c", b"b-c2", b"f", b"f2"],
                [b"b/c", b"b/c2", b"b/d", b"b/d2"],
                [b"b/d/e", b"b/d/e2"],
            ],
            state,
            [b"", b"b", b"b/d"],
        )

    def test_bisect_dirblocks_missing(self):
        _tree, state, expected = self.create_basic_dirstate()
        self.assertBisectDirBlocks(
            expected, [[b"b/d/e"], None], state, [b"b/d", b"b/e"]
        )
        # Files don't show up in this search
        self.assertBisectDirBlocks(expected, [None], state, [b"a"])
        self.assertBisectDirBlocks(expected, [None], state, [b"b/c"])
        self.assertBisectDirBlocks(expected, [None], state, [b"c"])
        self.assertBisectDirBlocks(expected, [None], state, [b"b/d/e"])
        self.assertBisectDirBlocks(expected, [None], state, [b"f"])

    def test_bisect_recursive_each(self):
        _tree, state, expected = self.create_basic_dirstate()
        self.assertBisectRecursive(expected, [b"a"], state, [b"a"])
        self.assertBisectRecursive(expected, [b"b/c"], state, [b"b/c"])
        self.assertBisectRecursive(expected, [b"b/d/e"], state, [b"b/d/e"])
        self.assertBisectRecursive(expected, [b"b-c"], state, [b"b-c"])
        self.assertBisectRecursive(expected, [b"b/d", b"b/d/e"], state, [b"b/d"])
        self.assertBisectRecursive(
            expected, [b"b", b"b/c", b"b/d", b"b/d/e"], state, [b"b"]
        )
        self.assertBisectRecursive(
            expected,
            [b"", b"a", b"b", b"b-c", b"f", b"b/c", b"b/d", b"b/d/e"],
            state,
            [b""],
        )

    def test_bisect_recursive_multiple(self):
        _tree, state, expected = self.create_basic_dirstate()
        self.assertBisectRecursive(expected, [b"a", b"b/c"], state, [b"a", b"b/c"])
        self.assertBisectRecursive(
            expected, [b"b/d", b"b/d/e"], state, [b"b/d", b"b/d/e"]
        )

    def test_bisect_recursive_missing(self):
        _tree, state, expected = self.create_basic_dirstate()
        self.assertBisectRecursive(expected, [], state, [b"d"])
        self.assertBisectRecursive(expected, [], state, [b"b/e"])
        self.assertBisectRecursive(expected, [], state, [b"g"])
        self.assertBisectRecursive(expected, [b"a"], state, [b"a", b"g"])

    def test_bisect_recursive_renamed(self):
        _tree, state, expected = self.create_renamed_dirstate()

        # Looking for either renamed item should find the other
        self.assertBisectRecursive(expected, [b"a", b"b/g"], state, [b"a"])
        self.assertBisectRecursive(expected, [b"a", b"b/g"], state, [b"b/g"])
        # Looking in the containing directory should find the rename target,
        # and anything in a subdir of the renamed target.
        self.assertBisectRecursive(
            expected,
            [b"a", b"b", b"b/c", b"b/d", b"b/d/e", b"b/g", b"h", b"h/e"],
            state,
            [b"b"],
        )


class TestDirstateValidation(TestCaseWithDirState):
    def test_validate_correct_dirstate(self):
        state = self.create_complex_dirstate()
        state._validate()
        state.unlock()
        # and make sure we can also validate with a read lock
        state.lock_read()
        try:
            state._validate()
        finally:
            state.unlock()

    def test_dirblock_not_sorted(self):
        _tree, state, _expected = self.create_renamed_dirstate()
        state._read_dirblocks_if_needed()
        last_dirblock = state._dirblocks[-1]
        # we're appending to the dirblock, but this name comes before some of
        # the existing names; that's wrong
        last_dirblock[1].append(
            (
                (b"h", b"aaaa", b"a-id"),
                [(b"a", b"", 0, False, b""), (b"a", b"", 0, False, b"")],
            )
        )
        e = self.assertRaises(AssertionError, state._validate)
        self.assertContainsRe(str(e), "not sorted")

    def test_dirblock_name_mismatch(self):
        _tree, state, _expected = self.create_renamed_dirstate()
        state._read_dirblocks_if_needed()
        last_dirblock = state._dirblocks[-1]
        # add an entry with the wrong directory name
        last_dirblock[1].append(
            (
                (b"", b"z", b"a-id"),
                [(b"a", b"", 0, False, b""), (b"a", b"", 0, False, b"")],
            )
        )
        e = self.assertRaises(AssertionError, state._validate)
        self.assertContainsRe(str(e), "doesn't match directory name")

    def test_dirblock_missing_rename(self):
        _tree, state, _expected = self.create_renamed_dirstate()
        state._read_dirblocks_if_needed()
        last_dirblock = state._dirblocks[-1]
        # make another entry for a-id, without a correct 'r' pointer to
        # the real occurrence in the working tree
        last_dirblock[1].append(
            (
                (b"h", b"z", b"a-id"),
                [(b"a", b"", 0, False, b""), (b"a", b"", 0, False, b"")],
            )
        )
        e = self.assertRaises(AssertionError, state._validate)
        self.assertContainsRe(str(e), "file a-id is absent in row")


class TestDirstateTreeReference(TestCaseWithDirState):
    def test_reference_revision_is_none(self):
        tree = self.make_branch_and_tree("tree", format="development-subtree")
        subtree = self.make_branch_and_tree(
            "tree/subtree", format="development-subtree"
        )
        subtree.set_root_id(b"subtree")
        tree.add_reference(subtree)
        tree.add("subtree")
        state = dirstate.DirState.from_tree(tree, "dirstate")
        key = (b"", b"subtree", b"subtree")
        expected = (
            b"",
            [(key, [(b"t", b"", 0, False, b"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")])],
        )

        try:
            self.assertEqual(expected, state._find_block(key))
        finally:
            state.unlock()


class TestDiscardMergeParents(TestCaseWithDirState):
    def test_discard_no_parents(self):
        # This should be a no-op
        state = self.create_empty_dirstate()
        self.addCleanup(state.unlock)
        state._discard_merge_parents()
        state._validate()

    def test_discard_one_parent(self):
        # No-op
        packed_stat = b"AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk"
        root_entry_direntry = (
            (b"", b"", b"a-root-value"),
            [
                (b"d", b"", 0, False, packed_stat),
                (b"d", b"", 0, False, packed_stat),
            ],
        )
        dirblocks = []
        dirblocks.append((b"", [root_entry_direntry]))
        dirblocks.append((b"", []))

        state = self.create_empty_dirstate()
        self.addCleanup(state.unlock)
        state._set_data([b"parent-id"], dirblocks[:])
        state._validate()

        state._discard_merge_parents()
        state._validate()
        self.assertEqual(dirblocks, state._dirblocks)

    def test_discard_simple(self):
        # No-op
        packed_stat = b"AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk"
        root_entry_direntry = (
            (b"", b"", b"a-root-value"),
            [
                (b"d", b"", 0, False, packed_stat),
                (b"d", b"", 0, False, packed_stat),
                (b"d", b"", 0, False, packed_stat),
            ],
        )
        expected_root_entry_direntry = (
            (b"", b"", b"a-root-value"),
            [
                (b"d", b"", 0, False, packed_stat),
                (b"d", b"", 0, False, packed_stat),
            ],
        )
        dirblocks = []
        dirblocks.append((b"", [root_entry_direntry]))
        dirblocks.append((b"", []))

        state = self.create_empty_dirstate()
        self.addCleanup(state.unlock)
        state._set_data([b"parent-id", b"merged-id"], dirblocks[:])
        state._validate()

        # This should strip of the extra column
        state._discard_merge_parents()
        state._validate()
        expected_dirblocks = [(b"", [expected_root_entry_direntry]), (b"", [])]
        self.assertEqual(expected_dirblocks, state._dirblocks)

    def test_discard_absent(self):
        """If entries are only in a merge, discard should remove the entries."""
        null_stat = dirstate.DirState.NULLSTAT
        present_dir = (b"d", b"", 0, False, null_stat)
        present_file = (b"f", b"", 0, False, null_stat)
        absent = dirstate.DirState.NULL_PARENT_DETAILS
        root_key = (b"", b"", b"a-root-value")
        file_in_root_key = (b"", b"file-in-root", b"a-file-id")
        file_in_merged_key = (b"", b"file-in-merged", b"b-file-id")
        dirblocks = [
            (b"", [(root_key, [present_dir, present_dir, present_dir])]),
            (
                b"",
                [
                    (file_in_merged_key, [absent, absent, present_file]),
                    (file_in_root_key, [present_file, present_file, present_file]),
                ],
            ),
        ]

        state = self.create_empty_dirstate()
        self.addCleanup(state.unlock)
        state._set_data([b"parent-id", b"merged-id"], dirblocks[:])
        state._validate()

        exp_dirblocks = [
            (b"", [(root_key, [present_dir, present_dir])]),
            (
                b"",
                [
                    (file_in_root_key, [present_file, present_file]),
                ],
            ),
        ]
        state._discard_merge_parents()
        state._validate()
        self.assertEqual(exp_dirblocks, state._dirblocks)

    def test_discard_renamed(self):
        null_stat = dirstate.DirState.NULLSTAT
        present_dir = (b"d", b"", 0, False, null_stat)
        present_file = (b"f", b"", 0, False, null_stat)
        absent = dirstate.DirState.NULL_PARENT_DETAILS
        root_key = (b"", b"", b"a-root-value")
        file_in_root_key = (b"", b"file-in-root", b"a-file-id")
        # Renamed relative to parent
        file_rename_s_key = (b"", b"file-s", b"b-file-id")
        file_rename_t_key = (b"", b"file-t", b"b-file-id")
        # And one that is renamed between the parents, but absent in this
        key_in_1 = (b"", b"file-in-1", b"c-file-id")
        key_in_2 = (b"", b"file-in-2", b"c-file-id")

        dirblocks = [
            (b"", [(root_key, [present_dir, present_dir, present_dir])]),
            (
                b"",
                [
                    (
                        key_in_1,
                        [absent, present_file, (b"r", b"file-in-2", b"c-file-id")],
                    ),
                    (
                        key_in_2,
                        [absent, (b"r", b"file-in-1", b"c-file-id"), present_file],
                    ),
                    (file_in_root_key, [present_file, present_file, present_file]),
                    (
                        file_rename_s_key,
                        [(b"r", b"file-t", b"b-file-id"), absent, present_file],
                    ),
                    (
                        file_rename_t_key,
                        [present_file, absent, (b"r", b"file-s", b"b-file-id")],
                    ),
                ],
            ),
        ]
        exp_dirblocks = [
            (b"", [(root_key, [present_dir, present_dir])]),
            (
                b"",
                [
                    (key_in_1, [absent, present_file]),
                    (file_in_root_key, [present_file, present_file]),
                    (file_rename_t_key, [present_file, absent]),
                ],
            ),
        ]
        state = self.create_empty_dirstate()
        self.addCleanup(state.unlock)
        state._set_data([b"parent-id", b"merged-id"], dirblocks[:])
        state._validate()

        state._discard_merge_parents()
        state._validate()
        self.assertEqual(exp_dirblocks, state._dirblocks)

    def test_discard_all_subdir(self):
        null_stat = dirstate.DirState.NULLSTAT
        present_dir = (b"d", b"", 0, False, null_stat)
        present_file = (b"f", b"", 0, False, null_stat)
        absent = dirstate.DirState.NULL_PARENT_DETAILS
        root_key = (b"", b"", b"a-root-value")
        subdir_key = (b"", b"sub", b"dir-id")
        child1_key = (b"sub", b"child1", b"child1-id")
        child2_key = (b"sub", b"child2", b"child2-id")
        child3_key = (b"sub", b"child3", b"child3-id")

        dirblocks = [
            (b"", [(root_key, [present_dir, present_dir, present_dir])]),
            (b"", [(subdir_key, [present_dir, present_dir, present_dir])]),
            (
                b"sub",
                [
                    (child1_key, [absent, absent, present_file]),
                    (child2_key, [absent, absent, present_file]),
                    (child3_key, [absent, absent, present_file]),
                ],
            ),
        ]
        exp_dirblocks = [
            (b"", [(root_key, [present_dir, present_dir])]),
            (b"", [(subdir_key, [present_dir, present_dir])]),
            (b"sub", []),
        ]
        state = self.create_empty_dirstate()
        self.addCleanup(state.unlock)
        state._set_data([b"parent-id", b"merged-id"], dirblocks[:])
        state._validate()

        state._discard_merge_parents()
        state._validate()
        self.assertEqual(exp_dirblocks, state._dirblocks)


class Test_InvEntryToDetails(tests.TestCase):
    def assertDetails(self, expected, inv_entry):
        details = dirstate.DirState._inv_entry_to_details(inv_entry)
        self.assertEqual(expected, details)
        # details should always allow join() and always be a plain str when
        # finished
        (minikind, fingerprint, _size, _executable, tree_data) = details
        self.assertIsInstance(minikind, bytes)
        self.assertIsInstance(fingerprint, bytes)
        self.assertIsInstance(tree_data, bytes)

    def test_unicode_symlink(self):
        inv_entry = inventory.InventoryLink(
            b"link-file-id", "nam\N{EURO SIGN}e", b"link-parent-id"
        )
        inv_entry.revision = b"link-revision-id"
        target = "link-targ\N{EURO SIGN}t"
        inv_entry.symlink_target = target
        self.assertDetails(
            (b"l", target.encode("UTF-8"), 0, False, b"link-revision-id"), inv_entry
        )


class TestSHA1Provider(tests.TestCaseInTempDir):
    def test_sha1provider_is_an_interface(self):
        p = dirstate.SHA1Provider()
        self.assertRaises(NotImplementedError, p.sha1, "foo")
        self.assertRaises(NotImplementedError, p.stat_and_sha1, "foo")

    def test_defaultsha1provider_sha1(self):
        text = b"test\r\nwith\nall\rpossible line endings\r\n"
        self.build_tree_contents([("foo", text)])
        expected_sha = osutils.sha_string(text)
        p = dirstate.DefaultSHA1Provider()
        self.assertEqual(expected_sha, p.sha1("foo"))

    def test_defaultsha1provider_stat_and_sha1(self):
        text = b"test\r\nwith\nall\rpossible line endings\r\n"
        self.build_tree_contents([("foo", text)])
        expected_sha = osutils.sha_string(text)
        p = dirstate.DefaultSHA1Provider()
        statvalue, sha1 = p.stat_and_sha1("foo")
        self.assertTrue(len(statvalue) >= 10)
        self.assertEqual(len(text), statvalue.st_size)
        self.assertEqual(expected_sha, sha1)


class _Repo:
    """A minimal api to get InventoryRevisionTree to work."""

    def __init__(self):
        default_format = controldir.format_registry.make_controldir("default")
        self._format = default_format.repository_format

    def lock_read(self):
        pass

    def unlock(self):
        pass


class TestUpdateBasisByDelta(tests.TestCase):
    def path_to_ie(self, path, file_id, rev_id, dir_ids):
        if path.endswith("/"):
            is_dir = True
            path = path[:-1]
        else:
            is_dir = False
        dirname, basename = osutils.split(path)
        try:
            dir_id = dir_ids[dirname]
        except KeyError:
            dir_id = osutils.basename(dirname).encode("utf-8") + b"-id"
        if is_dir:
            ie = inventory.InventoryDirectory(file_id, basename, dir_id)
            dir_ids[path] = file_id
        else:
            ie = inventory.InventoryFile(file_id, basename, dir_id)
            ie.text_size = 0
            ie.text_sha1 = b""
        ie.revision = rev_id
        return ie

    def create_tree_from_shape(self, rev_id, shape):
        dir_ids = {"": b"root-id"}
        inv = inventory.Inventory(b"root-id", rev_id)
        for info in shape:
            if len(info) == 2:
                path, file_id = info
                ie_rev_id = rev_id
            else:
                path, file_id, ie_rev_id = info
            if path == "":
                # Replace the root entry
                del inv._byid[inv.root.file_id]
                inv.root.file_id = file_id
                inv._byid[file_id] = inv.root
                dir_ids[""] = file_id
                continue
            inv.add(self.path_to_ie(path, file_id, ie_rev_id, dir_ids))
        return inventorytree.InventoryRevisionTree(_Repo(), inv, rev_id)

    def create_empty_dirstate(self):
        fd, path = tempfile.mkstemp(prefix="bzr-dirstate")
        self.addCleanup(os.remove, path)
        os.close(fd)
        state = dirstate.DirState.initialize(path)
        self.addCleanup(state.unlock)
        return state

    def create_inv_delta(self, delta, rev_id):
        """Translate a 'delta shape' into an actual InventoryDelta."""
        dir_ids = {"": b"root-id"}
        inv_delta = []
        for old_path, new_path, file_id in delta:
            if old_path is not None and old_path.endswith("/"):
                # Don't have to actually do anything for this, because only
                # new_path creates InventoryEntries
                old_path = old_path[:-1]
            if new_path is None:  # Delete
                inv_delta.append((old_path, None, file_id, None))
                continue
            ie = self.path_to_ie(new_path, file_id, rev_id, dir_ids)
            inv_delta.append((old_path, new_path, file_id, ie))
        return inv_delta

    def assertUpdate(self, active, basis, target):
        """Assert that update_basis_by_delta works how we want.

        Set up a DirState object with active_shape for tree 0, basis_shape for
        tree 1. Then apply the delta from basis_shape to target_shape,
        and assert that the DirState is still valid, and that its stored
        content matches the target_shape.
        """
        active_tree = self.create_tree_from_shape(b"active", active)
        basis_tree = self.create_tree_from_shape(b"basis", basis)
        target_tree = self.create_tree_from_shape(b"target", target)
        state = self.create_empty_dirstate()
        state.set_state_from_scratch(
            active_tree.root_inventory, [(b"basis", basis_tree)], []
        )
        delta = target_tree.root_inventory._make_delta(basis_tree.root_inventory)
        state.update_basis_by_delta(delta, b"target")
        state._validate()
        dirstate_tree = workingtree_4.DirStateRevisionTree(
            state, b"target", _Repo(), None
        )
        # The target now that delta has been applied should match the
        # RevisionTree
        self.assertEqual([], list(dirstate_tree.iter_changes(target_tree)))
        # And the dirblock state should be identical to the state if we created
        # it from scratch.
        state2 = self.create_empty_dirstate()
        state2.set_state_from_scratch(
            active_tree.root_inventory, [(b"target", target_tree)], []
        )
        self.assertEqual(state2._dirblocks, state._dirblocks)
        return state

    def assertBadDelta(self, active, basis, delta):
        """Test that we raise InconsistentDelta when appropriate.

        :param active: The active tree shape
        :param basis: The basis tree shape
        :param delta: A description of the delta to apply. Similar to the form
            for regular inventory deltas, but omitting the InventoryEntry.
            So adding a file is: (None, 'path', b'file-id')
            Adding a directory is: (None, 'path/', b'dir-id')
            Renaming a dir is: ('old/', 'new/', b'dir-id')
            etc.
        """
        active_tree = self.create_tree_from_shape(b"active", active)
        basis_tree = self.create_tree_from_shape(b"basis", basis)
        inv_delta = self.create_inv_delta(delta, b"target")
        state = self.create_empty_dirstate()
        state.set_state_from_scratch(
            active_tree.root_inventory, [(b"basis", basis_tree)], []
        )
        self.assertRaises(
            errors.InconsistentDelta, state.update_basis_by_delta, inv_delta, b"target"
        )
        # try:
        ##     state.update_basis_by_delta(inv_delta, b'target')
        # except errors.InconsistentDelta, e:
        ##     import pdb; pdb.set_trace()
        # else:
        ##     import pdb; pdb.set_trace()
        self.assertTrue(state._changes_aborted)

    def test_remove_file_matching_active_state(self):
        self.assertUpdate(
            active=[],
            basis=[("file", b"file-id")],
            target=[],
        )

    def test_remove_file_present_in_active_state(self):
        self.assertUpdate(
            active=[("file", b"file-id")],
            basis=[("file", b"file-id")],
            target=[],
        )

    def test_remove_file_present_elsewhere_in_active_state(self):
        self.assertUpdate(
            active=[("other-file", b"file-id")],
            basis=[("file", b"file-id")],
            target=[],
        )

    def test_remove_file_active_state_has_diff_file(self):
        self.assertUpdate(
            active=[("file", b"file-id-2")],
            basis=[("file", b"file-id")],
            target=[],
        )

    def test_remove_file_active_state_has_diff_file_and_file_elsewhere(self):
        self.assertUpdate(
            active=[("file", b"file-id-2"), ("other-file", b"file-id")],
            basis=[("file", b"file-id")],
            target=[],
        )

    def test_add_file_matching_active_state(self):
        self.assertUpdate(
            active=[("file", b"file-id")],
            basis=[],
            target=[("file", b"file-id")],
        )

    def test_add_file_in_empty_dir_not_matching_active_state(self):
        self.assertUpdate(
            active=[],
            basis=[("dir/", b"dir-id")],
            target=[("dir/", b"dir-id", b"basis"), ("dir/file", b"file-id")],
        )

    def test_add_file_missing_in_active_state(self):
        self.assertUpdate(
            active=[],
            basis=[],
            target=[("file", b"file-id")],
        )

    def test_add_file_elsewhere_in_active_state(self):
        self.assertUpdate(
            active=[("other-file", b"file-id")],
            basis=[],
            target=[("file", b"file-id")],
        )

    def test_add_file_active_state_has_diff_file_and_file_elsewhere(self):
        self.assertUpdate(
            active=[("other-file", b"file-id"), ("file", b"file-id-2")],
            basis=[],
            target=[("file", b"file-id")],
        )

    def test_rename_file_matching_active_state(self):
        self.assertUpdate(
            active=[("other-file", b"file-id")],
            basis=[("file", b"file-id")],
            target=[("other-file", b"file-id")],
        )

    def test_rename_file_missing_in_active_state(self):
        self.assertUpdate(
            active=[],
            basis=[("file", b"file-id")],
            target=[("other-file", b"file-id")],
        )

    def test_rename_file_present_elsewhere_in_active_state(self):
        self.assertUpdate(
            active=[("third", b"file-id")],
            basis=[("file", b"file-id")],
            target=[("other-file", b"file-id")],
        )

    def test_rename_file_active_state_has_diff_source_file(self):
        self.assertUpdate(
            active=[("file", b"file-id-2")],
            basis=[("file", b"file-id")],
            target=[("other-file", b"file-id")],
        )

    def test_rename_file_active_state_has_diff_target_file(self):
        self.assertUpdate(
            active=[("other-file", b"file-id-2")],
            basis=[("file", b"file-id")],
            target=[("other-file", b"file-id")],
        )

    def test_rename_file_active_has_swapped_files(self):
        self.assertUpdate(
            active=[("file", b"file-id"), ("other-file", b"file-id-2")],
            basis=[("file", b"file-id"), ("other-file", b"file-id-2")],
            target=[("file", b"file-id-2"), ("other-file", b"file-id")],
        )

    def test_rename_file_basis_has_swapped_files(self):
        self.assertUpdate(
            active=[("file", b"file-id"), ("other-file", b"file-id-2")],
            basis=[("file", b"file-id-2"), ("other-file", b"file-id")],
            target=[("file", b"file-id"), ("other-file", b"file-id-2")],
        )

    def test_rename_directory_with_contents(self):
        self.assertUpdate(  # active matches basis
            active=[("dir1/", b"dir-id"), ("dir1/file", b"file-id")],
            basis=[("dir1/", b"dir-id"), ("dir1/file", b"file-id")],
            target=[("dir2/", b"dir-id"), ("dir2/file", b"file-id")],
        )
        self.assertUpdate(  # active matches target
            active=[("dir2/", b"dir-id"), ("dir2/file", b"file-id")],
            basis=[("dir1/", b"dir-id"), ("dir1/file", b"file-id")],
            target=[("dir2/", b"dir-id"), ("dir2/file", b"file-id")],
        )
        self.assertUpdate(  # active empty
            active=[],
            basis=[("dir1/", b"dir-id"), ("dir1/file", b"file-id")],
            target=[("dir2/", b"dir-id"), ("dir2/file", b"file-id")],
        )
        self.assertUpdate(  # active present at other location
            active=[("dir3/", b"dir-id"), ("dir3/file", b"file-id")],
            basis=[("dir1/", b"dir-id"), ("dir1/file", b"file-id")],
            target=[("dir2/", b"dir-id"), ("dir2/file", b"file-id")],
        )
        self.assertUpdate(  # active has different ids
            active=[
                ("dir1/", b"dir1-id"),
                ("dir1/file", b"file1-id"),
                ("dir2/", b"dir2-id"),
                ("dir2/file", b"file2-id"),
            ],
            basis=[("dir1/", b"dir-id"), ("dir1/file", b"file-id")],
            target=[("dir2/", b"dir-id"), ("dir2/file", b"file-id")],
        )

    def test_invalid_file_not_present(self):
        self.assertBadDelta(
            active=[("file", b"file-id")],
            basis=[("file", b"file-id")],
            delta=[("other-file", "file", b"file-id")],
        )

    def test_invalid_new_id_same_path(self):
        # The bad entry comes after
        self.assertBadDelta(
            active=[("file", b"file-id")],
            basis=[("file", b"file-id")],
            delta=[(None, "file", b"file-id-2")],
        )
        # The bad entry comes first
        self.assertBadDelta(
            active=[("file", b"file-id-2")],
            basis=[("file", b"file-id-2")],
            delta=[(None, "file", b"file-id")],
        )

    def test_invalid_existing_id(self):
        self.assertBadDelta(
            active=[("file", b"file-id")],
            basis=[("file", b"file-id")],
            delta=[(None, "file", b"file-id")],
        )

    def test_invalid_parent_missing(self):
        self.assertBadDelta(
            active=[], basis=[], delta=[(None, "path/path2", b"file-id")]
        )
        # Note: we force the active tree to have the directory, by knowing how
        #       path_to_ie handles entries with missing parents
        self.assertBadDelta(
            active=[("path/", b"path-id")],
            basis=[],
            delta=[(None, "path/path2", b"file-id")],
        )
        self.assertBadDelta(
            active=[("path/", b"path-id"), ("path/path2", b"file-id")],
            basis=[],
            delta=[(None, "path/path2", b"file-id")],
        )

    def test_renamed_dir_same_path(self):
        # We replace the parent directory, with another parent dir. But the C
        # file doesn't look like it has been moved.
        self.assertUpdate(  # Same as basis
            active=[("dir/", b"A-id"), ("dir/B", b"B-id")],
            basis=[("dir/", b"A-id"), ("dir/B", b"B-id")],
            target=[("dir/", b"C-id"), ("dir/B", b"B-id")],
        )
        self.assertUpdate(  # Same as target
            active=[("dir/", b"C-id"), ("dir/B", b"B-id")],
            basis=[("dir/", b"A-id"), ("dir/B", b"B-id")],
            target=[("dir/", b"C-id"), ("dir/B", b"B-id")],
        )
        self.assertUpdate(  # empty active
            active=[],
            basis=[("dir/", b"A-id"), ("dir/B", b"B-id")],
            target=[("dir/", b"C-id"), ("dir/B", b"B-id")],
        )
        self.assertUpdate(  # different active
            active=[("dir/", b"D-id"), ("dir/B", b"B-id")],
            basis=[("dir/", b"A-id"), ("dir/B", b"B-id")],
            target=[("dir/", b"C-id"), ("dir/B", b"B-id")],
        )

    def test_parent_child_swap(self):
        self.assertUpdate(  # Same as basis
            active=[("A/", b"A-id"), ("A/B/", b"B-id"), ("A/B/C", b"C-id")],
            basis=[("A/", b"A-id"), ("A/B/", b"B-id"), ("A/B/C", b"C-id")],
            target=[("A/", b"B-id"), ("A/B/", b"A-id"), ("A/B/C", b"C-id")],
        )
        self.assertUpdate(  # Same as target
            active=[("A/", b"B-id"), ("A/B/", b"A-id"), ("A/B/C", b"C-id")],
            basis=[("A/", b"A-id"), ("A/B/", b"B-id"), ("A/B/C", b"C-id")],
            target=[("A/", b"B-id"), ("A/B/", b"A-id"), ("A/B/C", b"C-id")],
        )
        self.assertUpdate(  # empty active
            active=[],
            basis=[("A/", b"A-id"), ("A/B/", b"B-id"), ("A/B/C", b"C-id")],
            target=[("A/", b"B-id"), ("A/B/", b"A-id"), ("A/B/C", b"C-id")],
        )
        self.assertUpdate(  # different active
            active=[("D/", b"A-id"), ("D/E/", b"B-id"), ("F", b"C-id")],
            basis=[("A/", b"A-id"), ("A/B/", b"B-id"), ("A/B/C", b"C-id")],
            target=[("A/", b"B-id"), ("A/B/", b"A-id"), ("A/B/C", b"C-id")],
        )

    def test_change_root_id(self):
        self.assertUpdate(  # same as basis
            active=[("", b"root-id"), ("file", b"file-id")],
            basis=[("", b"root-id"), ("file", b"file-id")],
            target=[("", b"target-root-id"), ("file", b"file-id")],
        )
        self.assertUpdate(  # same as target
            active=[("", b"target-root-id"), ("file", b"file-id")],
            basis=[("", b"root-id"), ("file", b"file-id")],
            target=[("", b"target-root-id"), ("file", b"root-id")],
        )
        self.assertUpdate(  # all different
            active=[("", b"active-root-id"), ("file", b"file-id")],
            basis=[("", b"root-id"), ("file", b"file-id")],
            target=[("", b"target-root-id"), ("file", b"root-id")],
        )

    def test_change_file_absent_in_active(self):
        self.assertUpdate(
            active=[], basis=[("file", b"file-id")], target=[("file", b"file-id")]
        )

    def test_invalid_changed_file(self):
        self.assertBadDelta(  # Not present in basis
            active=[("file", b"file-id")],
            basis=[],
            delta=[("file", "file", b"file-id")],
        )
        self.assertBadDelta(  # present at another location in basis
            active=[("file", b"file-id")],
            basis=[("other-file", b"file-id")],
            delta=[("file", "file", b"file-id")],
        )
