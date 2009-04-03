# Copyright (C) 2009 Canonical Ltd
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

"""Tests for eol conversion."""

import sys

from bzrlib import rules
from bzrlib.tests import TestSkipped
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.workingtree import WorkingTree


# Sample files
_sample_text         = """hello\nworld\r\n"""
_sample_text_on_win  = """hello\r\nworld\r\n"""
_sample_text_on_unix = """hello\nworld\n"""
_sample_binary       = """hello\nworld\r\n\x00"""


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

    def assertNewContentForSetting(self, wt, eol, expected_unix,
        expected_win=None):
        """Clone a working tree and check the convenience content."""
        if expected_win is None:
            expected_win = expected_unix
        self.patch_rules_searcher(eol)
        wt2 = wt.bzrdir.sprout('tree-%s' % eol).open_workingtree()
        # To see exactly what got written to disk, we need an unfiltered read
        content = wt2.get_file('file1-id', filtered=False).read()
        if sys.platform == 'win32':
            self.assertEqual(expected_win, content)
        else:
            self.assertEqual(expected_unix, content)

    def assertContent(self, wt, basis, expected_raw, expected_unix,
        expected_win):
        """Check the committed content and content in cloned trees."""
        basis_content = basis.get_file('file1-id').read()
        self.assertEqual(expected_raw, basis_content)
        self.assertNewContentForSetting(wt, None, expected_raw)
        self.assertNewContentForSetting(wt, 'native',
            expected_unix, expected_win)
        self.assertNewContentForSetting(wt, 'lf',
            expected_unix, expected_unix)
        self.assertNewContentForSetting(wt, 'crlf',
            expected_win, expected_win)
        self.assertNewContentForSetting(wt, 'native-with-crlf-in-repo',
            expected_unix, expected_win)
        self.assertNewContentForSetting(wt, 'lf-with-crlf-in-repo',
            expected_unix, expected_unix)
        self.assertNewContentForSetting(wt, 'crlf-with-crlf-in-repo',
            expected_win, expected_win)
        self.assertNewContentForSetting(wt, 'exact', expected_raw)

    def test_eol_no_rules(self):
        wt, basis = self.prepare_tree(_sample_text)
        self.assertContent(wt, basis, _sample_text,
            _sample_text_on_unix, _sample_text_on_win)

    def test_eol_native(self):
        wt, basis = self.prepare_tree(_sample_text, eol='native')
        self.assertContent(wt, basis, _sample_text_on_unix,
            _sample_text_on_unix, _sample_text_on_win)

    def test_eol_native_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol='native')
        self.assertContent(wt, basis, _sample_binary, _sample_binary,
            _sample_binary)

    def test_eol_lf(self):
        wt, basis = self.prepare_tree(_sample_text, eol='lf')
        self.assertContent(wt, basis, _sample_text_on_unix,
            _sample_text_on_unix, _sample_text_on_win)

    def test_eol_lf_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol='lf')
        self.assertContent(wt, basis, _sample_binary, _sample_binary,
            _sample_binary)

    def test_eol_crlf(self):
        wt, basis = self.prepare_tree(_sample_text, eol='crlf')
        self.assertContent(wt, basis, _sample_text_on_unix,
            _sample_text_on_unix, _sample_text_on_win)

    def test_eol_crlf_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol='crlf')
        self.assertContent(wt, basis, _sample_binary, _sample_binary,
            _sample_binary)

    def test_eol_native_with_crlf_in_repo(self):
        wt, basis = self.prepare_tree(_sample_text,
            eol='native-with-crlf-in-repo')
        self.assertContent(wt, basis, _sample_text_on_win,
            _sample_text_on_unix, _sample_text_on_win)

    def test_eol_native_with_crlf_in_repo_binary(self):
        wt, basis = self.prepare_tree(_sample_binary,
            eol='native-with-crlf-in-repo')
        self.assertContent(wt, basis, _sample_binary, _sample_binary,
            _sample_binary)

    def test_eol_lf_with_crlf_in_repo(self):
        wt, basis = self.prepare_tree(_sample_text, eol='lf-with-crlf-in-repo')
        self.assertContent(wt, basis, _sample_text_on_win,
            _sample_text_on_unix, _sample_text_on_win)

    def test_eol_lf_with_crlf_in_repo_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol='lf-with-crlf-in-repo')
        self.assertContent(wt, basis, _sample_binary, _sample_binary,
            _sample_binary)

    def test_eol_crlf_with_crlf_in_repo(self):
        wt, basis = self.prepare_tree(_sample_text, eol='crlf-with-crlf-in-repo')
        self.assertContent(wt, basis, _sample_text_on_win,
            _sample_text_on_unix, _sample_text_on_win)

    def test_eol_crlf_with_crlf_in_repo_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol='crlf-with-crlf-in-repo')
        self.assertContent(wt, basis, _sample_binary, _sample_binary,
            _sample_binary)

    def test_eol_exact(self):
        wt, basis = self.prepare_tree(_sample_text, eol='exact')
        self.assertContent(wt, basis, _sample_text,
            _sample_text_on_unix, _sample_text_on_win)

    def test_eol_exact_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol='exact')
        self.assertContent(wt, basis, _sample_binary, _sample_binary,
            _sample_binary)
