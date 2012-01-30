# Copyright (C) 2008 Canonical Ltd
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

"""Tests for repositories that support CHK indices."""

from bzrlib import (
    btree_index,
    errors,
    osutils,
    repository,
    )
from bzrlib.remote import RemoteRepository
from bzrlib.versionedfile import VersionedFiles
from bzrlib.tests import TestNotApplicable
from bzrlib.tests.per_repository_chk import TestCaseWithRepositoryCHK


class TestCHKSupport(TestCaseWithRepositoryCHK):

    def test_chk_bytes_attribute_is_VersionedFiles(self):
        repo = self.make_repository('.')
        self.assertIsInstance(repo.chk_bytes, VersionedFiles)

    def test_add_bytes_to_chk_bytes_store(self):
        repo = self.make_repository('.')
        repo.lock_write()
        try:
            repo.start_write_group()
            try:
                sha1, len, _ = repo.chk_bytes.add_lines((None,),
                    None, ["foo\n", "bar\n"], random_id=True)
                self.assertEqual('4e48e2c9a3d2ca8a708cb0cc545700544efb5021',
                    sha1)
                self.assertEqual(
                    set([('sha1:4e48e2c9a3d2ca8a708cb0cc545700544efb5021',)]),
                    repo.chk_bytes.keys())
            except:
                repo.abort_write_group()
                raise
            else:
                repo.commit_write_group()
        finally:
            repo.unlock()
        # And after an unlock/lock pair
        repo.lock_read()
        try:
            self.assertEqual(
                set([('sha1:4e48e2c9a3d2ca8a708cb0cc545700544efb5021',)]),
                repo.chk_bytes.keys())
        finally:
            repo.unlock()
        # and reopening
        repo = repo.bzrdir.open_repository()
        repo.lock_read()
        try:
            self.assertEqual(
                set([('sha1:4e48e2c9a3d2ca8a708cb0cc545700544efb5021',)]),
                repo.chk_bytes.keys())
        finally:
            repo.unlock()

    def test_pack_preserves_chk_bytes_store(self):
        leaf_lines = ["chkleaf:\n", "0\n", "1\n", "0\n", "\n"]
        leaf_sha1 = osutils.sha_strings(leaf_lines)
        node_lines = ["chknode:\n", "0\n", "1\n", "1\n", "foo\n",
                      "\x00sha1:%s\n" % (leaf_sha1,)]
        node_sha1 = osutils.sha_strings(node_lines)
        expected_set = set([('sha1:' + leaf_sha1,), ('sha1:' + node_sha1,)])
        repo = self.make_repository('.')
        repo.lock_write()
        try:
            repo.start_write_group()
            try:
                # Internal node pointing at a leaf.
                repo.chk_bytes.add_lines((None,), None, node_lines, random_id=True)
            except:
                repo.abort_write_group()
                raise
            else:
                repo.commit_write_group()
            repo.start_write_group()
            try:
                # Leaf in a separate pack.
                repo.chk_bytes.add_lines((None,), None, leaf_lines, random_id=True)
            except:
                repo.abort_write_group()
                raise
            else:
                repo.commit_write_group()
            repo.pack()
            self.assertEqual(expected_set, repo.chk_bytes.keys())
        finally:
            repo.unlock()
        # and reopening
        repo = repo.bzrdir.open_repository()
        repo.lock_read()
        try:
            self.assertEqual(expected_set, repo.chk_bytes.keys())
        finally:
            repo.unlock()

    def test_chk_bytes_are_fully_buffered(self):
        repo = self.make_repository('.')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        try:
            sha1, len, _ = repo.chk_bytes.add_lines((None,),
                None, ["foo\n", "bar\n"], random_id=True)
            self.assertEqual('4e48e2c9a3d2ca8a708cb0cc545700544efb5021',
                sha1)
            self.assertEqual(
                set([('sha1:4e48e2c9a3d2ca8a708cb0cc545700544efb5021',)]),
                repo.chk_bytes.keys())
        except:
            repo.abort_write_group()
            raise
        else:
            repo.commit_write_group()
        # This may not always be correct if we change away from BTreeGraphIndex
        # in the future. But for now, lets check that chk_bytes are fully
        # buffered
        index = repo.chk_bytes._index._graph_index._indices[0]
        self.assertIsInstance(index, btree_index.BTreeGraphIndex)
        self.assertIs(type(index._leaf_node_cache), dict)
        # Re-opening the repository should also have a repo with everything
        # fully buffered
        repo2 = repository.Repository.open(self.get_url())
        repo2.lock_read()
        self.addCleanup(repo2.unlock)
        index = repo2.chk_bytes._index._graph_index._indices[0]
        self.assertIsInstance(index, btree_index.BTreeGraphIndex)
        self.assertIs(type(index._leaf_node_cache), dict)


