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
    cleanup,
    inventory,
    merge,
    osutils,
    tests,
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

    def do_merge_into(self, location, merge_as=None):
        operation = cleanup.OperationWithCleanups(merge.merge_into_helper)
        return operation.run_simple(location, merge_as, operation.add_cleanup)

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

