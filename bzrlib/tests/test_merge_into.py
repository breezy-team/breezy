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
    inventory,
    merge_into,
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


class TestMergeInto(TestMergeIntoBase):

    def test_merge_into_newdir_with_unique_roots(self):
        project_wt, lib_wt = self.setup_two_branches()

        merge_into.merge_into_helper('lib1', 'lib1',
                                     this_location='project')

        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        new_lib1_id = project_wt.path2id('lib1')
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

    def test_merge_into_subdir(self):
        project_wt, lib_wt = self.setup_two_branches()

        merge_into.merge_into_helper('lib1', 'dir/lib1',
                                     this_location='project')

        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        new_lib1_id = project_wt.path2id('dir/lib1')
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

    def test_merge_into_newdir_with_repeat_roots(self):
        project_wt, lib_wt = self.setup_two_branches(custom_root_ids=False)

        root_id = project_wt.path2id('')
        merge_into.merge_into_helper('lib1', 'lib1',
                                     this_location='project')

        project_wt.lock_read()
        self.addCleanup(project_wt.unlock)
        # The lib-1 revision should be merged into this one
        self.assertEqual(['project-1', 'lib-1'],
                         project_wt.get_parent_ids())
        new_lib1_id = project_wt.path2id('lib1')
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
