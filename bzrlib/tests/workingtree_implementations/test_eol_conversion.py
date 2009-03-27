# Copyright (C) 2009 Canonical Limited.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
#
"""Tests for eol conversion."""

import sys

from bzrlib import rules
from bzrlib.tests import TestSkipped
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.workingtree import WorkingTree


# Sample files
_sample_file1         = """hello\nworld\r\n"""
_sample_file1_on_dos  = """hello\r\nworld\r\n"""
_sample_file1_on_unix = """hello\nworld\n"""


class TestEolConversion(TestCaseWithWorkingTree):

    def setUp(self):
        # formats that don't support content filtering can skip these tests
        fmt = self.workingtree_format
        f = getattr(fmt, 'supports_content_filtering')
        if f is None:
            raise TestSkipped("format %s doesn't declare whether it "
                "supports content filtering, assuming not" % fmt)
        if not f():
            raise TestSkipped("format %s doesn't support content filtering"
                % fmt)
        TestCaseWithWorkingTree.setUp(self)

    def patch_rules_searcher(self, eol):
        """Patch in a custom rules searcher with a given eol setting."""
        if eol is None:
            WorkingTree._get_rules_searcher = self.real_rules_searcher
        else:
            def custom_eol_rules_searcher(tree, default_searcher):
                return rules._IniBasedRulesSearcher([
                    '[name *]\n',
                    'eol=%s\n' % eol,
                    ])
            WorkingTree._get_rules_searcher = custom_eol_rules_searcher

    def prepare_tree(self, content, eol=None):
        """Prepare a working tree and commit some content."""
        def restore_real_rules_searcher():
            WorkingTree._get_rules_searcher = self.real_rules_searcher
        self.real_rules_searcher = WorkingTree._get_rules_searcher
        self.addCleanup(restore_real_rules_searcher)
        self.patch_rules_searcher(eol)
        t = self.make_branch_and_tree('tree1')
        self.build_tree_contents([('tree1/file1', content)])
        t.add('file1', 'file1-id')
        t.commit("add file1")
        basis = t.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)
        return t, basis

    def assertNewContentForSetting(self, wt, eol, expected_unix, expected_dos):
        """Clone a working tree and check the convenience content."""
        self.patch_rules_searcher(eol)
        wt2 = wt.bzrdir.sprout('tree-%s' % eol).open_workingtree()
        # To see exactly what got written to disk, we need an unfiltered read
        content = wt2.get_file('file1-id', filtered=False).read()
        if sys.platform == 'win32':
            self.assertEqual(expected_dos, content)
        else:
            self.assertEqual(expected_unix, content)

    def assertContent(self, wt, basis, expected_raw, expected_unix,
        expected_dos):
        """Check the committed content and content in cloned trees."""
        basis_content = basis.get_file('file1-id').read()
        self.assertEqual(expected_raw, basis_content)
        self.assertNewContentForSetting(wt, None, expected_raw, expected_raw)
        self.assertNewContentForSetting(wt, 'exact', expected_raw, expected_raw)
        self.assertNewContentForSetting(wt, 'dos', expected_unix, expected_dos)
        self.assertNewContentForSetting(wt, 'unix', expected_unix, expected_dos)

    def test_eol_no_rules(self):
        wt, basis = self.prepare_tree(_sample_file1)
        self.assertContent(wt, basis, _sample_file1,
            _sample_file1_on_unix, _sample_file1_on_dos)

    def test_eol_exact(self):
        wt, basis = self.prepare_tree(_sample_file1, eol='exact')
        self.assertContent(wt, basis, _sample_file1,
            _sample_file1_on_unix, _sample_file1_on_dos)

    def test_eol_dos(self):
        wt, basis = self.prepare_tree(_sample_file1, eol='dos')
        self.assertContent(wt, basis, _sample_file1_on_dos,
            _sample_file1_on_unix, _sample_file1_on_dos)

    def test_eol_unix(self):
        wt, basis = self.prepare_tree(_sample_file1, eol='unix')
        self.assertContent(wt, basis, _sample_file1_on_unix,
            _sample_file1_on_unix, _sample_file1_on_dos)
