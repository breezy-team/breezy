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

from bzrlib import (
    controldir,
    dirstate,
    errors,
    inventory,
    memorytree,
    osutils,
    revision as _mod_revision,
    revisiontree,
    tests,
    workingtree_4,
    )
from bzrlib.tests import (
    features,
    test_osutils,
    )
from bzrlib.tests.scenarios import load_tests_apply_scenarios


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


load_tests = load_tests_apply_scenarios


class TestCaseWithDirState(tests.TestCaseWithTransport):
    """Helper functions for creating DirState objects with various content."""

    scenarios = test_osutils.dir_reader_scenarios()

    # Set by load_tests
    _dir_reader_class = None
    _native_to_unicode = None # Not used yet

    def setUp(self):
        super(TestCaseWithDirState, self).setUp()
        self.overrideAttr(osutils,
                          '_selected_dir_reader', self._dir_reader_class())

    def create_empty_dirstate(self):
        """Return a locked but empty dirstate"""
        state = dirstate.DirState.initialize('dirstate')
        return state

    def create_dirstate_with_root(self):
        """Return a write-locked state with a single root entry."""
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_entry_direntry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat),
            ]
        dirblocks = []
        dirblocks.append(('', [root_entry_direntry]))
        dirblocks.append(('', []))
        state = self.create_empty_dirstate()
        try:
            state._set_data([], dirblocks)
            state._validate()
        except:
            state.unlock()
            raise
        return state

    def create_dirstate_with_root_and_subdir(self):
        """Return a locked DirState with a root and a subdir"""
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        subdir_entry = ('', 'subdir', 'subdir-id'), [
            ('d', '', 0, False, packed_stat),
            ]
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
        """This dirstate contains multiple files and directories.

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
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        null_sha = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
        root_entry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat),
            ]
        a_entry = ('', 'a', 'a-dir'), [
            ('d', '', 0, False, packed_stat),
            ]
        b_entry = ('', 'b', 'b-dir'), [
            ('d', '', 0, False, packed_stat),
            ]
        c_entry = ('', 'c', 'c-file'), [
            ('f', null_sha, 10, False, packed_stat),
            ]
        d_entry = ('', 'd', 'd-file'), [
            ('f', null_sha, 20, False, packed_stat),
            ]
        e_entry = ('a', 'e', 'e-dir'), [
            ('d', '', 0, False, packed_stat),
            ]
        f_entry = ('a', 'f', 'f-file'), [
            ('f', null_sha, 30, False, packed_stat),
            ]
        g_entry = ('b', 'g', 'g-file'), [
            ('f', null_sha, 30, False, packed_stat),
            ]
        h_entry = ('b', 'h\xc3\xa5', 'h-\xc3\xa5-file'), [
            ('f', null_sha, 40, False, packed_stat),
            ]
        dirblocks = []
        dirblocks.append(('', [root_entry]))
        dirblocks.append(('', [a_entry, b_entry, c_entry, d_entry]))
        dirblocks.append(('a', [e_entry, f_entry]))
        dirblocks.append(('b', [g_entry, h_entry]))
        state = dirstate.DirState.initialize('dirstate')
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
            self.assertEqual(expected_result[0],  state.get_parent_ids())
            # there should be no ghosts in this tree.
            self.assertEqual([], state.get_ghosts())
            # there should be one fileid in this tree - the root of the tree.
            self.assertEqual(expected_result[1], list(state._iter_entries()))
            state.save()
        finally:
            state.unlock()
        del state
        state = dirstate.DirState.on_file('dirstate')
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
        tree = self.make_branch_and_tree('tree')
        paths = ['a', 'b/', 'b/c', 'b/d/', 'b/d/e', 'b-c', 'f']
        file_ids = ['a-id', 'b-id', 'c-id', 'd-id', 'e-id', 'b-c-id', 'f-id']
        self.build_tree(['tree/' + p for p in paths])
        tree.set_root_id('TREE_ROOT')
        tree.add([p.rstrip('/') for p in paths], file_ids)
        tree.commit('initial', rev_id='rev-1')
        revision_id = 'rev-1'
        # a_packed_stat = dirstate.pack_stat(os.stat('tree/a'))
        t = self.get_transport('tree')
        a_text = t.get_bytes('a')
        a_sha = osutils.sha_string(a_text)
        a_len = len(a_text)
        # b_packed_stat = dirstate.pack_stat(os.stat('tree/b'))
        # c_packed_stat = dirstate.pack_stat(os.stat('tree/b/c'))
        c_text = t.get_bytes('b/c')
        c_sha = osutils.sha_string(c_text)
        c_len = len(c_text)
        # d_packed_stat = dirstate.pack_stat(os.stat('tree/b/d'))
        # e_packed_stat = dirstate.pack_stat(os.stat('tree/b/d/e'))
        e_text = t.get_bytes('b/d/e')
        e_sha = osutils.sha_string(e_text)
        e_len = len(e_text)
        b_c_text = t.get_bytes('b-c')
        b_c_sha = osutils.sha_string(b_c_text)
        b_c_len = len(b_c_text)
        # f_packed_stat = dirstate.pack_stat(os.stat('tree/f'))
        f_text = t.get_bytes('f')
        f_sha = osutils.sha_string(f_text)
        f_len = len(f_text)
        null_stat = dirstate.DirState.NULLSTAT
        expected = {
            '':(('', '', 'TREE_ROOT'), [
                  ('d', '', 0, False, null_stat),
                  ('d', '', 0, False, revision_id),
                ]),
            'a':(('', 'a', 'a-id'), [
                   ('f', '', 0, False, null_stat),
                   ('f', a_sha, a_len, False, revision_id),
                 ]),
            'b':(('', 'b', 'b-id'), [
                  ('d', '', 0, False, null_stat),
                  ('d', '', 0, False, revision_id),
                 ]),
            'b/c':(('b', 'c', 'c-id'), [
                    ('f', '', 0, False, null_stat),
                    ('f', c_sha, c_len, False, revision_id),
                   ]),
            'b/d':(('b', 'd', 'd-id'), [
                    ('d', '', 0, False, null_stat),
                    ('d', '', 0, False, revision_id),
                   ]),
            'b/d/e':(('b/d', 'e', 'e-id'), [
                      ('f', '', 0, False, null_stat),
                      ('f', e_sha, e_len, False, revision_id),
                     ]),
            'b-c':(('', 'b-c', 'b-c-id'), [
                      ('f', '', 0, False, null_stat),
                      ('f', b_c_sha, b_c_len, False, revision_id),
                     ]),
            'f':(('', 'f', 'f-id'), [
                  ('f', '', 0, False, null_stat),
                  ('f', f_sha, f_len, False, revision_id),
                 ]),
        }
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        try:
            state.save()
        finally:
            state.unlock()
        # Use a different object, to make sure nothing is pre-cached in memory.
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        self.addCleanup(state.unlock)
        self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                         state._dirblock_state)
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
        tree.unversion(['f-id', 'b-c-id', 'e-id', 'd-id', 'c-id', 'b-id', 'a-id'])
        tree.add(['a', 'b', 'b/c', 'b/d', 'b/d/e', 'b-c', 'f'],
                 ['a-id2', 'b-id2', 'c-id2', 'd-id2', 'e-id2', 'b-c-id2', 'f-id2'])

        # Update the expected dictionary.
        for path in ['a', 'b', 'b/c', 'b/d', 'b/d/e', 'b-c', 'f']:
            orig = expected[path]
            path2 = path + '2'
            # This record was deleted in the current tree
            expected[path] = (orig[0], [dirstate.DirState.NULL_PARENT_DETAILS,
                                        orig[1][1]])
            new_key = (orig[0][0], orig[0][1], orig[0][2]+'2')
            # And didn't exist in the basis tree
            expected[path2] = (new_key, [orig[1][0],
                                         dirstate.DirState.NULL_PARENT_DETAILS])

        # We will replace the 'dirstate' file underneath 'state', but that is
        # okay as lock as we unlock 'state' first.
        state.unlock()
        try:
            new_state = dirstate.DirState.from_tree(tree, 'dirstate')
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
        tree.rename_one('a', 'b/g')
        # And a directory
        tree.rename_one('b/d', 'h')

        old_a = expected['a']
        expected['a'] = (old_a[0], [('r', 'b/g', 0, False, ''), old_a[1][1]])
        expected['b/g'] = (('b', 'g', 'a-id'), [old_a[1][0],
                                                ('r', 'a', 0, False, '')])
        old_d = expected['b/d']
        expected['b/d'] = (old_d[0], [('r', 'h', 0, False, ''), old_d[1][1]])
        expected['h'] = (('', 'h', 'd-id'), [old_d[1][0],
                                             ('r', 'b/d', 0, False, '')])

        old_e = expected['b/d/e']
        expected['b/d/e'] = (old_e[0], [('r', 'h/e', 0, False, ''),
                             old_e[1][1]])
        expected['h/e'] = (('h', 'e', 'e-id'), [old_e[1][0],
                                                ('r', 'b/d/e', 0, False, '')])

        state.unlock()
        try:
            new_state = dirstate.DirState.from_tree(tree, 'dirstate')
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
        tree = self.make_branch_and_tree('tree')
        expected_result = ([], [
            (('', '', tree.get_root_id()), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ])])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        state._validate()
        self.check_state_with_reopen(expected_result, state)

    def test_1_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post').encode('utf8')
        root_stat_pack = dirstate.pack_stat(os.stat(tree.basedir))
        expected_result = ([rev_id], [
            (('', '', tree.get_root_id()), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
              ('d', '', 0, False, rev_id), # first parent details
             ])])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)
        state.lock_read()
        try:
            state._validate()
        finally:
            state.unlock()

    def test_2_parents_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('first post')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        rev_id2 = tree2.commit('second post', allow_pointless=True)
        tree.merge_from_branch(tree2.branch)
        expected_result = ([rev_id, rev_id2], [
            (('', '', tree.get_root_id()), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
              ('d', '', 0, False, rev_id), # first parent details
              ('d', '', 0, False, rev_id), # second parent details
             ])])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)
        state.lock_read()
        try:
            state._validate()
        finally:
            state.unlock()

    def test_empty_unknowns_are_ignored_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are no files on disk and no parents
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/unknown'])
        expected_result = ([], [
            (('', '', tree.get_root_id()), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ])])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)

    def get_tree_with_a_file(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a file'])
        tree.add('a file', 'a-file-id')
        return tree

    def test_non_empty_no_parents_to_dirstate(self):
        """We should be able to create a dirstate for an empty tree."""
        # There are files on disk and no parents
        tree = self.get_tree_with_a_file()
        expected_result = ([], [
            (('', '', tree.get_root_id()), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ]),
            (('', 'a file', 'a-file-id'), # common
             [('f', '', 0, False, dirstate.DirState.NULLSTAT), # current
             ]),
            ])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)

    def test_1_parents_not_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.get_tree_with_a_file()
        rev_id = tree.commit('first post').encode('utf8')
        # change the current content to be different this will alter stat, sha
        # and length:
        self.build_tree_contents([('tree/a file', 'new content\n')])
        expected_result = ([rev_id], [
            (('', '', tree.get_root_id()), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
              ('d', '', 0, False, rev_id), # first parent details
             ]),
            (('', 'a file', 'a-file-id'), # common
             [('f', '', 0, False, dirstate.DirState.NULLSTAT), # current
              ('f', 'c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8', 24, False,
               rev_id), # first parent
             ]),
            ])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)

    def test_2_parents_not_empty_to_dirstate(self):
        # create a parent by doing a commit
        tree = self.get_tree_with_a_file()
        rev_id = tree.commit('first post').encode('utf8')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        # change the current content to be different this will alter stat, sha
        # and length:
        self.build_tree_contents([('tree2/a file', 'merge content\n')])
        rev_id2 = tree2.commit('second post').encode('utf8')
        tree.merge_from_branch(tree2.branch)
        # change the current content to be different this will alter stat, sha
        # and length again, giving us three distinct values:
        self.build_tree_contents([('tree/a file', 'new content\n')])
        expected_result = ([rev_id, rev_id2], [
            (('', '', tree.get_root_id()), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
              ('d', '', 0, False, rev_id), # first parent details
              ('d', '', 0, False, rev_id), # second parent details
             ]),
            (('', 'a file', 'a-file-id'), # common
             [('f', '', 0, False, dirstate.DirState.NULLSTAT), # current
              ('f', 'c3ed76e4bfd45ff1763ca206055bca8e9fc28aa8', 24, False,
               rev_id), # first parent
              ('f', '314d796174c9412647c3ce07dfb5d36a94e72958', 14, False,
               rev_id2), # second parent
             ]),
            ])
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        self.check_state_with_reopen(expected_result, state)

    def test_colliding_fileids(self):
        # test insertion of parents creating several entries at the same path.
        # we used to have a bug where they could cause the dirstate to break
        # its ordering invariants.
        # create some trees to test from
        parents = []
        for i in range(7):
            tree = self.make_branch_and_tree('tree%d' % i)
            self.build_tree(['tree%d/name' % i,])
            tree.add(['name'], ['file-id%d' % i])
            revision_id = 'revid-%d' % i
            tree.commit('message', rev_id=revision_id)
            parents.append((revision_id,
                tree.branch.repository.revision_tree(revision_id)))
        # now fold these trees into a dirstate
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.set_parent_trees(parents, [])
            state._validate()
        finally:
            state.unlock()


class TestDirStateOnFile(TestCaseWithDirState):

    def create_updated_dirstate(self):
        self.build_tree(['a-file'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a-file'], ['a-id'])
        tree.commit('add a-file')
        # Save and unlock the state, re-open it in readonly mode
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        state.save()
        state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        return state

    def test_construct_with_path(self):
        tree = self.make_branch_and_tree('tree')
        state = dirstate.DirState.from_tree(tree, 'dirstate.from_tree')
        # we want to be able to get the lines of the dirstate that we will
        # write to disk.
        lines = state.get_lines()
        state.unlock()
        self.build_tree_contents([('dirstate', ''.join(lines))])
        # get a state object
        # no parents, default tree content
        expected_result = ([], [
            (('', '', tree.get_root_id()), # common details
             # current tree details, but new from_tree skips statting, it
             # uses set_state_from_inventory, and thus depends on the
             # inventory state.
             [('d', '', 0, False, dirstate.DirState.NULLSTAT),
             ])
            ])
        state = dirstate.DirState.on_file('dirstate')
        state.lock_write() # check_state_with_reopen will save() and unlock it
        self.check_state_with_reopen(expected_result, state)

    def test_can_save_clean_on_file(self):
        tree = self.make_branch_and_tree('tree')
        state = dirstate.DirState.from_tree(tree, 'dirstate')
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
            entry = state._get_entry(0, path_utf8='a-file')
            # The current size should be 0 (default)
            self.assertEqual(0, entry[1][0][2])
            # We should have a real entry.
            self.assertNotEqual((None, None), entry)
            # Set the cutoff-time into the future, so things look cacheable
            state._sha_cutoff_time()
            state._cutoff_time += 10.0
            st = os.lstat('a-file')
            sha1sum = dirstate.update_entry(state, entry, 'a-file', st)
            # We updated the current sha1sum because the file is cacheable
            self.assertEqual('ecc5374e9ed82ad3ea3b4d452ea995a5fd3e70e3',
                             sha1sum)

            # The dirblock has been updated
            self.assertEqual(st.st_size, entry[1][0][2])
            self.assertEqual(dirstate.DirState.IN_MEMORY_HASH_MODIFIED,
                             state._dirblock_state)

            del entry
            # Now, since we are the only one holding a lock, we should be able
            # to save and have it written to disk
            state.save()
        finally:
            state.unlock()

        # Re-open the file, and ensure that the state has been updated.
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            entry = state._get_entry(0, path_utf8='a-file')
            self.assertEqual(st.st_size, entry[1][0][2])
        finally:
            state.unlock()

    def test_save_fails_quietly_if_locked(self):
        """If dirstate is locked, save will fail without complaining."""
        state = self.create_updated_dirstate()
        try:
            entry = state._get_entry(0, path_utf8='a-file')
            # No cached sha1 yet.
            self.assertEqual('', entry[1][0][1])
            # Set the cutoff-time into the future, so things look cacheable
            state._sha_cutoff_time()
            state._cutoff_time += 10.0
            st = os.lstat('a-file')
            sha1sum = dirstate.update_entry(state, entry, 'a-file', st)
            self.assertEqual('ecc5374e9ed82ad3ea3b4d452ea995a5fd3e70e3',
                             sha1sum)
            self.assertEqual(dirstate.DirState.IN_MEMORY_HASH_MODIFIED,
                             state._dirblock_state)

            # Now, before we try to save, grab another dirstate, and take out a
            # read lock.
            # TODO: jam 20070315 Ideally this would be locked by another
            #       process. To make sure the file is really OS locked.
            state2 = dirstate.DirState.on_file('dirstate')
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
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            entry = state._get_entry(0, path_utf8='a-file')
            self.assertEqual('', entry[1][0][1])
        finally:
            state.unlock()

    def test_save_refuses_if_changes_aborted(self):
        self.build_tree(['a-file', 'a-dir/'])
        state = dirstate.DirState.initialize('dirstate')
        try:
            # No stat and no sha1 sum.
            state.add('a-file', 'a-file-id', 'file', None, '')
            state.save()
        finally:
            state.unlock()

        # The dirstate should include TREE_ROOT and 'a-file' and nothing else
        expected_blocks = [
            ('', [(('', '', 'TREE_ROOT'),
                   [('d', '', 0, False, dirstate.DirState.NULLSTAT)])]),
            ('', [(('', 'a-file', 'a-file-id'),
                   [('f', '', 0, False, dirstate.DirState.NULLSTAT)])]),
        ]

        state = dirstate.DirState.on_file('dirstate')
        state.lock_write()
        try:
            state._read_dirblocks_if_needed()
            self.assertEqual(expected_blocks, state._dirblocks)

            # Now modify the state, but mark it as inconsistent
            state.add('a-dir', 'a-dir-id', 'directory', None, '')
            state._changes_aborted = True
            state.save()
        finally:
            state.unlock()

        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            state._read_dirblocks_if_needed()
            self.assertEqual(expected_blocks, state._dirblocks)
        finally:
            state.unlock()


class TestDirStateInitialize(TestCaseWithDirState):

    def test_initialize(self):
        expected_result = ([], [
            (('', '', 'TREE_ROOT'), # common details
             [('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ])
            ])
        state = dirstate.DirState.initialize('dirstate')
        try:
            self.assertIsInstance(state, dirstate.DirState)
            lines = state.get_lines()
        finally:
            state.unlock()
        # On win32 you can't read from a locked file, even within the same
        # process. So we have to unlock and release before we check the file
        # contents.
        self.assertFileEqual(''.join(lines), 'dirstate')
        state.lock_read() # check_state_with_reopen will unlock
        self.check_state_with_reopen(expected_result, state)


class TestDirStateManipulations(TestCaseWithDirState):

    def make_minimal_tree(self):
        tree1 = self.make_branch_and_memory_tree('tree1')
        tree1.lock_write()
        self.addCleanup(tree1.unlock)
        tree1.add('')
        revid1 = tree1.commit('foo')
        return tree1, revid1

    def test_update_minimal_updates_id_index(self):
        state = self.create_dirstate_with_root_and_subdir()
        self.addCleanup(state.unlock)
        id_index = state._get_id_index()
        self.assertEqual(['a-root-value', 'subdir-id'], sorted(id_index))
        state.add('file-name', 'file-id', 'file', None, '')
        self.assertEqual(['a-root-value', 'file-id', 'subdir-id'],
                         sorted(id_index))
        state.update_minimal(('', 'new-name', 'file-id'), 'f',
                             path_utf8='new-name')
        self.assertEqual(['a-root-value', 'file-id', 'subdir-id'],
                         sorted(id_index))
        self.assertEqual([('', 'new-name', 'file-id')],
                         sorted(id_index['file-id']))
        state._validate()

    def test_set_state_from_inventory_no_content_no_parents(self):
        # setting the current inventory is a slow but important api to support.
        tree1, revid1 = self.make_minimal_tree()
        inv = tree1.root_inventory
        root_id = inv.path2id('')
        expected_result = [], [
            (('', '', root_id), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT)])]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.set_state_from_inventory(inv)
            self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                             state._header_state)
            self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                             state._dirblock_state)
        except:
            state.unlock()
            raise
        else:
            # This will unlock it
            self.check_state_with_reopen(expected_result, state)

    def test_set_state_from_scratch_no_parents(self):
        tree1, revid1 = self.make_minimal_tree()
        inv = tree1.root_inventory
        root_id = inv.path2id('')
        expected_result = [], [
            (('', '', root_id), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT)])]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.set_state_from_scratch(inv, [], [])
            self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                             state._header_state)
            self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                             state._dirblock_state)
        except:
            state.unlock()
            raise
        else:
            # This will unlock it
            self.check_state_with_reopen(expected_result, state)

    def test_set_state_from_scratch_identical_parent(self):
        tree1, revid1 = self.make_minimal_tree()
        inv = tree1.root_inventory
        root_id = inv.path2id('')
        rev_tree1 = tree1.branch.repository.revision_tree(revid1)
        d_entry = ('d', '', 0, False, dirstate.DirState.NULLSTAT)
        parent_entry = ('d', '', 0, False, revid1)
        expected_result = [revid1], [
            (('', '', root_id), [d_entry, parent_entry])]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.set_state_from_scratch(inv, [(revid1, rev_tree1)], [])
            self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                             state._header_state)
            self.assertEqual(dirstate.DirState.IN_MEMORY_MODIFIED,
                             state._dirblock_state)
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

        tree = self.make_branch_and_tree('.')
        # depends on the default format using dirstate...
        tree.lock_write()
        try:
            # make a dirstate with some valid hashcache data
            # file on disk, but that's not needed for this test
            foo_contents = 'contents of foo'
            self.build_tree_contents([('foo', foo_contents)])
            tree.add('foo', 'foo-id')

            foo_stat = os.stat('foo')
            foo_packed = dirstate.pack_stat(foo_stat)
            foo_sha = osutils.sha_string(foo_contents)
            foo_size = len(foo_contents)

            # should not be cached yet, because the file's too fresh
            self.assertEqual(
                (('', 'foo', 'foo-id',),
                 [('f', '', 0, False, dirstate.DirState.NULLSTAT)]),
                tree._dirstate._get_entry(0, 'foo-id'))
            # poke in some hashcache information - it wouldn't normally be
            # stored because it's too fresh
            tree._dirstate.update_minimal(
                ('', 'foo', 'foo-id'),
                'f', False, foo_sha, foo_packed, foo_size, 'foo')
            # now should be cached
            self.assertEqual(
                (('', 'foo', 'foo-id',),
                 [('f', foo_sha, foo_size, False, foo_packed)]),
                tree._dirstate._get_entry(0, 'foo-id'))

            # extract the inventory, and add something to it
            inv = tree._get_root_inventory()
            # should see the file we poked in...
            self.assertTrue(inv.has_id('foo-id'))
            self.assertTrue(inv.has_filename('foo'))
            inv.add_path('bar', 'file', 'bar-id')
            tree._dirstate._validate()
            # this used to cause it to lose its hashcache
            tree._dirstate.set_state_from_inventory(inv)
            tree._dirstate._validate()
        finally:
            tree.unlock()

        tree.lock_read()
        try:
            # now check that the state still has the original hashcache value
            state = tree._dirstate
            state._validate()
            foo_tuple = state._get_entry(0, path_utf8='foo')
            self.assertEqual(
                (('', 'foo', 'foo-id',),
                 [('f', foo_sha, len(foo_contents), False,
                   dirstate.pack_stat(foo_stat))]),
                foo_tuple)
        finally:
            tree.unlock()

    def test_set_state_from_inventory_mixed_paths(self):
        tree1 = self.make_branch_and_tree('tree1')
        self.build_tree(['tree1/a/', 'tree1/a/b/', 'tree1/a-b/',
                         'tree1/a/b/foo', 'tree1/a-b/bar'])
        tree1.lock_write()
        try:
            tree1.add(['a', 'a/b', 'a-b', 'a/b/foo', 'a-b/bar'],
                      ['a-id', 'b-id', 'a-b-id', 'foo-id', 'bar-id'])
            tree1.commit('rev1', rev_id='rev1')
            root_id = tree1.get_root_id()
            inv = tree1.root_inventory
        finally:
            tree1.unlock()
        expected_result1 = [('', '', root_id, 'd'),
                            ('', 'a', 'a-id', 'd'),
                            ('', 'a-b', 'a-b-id', 'd'),
                            ('a', 'b', 'b-id', 'd'),
                            ('a/b', 'foo', 'foo-id', 'f'),
                            ('a-b', 'bar', 'bar-id', 'f'),
                           ]
        expected_result2 = [('', '', root_id, 'd'),
                            ('', 'a', 'a-id', 'd'),
                            ('', 'a-b', 'a-b-id', 'd'),
                            ('a-b', 'bar', 'bar-id', 'f'),
                           ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.set_state_from_inventory(inv)
            values = []
            for entry in state._iter_entries():
                values.append(entry[0] + entry[1][0][:1])
            self.assertEqual(expected_result1, values)
            del inv['b-id']
            state.set_state_from_inventory(inv)
            values = []
            for entry in state._iter_entries():
                values.append(entry[0] + entry[1][0][:1])
            self.assertEqual(expected_result2, values)
        finally:
            state.unlock()

    def test_set_path_id_no_parents(self):
        """The id of a path can be changed trivally with no parents."""
        state = dirstate.DirState.initialize('dirstate')
        try:
            # check precondition to be sure the state does change appropriately.
            root_entry = (('', '', 'TREE_ROOT'), [('d', '', 0, False, 'x'*32)])
            self.assertEqual([root_entry], list(state._iter_entries()))
            self.assertEqual(root_entry, state._get_entry(0, path_utf8=''))
            self.assertEqual(root_entry,
                             state._get_entry(0, fileid_utf8='TREE_ROOT'))
            self.assertEqual((None, None),
                             state._get_entry(0, fileid_utf8='second-root-id'))
            state.set_path_id('', 'second-root-id')
            new_root_entry = (('', '', 'second-root-id'),
                              [('d', '', 0, False, 'x'*32)])
            expected_rows = [new_root_entry]
            self.assertEqual(expected_rows, list(state._iter_entries()))
            self.assertEqual(new_root_entry, state._get_entry(0, path_utf8=''))
            self.assertEqual(new_root_entry, 
                             state._get_entry(0, fileid_utf8='second-root-id'))
            self.assertEqual((None, None),
                             state._get_entry(0, fileid_utf8='TREE_ROOT'))
            # should work across save too
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            state._validate()
            self.assertEqual(expected_rows, list(state._iter_entries()))
        finally:
            state.unlock()

    def test_set_path_id_with_parents(self):
        """Set the root file id in a dirstate with parents"""
        mt = self.make_branch_and_tree('mt')
        # in case the default tree format uses a different root id
        mt.set_root_id('TREE_ROOT')
        mt.commit('foo', rev_id='parent-revid')
        rt = mt.branch.repository.revision_tree('parent-revid')
        state = dirstate.DirState.initialize('dirstate')
        state._validate()
        try:
            state.set_parent_trees([('parent-revid', rt)], ghosts=[])
            root_entry = (('', '', 'TREE_ROOT'),
                          [('d', '', 0, False, 'x'*32),
                           ('d', '', 0, False, 'parent-revid')])
            self.assertEqual(root_entry, state._get_entry(0, path_utf8=''))
            self.assertEqual(root_entry,
                             state._get_entry(0, fileid_utf8='TREE_ROOT'))
            self.assertEqual((None, None),
                             state._get_entry(0, fileid_utf8='Asecond-root-id'))
            state.set_path_id('', 'Asecond-root-id')
            state._validate()
            # now see that it is what we expected
            old_root_entry = (('', '', 'TREE_ROOT'),
                              [('a', '', 0, False, ''),
                               ('d', '', 0, False, 'parent-revid')])
            new_root_entry = (('', '', 'Asecond-root-id'),
                              [('d', '', 0, False, ''),
                               ('a', '', 0, False, '')])
            expected_rows = [new_root_entry, old_root_entry]
            state._validate()
            self.assertEqual(expected_rows, list(state._iter_entries()))
            self.assertEqual(new_root_entry, state._get_entry(0, path_utf8=''))
            self.assertEqual(old_root_entry, state._get_entry(1, path_utf8=''))
            self.assertEqual((None, None),
                             state._get_entry(0, fileid_utf8='TREE_ROOT'))
            self.assertEqual(old_root_entry,
                             state._get_entry(1, fileid_utf8='TREE_ROOT'))
            self.assertEqual(new_root_entry,
                             state._get_entry(0, fileid_utf8='Asecond-root-id'))
            self.assertEqual((None, None),
                             state._get_entry(1, fileid_utf8='Asecond-root-id'))
            # should work across save too
            state.save()
        finally:
            state.unlock()
        # now flush & check we get the same
        state = dirstate.DirState.on_file('dirstate')
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
            state.set_path_id('', 'tree-root-2')
            state._validate()
        finally:
            state.unlock()

    def test_set_parent_trees_no_content(self):
        # set_parent_trees is a slow but important api to support.
        tree1 = self.make_branch_and_memory_tree('tree1')
        tree1.lock_write()
        try:
            tree1.add('')
            revid1 = tree1.commit('foo')
        finally:
            tree1.unlock()
        branch2 = tree1.branch.bzrdir.clone('tree2').open_branch()
        tree2 = memorytree.MemoryTree.create_on_branch(branch2)
        tree2.lock_write()
        try:
            revid2 = tree2.commit('foo')
            root_id = tree2.get_root_id()
        finally:
            tree2.unlock()
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.set_path_id('', root_id)
            state.set_parent_trees(
                ((revid1, tree1.branch.repository.revision_tree(revid1)),
                 (revid2, tree2.branch.repository.revision_tree(revid2)),
                 ('ghost-rev', None)),
                ['ghost-rev'])
            # check we can reopen and use the dirstate after setting parent
            # trees.
            state._validate()
            state.save()
            state._validate()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_write()
        try:
            self.assertEqual([revid1, revid2, 'ghost-rev'],
                             state.get_parent_ids())
            # iterating the entire state ensures that the state is parsable.
            list(state._iter_entries())
            # be sure that it sets not appends - change it
            state.set_parent_trees(
                ((revid1, tree1.branch.repository.revision_tree(revid1)),
                 ('ghost-rev', None)),
                ['ghost-rev'])
            # and now put it back.
            state.set_parent_trees(
                ((revid1, tree1.branch.repository.revision_tree(revid1)),
                 (revid2, tree2.branch.repository.revision_tree(revid2)),
                 ('ghost-rev', tree2.branch.repository.revision_tree(
                                   _mod_revision.NULL_REVISION))),
                ['ghost-rev'])
            self.assertEqual([revid1, revid2, 'ghost-rev'],
                             state.get_parent_ids())
            # the ghost should be recorded as such by set_parent_trees.
            self.assertEqual(['ghost-rev'], state.get_ghosts())
            self.assertEqual(
                [(('', '', root_id), [
                  ('d', '', 0, False, dirstate.DirState.NULLSTAT),
                  ('d', '', 0, False, revid1),
                  ('d', '', 0, False, revid1)
                  ])],
                list(state._iter_entries()))
        finally:
            state.unlock()

    def test_set_parent_trees_file_missing_from_tree(self):
        # Adding a parent tree may reference files not in the current state.
        # they should get listed just once by id, even if they are in two
        # separate trees.
        # set_parent_trees is a slow but important api to support.
        tree1 = self.make_branch_and_memory_tree('tree1')
        tree1.lock_write()
        try:
            tree1.add('')
            tree1.add(['a file'], ['file-id'], ['file'])
            tree1.put_file_bytes_non_atomic('file-id', 'file-content')
            revid1 = tree1.commit('foo')
        finally:
            tree1.unlock()
        branch2 = tree1.branch.bzrdir.clone('tree2').open_branch()
        tree2 = memorytree.MemoryTree.create_on_branch(branch2)
        tree2.lock_write()
        try:
            tree2.put_file_bytes_non_atomic('file-id', 'new file-content')
            revid2 = tree2.commit('foo')
            root_id = tree2.get_root_id()
        finally:
            tree2.unlock()
        # check the layout in memory
        expected_result = [revid1.encode('utf8'), revid2.encode('utf8')], [
            (('', '', root_id), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT),
             ('d', '', 0, False, revid1.encode('utf8')),
             ('d', '', 0, False, revid1.encode('utf8'))
             ]),
            (('', 'a file', 'file-id'), [
             ('a', '', 0, False, ''),
             ('f', '2439573625385400f2a669657a7db6ae7515d371', 12, False,
              revid1.encode('utf8')),
             ('f', '542e57dc1cda4af37cb8e55ec07ce60364bb3c7d', 16, False,
              revid2.encode('utf8'))
             ])
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.set_path_id('', root_id)
            state.set_parent_trees(
                ((revid1, tree1.branch.repository.revision_tree(revid1)),
                 (revid2, tree2.branch.repository.revision_tree(revid2)),
                 ), [])
        except:
            state.unlock()
            raise
        else:
            # check_state_with_reopen will unlock
            self.check_state_with_reopen(expected_result, state)

    ### add a path via _set_data - so we dont need delta work, just
    # raw data in, and ensure that it comes out via get_lines happily.

    def test_add_path_to_root_no_parents_all_data(self):
        # The most trivial addition of a path is when there are no parents and
        # its in the root and all data about the file is supplied
        self.build_tree(['a file'])
        stat = os.lstat('a file')
        # the 1*20 is the sha1 pretend value.
        state = dirstate.DirState.initialize('dirstate')
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ]),
            (('', 'a file', 'a-file-id'), [
             ('f', '1'*20, 19, False, dirstate.pack_stat(stat)), # current tree
             ]),
            ]
        try:
            state.add('a file', 'a-file-id', 'file', stat, '1'*20)
            # having added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        self.addCleanup(state.unlock)
        self.assertEqual(expected_entries, list(state._iter_entries()))

    def test_add_path_to_unversioned_directory(self):
        """Adding a path to an unversioned directory should error.

        This is a duplicate of TestWorkingTree.test_add_in_unversioned,
        once dirstate is stable and if it is merged with WorkingTree3, consider
        removing this copy of the test.
        """
        self.build_tree(['unversioned/', 'unversioned/a file'])
        state = dirstate.DirState.initialize('dirstate')
        self.addCleanup(state.unlock)
        self.assertRaises(errors.NotVersionedError, state.add,
                          'unversioned/a file', 'a-file-id', 'file', None, None)

    def test_add_directory_to_root_no_parents_all_data(self):
        # The most trivial addition of a dir is when there are no parents and
        # its in the root and all data about the file is supplied
        self.build_tree(['a dir/'])
        stat = os.lstat('a dir')
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ]),
            (('', 'a dir', 'a dir id'), [
             ('d', '', 0, False, dirstate.pack_stat(stat)), # current tree
             ]),
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.add('a dir', 'a dir id', 'directory', stat, None)
            # having added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        self.addCleanup(state.unlock)
        state._validate()
        self.assertEqual(expected_entries, list(state._iter_entries()))

    def _test_add_symlink_to_root_no_parents_all_data(self, link_name, target):
        # The most trivial addition of a symlink when there are no parents and
        # its in the root and all data about the file is supplied
        # bzr doesn't support fake symlinks on windows, yet.
        self.requireFeature(features.SymlinkFeature)
        os.symlink(target, link_name)
        stat = os.lstat(link_name)
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ]),
            (('', link_name.encode('UTF-8'), 'a link id'), [
             ('l', target.encode('UTF-8'), stat[6],
              False, dirstate.pack_stat(stat)), # current tree
             ]),
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.add(link_name, 'a link id', 'symlink', stat,
                      target.encode('UTF-8'))
            # having added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        self.addCleanup(state.unlock)
        self.assertEqual(expected_entries, list(state._iter_entries()))

    def test_add_symlink_to_root_no_parents_all_data(self):
        self._test_add_symlink_to_root_no_parents_all_data('a link', 'target')

    def test_add_symlink_unicode_to_root_no_parents_all_data(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_add_symlink_to_root_no_parents_all_data(
            u'\N{Euro Sign}link', u'targ\N{Euro Sign}et')

    def test_add_directory_and_child_no_parents_all_data(self):
        # after adding a directory, we should be able to add children to it.
        self.build_tree(['a dir/', 'a dir/a file'])
        dirstat = os.lstat('a dir')
        filestat = os.lstat('a dir/a file')
        expected_entries = [
            (('', '', 'TREE_ROOT'), [
             ('d', '', 0, False, dirstate.DirState.NULLSTAT), # current tree
             ]),
            (('', 'a dir', 'a dir id'), [
             ('d', '', 0, False, dirstate.pack_stat(dirstat)), # current tree
             ]),
            (('a dir', 'a file', 'a-file-id'), [
             ('f', '1'*20, 25, False,
              dirstate.pack_stat(filestat)), # current tree details
             ]),
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            state.add('a dir', 'a dir id', 'directory', dirstat, None)
            state.add('a dir/a file', 'a-file-id', 'file', filestat, '1'*20)
            # added it, it should be in the output of iter_entries.
            self.assertEqual(expected_entries, list(state._iter_entries()))
            # saving and reloading should not affect this.
            state.save()
        finally:
            state.unlock()
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        self.addCleanup(state.unlock)
        self.assertEqual(expected_entries, list(state._iter_entries()))

    def test_add_tree_reference(self):
        # make a dirstate and add a tree reference
        state = dirstate.DirState.initialize('dirstate')
        expected_entry = (
            ('', 'subdir', 'subdir-id'),
            [('t', 'subtree-123123', 0, False,
              'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')],
            )
        try:
            state.add('subdir', 'subdir-id', 'tree-reference', None, 'subtree-123123')
            entry = state._get_entry(0, 'subdir-id', 'subdir')
            self.assertEqual(entry, expected_entry)
            state._validate()
            state.save()
        finally:
            state.unlock()
        # now check we can read it back
        state.lock_read()
        self.addCleanup(state.unlock)
        state._validate()
        entry2 = state._get_entry(0, 'subdir-id', 'subdir')
        self.assertEqual(entry, entry2)
        self.assertEqual(entry, expected_entry)
        # and lookup by id should work too
        entry2 = state._get_entry(0, fileid_utf8='subdir-id')
        self.assertEqual(entry, expected_entry)

    def test_add_forbidden_names(self):
        state = dirstate.DirState.initialize('dirstate')
        self.addCleanup(state.unlock)
        self.assertRaises(errors.BzrError,
            state.add, '.', 'ass-id', 'directory', None, None)
        self.assertRaises(errors.BzrError,
            state.add, '..', 'ass-id', 'directory', None, None)

    def test_set_state_with_rename_b_a_bug_395556(self):
        # bug 395556 uncovered a bug where the dirstate ends up with a false
        # relocation record - in a tree with no parents there should be no
        # absent or relocated records. This then leads to further corruption
        # when a commit occurs, as the incorrect relocation gathers an
        # incorrect absent in tree 1, and future changes go to pot.
        tree1 = self.make_branch_and_tree('tree1')
        self.build_tree(['tree1/b'])
        tree1.lock_write()
        try:
            tree1.add(['b'], ['b-id'])
            root_id = tree1.get_root_id()
            inv = tree1.root_inventory
            state = dirstate.DirState.initialize('dirstate')
            try:
                # Set the initial state with 'b'
                state.set_state_from_inventory(inv)
                inv.rename('b-id', root_id, 'a')
                # Set the new state with 'a', which currently corrupts.
                state.set_state_from_inventory(inv)
                expected_result1 = [('', '', root_id, 'd'),
                                    ('', 'a', 'b-id', 'f'),
                                   ]
                values = []
                for entry in state._iter_entries():
                    values.append(entry[0] + entry[1][0][:1])
                self.assertEqual(expected_result1, values)
            finally:
                state.unlock()
        finally:
            tree1.unlock()


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
        tree = self.make_branch_and_tree('.')
        self.build_tree(['c', 'd'])
        tree.lock_write()
        tree.add(['c', 'd'], ['c-id', 'd-id'])
        tree.commit('add c and d')
        state = InstrumentedDirState.on_file(tree.current_dirstate()._filename,
                                             worth_saving_limit=2)
        tree.unlock()
        state.lock_write()
        self.addCleanup(state.unlock)
        state._read_dirblocks_if_needed()
        state.adjust_time(+20) # Allow things to be cached
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        content = self._read_state_content(state)
        self.do_update_entry(state, 'c')
        self.assertEqual(1, len(state._known_hash_changes))
        self.assertEqual(dirstate.DirState.IN_MEMORY_HASH_MODIFIED,
                         state._dirblock_state)
        state.save()
        # It should not have set the state to IN_MEMORY_UNMODIFIED because the
        # hash values haven't been written out.
        self.assertEqual(dirstate.DirState.IN_MEMORY_HASH_MODIFIED,
                         state._dirblock_state)
        self.assertEqual(content, self._read_state_content(state))
        self.assertEqual(dirstate.DirState.IN_MEMORY_HASH_MODIFIED,
                         state._dirblock_state)
        self.do_update_entry(state, 'd')
        self.assertEqual(2, len(state._known_hash_changes))
        state.save()
        self.assertEqual(dirstate.DirState.IN_MEMORY_UNMODIFIED,
                         state._dirblock_state)
        self.assertEqual(0, len(state._known_hash_changes))


class TestGetLines(TestCaseWithDirState):

    def test_get_line_with_2_rows(self):
        state = self.create_dirstate_with_root_and_subdir()
        try:
            self.assertEqual(['#bazaar dirstate flat format 3\n',
                'crc32: 41262208\n',
                'num_entries: 2\n',
                '0\x00\n\x00'
                '0\x00\n\x00'
                '\x00\x00a-root-value\x00'
                'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00\n\x00'
                '\x00subdir\x00subdir-id\x00'
                'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00\n\x00'
                ], state.get_lines())
        finally:
            state.unlock()

    def test_entry_to_line(self):
        state = self.create_dirstate_with_root()
        try:
            self.assertEqual(
                '\x00\x00a-root-value\x00d\x00\x000\x00n'
                '\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk',
                state._entry_to_line(state._dirblocks[0][1][0]))
        finally:
            state.unlock()

    def test_entry_to_line_with_parent(self):
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_entry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat), # current tree details
             # first: a pointer to the current location
            ('a', 'dirname/basename', 0, False, ''),
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            self.assertEqual(
                '\x00\x00a-root-value\x00'
                'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00'
                'a\x00dirname/basename\x000\x00n\x00',
                state._entry_to_line(root_entry))
        finally:
            state.unlock()

    def test_entry_to_line_with_two_parents_at_different_paths(self):
        # / in the tree, at / in one parent and /dirname/basename in the other.
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_entry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat), # current tree details
            ('d', '', 0, False, 'rev_id'), # first parent details
             # second: a pointer to the current location
            ('a', 'dirname/basename', 0, False, ''),
            ]
        state = dirstate.DirState.initialize('dirstate')
        try:
            self.assertEqual(
                '\x00\x00a-root-value\x00'
                'd\x00\x000\x00n\x00AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk\x00'
                'd\x00\x000\x00n\x00rev_id\x00'
                'a\x00dirname/basename\x000\x00n\x00',
                state._entry_to_line(root_entry))
        finally:
            state.unlock()

    def test_iter_entries(self):
        # we should be able to iterate the dirstate entries from end to end
        # this is for get_lines to be easy to read.
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        dirblocks = []
        root_entries = [(('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat), # current tree details
            ])]
        dirblocks.append(('', root_entries))
        # add two files in the root
        subdir_entry = ('', 'subdir', 'subdir-id'), [
            ('d', '', 0, False, packed_stat), # current tree details
            ]
        afile_entry = ('', 'afile', 'afile-id'), [
            ('f', 'sha1value', 34, False, packed_stat), # current tree details
            ]
        dirblocks.append(('', [subdir_entry, afile_entry]))
        # and one in subdir
        file_entry2 = ('subdir', '2file', '2file-id'), [
            ('f', 'sha1value', 23, False, packed_stat), # current tree details
            ]
        dirblocks.append(('subdir', [file_entry2]))
        state = dirstate.DirState.initialize('dirstate')
        try:
            state._set_data([], dirblocks)
            expected_entries = [root_entries[0], subdir_entry, afile_entry,
                                file_entry2]
            self.assertEqual(expected_entries, list(state._iter_entries()))
        finally:
            state.unlock()


class TestGetBlockRowIndex(TestCaseWithDirState):

    def assertBlockRowIndexEqual(self, block_index, row_index, dir_present,
        file_present, state, dirname, basename, tree_index):
        self.assertEqual((block_index, row_index, dir_present, file_present),
            state._get_block_entry_index(dirname, basename, tree_index))
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
        self.assertBlockRowIndexEqual(1, 0, True, True, state, '', 'subdir', 0)
        self.assertBlockRowIndexEqual(1, 0, True, False, state, '', 'bdir', 0)
        self.assertBlockRowIndexEqual(1, 1, True, False, state, '', 'zdir', 0)
        self.assertBlockRowIndexEqual(2, 0, False, False, state, 'a', 'foo', 0)
        self.assertBlockRowIndexEqual(2, 0, False, False, state,
                                      'subdir', 'foo', 0)

    def test_complex_structure_exists(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        # Make sure we can find everything that exists
        self.assertBlockRowIndexEqual(0, 0, True, True, state, '', '', 0)
        self.assertBlockRowIndexEqual(1, 0, True, True, state, '', 'a', 0)
        self.assertBlockRowIndexEqual(1, 1, True, True, state, '', 'b', 0)
        self.assertBlockRowIndexEqual(1, 2, True, True, state, '', 'c', 0)
        self.assertBlockRowIndexEqual(1, 3, True, True, state, '', 'd', 0)
        self.assertBlockRowIndexEqual(2, 0, True, True, state, 'a', 'e', 0)
        self.assertBlockRowIndexEqual(2, 1, True, True, state, 'a', 'f', 0)
        self.assertBlockRowIndexEqual(3, 0, True, True, state, 'b', 'g', 0)
        self.assertBlockRowIndexEqual(3, 1, True, True, state,
                                      'b', 'h\xc3\xa5', 0)

    def test_complex_structure_missing(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        # Make sure things would be inserted in the right locations
        # '_' comes before 'a'
        self.assertBlockRowIndexEqual(0, 0, True, True, state, '', '', 0)
        self.assertBlockRowIndexEqual(1, 0, True, False, state, '', '_', 0)
        self.assertBlockRowIndexEqual(1, 1, True, False, state, '', 'aa', 0)
        self.assertBlockRowIndexEqual(1, 4, True, False, state,
                                      '', 'h\xc3\xa5', 0)
        self.assertBlockRowIndexEqual(2, 0, False, False, state, '_', 'a', 0)
        self.assertBlockRowIndexEqual(3, 0, False, False, state, 'aa', 'a', 0)
        self.assertBlockRowIndexEqual(4, 0, False, False, state, 'bb', 'a', 0)
        # This would be inserted between a/ and b/
        self.assertBlockRowIndexEqual(3, 0, False, False, state, 'a/e', 'a', 0)
        # Put at the end
        self.assertBlockRowIndexEqual(4, 0, False, False, state, 'e', 'a', 0)


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
        self.assertEntryEqual('', '', 'a-root-value', state, '', 0)
        self.assertEntryEqual('', 'subdir', 'subdir-id', state, 'subdir', 0)
        self.assertEntryEqual(None, None, None, state, 'missing', 0)
        self.assertEntryEqual(None, None, None, state, 'missing/foo', 0)
        self.assertEntryEqual(None, None, None, state, 'subdir/foo', 0)

    def test_complex_structure_exists(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        self.assertEntryEqual('', '', 'a-root-value', state, '', 0)
        self.assertEntryEqual('', 'a', 'a-dir', state, 'a', 0)
        self.assertEntryEqual('', 'b', 'b-dir', state, 'b', 0)
        self.assertEntryEqual('', 'c', 'c-file', state, 'c', 0)
        self.assertEntryEqual('', 'd', 'd-file', state, 'd', 0)
        self.assertEntryEqual('a', 'e', 'e-dir', state, 'a/e', 0)
        self.assertEntryEqual('a', 'f', 'f-file', state, 'a/f', 0)
        self.assertEntryEqual('b', 'g', 'g-file', state, 'b/g', 0)
        self.assertEntryEqual('b', 'h\xc3\xa5', 'h-\xc3\xa5-file', state,
                              'b/h\xc3\xa5', 0)

    def test_complex_structure_missing(self):
        state = self.create_complex_dirstate()
        self.addCleanup(state.unlock)
        self.assertEntryEqual(None, None, None, state, '_', 0)
        self.assertEntryEqual(None, None, None, state, '_\xc3\xa5', 0)
        self.assertEntryEqual(None, None, None, state, 'a/b', 0)
        self.assertEntryEqual(None, None, None, state, 'c/d', 0)

    def test_get_entry_uninitialized(self):
        """Calling get_entry will load data if it needs to"""
        state = self.create_dirstate_with_root()
        try:
            state.save()
        finally:
            state.unlock()
        del state
        state = dirstate.DirState.on_file('dirstate')
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._header_state)
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            self.assertEntryEqual('', '', 'a-root-value', state, '', 0)
        finally:
            state.unlock()


class TestIterChildEntries(TestCaseWithDirState):

    def create_dirstate_with_two_trees(self):
        """This dirstate contains multiple files and directories.

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
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        null_sha = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
        NULL_PARENT_DETAILS = dirstate.DirState.NULL_PARENT_DETAILS
        root_entry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat),
            ('d', '', 0, False, 'parent-revid'),
            ]
        a_entry = ('', 'a', 'a-dir'), [
            ('d', '', 0, False, packed_stat),
            ('d', '', 0, False, 'parent-revid'),
            ]
        b_entry = ('', 'b', 'b-dir'), [
            ('d', '', 0, False, packed_stat),
            ('d', '', 0, False, 'parent-revid'),
            ]
        c_entry = ('', 'c', 'c-file'), [
            ('f', null_sha, 10, False, packed_stat),
            ('r', 'b/j', 0, False, ''),
            ]
        d_entry = ('', 'd', 'd-file'), [
            ('f', null_sha, 20, False, packed_stat),
            ('f', 'd', 20, False, 'parent-revid'),
            ]
        e_entry = ('a', 'e', 'e-dir'), [
            ('d', '', 0, False, packed_stat),
            ('d', '', 0, False, 'parent-revid'),
            ]
        f_entry = ('a', 'f', 'f-file'), [
            ('f', null_sha, 30, False, packed_stat),
            ('f', 'f', 20, False, 'parent-revid'),
            ]
        g_entry = ('b', 'g', 'g-file'), [
            ('f', null_sha, 30, False, packed_stat),
            NULL_PARENT_DETAILS,
            ]
        h_entry1 = ('b', 'h\xc3\xa5', 'h-\xc3\xa5-file1'), [
            ('f', null_sha, 40, False, packed_stat),
            NULL_PARENT_DETAILS,
            ]
        h_entry2 = ('b', 'h\xc3\xa5', 'h-\xc3\xa5-file2'), [
            NULL_PARENT_DETAILS,
            ('f', 'h', 20, False, 'parent-revid'),
            ]
        i_entry = ('b', 'i', 'i-file'), [
            NULL_PARENT_DETAILS,
            ('f', 'h', 20, False, 'parent-revid'),
            ]
        j_entry = ('b', 'j', 'c-file'), [
            ('r', 'c', 0, False, ''),
            ('f', 'j', 20, False, 'parent-revid'),
            ]
        dirblocks = []
        dirblocks.append(('', [root_entry]))
        dirblocks.append(('', [a_entry, b_entry, c_entry, d_entry]))
        dirblocks.append(('a', [e_entry, f_entry]))
        dirblocks.append(('b', [g_entry, h_entry1, h_entry2, i_entry, j_entry]))
        state = dirstate.DirState.initialize('dirstate')
        state._validate()
        try:
            state._set_data(['parent'], dirblocks)
        except:
            state.unlock()
            raise
        return state, dirblocks

    def test_iter_children_b(self):
        state, dirblocks = self.create_dirstate_with_two_trees()
        self.addCleanup(state.unlock)
        expected_result = []
        expected_result.append(dirblocks[3][1][2]) # h2
        expected_result.append(dirblocks[3][1][3]) # i
        expected_result.append(dirblocks[3][1][4]) # j
        self.assertEqual(expected_result,
            list(state._iter_child_entries(1, 'b')))

    def test_iter_child_root(self):
        state, dirblocks = self.create_dirstate_with_two_trees()
        self.addCleanup(state.unlock)
        expected_result = []
        expected_result.append(dirblocks[1][1][0]) # a
        expected_result.append(dirblocks[1][1][1]) # b
        expected_result.append(dirblocks[1][1][3]) # d
        expected_result.append(dirblocks[2][1][0]) # e
        expected_result.append(dirblocks[2][1][1]) # f
        expected_result.append(dirblocks[3][1][2]) # h2
        expected_result.append(dirblocks[3][1][3]) # i
        expected_result.append(dirblocks[3][1][4]) # j
        self.assertEqual(expected_result,
            list(state._iter_child_entries(1, '')))