class TestCommitWriteGroupIntegrityCheck(TestCaseWithRepositoryCHK):
    """Tests that commit_write_group prevents various kinds of invalid data
    from being committed to a CHK repository.
    """

    def reopen_repo_and_resume_write_group(self, repo):
        resume_tokens = repo.suspend_write_group()
        repo.unlock()
        reopened_repo = repo.bzrdir.open_repository()
        reopened_repo.lock_write()
        self.addCleanup(reopened_repo.unlock)
        reopened_repo.resume_write_group(resume_tokens)
        return reopened_repo

    def test_missing_chk_root_for_inventory(self):
        """commit_write_group fails with BzrCheckError when the chk root record
        for a new inventory is missing.
        """
        repo = self.make_repository('damaged-repo')
        builder = self.make_branch_builder('simple-branch')
        builder.build_snapshot('A-id', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'content\n'))])
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        repo.lock_write()
        repo.start_write_group()
        # Now, add the objects manually
        text_keys = [('file-id', 'A-id'), ('root-id', 'A-id')]
        # Directly add the texts, inventory, and revision object for 'A-id' --
        # but don't add the chk_bytes.
        src_repo = b.repository
        repo.texts.insert_record_stream(src_repo.texts.get_record_stream(
            text_keys, 'unordered', True))
        repo.inventories.insert_record_stream(
            src_repo.inventories.get_record_stream(
                [('A-id',)], 'unordered', True))
        repo.revisions.insert_record_stream(
            src_repo.revisions.get_record_stream(
                [('A-id',)], 'unordered', True))
        # Make sure the presence of the missing data in a fallback does not
        # avoid the error.
        repo.add_fallback_repository(b.repository)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)
        reopened_repo = self.reopen_repo_and_resume_write_group(repo)
        self.assertRaises(
            errors.BzrCheckError, reopened_repo.commit_write_group)
        reopened_repo.abort_write_group()

    def test_missing_chk_root_for_unchanged_inventory(self):
        """commit_write_group fails with BzrCheckError when the chk root record
        for a new inventory is missing, even if the parent inventory is present
        and has identical content (i.e. the same chk root).
        
        A stacked repository containing only a revision with an identical
        inventory to its parent will still have the chk root records for those
        inventories.

        (In principle the chk records are unnecessary in this case, but in
        practice bzr 2.0rc1 (at least) expects to find them.)
        """
        repo = self.make_repository('damaged-repo')
        # Make a branch where the last two revisions have identical
        # inventories.
        builder = self.make_branch_builder('simple-branch')
        builder.build_snapshot('A-id', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'content\n'))])
        builder.build_snapshot('B-id', None, [])
        builder.build_snapshot('C-id', None, [])
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        # check our setup: B-id and C-id should have identical chk root keys.
        inv_b = b.repository.get_inventory('B-id')
        inv_c = b.repository.get_inventory('C-id')
        if not isinstance(repo, RemoteRepository):
            # Remote repositories always return plain inventories
            self.assertEqual(inv_b.id_to_entry.key(), inv_c.id_to_entry.key())
        # Now, manually insert objects for a stacked repo with only revision
        # C-id:
        # We need ('revisions', 'C-id'), ('inventories', 'C-id'),
        # ('inventories', 'B-id'), and the corresponding chk roots for those
        # inventories.
        repo.lock_write()
        repo.start_write_group()
        src_repo = b.repository
        repo.inventories.insert_record_stream(
            src_repo.inventories.get_record_stream(
                [('B-id',), ('C-id',)], 'unordered', True))
        repo.revisions.insert_record_stream(
            src_repo.revisions.get_record_stream(
                [('C-id',)], 'unordered', True))
        # Make sure the presence of the missing data in a fallback does not
        # avoid the error.
        repo.add_fallback_repository(b.repository)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)
        reopened_repo = self.reopen_repo_and_resume_write_group(repo)
        self.assertRaises(
            errors.BzrCheckError, reopened_repo.commit_write_group)
        reopened_repo.abort_write_group()

    def test_missing_chk_leaf_for_inventory(self):
        """commit_write_group fails with BzrCheckError when the chk root record
        for a parent inventory of a new revision is missing.
        """
        repo = self.make_repository('damaged-repo')
        if isinstance(repo, RemoteRepository):
            raise TestNotApplicable(
                "Unable to obtain CHKInventory from remote repo")
        b = self.make_branch_with_multiple_chk_nodes()
        src_repo = b.repository
        src_repo.lock_read()
        self.addCleanup(src_repo.unlock)
        # Now, manually insert objects for a stacked repo with only revision
        # C-id, *except* drop the non-root chk records.
        inv_b = src_repo.get_inventory('B-id')
        inv_c = src_repo.get_inventory('C-id')
        chk_root_keys_only = [
            inv_b.id_to_entry.key(), inv_b.parent_id_basename_to_file_id.key(),
            inv_c.id_to_entry.key(), inv_c.parent_id_basename_to_file_id.key()]
        all_chks = src_repo.chk_bytes.keys()
        # Pick a non-root key to drop
        key_to_drop = all_chks.difference(chk_root_keys_only).pop()
        all_chks.discard(key_to_drop)
        repo.lock_write()
        repo.start_write_group()
        repo.chk_bytes.insert_record_stream(
            src_repo.chk_bytes.get_record_stream(
                all_chks, 'unordered', True))
        repo.texts.insert_record_stream(
            src_repo.texts.get_record_stream(
                src_repo.texts.keys(), 'unordered', True))
        repo.inventories.insert_record_stream(
            src_repo.inventories.get_record_stream(
                [('B-id',), ('C-id',)], 'unordered', True))
        repo.revisions.insert_record_stream(
            src_repo.revisions.get_record_stream(
                [('C-id',)], 'unordered', True))
        # Make sure the presence of the missing data in a fallback does not
        # avoid the error.
        repo.add_fallback_repository(b.repository)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)
        reopened_repo = self.reopen_repo_and_resume_write_group(repo)
        self.assertRaises(
            errors.BzrCheckError, reopened_repo.commit_write_group)
        reopened_repo.abort_write_group()

    def test_missing_chk_root_for_parent_inventory(self):
        """commit_write_group fails with BzrCheckError when the chk root record
        for a parent inventory of a new revision is missing.
        """
        repo = self.make_repository('damaged-repo')
        if isinstance(repo, RemoteRepository):
            raise TestNotApplicable(
                "Unable to obtain CHKInventory from remote repo")
        b = self.make_branch_with_multiple_chk_nodes()
        b.lock_read()
        self.addCleanup(b.unlock)
        # Now, manually insert objects for a stacked repo with only revision
        # C-id, *except* the chk root entry for the parent inventory.
        # We need ('revisions', 'C-id'), ('inventories', 'C-id'),
        # ('inventories', 'B-id'), and the corresponding chk roots for those
        # inventories.
        inv_c = b.repository.get_inventory('C-id')
        chk_keys_for_c_only = [
            inv_c.id_to_entry.key(), inv_c.parent_id_basename_to_file_id.key()]
        repo.lock_write()
        repo.start_write_group()
        src_repo = b.repository
        repo.chk_bytes.insert_record_stream(
            src_repo.chk_bytes.get_record_stream(
                chk_keys_for_c_only, 'unordered', True))
        repo.inventories.insert_record_stream(
            src_repo.inventories.get_record_stream(
                [('B-id',), ('C-id',)], 'unordered', True))
        repo.revisions.insert_record_stream(
            src_repo.revisions.get_record_stream(
                [('C-id',)], 'unordered', True))
        # Make sure the presence of the missing data in a fallback does not
        # avoid the error.
        repo.add_fallback_repository(b.repository)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)
        reopened_repo = self.reopen_repo_and_resume_write_group(repo)
        self.assertRaises(
            errors.BzrCheckError, reopened_repo.commit_write_group)
        reopened_repo.abort_write_group()

    def make_branch_with_multiple_chk_nodes(self):
        # add and modify files with very long file-ids, so that the chk map
        # will need more than just a root node.
        builder = self.make_branch_builder('simple-branch')
        file_adds = []
        file_modifies = []
        for char in 'abc':
            name = char * 10000
            file_adds.append(
                ('add', ('file-' + name, 'file-%s-id' % name, 'file',
                         'content %s\n' % name)))
            file_modifies.append(
                ('modify', ('file-%s-id' % name, 'new content %s\n' % name)))
        builder.build_snapshot('A-id', None, [
            ('add', ('', 'root-id', 'directory', None))] +
            file_adds)
        builder.build_snapshot('B-id', None, [])
        builder.build_snapshot('C-id', None, file_modifies)
        return builder.get_branch()
        
    def test_missing_text_record(self):
        """commit_write_group fails with BzrCheckError when a text is missing.
        """
        repo = self.make_repository('damaged-repo')
        b = self.make_branch_with_multiple_chk_nodes()
        src_repo = b.repository
        src_repo.lock_read()
        self.addCleanup(src_repo.unlock)
        # Now, manually insert objects for a stacked repo with only revision
        # C-id, *except* drop one changed text.
        all_texts = src_repo.texts.keys()
        all_texts.remove(('file-%s-id' % ('c'*10000,), 'C-id'))
        repo.lock_write()
        repo.start_write_group()
        repo.chk_bytes.insert_record_stream(
            src_repo.chk_bytes.get_record_stream(
                src_repo.chk_bytes.keys(), 'unordered', True))
        repo.texts.insert_record_stream(
            src_repo.texts.get_record_stream(
                all_texts, 'unordered', True))
        repo.inventories.insert_record_stream(
            src_repo.inventories.get_record_stream(
                [('B-id',), ('C-id',)], 'unordered', True))
        repo.revisions.insert_record_stream(
            src_repo.revisions.get_record_stream(
                [('C-id',)], 'unordered', True))
        # Make sure the presence of the missing data in a fallback does not
        # avoid the error.
        repo.add_fallback_repository(b.repository)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)
        reopened_repo = self.reopen_repo_and_resume_write_group(repo)
        self.assertRaises(
            errors.BzrCheckError, reopened_repo.commit_write_group)
        reopened_repo.abort_write_group()




