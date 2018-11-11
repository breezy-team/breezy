# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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

from ... import (
    osutils,
    tests,
    )
from .. import KnownFailure
from ...osutils import canonical_relpath, pathjoin
from ..script import run_script
from ..features import (
    CaseInsCasePresFilenameFeature,
    )


class TestCICPBase(tests.TestCaseWithTransport):
    """Base class for tests on a case-insensitive, case-preserving filesystem.
    """

    _test_needs_features = [CaseInsCasePresFilenameFeature]

    def _make_mixed_case_tree(self):
        """Make a working tree with mixed-case filenames."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case parent and base name
        self.build_tree(['CamelCaseParent/', 'lowercaseparent/'])
        self.build_tree_contents([('CamelCaseParent/CamelCase', b'camel case'),
                                  ('lowercaseparent/lowercase', b'lower case'),
                                  ('lowercaseparent/mixedCase', b'mixedCasecase'),
                                  ])
        return wt


class TestAdd(TestCICPBase):

    def test_add_simple(self):
        """Test add always uses the case of the filename reported by the os."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case name
        self.build_tree(['CamelCase'])
        run_script(self, """
            $ brz add camelcase
            adding CamelCase
            """)

    def test_add_subdir(self):
        """test_add_simple but with subdirectories tested too."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case parent and base name
        self.build_tree(['CamelCaseParent/', 'CamelCaseParent/CamelCase'])
        run_script(self, """
            $ brz add camelcaseparent/camelcase
            adding CamelCaseParent
            adding CamelCaseParent/CamelCase
            """)

    def test_add_implied(self):
        """test add with no args sees the correct names."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case parent and base name
        self.build_tree(['CamelCaseParent/', 'CamelCaseParent/CamelCase'])
        run_script(self, """
            $ brz add
            adding CamelCaseParent
            adding CamelCaseParent/CamelCase
            """)

    def test_re_add(self):
        """Test than when a file has 'unintentionally' changed case, we can't
        add a new entry using the new case."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case name
        self.build_tree(['MixedCase'])
        run_script(self, """
            $ brz add MixedCase
            adding MixedCase
            """)
        # 'accidently' rename the file on disk
        osutils.rename('MixedCase', 'mixedcase')
        run_script(self, """
            $ brz add mixedcase
            """)

    def test_re_add_dir(self):
        # like re-add, but tests when the operation is on a directory.
        """Test than when a file has 'unintentionally' changed case, we can't
        add a new entry using the new case."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case name
        self.build_tree(['MixedCaseParent/', 'MixedCaseParent/MixedCase'])
        run_script(self, """
            $ brz add MixedCaseParent
            adding MixedCaseParent
            adding MixedCaseParent/MixedCase
            """)
        # 'accidently' rename the directory on disk
        osutils.rename('MixedCaseParent', 'mixedcaseparent')
        run_script(self, """
            $ brz add mixedcaseparent
            """)

    def test_add_not_found(self):
        """Test add when the input file doesn't exist."""
        wt = self.make_branch_and_tree('.')
        # create a file on disk with the mixed-case name
        self.build_tree(['MixedCaseParent/', 'MixedCaseParent/MixedCase'])
        expected_fname = pathjoin(wt.basedir, "MixedCaseParent", "notfound")
        run_script(self, """
            $ brz add mixedcaseparent/notfound
            2>brz: ERROR: No such file: %s
            """ % (repr(expected_fname),))


