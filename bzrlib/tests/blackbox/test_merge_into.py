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
        self.assertLib1MergedIntoProject(project_wt)

    def test_dotted_name(self):
        project_wt, lib_wt = self.setup_two_branches()
        self.run_bzr('merge-into ../lib1 ./lib1', working_dir='project')
        self.assertLib1MergedIntoProject(project_wt)

    def test_one_arg(self):
        """The MERGE_AS argument is optional, and defaults to the basename of
        LOCATION in the current working dir.
        """
        project_wt, lib_wt = self.setup_two_branches()
        self.run_bzr('merge-into ../lib1', working_dir='project')
        self.assertLib1MergedIntoProject(project_wt)

    def assertLib1MergedIntoProject(self, project_wt):
        project_wt.lock_read()
        try:
            new_lib1_id = project_wt.path2id('lib1')
            # The lib-1 revision should be merged into this one
            self.assertEqual(['r1-project', 'r1-lib1'],
                             project_wt.get_parent_ids())
            files = [(path, ie.kind, ie.file_id)
                     for path, ie in project_wt.iter_entries_by_dir()]
            exp_files = [('', 'directory', 'project-root-id'),
                         ('README', 'file', 'project-README-id'),
                         ('dir', 'directory', 'project-dir-id'),
                         ('lib1', 'directory', new_lib1_id),
                         ('dir/file.c', 'file', 'project-file.c-id'),
                         ('lib1/Makefile', 'file', 'lib1-Makefile-id'),
                         ('lib1/README', 'file', 'lib1-README-id'),
                         ('lib1/foo.c', 'file', 'lib1-foo.c-id'),
                        ]
            self.assertEqual(exp_files, files)
        finally:
            project_wt.unlock()

    def test_no_such_source_subdir(self):
        dest_wt = self.setup_simple_branch('dest')
        two_file_wt = self.setup_simple_branch('src', ['dir/'])
        out, err = self.run_bzr(
            'merge-into ../src/no-such-dir', working_dir='dest', retcode=3)
        self.assertEqual('', out)
        self.assertContainsRe(
            err, 'ERROR: Source tree does not contain no-such-dir')

    def test_no_such_target_subdir(self):
        dest_wt = self.setup_simple_branch('dest')
        two_file_wt = self.setup_simple_branch('src', ['dir/'])
        out, err = self.run_bzr(
            'merge-into ../src no-such-dir/foo', working_dir='dest', retcode=3)
        self.assertEqual('', out)
        self.assertContainsRe(
            err, 'ERROR: Target tree does not contain no-such-dir')
