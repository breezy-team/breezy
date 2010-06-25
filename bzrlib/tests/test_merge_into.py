# Copyright (C) 2007,2010 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Whitebox testing for merge_into functionality."""

from bzrlib import (
    branch as _mod_branch,
    cleanup,
    inventory,
    merge,
    osutils,
    revision as _mod_revision,
    tests,
    workingtree,
    )


class TestMergeIntoBase(tests.TestCaseWithTransport):

    def setup_simple_branch(self, relpath, shape=None, root_id=None):
        """One commit, containing tree specified by optional shape.
        
        Default is empty tree (just root entry).
        """
        if root_id is None:
            root_id = '%s-root-id' % (relpath,)
        wt = self.make_branch_and_tree(relpath)
        wt.set_root_id(root_id)
        if shape is not None:
            adjusted_shape = [relpath + '/' + elem for elem in shape]
            self.build_tree(adjusted_shape)
            ids = ['%s-%s-id' % (relpath, osutils.basename(elem.rstrip('/')))
                   for elem in shape]
            wt.add(shape, ids=ids)
        rev_id = 'r1-%s' % (relpath,)
        wt.commit("Initial commit of %s" % (relpath,), rev_id=rev_id)
        self.assertEqual(root_id, wt.path2id(''))
        return wt

    def setup_two_branches(self, custom_root_ids=True):
        """Setup 2 branches, one will be a library, the other a project."""
        if custom_root_ids:
            root_id = None
        else:
            root_id = inventory.ROOT_ID
        project_wt = self.setup_simple_branch(
            'project', ['README', 'dir/', 'dir/file.c'],
            root_id)
        lib_wt = self.setup_simple_branch(
            'lib1', ['README', 'Makefile', 'foo.c'], root_id)

        return project_wt, lib_wt

    def do_merge_into(self, location, merge_as):
        """Helper for using MergeIntoMerger.
        
        :param location: location of directory to merge from, either the
            location of a branch or of a path inside a branch.
        :param merge_as: the path in a tree to add the new directory as.
        :returns: the conflicts from 'do_merge'.
        """
        operation = cleanup.OperationWithCleanups(self._merge_into)
        return operation.run(location, merge_as)

    def _merge_into(self, op, location, merge_as):
        # Open and lock the various tree and branch objects
        wt, subdir_relpath = workingtree.WorkingTree.open_containing(merge_as)
        op.add_cleanup(wt.lock_write().unlock)
        branch_to_merge, subdir_to_merge = _mod_branch.Branch.open_containing(
            location)
        op.add_cleanup(branch_to_merge.lock_read().unlock)
        other_tree = branch_to_merge.basis_tree()
        op.add_cleanup(other_tree.lock_read().unlock)
        # Perform the merge
        merger = merge.MergeIntoMerger(this_tree=wt, other_tree=other_tree,
            other_branch=branch_to_merge, target_subdir=subdir_relpath,
            source_subpath=subdir_to_merge)
        merger.set_base_revision(_mod_revision.NULL_REVISION, branch_to_merge)
        conflicts = merger.do_merge()
        merger.set_pending()
        return conflicts

    def assertTreeEntriesEqual(self, expected_entries, tree):
        """Assert that 'tree' contains the expected inventory entries.

        :param expected_entries: sequence of (path, file-id) pairs.
        """
        files = [(path, ie.file_id) for path, ie in tree.iter_entries_by_dir()]
        self.assertEqual(expected_entries, files)


