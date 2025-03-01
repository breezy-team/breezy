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
from io import BytesIO

from ... import rules, status
from ...workingtree import WorkingTree
from .. import TestSkipped
from . import TestCaseWithWorkingTree

# Sample files
_sample_text = b"""hello\nworld\r\n"""
_sample_text_on_win = b"""hello\r\nworld\r\n"""
_sample_text_on_unix = b"""hello\nworld\n"""
_sample_binary = b"""hello\nworld\r\n\x00"""
_sample_clean_lf = _sample_text_on_unix
_sample_clean_crlf = _sample_text_on_win


# Lists of formats for each storage policy
_LF_IN_REPO = ["native", "lf", "crlf"]
_CRLF_IN_REPO = ["{}-with-crlf-in-repo".format(f) for f in _LF_IN_REPO]


class TestEolConversion(TestCaseWithWorkingTree):
    def setUp(self):
        # formats that don't support content filtering can skip these tests
        fmt = self.workingtree_format
        f = fmt.supports_content_filtering
        if f is None:
            raise TestSkipped(
                "format {} doesn't declare whether it "
                "supports content filtering, assuming not".format(fmt)
            )
        if not f():
            raise TestSkipped("format {} doesn't support content filtering".format(fmt))
        super().setUp()

    def patch_rules_searcher(self, eol):
        """Patch in a custom rules searcher with a given eol setting."""
        if eol is None:
            WorkingTree._get_rules_searcher = self.real_rules_searcher
        else:

            def custom_eol_rules_searcher(tree, default_searcher):
                return rules._IniBasedRulesSearcher(
                    [
                        "[name *]\n",
                        "eol={}\n".format(eol),
                    ]
                )

            WorkingTree._get_rules_searcher = custom_eol_rules_searcher

    def prepare_tree(self, content, eol=None):
        """Prepare a working tree and commit some content."""
        self.real_rules_searcher = self.overrideAttr(WorkingTree, "_get_rules_searcher")
        self.patch_rules_searcher(eol)
        t = self.make_branch_and_tree("tree1")
        self.build_tree_contents([("tree1/file1", content)])
        t.add("file1")
        t.commit("add file1")
        basis = t.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)
        return t, basis

    def assertNewContentForSetting(
        self, wt, eol, expected_unix, expected_win, roundtrip
    ):
        """Clone a working tree and check the convenience content.

        If roundtrip is True, status and commit should see no changes.
        """
        if expected_win is None:
            expected_win = expected_unix
        self.patch_rules_searcher(eol)
        wt2 = wt.controldir.sprout("tree-{}".format(eol)).open_workingtree()
        # To see exactly what got written to disk, we need an unfiltered read
        with wt2.get_file("file1", filtered=False) as f:
            content = f.read()
        if sys.platform == "win32":
            self.assertEqual(expected_win, content)
        else:
            self.assertEqual(expected_unix, content)
        # Confirm that status thinks nothing has changed if the text roundtrips
        if roundtrip:
            status_io = BytesIO()
            status.show_tree_status(wt2, to_file=status_io)
            self.assertEqual(b"", status_io.getvalue())

    def assertContent(
        self, wt, basis, expected_raw, expected_unix, expected_win, roundtrip_to=None
    ):
        """Check the committed content and content in cloned trees.

        :param roundtrip_to: the set of formats (excluding exact) we
          can round-trip to or None for all
        """
        with basis.get_file("file1") as f:
            basis_content = f.read()
        self.assertEqual(expected_raw, basis_content)

        # No setting and exact should always roundtrip
        self.assertNewContentForSetting(
            wt, None, expected_raw, expected_raw, roundtrip=True
        )
        self.assertNewContentForSetting(
            wt, "exact", expected_raw, expected_raw, roundtrip=True
        )

        # Roundtripping is otherwise dependent on whether the original
        # text is clean - mixed line endings will prevent it. It also
        # depends on whether the format in the repository is being changed.
        if roundtrip_to is None:
            roundtrip_to = _LF_IN_REPO + _CRLF_IN_REPO
        self.assertNewContentForSetting(
            wt, "native", expected_unix, expected_win, "native" in roundtrip_to
        )
        self.assertNewContentForSetting(
            wt, "lf", expected_unix, expected_unix, "lf" in roundtrip_to
        )
        self.assertNewContentForSetting(
            wt, "crlf", expected_win, expected_win, "crlf" in roundtrip_to
        )
        self.assertNewContentForSetting(
            wt,
            "native-with-crlf-in-repo",
            expected_unix,
            expected_win,
            "native-with-crlf-in-repo" in roundtrip_to,
        )
        self.assertNewContentForSetting(
            wt,
            "lf-with-crlf-in-repo",
            expected_unix,
            expected_unix,
            "lf-with-crlf-in-repo" in roundtrip_to,
        )
        self.assertNewContentForSetting(
            wt,
            "crlf-with-crlf-in-repo",
            expected_win,
            expected_win,
            "crlf-with-crlf-in-repo" in roundtrip_to,
        )

    # Test binary files. These always roundtrip.

    def test_eol_no_rules_binary(self):
        wt, basis = self.prepare_tree(_sample_binary)
        self.assertContent(wt, basis, _sample_binary, _sample_binary, _sample_binary)

    def test_eol_exact_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol="exact")
        self.assertContent(wt, basis, _sample_binary, _sample_binary, _sample_binary)

    def test_eol_native_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol="native")
        self.assertContent(wt, basis, _sample_binary, _sample_binary, _sample_binary)

    def test_eol_lf_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol="lf")
        self.assertContent(wt, basis, _sample_binary, _sample_binary, _sample_binary)

    def test_eol_crlf_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol="crlf")
        self.assertContent(wt, basis, _sample_binary, _sample_binary, _sample_binary)

    def test_eol_native_with_crlf_in_repo_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol="native-with-crlf-in-repo")
        self.assertContent(wt, basis, _sample_binary, _sample_binary, _sample_binary)

    def test_eol_lf_with_crlf_in_repo_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol="lf-with-crlf-in-repo")
        self.assertContent(wt, basis, _sample_binary, _sample_binary, _sample_binary)

    def test_eol_crlf_with_crlf_in_repo_binary(self):
        wt, basis = self.prepare_tree(_sample_binary, eol="crlf-with-crlf-in-repo")
        self.assertContent(wt, basis, _sample_binary, _sample_binary, _sample_binary)

    # Test text with mixed line endings ("dirty text").
    # This doesn't roundtrip so status always thinks something has changed.

    def test_eol_no_rules_dirty(self):
        wt, basis = self.prepare_tree(_sample_text)
        self.assertContent(
            wt,
            basis,
            _sample_text,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=[],
        )

    def test_eol_exact_dirty(self):
        wt, basis = self.prepare_tree(_sample_text, eol="exact")
        self.assertContent(
            wt,
            basis,
            _sample_text,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=[],
        )

    def test_eol_native_dirty(self):
        wt, basis = self.prepare_tree(_sample_text, eol="native")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_unix,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=[],
        )

    def test_eol_lf_dirty(self):
        wt, basis = self.prepare_tree(_sample_text, eol="lf")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_unix,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=[],
        )

    def test_eol_crlf_dirty(self):
        wt, basis = self.prepare_tree(_sample_text, eol="crlf")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_unix,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=[],
        )

    def test_eol_native_with_crlf_in_repo_dirty(self):
        wt, basis = self.prepare_tree(_sample_text, eol="native-with-crlf-in-repo")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_win,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=[],
        )

    def test_eol_lf_with_crlf_in_repo_dirty(self):
        wt, basis = self.prepare_tree(_sample_text, eol="lf-with-crlf-in-repo")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_win,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=[],
        )

    def test_eol_crlf_with_crlf_in_repo_dirty(self):
        wt, basis = self.prepare_tree(_sample_text, eol="crlf-with-crlf-in-repo")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_win,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=[],
        )

    # Test text with clean line endings, either always lf or always crlf.
    # This selectively roundtrips (based on what's stored in the repo).

    def test_eol_no_rules_clean_lf(self):
        wt, basis = self.prepare_tree(_sample_clean_lf)
        self.assertContent(
            wt,
            basis,
            _sample_clean_lf,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_LF_IN_REPO,
        )

    def test_eol_no_rules_clean_crlf(self):
        wt, basis = self.prepare_tree(_sample_clean_crlf)
        self.assertContent(
            wt,
            basis,
            _sample_clean_crlf,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_CRLF_IN_REPO,
        )

    def test_eol_exact_clean_lf(self):
        wt, basis = self.prepare_tree(_sample_clean_lf, eol="exact")
        self.assertContent(
            wt,
            basis,
            _sample_clean_lf,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_LF_IN_REPO,
        )

    def test_eol_exact_clean_crlf(self):
        wt, basis = self.prepare_tree(_sample_clean_crlf, eol="exact")
        self.assertContent(
            wt,
            basis,
            _sample_clean_crlf,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_CRLF_IN_REPO,
        )

    def test_eol_native_clean_lf(self):
        wt, basis = self.prepare_tree(_sample_clean_lf, eol="native")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_unix,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_LF_IN_REPO,
        )

    def test_eol_native_clean_crlf(self):
        wt, basis = self.prepare_tree(_sample_clean_crlf, eol="native")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_unix,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_LF_IN_REPO,
        )

    def test_eol_lf_clean_lf(self):
        wt, basis = self.prepare_tree(_sample_clean_lf, eol="lf")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_unix,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_LF_IN_REPO,
        )

    def test_eol_lf_clean_crlf(self):
        wt, basis = self.prepare_tree(_sample_clean_crlf, eol="lf")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_unix,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_LF_IN_REPO,
        )

    def test_eol_crlf_clean_lf(self):
        wt, basis = self.prepare_tree(_sample_clean_lf, eol="crlf")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_unix,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_LF_IN_REPO,
        )

    def test_eol_crlf_clean_crlf(self):
        wt, basis = self.prepare_tree(_sample_clean_crlf, eol="crlf")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_unix,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_LF_IN_REPO,
        )

    def test_eol_native_with_crlf_in_repo_clean_lf(self):
        wt, basis = self.prepare_tree(_sample_clean_lf, eol="native-with-crlf-in-repo")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_win,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_CRLF_IN_REPO,
        )

    def test_eol_native_with_crlf_in_repo_clean_crlf(self):
        wt, basis = self.prepare_tree(
            _sample_clean_crlf, eol="native-with-crlf-in-repo"
        )
        self.assertContent(
            wt,
            basis,
            _sample_text_on_win,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_CRLF_IN_REPO,
        )

    def test_eol_lf_with_crlf_in_repo_clean_lf(self):
        wt, basis = self.prepare_tree(_sample_clean_lf, eol="lf-with-crlf-in-repo")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_win,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_CRLF_IN_REPO,
        )

    def test_eol_lf_with_crlf_in_repo_clean_crlf(self):
        wt, basis = self.prepare_tree(_sample_clean_crlf, eol="lf-with-crlf-in-repo")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_win,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_CRLF_IN_REPO,
        )

    def test_eol_crlf_with_crlf_in_repo_clean_lf(self):
        wt, basis = self.prepare_tree(_sample_clean_lf, eol="crlf-with-crlf-in-repo")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_win,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_CRLF_IN_REPO,
        )

    def test_eol_crlf_with_crlf_in_repo_clean_crlf(self):
        wt, basis = self.prepare_tree(_sample_clean_crlf, eol="crlf-with-crlf-in-repo")
        self.assertContent(
            wt,
            basis,
            _sample_text_on_win,
            _sample_text_on_unix,
            _sample_text_on_win,
            roundtrip_to=_CRLF_IN_REPO,
        )
