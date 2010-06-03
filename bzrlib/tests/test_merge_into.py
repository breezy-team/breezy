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
    tests,
    )


class TestMergeIntoBase(tests.TestCaseWithTransport):

    def setup_two_branches(self, custom_root_ids=True):
        """Setup 2 branches, one will be a library, the other a project."""
        if custom_root_ids:
            proj_root = 'project-root-id'
            lib_root = 'lib1-root-id'
        else:
            proj_root = lib_root = inventory.ROOT_ID

        project_wt = self.make_branch_and_tree('project')
        self.build_tree(['project/README', 'project/dir/',
                         'project/dir/file.c'])
        project_wt.add(['README', 'dir', 'dir/file.c'],
                       ['readme-id', 'dir-id', 'file.c-id'])
        project_wt.set_root_id(proj_root)
        project_wt.commit('Initial project', rev_id='project-1')
        self.assertEqual(proj_root, project_wt.path2id(''))

        lib_wt = self.make_branch_and_tree('lib1')
        self.build_tree(['lib1/README', 'lib1/Makefile',
                         'lib1/foo.c'])
        lib_wt.add(['README', 'Makefile', 'foo.c'],
                   ['readme-lib-id', 'makefile-lib-id',
                    'foo.c-lib-id'])
        lib_wt.set_root_id(lib_root)
        lib_wt.commit('Initial lib project', rev_id='lib-1')
        self.assertEqual(lib_root, lib_wt.path2id(''))

        return project_wt, lib_wt

    def do_merge_into(self, location, merge_as=None):
        operation = cleanup.OperationWithCleanups(merge.merge_into_helper)
        return operation.run_simple(location, merge_as, operation.add_cleanup)


class TestMergeInto(TestMergeIntoBase):

    def test_newdir_with_unique_roots(self):
        """Merge a branch with a unique root into a new directory."""
        project_wt, lib_wt = self.setup_two_branches()

        self.do_merge_into('lib1', 'project/lib1')

        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        new_lib1_id = project_wt.path2id('lib1')
        self.assertNotEqual(None, new_lib1_id)
        # The lib-1 revision should be merged into this one
        self.assertEqual(['project-1', 'lib-1'],
                         project_wt.get_parent_ids())
        files = [(path, ie.kind, ie.file_id)
                 for path, ie in project_wt.iter_entries_by_dir()]
        exp_files = [('', 'directory', 'project-root-id'),
                     ('README', 'file', 'readme-id'),
                     ('dir', 'directory', 'dir-id'),
                     ('lib1', 'directory', new_lib1_id),
                     ('dir/file.c', 'file', 'file.c-id'),
                     ('lib1/Makefile', 'file', 'makefile-lib-id'),
                     ('lib1/README', 'file', 'readme-lib-id'),
                     ('lib1/foo.c', 'file', 'foo.c-lib-id'),
                    ]
        self.assertEqual(exp_files, files)

    def test_subdir(self):
        """Merge a branch into a subdirectory of an existing directory."""
        project_wt, lib_wt = self.setup_two_branches()

        self.do_merge_into('lib1', 'project/dir/lib1')

        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        new_lib1_id = project_wt.path2id('dir/lib1')
        self.assertNotEqual(None, new_lib1_id)
        # The lib-1 revision should be merged into this one
        self.assertEqual(['project-1', 'lib-1'],
                         project_wt.get_parent_ids())
        files = [(path, ie.kind, ie.file_id)
                 for path, ie in project_wt.iter_entries_by_dir()]
        exp_files = [('', 'directory', 'project-root-id'),
                     ('README', 'file', 'readme-id'),
                     ('dir', 'directory', 'dir-id'),
                     ('dir/file.c', 'file', 'file.c-id'),
                     ('dir/lib1', 'directory', new_lib1_id),
                     ('dir/lib1/Makefile', 'file', 'makefile-lib-id'),
                     ('dir/lib1/README', 'file', 'readme-lib-id'),
                     ('dir/lib1/foo.c', 'file', 'foo.c-lib-id'),
                    ]
        self.assertEqual(exp_files, files)

    def test_newdir_with_repeat_roots(self):
        """If the file-id of the dir to be merged already exists it a new ID
        will be allocated to let the merge happen.
        """
        project_wt, lib_wt = self.setup_two_branches(custom_root_ids=False)

        root_id = project_wt.path2id('')
        self.do_merge_into('lib1', 'project/lib1')

        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        # The lib-1 revision should be merged into this one
        self.assertEqual(['project-1', 'lib-1'],
                         project_wt.get_parent_ids())
        new_lib1_id = project_wt.path2id('lib1')
        self.assertNotEqual(None, new_lib1_id)
        files = [(path, ie.kind, ie.file_id)
                 for path, ie in project_wt.iter_entries_by_dir()]
        exp_files = [('', 'directory', root_id),
                     ('README', 'file', 'readme-id'),
                     ('dir', 'directory', 'dir-id'),
                     ('lib1', 'directory', new_lib1_id),
                     ('dir/file.c', 'file', 'file.c-id'),
                     ('lib1/Makefile', 'file', 'makefile-lib-id'),
                     ('lib1/README', 'file', 'readme-lib-id'),
                     ('lib1/foo.c', 'file', 'foo.c-lib-id'),
                    ]
        self.assertEqual(exp_files, files)

    def test_name_conflict(self):
        """When the target directory name already exists a conflict is
        generated and the original directory is renamed to foo.moved.
        """
        project_wt, lib_wt = self.setup_two_branches()
        conflicts = self.do_merge_into('lib1', 'project/dir')
        self.assertEqual(1, conflicts)
        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        new_lib1_id = project_wt.path2id('dir')
        self.assertNotEqual(None, new_lib1_id)
        # The lib-1 revision should be merged into this one
        self.assertEqual(['project-1', 'lib-1'],
                         project_wt.get_parent_ids())
        files = [(path, ie.kind, ie.file_id)
                 for path, ie in project_wt.iter_entries_by_dir()]
        exp_files = [('', 'directory', 'project-root-id'),
                     ('README', 'file', 'readme-id'),
                     ('dir', 'directory', new_lib1_id),
                     ('dir.moved', 'directory', 'dir-id'),
                     ('dir/Makefile', 'file', 'makefile-lib-id'),
                     ('dir/README', 'file', 'readme-lib-id'),
                     ('dir/foo.c', 'file', 'foo.c-lib-id'),
                     ('dir.moved/file.c', 'file', 'file.c-id'),
                    ]
        self.assertEqual(exp_files, files)

    def test_merge_just_file(self):
        """An edge case: merge just one file, not a whole dir."""
        project_wt, lib_wt = self.setup_two_branches()
        conflicts = self.do_merge_into('lib1/foo.c', 'project/foo.c')
        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        # The lib-1 revision should be merged into this one
        self.assertEqual(['project-1', 'lib-1'],
                         project_wt.get_parent_ids())
        files = [(path, ie.kind, ie.file_id)
                 for path, ie in project_wt.iter_entries_by_dir()]
        exp_files = [('', 'directory', 'project-root-id'),
                     ('README', 'file', 'readme-id'),
                     ('dir', 'directory', 'dir-id'),
                     ('foo.c', 'file', 'foo.c-lib-id'),
                     ('dir/file.c', 'file', 'file.c-id'),
                    ]
        self.assertEqual(exp_files, files)

