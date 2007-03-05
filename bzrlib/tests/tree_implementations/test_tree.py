# Copyright (C) 2006, 2007 Canonical Ltd
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

from bzrlib import (
    errors,
    )
from bzrlib.tests.tree_implementations import TestCaseWithTree

class TestAnnotate(TestCaseWithTree):

    def test_annotate(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        tree_revision = getattr(tree, 'get_revision_id', lambda: 'current:')()
        tree.lock_read()
        try:
            for revision, line in tree.annotate_iter('a-id'):
                self.assertEqual('contents of a\n', line)
                self.assertEqual(tree_revision, revision)
        finally:
            tree.unlock()


class TestFileIds(TestCaseWithTree):

    def test_id2path(self):
        # translate from file-id back to path
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        tree.lock_read()
        try:
            self.assertEqual(u'a', tree.id2path('a-id'))
            # other ids give an error- don't return None for this case
            self.assertRaises(errors.NoSuchId, tree.id2path, 'a')
        finally:
            tree.unlock()
