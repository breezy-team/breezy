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

"""Tests for keyword expansion/contraction in trees."""

## TODO: add tests for xml_escaped

from cStringIO import StringIO
import sys

from bzrlib import config, rules
from bzrlib.tests import TestCaseWithTransport, TestSkipped
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.workingtree import WorkingTree


# Sample files. We exclude keywords that change from one run to another,
# TODO: Test Date, Path, Now, User, User-Email
_sample_text_raw = """
Author:       $Author$
Author-Email: $Author-Email$
Revision-Id:  $Revision-Id$
Filename:     $Filename$
Directory:    $Directory$
File-Id:      $File-Id$
"""
#User:         $User$
#User-Email:   $User-Email$
_sample_text_cooked = """
Author:       $Author: Sue Smith <sue@example.com> $
Author-Email: $Author-Email: sue@example.com $
Revision-Id:  $Revision-Id: rev1-id $
Filename:     $Filename: file1 $
Directory:    $Directory:  $
File-Id:      $File-Id: file1-id $
"""
#User:         $User: Dave Smith <dave@example.com>$
#User-Email:   $User-Email: dave@example.com $
_sample_binary = _sample_text_raw + """\x00"""


class TestKeywordsInTrees(TestCaseWithTransport):

    def patch_rules_searcher(self, keywords):
        """Patch in a custom rules searcher with a given keywords setting."""
        if keywords is None:
            WorkingTree._get_rules_searcher = self.real_rules_searcher
        else:
            def custom__rules_searcher(tree, default_searcher):
                return rules._IniBasedRulesSearcher([
                    '[name *]\n',
                    'keywords=%s\n' % keywords,
                    ])
            WorkingTree._get_rules_searcher = custom__rules_searcher

    def prepare_tree(self, content, keywords=None):
        """Prepare a working tree and commit some content."""
        def restore_real_rules_searcher():
            WorkingTree._get_rules_searcher = self.real_rules_searcher
        self.real_rules_searcher = WorkingTree._get_rules_searcher
        self.addCleanup(restore_real_rules_searcher)
        self.patch_rules_searcher(keywords)
        t = self.make_branch_and_tree('tree1', format="development-wt5")
        # Patch is a custom username
        #def custom_global_config():
        #    config_file = StringIO(
        #        "[DEFAULT]\nemail=Dave Smith <dave@example.com>\n")
        #    my_config = config.GlobalConfig()
        #    my_config._parser = my_config._get_parser(file=config_file)
        #    return my_config
        #t.branch.get_config()._get_global_config = custom_global_config
        self.build_tree_contents([('tree1/file1', content)])
        t.add('file1', 'file1-id')
        t.commit("add file1", rev_id="rev1-id",
            author="Sue Smith <sue@example.com>")
        basis = t.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)
        return t, basis

    def assertNewContentForSetting(self, wt, keywords, expected):
        """Clone a working tree and check the convenience content."""
        self.patch_rules_searcher(keywords)
        wt2 = wt.bzrdir.sprout('tree-%s' % keywords).open_workingtree()
        # To see exactly what got written to disk, we need an unfiltered read
        content = wt2.get_file('file1-id', filtered=False).read()
        self.assertEqualDiff(expected, content)

    def assertContent(self, wt, basis, expected_raw, expected_cooked):
        """Check the committed content and content in cloned trees."""
        basis_content = basis.get_file('file1-id').read()
        self.assertEqual(expected_raw, basis_content)
        self.assertNewContentForSetting(wt, None, expected_raw)
        self.assertNewContentForSetting(wt, 'on', expected_cooked)
        self.assertNewContentForSetting(wt, 'off', expected_raw)

    def test_keywords_no_rules(self):
        wt, basis = self.prepare_tree(_sample_text_raw)
        self.assertContent(wt, basis, _sample_text_raw, _sample_text_cooked)

    def test_keywords_on(self):
        wt, basis = self.prepare_tree(_sample_text_raw, keywords='on')
        self.assertContent(wt, basis, _sample_text_raw, _sample_text_cooked)

    def test_keywords_off(self):
        wt, basis = self.prepare_tree(_sample_text_raw, keywords='off')
        self.assertContent(wt, basis, _sample_text_raw, _sample_text_cooked)
