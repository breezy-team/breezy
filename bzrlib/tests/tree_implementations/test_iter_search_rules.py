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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test that all Tree's implement iter_search_rules."""

from bzrlib import (
    rules,
    tests,
    )
from bzrlib.tests.tree_implementations import TestCaseWithTree


def _patch_in_namespace(lines):
    lines_with_prefix = []
    if lines:
        for line in lines:
            if line.startswith('['):
                line = '[%s%s' % (rules.FILE_PREFS_PREFIX, line[1:])
            lines_with_prefix.append(line)
    return lines_with_prefix


class TestIterSearchRules(TestCaseWithTree):

    def make_per_user_searcher(self, lines):
        """Make a _RulesSearcher from a list of strings"""
        return rules._IniBasedRulesSearcher(_patch_in_namespace(lines))

    def make_tree_with_rules(self, text):
        tree = self.make_branch_and_tree('.')
        if text is not None:
            text = ''.join(_patch_in_namespace(text.splitlines(True)))
            text_utf8 = text.encode('utf-8')
            self.build_tree_contents([(rules.RULES_TREE_FILENAME, text_utf8)])
            tree.add(rules.RULES_TREE_FILENAME)
            tree.commit("add rules file")
        result = self._convert_tree(tree)
        result.lock_read()
        self.addCleanup(result.unlock)
        return result

    def test_iter_search_rules_no_tree(self):
        per_user = self.make_per_user_searcher([
            "[./a.txt]", "foo=baz",
            "[*.txt]", "foo=bar", "a=True"])
        tree = self.make_tree_with_rules(None)
        result = list(tree.iter_search_rules(['a.txt', 'dir/a.txt'],
            _default_searcher=per_user))
        self.assertEquals((('foo', 'baz'),), result[0])
        self.assertEquals((('foo', 'bar'), ('a', 'True')), result[1])

    def test_iter_search_rules_just_tree(self):
        per_user = self.make_per_user_searcher([])
        tree = self.make_tree_with_rules(
            "[./a.txt]\n"
            "foo=baz\n"
            "[*.txt]\n"
            "foo=bar\n"
            "a=True\n")
        result = list(tree.iter_search_rules(['a.txt', 'dir/a.txt'],
            _default_searcher=per_user))
        self.assertEquals((('foo', 'baz'),), result[0])
        self.assertEquals((('foo', 'bar'), ('a', 'True')), result[1])

    def test_iter_search_rules_tree_and_per_user(self):
        per_user = self.make_per_user_searcher([
            "[./a.txt]", "foo=baz",
            "[*.txt]", "foo=bar", "a=True"])
        tree = self.make_tree_with_rules(
            "[./a.txt]\n"
            "foo=qwerty\n")
        result = list(tree.iter_search_rules(['a.txt', 'dir/a.txt'],
            _default_searcher=per_user))
        self.assertEquals((('foo', 'qwerty'),), result[0])
        self.assertEquals((('foo', 'bar'), ('a', 'True')), result[1])
