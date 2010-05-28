# Copyright (C) 2007 Canonical Ltd
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

"""Blackbox testing for merge_into functionality."""

from bzrlib import (
    tests,
    )

from bzrlib.tests.test_merge_into import TestMergeIntoBase


class TestMergeInto(TestMergeIntoBase):

    def test_smoke(self):
        # Just make sure the command-line works
        project_wt, lib_wt = self.setup_two_branches()

        self.run_bzr('merge-into ../lib1 lib1', working_dir='project')

        project_wt.lock_read()
        try:
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
        finally:
            project_wt.unlock()

    def test_dotted_name(self):
        project_wt, lib_wt = self.setup_two_branches()

        self.run_bzr('merge-into ../lib1 ./lib1', working_dir='project')

        project_wt.lock_read()
        try:
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
        finally:
            project_wt.unlock()