class TestDirstateSortOrder(tests.TestCaseWithTransport):
    """Test that DirState adds entries in the right order."""

    def test_add_sorting(self):
        """Add entries in lexicographical order, we get path sorted order.

        This tests it to a depth of 4, to make sure we don't just get it right
        at a single depth. 'a/a' should come before 'a-a', even though it
        doesn't lexicographically.
        """
        dirs = ['a', 'a/a', 'a/a/a', 'a/a/a/a',
                'a-a', 'a/a-a', 'a/a/a-a', 'a/a/a/a-a',
               ]
        null_sha = ''
        state = dirstate.DirState.initialize('dirstate')
        self.addCleanup(state.unlock)

        fake_stat = os.stat('dirstate')
        for d in dirs:
            d_id = d.replace('/', '_')+'-id'
            file_path = d + '/f'
            file_id = file_path.replace('/', '_')+'-id'
            state.add(d, d_id, 'directory', fake_stat, null_sha)
            state.add(file_path, file_id, 'file', fake_stat, null_sha)

        expected = ['', '', 'a',
                'a/a', 'a/a/a', 'a/a/a/a',
                'a/a/a/a-a', 'a/a/a-a', 'a/a-a', 'a-a',
               ]
        split = lambda p:p.split('/')
        self.assertEqual(sorted(expected, key=split), expected)
        dirblock_names = [d[0] for d in state._dirblocks]
        self.assertEqual(expected, dirblock_names)

    def test_set_parent_trees_correct_order(self):
        """After calling set_parent_trees() we should maintain the order."""
        dirs = ['a', 'a-a', 'a/a']
        null_sha = ''
        state = dirstate.DirState.initialize('dirstate')
        self.addCleanup(state.unlock)

        fake_stat = os.stat('dirstate')
        for d in dirs:
            d_id = d.replace('/', '_')+'-id'
            file_path = d + '/f'
            file_id = file_path.replace('/', '_')+'-id'
            state.add(d, d_id, 'directory', fake_stat, null_sha)
            state.add(file_path, file_id, 'file', fake_stat, null_sha)

        expected = ['', '', 'a', 'a/a', 'a-a']
        dirblock_names = [d[0] for d in state._dirblocks]
        self.assertEqual(expected, dirblock_names)

        # *really* cheesy way to just get an empty tree
        repo = self.make_repository('repo')
        empty_tree = repo.revision_tree(_mod_revision.NULL_REVISION)
        state.set_parent_trees([('null:', empty_tree)], [])

        dirblock_names = [d[0] for d in state._dirblocks]
        self.assertEqual(expected, dirblock_names)


