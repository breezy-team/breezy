# Copyright (C) 2008, 2009, 2010, 2016 Canonical Ltd
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

"""Test that all Tree's implement iter_search_rules."""

from breezy import rules
from breezy.tests.per_tree import TestCaseWithTree


class TestIterSearchRules(TestCaseWithTree):
    def make_per_user_searcher(self, text):
        """Make a _RulesSearcher from a string."""
        return rules._IniBasedRulesSearcher(text.splitlines(True))

    def make_tree_with_rules(self, text):
        tree = self.make_branch_and_tree(".")
        if text is not None:
            self.fail("No method for in-tree rules agreed on yet.")
            text_utf8 = text.encode("utf-8")
            self.build_tree_contents([(rules.RULES_TREE_FILENAME, text_utf8)])
            tree.add(rules.RULES_TREE_FILENAME)
            tree.commit("add rules file")
        result = self._convert_tree(tree)
        result.lock_read()
        self.addCleanup(result.unlock)
        return result

    def test_iter_search_rules_no_tree(self):
        per_user = self.make_per_user_searcher(
            "[name ./a.txt]\nfoo=baz\n[name *.txt]\nfoo=bar\na=True\n"
        )
        tree = self.make_tree_with_rules(None)
        result = list(
            tree.iter_search_rules(["a.txt", "dir/a.txt"], _default_searcher=per_user)
        )
        self.assertEqual((("foo", "baz"),), result[0])
        self.assertEqual((("foo", "bar"), ("a", "True")), result[1])

    def _disabled_test_iter_search_rules_just_tree(self):
        per_user = self.make_per_user_searcher("")
        tree = self.make_tree_with_rules(
            "[name ./a.txt]\nfoo=baz\n[name *.txt]\nfoo=bar\na=True\n"
        )
        result = list(
            tree.iter_search_rules(["a.txt", "dir/a.txt"], _default_searcher=per_user)
        )
        self.assertEqual((("foo", "baz"),), result[0])
        self.assertEqual((("foo", "bar"), ("a", "True")), result[1])

    def _disabled_test_iter_search_rules_tree_and_per_user(self):
        per_user = self.make_per_user_searcher(
            "[name ./a.txt]\nfoo=baz\n[name *.txt]\nfoo=bar\na=True\n"
        )
        tree = self.make_tree_with_rules("[name ./a.txt]\nfoo=qwerty\n")
        result = list(
            tree.iter_search_rules(["a.txt", "dir/a.txt"], _default_searcher=per_user)
        )
        self.assertEqual((("foo", "qwerty"),), result[0])
        self.assertEqual((("foo", "bar"), ("a", "True")), result[1])
