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
#

"""Tests variations of case-insensitive and case-preserving file-systems."""

import os

from bzrlib.tests.blackbox import ExternalBase
from bzrlib.tests import CaseInsCasePresFilenameFeature, KnownFailure
from bzrlib.osutils import canonical_relpath, pathjoin

class TestCICPBase(ExternalBase):
    """Base class for tests on a case-insensitive, case-preserving filesystem.
    """

    _test_needs_features = [CaseInsCasePresFilenameFeature]

    def _make_mixed_case_tree(self):
        """Make a working tree with mixed-case filenames."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case parent and base name
        self.build_tree(['CamelCaseParent/', 'lowercaseparent/'])
        self.build_tree_contents([('CamelCaseParent/CamelCase', 'camel case'),
                                  ('lowercaseparent/lowercase', 'lower case'),
                                  ('lowercaseparent/mixedCase', 'mixedCasecase'),
                                 ])
        return wt

    def check_error_output(self, retcode, output, *args):
        got = self.run_bzr(retcode=retcode, *args)[1]
        self.failUnlessEqual(got, output)

    def check_empty_output(self, *args):
        """Check a bzr command generates no output anywhere and exits with 0"""
        out, err = self.run_bzr(retcode=0, *args)
        self.failIf(out)
        self.failIf(err)


class TestAdd(TestCICPBase):

    def test_add_simple(self):
        """Test add always uses the case of the filename reported by the os."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case name
        self.build_tree(['CamelCase'])

        self.check_output('adding CamelCase\n', 'add camelcase')

    def test_add_subdir(self):
        """test_add_simple but with subdirectories tested too."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case parent and base name
        self.build_tree(['CamelCaseParent/', 'CamelCaseParent/CamelCase'])

        self.check_output('adding CamelCaseParent\n'
                          'adding CamelCaseParent/CamelCase\n',
                          'add camelcaseparent/camelcase')

    def test_add_implied(self):
        """test add with no args sees the correct names."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case parent and base name
        self.build_tree(['CamelCaseParent/', 'CamelCaseParent/CamelCase'])

        self.check_output('adding CamelCaseParent\n'
                          'adding CamelCaseParent/CamelCase\n',
                          'add')

    def test_re_add(self):
        """Test than when a file has 'unintentionally' changed case, we can't
        add a new entry using the new case."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case name
        self.build_tree(['MixedCase'])
        self.check_output('adding MixedCase\n', 'add MixedCase')
        # 'accidently' rename the file on disk
        os.rename('MixedCase', 'mixedcase')
        self.check_empty_output('add mixedcase')

    def test_re_add_dir(self):
        # like re-add, but tests when the operation is on a directory.
        """Test than when a file has 'unintentionally' changed case, we can't
        add a new entry using the new case."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case name
        self.build_tree(['MixedCaseParent/', 'MixedCaseParent/MixedCase'])
        self.check_output('adding MixedCaseParent\n'
                          'adding MixedCaseParent/MixedCase\n',
                          'add MixedCaseParent')
        # 'accidently' rename the directory on disk
        os.rename('MixedCaseParent', 'mixedcaseparent')
        self.check_empty_output('add mixedcaseparent')

    def test_add_not_found(self):
        """Test add when the input file doesn't exist."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case name
        self.build_tree(['MixedCaseParent/', 'MixedCaseParent/MixedCase'])
        expected_fname = pathjoin(wt.basedir, "MixedCaseParent", "notfound")
        expected_msg = "bzr: ERROR: No such file: %r\n" % expected_fname
        self.check_error_output(3, expected_msg, 'add mixedcaseparent/notfound')


class TestMove(TestCICPBase):
    def test_mv_newname(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')

        self.check_output(
            'CamelCaseParent/CamelCase => CamelCaseParent/NewCamelCase\n',
            'mv camelcaseparent/camelcase camelcaseparent/NewCamelCase')

    def test_mv_newname_after(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')
        os.rename('CamelCaseParent/CamelCase', 'CamelCaseParent/NewCamelCase')

        # In this case we can specify the incorrect case for the destination,
        # as we use --after, so the file-system is sniffed.
        self.check_output(
            'CamelCaseParent/CamelCase => CamelCaseParent/NewCamelCase\n',
            'mv --after camelcaseparent/camelcase camelcaseparent/newcamelcase')

    def test_mv_newname_exists(self):
        # test a mv, but when the target already exists with a name that
        # differs only by case.
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')
        ex = 'bzr: ERROR: Could not move CamelCase => lowercase: lowercaseparent/lowercase is already versioned.\n'
        self.check_error_output(3, ex, 'mv camelcaseparent/camelcase LOWERCASEPARENT/LOWERCASE')

    def test_mv_newname_exists_after(self):
        # test a 'mv --after', but when the target already exists with a name
        # that differs only by case.  Note that this is somewhat unlikely
        # but still reasonable.
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')
        # Remove the source and create a destination file on disk with a different case.
        # bzr should report that the filename is already versioned.
        os.unlink('CamelCaseParent/CamelCase')
        os.rename('lowercaseparent/lowercase', 'lowercaseparent/LOWERCASE')
        ex = 'bzr: ERROR: Could not move CamelCase => lowercase: lowercaseparent/lowercase is already versioned.\n'
        self.check_error_output(3, ex, 'mv --after camelcaseparent/camelcase LOWERCASEPARENT/LOWERCASE')

    def test_mv_newname_root(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')

        self.check_output('CamelCaseParent => NewCamelCaseParent\n',
                          'mv camelcaseparent NewCamelCaseParent')

    def test_mv_newname_root_after(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')
        os.rename('CamelCaseParent', 'NewCamelCaseParent')

        # In this case we can specify the incorrect case for the destination,
        # as we use --after, so the file-system is sniffed.
        self.check_output('CamelCaseParent => NewCamelCaseParent\n',
                          'mv --after camelcaseparent newcamelcaseparent')

    def test_mv_newcase(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')

        # perform a mv to the new case - we expect bzr to accept the new
        # name, as specified, and rename the file on the file-system too.
        self.check_output('CamelCaseParent/CamelCase => CamelCaseParent/camelCase\n',
                          'mv camelcaseparent/camelcase camelcaseparent/camelCase')
        self.failUnlessEqual(canonical_relpath(wt.basedir, 'camelcaseparent/camelcase'),
                             'CamelCaseParent/camelCase')

    def test_mv_newcase_after(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')

        # perform a mv to the new case - we must ensure the file-system has the
        # new case first.
        os.rename('CamelCaseParent/CamelCase', 'CamelCaseParent/camelCase')
        self.check_output('CamelCaseParent/CamelCase => CamelCaseParent/camelCase\n',
                          'mv --after camelcaseparent/camelcase camelcaseparent/camelCase')
        # bzr should not have renamed the file to a different case
        self.failUnlessEqual(canonical_relpath(wt.basedir, 'camelcaseparent/camelcase'),
                             'CamelCaseParent/camelCase')

    def test_mv_multiple(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')
        self.check_output('lowercaseparent/lowercase => CamelCaseParent/lowercase\n'
                          'lowercaseparent/mixedCase => CamelCaseParent/mixedCase\n',
                          'mv LOWercaseparent/LOWercase LOWercaseparent/MIXEDCase camelcaseparent')


class TestMisc(TestCICPBase):
    def test_status(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')

        self.check_output('added:\n  CamelCaseParent/CamelCase\n  lowercaseparent/lowercase\n',
                          'status camelcaseparent/camelcase LOWERCASEPARENT/LOWERCASE')

    def test_ci(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')

        got = self.run_bzr('ci -m message camelcaseparent LOWERCASEPARENT')[1]
        for expected in ['CamelCaseParent', 'lowercaseparent',
                         'CamelCaseParent/CamelCase', 'lowercaseparent/lowercase']:
            self.assertContainsRe(got, 'added ' + expected + '\n')

    def test_rm(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')

        got = self.run_bzr('rm camelcaseparent LOWERCASEPARENT')[1]
        for expected in ['lowercaseparent/lowercase', 'CamelCaseParent/CamelCase']:
            self.assertContainsRe(got, 'deleted ' + expected + '\n')


    # The following commands need tests and/or cicp lovin':
    # update, remove, file_id, file_path, diff, log, touching_revisions, ls,
    # ignore, cat, revert, resolve.