class InstrumentedDirState(dirstate.DirState):
    """An DirState with instrumented sha1 functionality."""

    def __init__(self, path, sha1_provider, worth_saving_limit=0):
        super(InstrumentedDirState, self).__init__(path, sha1_provider,
            worth_saving_limit=worth_saving_limit)
        self._time_offset = 0
        self._log = []
        # member is dynamically set in DirState.__init__ to turn on trace
        self._sha1_provider = sha1_provider
        self._sha1_file = self._sha1_file_and_log

    def _sha_cutoff_time(self):
        timestamp = super(InstrumentedDirState, self)._sha_cutoff_time()
        self._cutoff_time = timestamp + self._time_offset

    def _sha1_file_and_log(self, abspath):
        self._log.append(('sha1', abspath))
        return self._sha1_provider.sha1(abspath)

    def _read_link(self, abspath, old_link):
        self._log.append(('read_link', abspath, old_link))
        return super(InstrumentedDirState, self)._read_link(abspath, old_link)

    def _lstat(self, abspath, entry):
        self._log.append(('lstat', abspath))
        return super(InstrumentedDirState, self)._lstat(abspath, entry)

    def _is_executable(self, mode, old_executable):
        self._log.append(('is_exec', mode, old_executable))
        return super(InstrumentedDirState, self)._is_executable(mode,
                                                                old_executable)

    def adjust_time(self, secs):
        """Move the clock forward or back.

        :param secs: The amount to adjust the clock by. Positive values make it
        seem as if we are in the future, negative values make it seem like we
        are in the past.
        """
        self._time_offset += secs
        self._cutoff_time = None