class TestMergeInto(TestMergeIntoBase):

    def test_newdir_with_unique_roots(self):
        """Merge a branch with a unique root into a new directory."""
        project_wt, lib_wt = self.setup_two_branches()
        self.do_merge_into('lib1', 'project/lib1')
        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        # The r1-lib1 revision should be merged into this one
        self.assertEqual(['r1-project', 'r1-lib1'], project_wt.get_parent_ids())
        self.assertTreeEntriesEqual(
            [('', 'project-root-id'),
             ('README', 'project-README-id'),
             ('dir', 'project-dir-id'),
             ('lib1', 'lib1-root-id'),
             ('dir/file.c', 'project-file.c-id'),
             ('lib1/Makefile', 'lib1-Makefile-id'),
             ('lib1/README', 'lib1-README-id'),
             ('lib1/foo.c', 'lib1-foo.c-id'),
            ], project_wt)

    def test_subdir(self):
        """Merge a branch into a subdirectory of an existing directory."""
        project_wt, lib_wt = self.setup_two_branches()
        self.do_merge_into('lib1', 'project/dir/lib1')
        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        # The r1-lib1 revision should be merged into this one
        self.assertEqual(['r1-project', 'r1-lib1'], project_wt.get_parent_ids())
        self.assertTreeEntriesEqual(
            [('', 'project-root-id'),
             ('README', 'project-README-id'),
             ('dir', 'project-dir-id'),
             ('dir/file.c', 'project-file.c-id'),
             ('dir/lib1', 'lib1-root-id'),
             ('dir/lib1/Makefile', 'lib1-Makefile-id'),
             ('dir/lib1/README', 'lib1-README-id'),
             ('dir/lib1/foo.c', 'lib1-foo.c-id'),
            ], project_wt)

    def test_newdir_with_repeat_roots(self):
        """If the file-id of the dir to be merged already exists a new ID will
        be allocated to let the merge happen.
        """
        project_wt, lib_wt = self.setup_two_branches(custom_root_ids=False)
        root_id = project_wt.path2id('')
        self.do_merge_into('lib1', 'project/lib1')
        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        # The r1-lib1 revision should be merged into this one
        self.assertEqual(['r1-project', 'r1-lib1'], project_wt.get_parent_ids())
        new_lib1_id = project_wt.path2id('lib1')
        self.assertNotEqual(None, new_lib1_id)
        self.assertTreeEntriesEqual(
            [('', root_id),
             ('README', 'project-README-id'),
             ('dir', 'project-dir-id'),
             ('lib1', new_lib1_id),
             ('dir/file.c', 'project-file.c-id'),
             ('lib1/Makefile', 'lib1-Makefile-id'),
             ('lib1/README', 'lib1-README-id'),
             ('lib1/foo.c', 'lib1-foo.c-id'),
            ], project_wt)

    def test_name_conflict(self):
        """When the target directory name already exists a conflict is
        generated and the original directory is renamed to foo.moved.
        """
        dest_wt = self.setup_simple_branch('dest', ['dir/', 'dir/file.txt'])
        src_wt = self.setup_simple_branch('src', ['README'])
        conflicts = self.do_merge_into('src', 'dest/dir')
        self.assertEqual(1, conflicts)
        dest_wt.lock_read()
        self.addCleanup(dest_wt.unlock)
        # The r1-lib1 revision should be merged into this one
        self.assertEqual(['r1-dest', 'r1-src'], dest_wt.get_parent_ids())
        self.assertTreeEntriesEqual(
            [('', 'dest-root-id'),
             ('dir', 'src-root-id'),
             ('dir.moved', 'dest-dir-id'),
             ('dir/README', 'src-README-id'),
             ('dir.moved/file.txt', 'dest-file.txt-id'),
            ], dest_wt)

    def test_file_id_conflict(self):
        """A conflict is generated if the merge-into adds a file (or other
        inventory entry) with a file-id that already exists in the target tree.
        """
        dest_wt = self.setup_simple_branch('dest', ['file.txt'])
        # Make a second tree with a file-id that will clash with file.txt in
        # dest.
        src_wt = self.make_branch_and_tree('src')
        self.build_tree(['src/README'])
        src_wt.add(['README'], ids=['dest-file.txt-id'])
        src_wt.commit("Rev 1 of src.", rev_id='r1-src')
        conflicts = self.do_merge_into('src', 'dest/dir')
        # This is an edge case that shouldn't happen to users very often.  So
        # we don't care really about the exact presentation of the conflict,
        # just that there is one.
        self.assertEqual(1, conflicts)

    def test_only_subdir(self):
        """When the location points to just part of a tree, merge just that
        subtree.
        """
        dest_wt = self.setup_simple_branch('dest')
        src_wt = self.setup_simple_branch(
            'src', ['hello.txt', 'dir/', 'dir/foo.c'])
        conflicts = self.do_merge_into('src/dir', 'dest/dir')
        dest_wt.lock_read()
        self.addCleanup(dest_wt.unlock)
        # The r1-lib1 revision should NOT be merged into this one (this is a
        # partial merge).
        self.assertEqual(['r1-dest'], dest_wt.get_parent_ids())
        self.assertTreeEntriesEqual(
            [('', 'dest-root-id'),
             ('dir', 'src-dir-id'),
             ('dir/foo.c', 'src-foo.c-id'),
            ], dest_wt)

    def test_only_file(self):
        """An edge case: merge just one file, not a whole dir."""
        dest_wt = self.setup_simple_branch('dest')
        two_file_wt = self.setup_simple_branch(
            'two-file', ['file1.txt', 'file2.txt'])
        conflicts = self.do_merge_into('two-file/file1.txt', 'dest/file1.txt')
        dest_wt.lock_read()
        self.addCleanup(dest_wt.unlock)
        # The r1-lib1 revision should NOT be merged into this one
        self.assertEqual(['r1-dest'], dest_wt.get_parent_ids())
        self.assertTreeEntriesEqual(
            [('', 'dest-root-id'), ('file1.txt', 'two-file-file1.txt-id')],
            dest_wt)

    def test_no_such_source_path(self):
        """PathNotInTree is raised if the specified path in the source tree
        does not exist.
        """
        dest_wt = self.setup_simple_branch('dest')
        two_file_wt = self.setup_simple_branch('src', ['dir/'])
        self.assertRaises(merge.PathNotInTree, self.do_merge_into,
            'src/no-such-dir', 'dest/foo')
        dest_wt.lock_read()
        self.addCleanup(dest_wt.unlock)
        # The dest tree is unmodified.
        self.assertEqual(['r1-dest'], dest_wt.get_parent_ids())
        self.assertTreeEntriesEqual([('', 'dest-root-id')], dest_wt)

    def test_no_such_target_path(self):
        """PathNotInTree is also raised if the specified path in the target
        tree does not exist.
        """
        dest_wt = self.setup_simple_branch('dest')
        two_file_wt = self.setup_simple_branch('src', ['file.txt'])
        self.assertRaises(merge.PathNotInTree, self.do_merge_into,
            'src', 'dest/no-such-dir/foo')
        dest_wt.lock_read()
        self.addCleanup(dest_wt.unlock)
        # The dest tree is unmodified.
        self.assertEqual(['r1-dest'], dest_wt.get_parent_ids())
        self.assertTreeEntriesEqual([('', 'dest-root-id')], dest_wt)