class TestMove(TestCICPBase):

    def test_mv_newname(self):
        wt = self._make_mixed_case_tree()
        run_script(self, """
            $ brz add -q
            $ brz ci -qm message
            $ brz mv camelcaseparent/camelcase camelcaseparent/NewCamelCase
            CamelCaseParent/CamelCase => CamelCaseParent/NewCamelCase
            """)

    def test_mv_newname_after(self):
        wt = self._make_mixed_case_tree()
        # In this case we can specify the incorrect case for the destination,
        # as we use --after, so the file-system is sniffed.
        run_script(self, """
            $ brz add -q
            $ brz ci -qm message
            $ mv CamelCaseParent/CamelCase CamelCaseParent/NewCamelCase
            $ brz mv --after camelcaseparent/camelcase camelcaseparent/newcamelcase
            CamelCaseParent/CamelCase => CamelCaseParent/NewCamelCase
            """)

    def test_mv_newname_exists(self):
        # test a mv, but when the target already exists with a name that
        # differs only by case.
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')
        run_script(self, """
            $ brz mv camelcaseparent/camelcase LOWERCASEPARENT/LOWERCASE
            2>brz: ERROR: Could not move CamelCase => lowercase: \
lowercaseparent/lowercase is already versioned.
            """)

    def test_mv_newname_exists_after(self):
        # test a 'mv --after', but when the target already exists with a name
        # that differs only by case.  Note that this is somewhat unlikely
        # but still reasonable.
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')
        # Remove the source and create a destination file on disk with a different case.
        # brz should report that the filename is already versioned.
        os.unlink('CamelCaseParent/CamelCase')
        osutils.rename('lowercaseparent/lowercase',
                       'lowercaseparent/LOWERCASE')
        run_script(self, """
            $ brz mv --after camelcaseparent/camelcase LOWERCASEPARENT/LOWERCASE
            2>brz: ERROR: Could not move CamelCase => lowercase: \
lowercaseparent/lowercase is already versioned.
            """)

    def test_mv_newname_root(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')
        run_script(self, """
            $ brz mv camelcaseparent NewCamelCaseParent
            CamelCaseParent => NewCamelCaseParent
            """)

    def test_mv_newname_root_after(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')
        # In this case we can specify the incorrect case for the destination,
        # as we use --after, so the file-system is sniffed.
        run_script(self, """
            $ mv CamelCaseParent NewCamelCaseParent
            $ brz mv --after camelcaseparent NewCamelCaseParent
            CamelCaseParent => NewCamelCaseParent
            """)

    def test_mv_newcase(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')

        # perform a mv to the new case - we expect brz to accept the new
        # name, as specified, and rename the file on the file-system too.
        run_script(self, """
            $ brz mv camelcaseparent/camelcase camelcaseparent/camelCase
            CamelCaseParent/CamelCase => CamelCaseParent/camelCase
            """)
        self.assertEqual(canonical_relpath(wt.basedir, 'camelcaseparent/camelcase'),
                         'CamelCaseParent/camelCase')

    def test_mv_newcase_after(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')

        # perform a mv to the new case - we must ensure the file-system has the
        # new case first.
        osutils.rename('CamelCaseParent/CamelCase',
                       'CamelCaseParent/camelCase')
        run_script(self, """
            $ brz mv --after camelcaseparent/camelcase camelcaseparent/camelCase
            CamelCaseParent/CamelCase => CamelCaseParent/camelCase
            """)
        # brz should not have renamed the file to a different case
        self.assertEqual(canonical_relpath(wt.basedir, 'camelcaseparent/camelcase'),
                         'CamelCaseParent/camelCase')

    def test_mv_multiple(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        self.run_bzr('ci -m message')
        run_script(self, """
            $ brz mv LOWercaseparent/LOWercase LOWercaseparent/MIXEDCase camelcaseparent
            lowercaseparent/lowercase => CamelCaseParent/lowercase
            lowercaseparent/mixedCase => CamelCaseParent/mixedCase
            """)


class TestMisc(TestCICPBase):

    def test_status(self):
        wt = self._make_mixed_case_tree()
        self.run_bzr('add')
        run_script(self, """
            $ brz status camelcaseparent/camelcase LOWERCASEPARENT/LOWERCASE
            added:
              CamelCaseParent/
              CamelCaseParent/CamelCase
              lowercaseparent/
              lowercaseparent/lowercase
            """)

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