class _FakeStat(object):
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
        return _FakeStat(st.st_size, st.st_mtime, st.st_ctime, st.st_dev,
            st.st_ino, st.st_mode)


class TestPackStat(tests.TestCaseWithTransport):

    def assertPackStat(self, expected, stat_value):
        """Check the packed and serialized form of a stat value."""
        self.assertEqual(expected, dirstate.pack_stat(stat_value))

    def test_pack_stat_int(self):
        st = _FakeStat(6859L, 1172758614, 1172758617, 777L, 6499538L, 0100644)
        # Make sure that all parameters have an impact on the packed stat.
        self.assertPackStat('AAAay0Xm4FZF5uBZAAADCQBjLNIAAIGk', st)
        st.st_size = 7000L
        #                ay0 => bWE
        self.assertPackStat('AAAbWEXm4FZF5uBZAAADCQBjLNIAAIGk', st)
        st.st_mtime = 1172758620
        #                     4FZ => 4Fx
        self.assertPackStat('AAAbWEXm4FxF5uBZAAADCQBjLNIAAIGk', st)
        st.st_ctime = 1172758630
        #                          uBZ => uBm
        self.assertPackStat('AAAbWEXm4FxF5uBmAAADCQBjLNIAAIGk', st)
        st.st_dev = 888L
        #                                DCQ => DeA
        self.assertPackStat('AAAbWEXm4FxF5uBmAAADeABjLNIAAIGk', st)
        st.st_ino = 6499540L
        #                                     LNI => LNQ
        self.assertPackStat('AAAbWEXm4FxF5uBmAAADeABjLNQAAIGk', st)
        st.st_mode = 0100744
        #                                          IGk => IHk
        self.assertPackStat('AAAbWEXm4FxF5uBmAAADeABjLNQAAIHk', st)

    def test_pack_stat_float(self):
        """On some platforms mtime and ctime are floats.

        Make sure we don't get warnings or errors, and that we ignore changes <
        1s
        """
        st = _FakeStat(7000L, 1172758614.0, 1172758617.0,
                       777L, 6499538L, 0100644)
        # These should all be the same as the integer counterparts
        self.assertPackStat('AAAbWEXm4FZF5uBZAAADCQBjLNIAAIGk', st)
        st.st_mtime = 1172758620.0
        #                     FZF5 => FxF5
        self.assertPackStat('AAAbWEXm4FxF5uBZAAADCQBjLNIAAIGk', st)
        st.st_ctime = 1172758630.0
        #                          uBZ => uBm
        self.assertPackStat('AAAbWEXm4FxF5uBmAAADCQBjLNIAAIGk', st)
        # fractional seconds are discarded, so no change from above
        st.st_mtime = 1172758620.453
        self.assertPackStat('AAAbWEXm4FxF5uBmAAADCQBjLNIAAIGk', st)
        st.st_ctime = 1172758630.228
        self.assertPackStat('AAAbWEXm4FxF5uBmAAADCQBjLNIAAIGk', st)


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
        for path, keys in zip(paths, map_keys):
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
        for path, keys in zip(paths, map_keys):
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
        tree, state, expected = self.create_basic_dirstate()

        # Bisect should return the rows for the specified files.
        self.assertBisect(expected, [['']], state, [''])
        self.assertBisect(expected, [['a']], state, ['a'])
        self.assertBisect(expected, [['b']], state, ['b'])
        self.assertBisect(expected, [['b/c']], state, ['b/c'])
        self.assertBisect(expected, [['b/d']], state, ['b/d'])
        self.assertBisect(expected, [['b/d/e']], state, ['b/d/e'])
        self.assertBisect(expected, [['b-c']], state, ['b-c'])
        self.assertBisect(expected, [['f']], state, ['f'])

    def test_bisect_multi(self):
        """Bisect can be used to find multiple records at the same time."""
        tree, state, expected = self.create_basic_dirstate()
        # Bisect should be capable of finding multiple entries at the same time
        self.assertBisect(expected, [['a'], ['b'], ['f']],
                          state, ['a', 'b', 'f'])
        self.assertBisect(expected, [['f'], ['b/d'], ['b/d/e']],
                          state, ['f', 'b/d', 'b/d/e'])
        self.assertBisect(expected, [['b'], ['b-c'], ['b/c']],
                          state, ['b', 'b-c', 'b/c'])

    def test_bisect_one_page(self):
        """Test bisect when there is only 1 page to read"""
        tree, state, expected = self.create_basic_dirstate()
        state._bisect_page_size = 5000
        self.assertBisect(expected,[['']], state, [''])
        self.assertBisect(expected,[['a']], state, ['a'])
        self.assertBisect(expected,[['b']], state, ['b'])
        self.assertBisect(expected,[['b/c']], state, ['b/c'])
        self.assertBisect(expected,[['b/d']], state, ['b/d'])
        self.assertBisect(expected,[['b/d/e']], state, ['b/d/e'])
        self.assertBisect(expected,[['b-c']], state, ['b-c'])
        self.assertBisect(expected,[['f']], state, ['f'])
        self.assertBisect(expected,[['a'], ['b'], ['f']],
                          state, ['a', 'b', 'f'])
        self.assertBisect(expected, [['b/d'], ['b/d/e'], ['f']],
                          state, ['b/d', 'b/d/e', 'f'])
        self.assertBisect(expected, [['b'], ['b/c'], ['b-c']],
                          state, ['b', 'b/c', 'b-c'])

    def test_bisect_duplicate_paths(self):
        """When bisecting for a path, handle multiple entries."""
        tree, state, expected = self.create_duplicated_dirstate()

        # Now make sure that both records are properly returned.
        self.assertBisect(expected, [['']], state, [''])
        self.assertBisect(expected, [['a', 'a2']], state, ['a'])
        self.assertBisect(expected, [['b', 'b2']], state, ['b'])
        self.assertBisect(expected, [['b/c', 'b/c2']], state, ['b/c'])
        self.assertBisect(expected, [['b/d', 'b/d2']], state, ['b/d'])
        self.assertBisect(expected, [['b/d/e', 'b/d/e2']],
                          state, ['b/d/e'])
        self.assertBisect(expected, [['b-c', 'b-c2']], state, ['b-c'])
        self.assertBisect(expected, [['f', 'f2']], state, ['f'])

    def test_bisect_page_size_too_small(self):
        """If the page size is too small, we will auto increase it."""
        tree, state, expected = self.create_basic_dirstate()
        state._bisect_page_size = 50
        self.assertBisect(expected, [None], state, ['b/e'])
        self.assertBisect(expected, [['a']], state, ['a'])
        self.assertBisect(expected, [['b']], state, ['b'])
        self.assertBisect(expected, [['b/c']], state, ['b/c'])
        self.assertBisect(expected, [['b/d']], state, ['b/d'])
        self.assertBisect(expected, [['b/d/e']], state, ['b/d/e'])
        self.assertBisect(expected, [['b-c']], state, ['b-c'])
        self.assertBisect(expected, [['f']], state, ['f'])

    def test_bisect_missing(self):
        """Test that bisect return None if it cannot find a path."""
        tree, state, expected = self.create_basic_dirstate()
        self.assertBisect(expected, [None], state, ['foo'])
        self.assertBisect(expected, [None], state, ['b/foo'])
        self.assertBisect(expected, [None], state, ['bar/foo'])
        self.assertBisect(expected, [None], state, ['b-c/foo'])

        self.assertBisect(expected, [['a'], None, ['b/d']],
                          state, ['a', 'foo', 'b/d'])

    def test_bisect_rename(self):
        """Check that we find a renamed row."""
        tree, state, expected = self.create_renamed_dirstate()

        # Search for the pre and post renamed entries
        self.assertBisect(expected, [['a']], state, ['a'])
        self.assertBisect(expected, [['b/g']], state, ['b/g'])
        self.assertBisect(expected, [['b/d']], state, ['b/d'])
        self.assertBisect(expected, [['h']], state, ['h'])

        # What about b/d/e? shouldn't that also get 2 directory entries?
        self.assertBisect(expected, [['b/d/e']], state, ['b/d/e'])
        self.assertBisect(expected, [['h/e']], state, ['h/e'])

    def test_bisect_dirblocks(self):
        tree, state, expected = self.create_duplicated_dirstate()
        self.assertBisectDirBlocks(expected,
            [['', 'a', 'a2', 'b', 'b2', 'b-c', 'b-c2', 'f', 'f2']],
            state, [''])
        self.assertBisectDirBlocks(expected,
            [['b/c', 'b/c2', 'b/d', 'b/d2']], state, ['b'])
        self.assertBisectDirBlocks(expected,
            [['b/d/e', 'b/d/e2']], state, ['b/d'])
        self.assertBisectDirBlocks(expected,
            [['', 'a', 'a2', 'b', 'b2', 'b-c', 'b-c2', 'f', 'f2'],
             ['b/c', 'b/c2', 'b/d', 'b/d2'],
             ['b/d/e', 'b/d/e2'],
            ], state, ['', 'b', 'b/d'])

    def test_bisect_dirblocks_missing(self):
        tree, state, expected = self.create_basic_dirstate()
        self.assertBisectDirBlocks(expected, [['b/d/e'], None],
            state, ['b/d', 'b/e'])
        # Files don't show up in this search
        self.assertBisectDirBlocks(expected, [None], state, ['a'])
        self.assertBisectDirBlocks(expected, [None], state, ['b/c'])
        self.assertBisectDirBlocks(expected, [None], state, ['c'])
        self.assertBisectDirBlocks(expected, [None], state, ['b/d/e'])
        self.assertBisectDirBlocks(expected, [None], state, ['f'])

    def test_bisect_recursive_each(self):
        tree, state, expected = self.create_basic_dirstate()
        self.assertBisectRecursive(expected, ['a'], state, ['a'])
        self.assertBisectRecursive(expected, ['b/c'], state, ['b/c'])
        self.assertBisectRecursive(expected, ['b/d/e'], state, ['b/d/e'])
        self.assertBisectRecursive(expected, ['b-c'], state, ['b-c'])
        self.assertBisectRecursive(expected, ['b/d', 'b/d/e'],
                                   state, ['b/d'])
        self.assertBisectRecursive(expected, ['b', 'b/c', 'b/d', 'b/d/e'],
                                   state, ['b'])
        self.assertBisectRecursive(expected, ['', 'a', 'b', 'b-c', 'f', 'b/c',
                                              'b/d', 'b/d/e'],
                                   state, [''])

    def test_bisect_recursive_multiple(self):
        tree, state, expected = self.create_basic_dirstate()
        self.assertBisectRecursive(expected, ['a', 'b/c'], state, ['a', 'b/c'])
        self.assertBisectRecursive(expected, ['b/d', 'b/d/e'],
                                   state, ['b/d', 'b/d/e'])

    def test_bisect_recursive_missing(self):
        tree, state, expected = self.create_basic_dirstate()
        self.assertBisectRecursive(expected, [], state, ['d'])
        self.assertBisectRecursive(expected, [], state, ['b/e'])
        self.assertBisectRecursive(expected, [], state, ['g'])
        self.assertBisectRecursive(expected, ['a'], state, ['a', 'g'])

    def test_bisect_recursive_renamed(self):
        tree, state, expected = self.create_renamed_dirstate()

        # Looking for either renamed item should find the other
        self.assertBisectRecursive(expected, ['a', 'b/g'], state, ['a'])
        self.assertBisectRecursive(expected, ['a', 'b/g'], state, ['b/g'])
        # Looking in the containing directory should find the rename target,
        # and anything in a subdir of the renamed target.
        self.assertBisectRecursive(expected, ['a', 'b', 'b/c', 'b/d',
                                              'b/d/e', 'b/g', 'h', 'h/e'],
                                   state, ['b'])


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
        tree, state, expected = self.create_renamed_dirstate()
        state._read_dirblocks_if_needed()
        last_dirblock = state._dirblocks[-1]
        # we're appending to the dirblock, but this name comes before some of
        # the existing names; that's wrong
        last_dirblock[1].append(
            (('h', 'aaaa', 'a-id'),
             [('a', '', 0, False, ''),
              ('a', '', 0, False, '')]))
        e = self.assertRaises(AssertionError,
            state._validate)
        self.assertContainsRe(str(e), 'not sorted')

    def test_dirblock_name_mismatch(self):
        tree, state, expected = self.create_renamed_dirstate()
        state._read_dirblocks_if_needed()
        last_dirblock = state._dirblocks[-1]
        # add an entry with the wrong directory name
        last_dirblock[1].append(
            (('', 'z', 'a-id'),
             [('a', '', 0, False, ''),
              ('a', '', 0, False, '')]))
        e = self.assertRaises(AssertionError,
            state._validate)
        self.assertContainsRe(str(e),
            "doesn't match directory name")

    def test_dirblock_missing_rename(self):
        tree, state, expected = self.create_renamed_dirstate()
        state._read_dirblocks_if_needed()
        last_dirblock = state._dirblocks[-1]
        # make another entry for a-id, without a correct 'r' pointer to
        # the real occurrence in the working tree
        last_dirblock[1].append(
            (('h', 'z', 'a-id'),
             [('a', '', 0, False, ''),
              ('a', '', 0, False, '')]))
        e = self.assertRaises(AssertionError,
            state._validate)
        self.assertContainsRe(str(e),
            'file a-id is absent in row')


class TestDirstateTreeReference(TestCaseWithDirState):

    def test_reference_revision_is_none(self):
        tree = self.make_branch_and_tree('tree', format='development-subtree')
        subtree = self.make_branch_and_tree('tree/subtree',
                            format='development-subtree')
        subtree.set_root_id('subtree')
        tree.add_reference(subtree)
        tree.add('subtree')
        state = dirstate.DirState.from_tree(tree, 'dirstate')
        key = ('', 'subtree', 'subtree')
        expected = ('', [(key,
            [('t', '', 0, False, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')])])

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
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_entry_direntry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat),
            ('d', '', 0, False, packed_stat),
            ]
        dirblocks = []
        dirblocks.append(('', [root_entry_direntry]))
        dirblocks.append(('', []))

        state = self.create_empty_dirstate()
        self.addCleanup(state.unlock)
        state._set_data(['parent-id'], dirblocks[:])
        state._validate()

        state._discard_merge_parents()
        state._validate()
        self.assertEqual(dirblocks, state._dirblocks)

    def test_discard_simple(self):
        # No-op
        packed_stat = 'AAAAREUHaIpFB2iKAAADAQAtkqUAAIGk'
        root_entry_direntry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat),
            ('d', '', 0, False, packed_stat),
            ('d', '', 0, False, packed_stat),
            ]
        expected_root_entry_direntry = ('', '', 'a-root-value'), [
            ('d', '', 0, False, packed_stat),
            ('d', '', 0, False, packed_stat),
            ]
        dirblocks = []
        dirblocks.append(('', [root_entry_direntry]))
        dirblocks.append(('', []))

        state = self.create_empty_dirstate()
        self.addCleanup(state.unlock)
        state._set_data(['parent-id', 'merged-id'], dirblocks[:])
        state._validate()

        # This should strip of the extra column
        state._discard_merge_parents()
        state._validate()
        expected_dirblocks = [('', [expected_root_entry_direntry]), ('', [])]
        self.assertEqual(expected_dirblocks, state._dirblocks)

    def test_discard_absent(self):
        """If entries are only in a merge, discard should remove the entries"""
        null_stat = dirstate.DirState.NULLSTAT
        present_dir = ('d', '', 0, False, null_stat)
        present_file = ('f', '', 0, False, null_stat)
        absent = dirstate.DirState.NULL_PARENT_DETAILS
        root_key = ('', '', 'a-root-value')
        file_in_root_key = ('', 'file-in-root', 'a-file-id')
        file_in_merged_key = ('', 'file-in-merged', 'b-file-id')
        dirblocks = [('', [(root_key, [present_dir, present_dir, present_dir])]),
                     ('', [(file_in_merged_key,
                            [absent, absent, present_file]),
                           (file_in_root_key,
                            [present_file, present_file, present_file]),
                          ]),
                    ]

        state = self.create_empty_dirstate()
        self.addCleanup(state.unlock)
        state._set_data(['parent-id', 'merged-id'], dirblocks[:])
        state._validate()

        exp_dirblocks = [('', [(root_key, [present_dir, present_dir])]),
                         ('', [(file_in_root_key,
                                [present_file, present_file]),
                              ]),
                        ]
        state._discard_merge_parents()
        state._validate()
        self.assertEqual(exp_dirblocks, state._dirblocks)

    def test_discard_renamed(self):
        null_stat = dirstate.DirState.NULLSTAT
        present_dir = ('d', '', 0, False, null_stat)
        present_file = ('f', '', 0, False, null_stat)
        absent = dirstate.DirState.NULL_PARENT_DETAILS
        root_key = ('', '', 'a-root-value')
        file_in_root_key = ('', 'file-in-root', 'a-file-id')
        # Renamed relative to parent
        file_rename_s_key = ('', 'file-s', 'b-file-id')
        file_rename_t_key = ('', 'file-t', 'b-file-id')
        # And one that is renamed between the parents, but absent in this
        key_in_1 = ('', 'file-in-1', 'c-file-id')
        key_in_2 = ('', 'file-in-2', 'c-file-id')

        dirblocks = [
            ('', [(root_key, [present_dir, present_dir, present_dir])]),
            ('', [(key_in_1,
                   [absent, present_file, ('r', 'file-in-2', 'c-file-id')]),
                  (key_in_2,
                   [absent, ('r', 'file-in-1', 'c-file-id'), present_file]),
                  (file_in_root_key,
                   [present_file, present_file, present_file]),
                  (file_rename_s_key,
                   [('r', 'file-t', 'b-file-id'), absent, present_file]),
                  (file_rename_t_key,
                   [present_file, absent, ('r', 'file-s', 'b-file-id')]),
                 ]),
        ]
        exp_dirblocks = [
            ('', [(root_key, [present_dir, present_dir])]),
            ('', [(key_in_1, [absent, present_file]),
                  (file_in_root_key, [present_file, present_file]),
                  (file_rename_t_key, [present_file, absent]),
                 ]),
        ]
        state = self.create_empty_dirstate()
        self.addCleanup(state.unlock)
        state._set_data(['parent-id', 'merged-id'], dirblocks[:])
        state._validate()

        state._discard_merge_parents()
        state._validate()
        self.assertEqual(exp_dirblocks, state._dirblocks)

    def test_discard_all_subdir(self):
        null_stat = dirstate.DirState.NULLSTAT
        present_dir = ('d', '', 0, False, null_stat)
        present_file = ('f', '', 0, False, null_stat)
        absent = dirstate.DirState.NULL_PARENT_DETAILS
        root_key = ('', '', 'a-root-value')
        subdir_key = ('', 'sub', 'dir-id')
        child1_key = ('sub', 'child1', 'child1-id')
        child2_key = ('sub', 'child2', 'child2-id')
        child3_key = ('sub', 'child3', 'child3-id')

        dirblocks = [
            ('', [(root_key, [present_dir, present_dir, present_dir])]),
            ('', [(subdir_key, [present_dir, present_dir, present_dir])]),
            ('sub', [(child1_key, [absent, absent, present_file]),
                     (child2_key, [absent, absent, present_file]),
                     (child3_key, [absent, absent, present_file]),
                    ]),
        ]
        exp_dirblocks = [
            ('', [(root_key, [present_dir, present_dir])]),
            ('', [(subdir_key, [present_dir, present_dir])]),
            ('sub', []),
        ]
        state = self.create_empty_dirstate()
        self.addCleanup(state.unlock)
        state._set_data(['parent-id', 'merged-id'], dirblocks[:])
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
        (minikind, fingerprint, size, executable, tree_data) = details
        self.assertIsInstance(minikind, str)
        self.assertIsInstance(fingerprint, str)
        self.assertIsInstance(tree_data, str)

    def test_unicode_symlink(self):
        inv_entry = inventory.InventoryLink('link-file-id',
                                            u'nam\N{Euro Sign}e',
                                            'link-parent-id')
        inv_entry.revision = 'link-revision-id'
        target = u'link-targ\N{Euro Sign}t'
        inv_entry.symlink_target = target
        self.assertDetails(('l', target.encode('UTF-8'), 0, False,
                            'link-revision-id'), inv_entry)


class TestSHA1Provider(tests.TestCaseInTempDir):

    def test_sha1provider_is_an_interface(self):
        p = dirstate.SHA1Provider()
        self.assertRaises(NotImplementedError, p.sha1, "foo")
        self.assertRaises(NotImplementedError, p.stat_and_sha1, "foo")

    def test_defaultsha1provider_sha1(self):
        text = 'test\r\nwith\nall\rpossible line endings\r\n'
        self.build_tree_contents([('foo', text)])
        expected_sha = osutils.sha_string(text)
        p = dirstate.DefaultSHA1Provider()
        self.assertEqual(expected_sha, p.sha1('foo'))

    def test_defaultsha1provider_stat_and_sha1(self):
        text = 'test\r\nwith\nall\rpossible line endings\r\n'
        self.build_tree_contents([('foo', text)])
        expected_sha = osutils.sha_string(text)
        p = dirstate.DefaultSHA1Provider()
        statvalue, sha1 = p.stat_and_sha1('foo')
        self.assertTrue(len(statvalue) >= 10)
        self.assertEqual(len(text), statvalue.st_size)
        self.assertEqual(expected_sha, sha1)


class _Repo(object):
    """A minimal api to get InventoryRevisionTree to work."""

    def __init__(self):
        default_format = controldir.format_registry.make_bzrdir('default')
        self._format = default_format.repository_format

    def lock_read(self):
        pass

    def unlock(self):
        pass


class TestUpdateBasisByDelta(tests.TestCase):

    def path_to_ie(self, path, file_id, rev_id, dir_ids):
        if path.endswith('/'):
            is_dir = True
            path = path[:-1]
        else:
            is_dir = False
        dirname, basename = osutils.split(path)
        try:
            dir_id = dir_ids[dirname]
        except KeyError:
            dir_id = osutils.basename(dirname) + '-id'
        if is_dir:
            ie = inventory.InventoryDirectory(file_id, basename, dir_id)
            dir_ids[path] = file_id
        else:
            ie = inventory.InventoryFile(file_id, basename, dir_id)
            ie.text_size = 0
            ie.text_sha1 = ''
        ie.revision = rev_id
        return ie

    def create_tree_from_shape(self, rev_id, shape):
        dir_ids = {'': 'root-id'}
        inv = inventory.Inventory('root-id', rev_id)
        for info in shape:
            if len(info) == 2:
                path, file_id = info
                ie_rev_id = rev_id
            else:
                path, file_id, ie_rev_id = info
            if path == '':
                # Replace the root entry
                del inv._byid[inv.root.file_id]
                inv.root.file_id = file_id
                inv._byid[file_id] = inv.root
                dir_ids[''] = file_id
                continue
            inv.add(self.path_to_ie(path, file_id, ie_rev_id, dir_ids))
        return revisiontree.InventoryRevisionTree(_Repo(), inv, rev_id)

    def create_empty_dirstate(self):
        fd, path = tempfile.mkstemp(prefix='bzr-dirstate')
        self.addCleanup(os.remove, path)
        os.close(fd)
        state = dirstate.DirState.initialize(path)
        self.addCleanup(state.unlock)
        return state

    def create_inv_delta(self, delta, rev_id):
        """Translate a 'delta shape' into an actual InventoryDelta"""
        dir_ids = {'': 'root-id'}
        inv_delta = []
        for old_path, new_path, file_id in delta:
            if old_path is not None and old_path.endswith('/'):
                # Don't have to actually do anything for this, because only
                # new_path creates InventoryEntries
                old_path = old_path[:-1]
            if new_path is None: # Delete
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
        active_tree = self.create_tree_from_shape('active', active)
        basis_tree = self.create_tree_from_shape('basis', basis)
        target_tree = self.create_tree_from_shape('target', target)
        state = self.create_empty_dirstate()
        state.set_state_from_scratch(active_tree.root_inventory,
            [('basis', basis_tree)], [])
        delta = target_tree.root_inventory._make_delta(
            basis_tree.root_inventory)
        state.update_basis_by_delta(delta, 'target')
        state._validate()
        dirstate_tree = workingtree_4.DirStateRevisionTree(state,
            'target', _Repo())
        # The target now that delta has been applied should match the
        # RevisionTree
        self.assertEqual([], list(dirstate_tree.iter_changes(target_tree)))
        # And the dirblock state should be identical to the state if we created
        # it from scratch.
        state2 = self.create_empty_dirstate()
        state2.set_state_from_scratch(active_tree.root_inventory,
            [('target', target_tree)], [])
        self.assertEqual(state2._dirblocks, state._dirblocks)
        return state

    def assertBadDelta(self, active, basis, delta):
        """Test that we raise InconsistentDelta when appropriate.

        :param active: The active tree shape
        :param basis: The basis tree shape
        :param delta: A description of the delta to apply. Similar to the form
            for regular inventory deltas, but omitting the InventoryEntry.
            So adding a file is: (None, 'path', 'file-id')
            Adding a directory is: (None, 'path/', 'dir-id')
            Renaming a dir is: ('old/', 'new/', 'dir-id')
            etc.
        """
        active_tree = self.create_tree_from_shape('active', active)
        basis_tree = self.create_tree_from_shape('basis', basis)
        inv_delta = self.create_inv_delta(delta, 'target')
        state = self.create_empty_dirstate()
        state.set_state_from_scratch(active_tree.root_inventory,
            [('basis', basis_tree)], [])
        self.assertRaises(errors.InconsistentDelta,
            state.update_basis_by_delta, inv_delta, 'target')
        ## try:
        ##     state.update_basis_by_delta(inv_delta, 'target')
        ## except errors.InconsistentDelta, e:
        ##     import pdb; pdb.set_trace()
        ## else:
        ##     import pdb; pdb.set_trace()
        self.assertTrue(state._changes_aborted)

    def test_remove_file_matching_active_state(self):
        state = self.assertUpdate(
            active=[],
            basis =[('file', 'file-id')],
            target=[],
            )

    def test_remove_file_present_in_active_state(self):
        state = self.assertUpdate(
            active=[('file', 'file-id')],
            basis =[('file', 'file-id')],
            target=[],
            )

    def test_remove_file_present_elsewhere_in_active_state(self):
        state = self.assertUpdate(
            active=[('other-file', 'file-id')],
            basis =[('file', 'file-id')],
            target=[],
            )

    def test_remove_file_active_state_has_diff_file(self):
        state = self.assertUpdate(
            active=[('file', 'file-id-2')],
            basis =[('file', 'file-id')],
            target=[],
            )

    def test_remove_file_active_state_has_diff_file_and_file_elsewhere(self):
        state = self.assertUpdate(
            active=[('file', 'file-id-2'),
                    ('other-file', 'file-id')],
            basis =[('file', 'file-id')],
            target=[],
            )

    def test_add_file_matching_active_state(self):
        state = self.assertUpdate(
            active=[('file', 'file-id')],
            basis =[],
            target=[('file', 'file-id')],
            )

    def test_add_file_in_empty_dir_not_matching_active_state(self):
        state = self.assertUpdate(
                active=[],
                basis=[('dir/', 'dir-id')],
                target=[('dir/', 'dir-id', 'basis'), ('dir/file', 'file-id')],
                )

    def test_add_file_missing_in_active_state(self):
        state = self.assertUpdate(
            active=[],
            basis =[],
            target=[('file', 'file-id')],
            )

    def test_add_file_elsewhere_in_active_state(self):
        state = self.assertUpdate(
            active=[('other-file', 'file-id')],
            basis =[],
            target=[('file', 'file-id')],
            )

    def test_add_file_active_state_has_diff_file_and_file_elsewhere(self):
        state = self.assertUpdate(
            active=[('other-file', 'file-id'),
                    ('file', 'file-id-2')],
            basis =[],
            target=[('file', 'file-id')],
            )

    def test_rename_file_matching_active_state(self):
        state = self.assertUpdate(
            active=[('other-file', 'file-id')],
            basis =[('file', 'file-id')],
            target=[('other-file', 'file-id')],
            )

    def test_rename_file_missing_in_active_state(self):
        state = self.assertUpdate(
            active=[],
            basis =[('file', 'file-id')],
            target=[('other-file', 'file-id')],
            )

    def test_rename_file_present_elsewhere_in_active_state(self):
        state = self.assertUpdate(
            active=[('third', 'file-id')],
            basis =[('file', 'file-id')],
            target=[('other-file', 'file-id')],
            )

    def test_rename_file_active_state_has_diff_source_file(self):
        state = self.assertUpdate(
            active=[('file', 'file-id-2')],
            basis =[('file', 'file-id')],
            target=[('other-file', 'file-id')],
            )

    def test_rename_file_active_state_has_diff_target_file(self):
        state = self.assertUpdate(
            active=[('other-file', 'file-id-2')],
            basis =[('file', 'file-id')],
            target=[('other-file', 'file-id')],
            )

    def test_rename_file_active_has_swapped_files(self):
        state = self.assertUpdate(
            active=[('file', 'file-id'),
                    ('other-file', 'file-id-2')],
            basis= [('file', 'file-id'),
                    ('other-file', 'file-id-2')],
            target=[('file', 'file-id-2'),
                    ('other-file', 'file-id')])

    def test_rename_file_basis_has_swapped_files(self):
        state = self.assertUpdate(
            active=[('file', 'file-id'),
                    ('other-file', 'file-id-2')],
            basis= [('file', 'file-id-2'),
                    ('other-file', 'file-id')],
            target=[('file', 'file-id'),
                    ('other-file', 'file-id-2')])

    def test_rename_directory_with_contents(self):
        state = self.assertUpdate( # active matches basis
            active=[('dir1/', 'dir-id'),
                    ('dir1/file', 'file-id')],
            basis= [('dir1/', 'dir-id'),
                    ('dir1/file', 'file-id')],
            target=[('dir2/', 'dir-id'),
                    ('dir2/file', 'file-id')])
        state = self.assertUpdate( # active matches target
            active=[('dir2/', 'dir-id'),
                    ('dir2/file', 'file-id')],
            basis= [('dir1/', 'dir-id'),
                    ('dir1/file', 'file-id')],
            target=[('dir2/', 'dir-id'),
                    ('dir2/file', 'file-id')])
        state = self.assertUpdate( # active empty
            active=[],
            basis= [('dir1/', 'dir-id'),
                    ('dir1/file', 'file-id')],
            target=[('dir2/', 'dir-id'),
                    ('dir2/file', 'file-id')])
        state = self.assertUpdate( # active present at other location
            active=[('dir3/', 'dir-id'),
                    ('dir3/file', 'file-id')],
            basis= [('dir1/', 'dir-id'),
                    ('dir1/file', 'file-id')],
            target=[('dir2/', 'dir-id'),
                    ('dir2/file', 'file-id')])
        state = self.assertUpdate( # active has different ids
            active=[('dir1/', 'dir1-id'),
                    ('dir1/file', 'file1-id'),
                    ('dir2/', 'dir2-id'),
                    ('dir2/file', 'file2-id')],
            basis= [('dir1/', 'dir-id'),
                    ('dir1/file', 'file-id')],
            target=[('dir2/', 'dir-id'),
                    ('dir2/file', 'file-id')])

    def test_invalid_file_not_present(self):
        state = self.assertBadDelta(
            active=[('file', 'file-id')],
            basis= [('file', 'file-id')],
            delta=[('other-file', 'file', 'file-id')])

    def test_invalid_new_id_same_path(self):
        # The bad entry comes after
        state = self.assertBadDelta(
            active=[('file', 'file-id')],
            basis= [('file', 'file-id')],
            delta=[(None, 'file', 'file-id-2')])
        # The bad entry comes first
        state = self.assertBadDelta(
            active=[('file', 'file-id-2')],
            basis=[('file', 'file-id-2')],
            delta=[(None, 'file', 'file-id')])

    def test_invalid_existing_id(self):
        state = self.assertBadDelta(
            active=[('file', 'file-id')],
            basis= [('file', 'file-id')],
            delta=[(None, 'file', 'file-id')])

    def test_invalid_parent_missing(self):
        state = self.assertBadDelta(
            active=[],
            basis= [],
            delta=[(None, 'path/path2', 'file-id')])
        # Note: we force the active tree to have the directory, by knowing how
        #       path_to_ie handles entries with missing parents
        state = self.assertBadDelta(
            active=[('path/', 'path-id')],
            basis= [],
            delta=[(None, 'path/path2', 'file-id')])
        state = self.assertBadDelta(
            active=[('path/', 'path-id'),
                    ('path/path2', 'file-id')],
            basis= [],
            delta=[(None, 'path/path2', 'file-id')])

    def test_renamed_dir_same_path(self):
        # We replace the parent directory, with another parent dir. But the C
        # file doesn't look like it has been moved.
        state = self.assertUpdate(# Same as basis
            active=[('dir/', 'A-id'),
                    ('dir/B', 'B-id')],
            basis= [('dir/', 'A-id'),
                    ('dir/B', 'B-id')],
            target=[('dir/', 'C-id'),
                    ('dir/B', 'B-id')])
        state = self.assertUpdate(# Same as target
            active=[('dir/', 'C-id'),
                    ('dir/B', 'B-id')],
            basis= [('dir/', 'A-id'),
                    ('dir/B', 'B-id')],
            target=[('dir/', 'C-id'),
                    ('dir/B', 'B-id')])
        state = self.assertUpdate(# empty active
            active=[],
            basis= [('dir/', 'A-id'),
                    ('dir/B', 'B-id')],
            target=[('dir/', 'C-id'),
                    ('dir/B', 'B-id')])
        state = self.assertUpdate(# different active
            active=[('dir/', 'D-id'),
                    ('dir/B', 'B-id')],
            basis= [('dir/', 'A-id'),
                    ('dir/B', 'B-id')],
            target=[('dir/', 'C-id'),
                    ('dir/B', 'B-id')])

    def test_parent_child_swap(self):
        state = self.assertUpdate(# Same as basis
            active=[('A/', 'A-id'),
                    ('A/B/', 'B-id'),
                    ('A/B/C', 'C-id')],
            basis= [('A/', 'A-id'),
                    ('A/B/', 'B-id'),
                    ('A/B/C', 'C-id')],
            target=[('A/', 'B-id'),
                    ('A/B/', 'A-id'),
                    ('A/B/C', 'C-id')])
        state = self.assertUpdate(# Same as target
            active=[('A/', 'B-id'),
                    ('A/B/', 'A-id'),
                    ('A/B/C', 'C-id')],
            basis= [('A/', 'A-id'),
                    ('A/B/', 'B-id'),
                    ('A/B/C', 'C-id')],
            target=[('A/', 'B-id'),
                    ('A/B/', 'A-id'),
                    ('A/B/C', 'C-id')])
        state = self.assertUpdate(# empty active
            active=[],
            basis= [('A/', 'A-id'),
                    ('A/B/', 'B-id'),
                    ('A/B/C', 'C-id')],
            target=[('A/', 'B-id'),
                    ('A/B/', 'A-id'),
                    ('A/B/C', 'C-id')])
        state = self.assertUpdate(# different active
            active=[('D/', 'A-id'),
                    ('D/E/', 'B-id'),
                    ('F', 'C-id')],
            basis= [('A/', 'A-id'),
                    ('A/B/', 'B-id'),
                    ('A/B/C', 'C-id')],
            target=[('A/', 'B-id'),
                    ('A/B/', 'A-id'),
                    ('A/B/C', 'C-id')])

    def test_change_root_id(self):
        state = self.assertUpdate( # same as basis
            active=[('', 'root-id'),
                    ('file', 'file-id')],
            basis= [('', 'root-id'),
                    ('file', 'file-id')],
            target=[('', 'target-root-id'),
                    ('file', 'file-id')])
        state = self.assertUpdate( # same as target
            active=[('', 'target-root-id'),
                    ('file', 'file-id')],
            basis= [('', 'root-id'),
                    ('file', 'file-id')],
            target=[('', 'target-root-id'),
                    ('file', 'root-id')])
        state = self.assertUpdate( # all different
            active=[('', 'active-root-id'),
                    ('file', 'file-id')],
            basis= [('', 'root-id'),
                    ('file', 'file-id')],
            target=[('', 'target-root-id'),
                    ('file', 'root-id')])

    def test_change_file_absent_in_active(self):
        state = self.assertUpdate(
            active=[],
            basis= [('file', 'file-id')],
            target=[('file', 'file-id')])

    def test_invalid_changed_file(self):
        state = self.assertBadDelta( # Not present in basis
            active=[('file', 'file-id')],
            basis= [],
            delta=[('file', 'file', 'file-id')])
        state = self.assertBadDelta( # present at another location in basis
            active=[('file', 'file-id')],
            basis= [('other-file', 'file-id')],
            delta=[('file', 'file', 'file-id')])
