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

"""Test that all Tree's implement get_attributes"""

import os

from bzrlib import (
    errors,
    osutils,
    tests,
    )
from bzrlib.tests.tree_implementations import TestCaseWithTree


class TestGetAttributes(TestCaseWithTree):

    def get_tree_with_attributes(self):
        tree = self.make_branch_and_tree('tree')
        class TestAttributesProvider(object):
            def get_attributes(self, path, names=None):
                if path == 'foo':
                    all = {'a': 'True'}
                else:
                    all = {}
                if names is None:
                    return all
                else:
                    return dict((k, all.get(k)) for k in names)
        def dummy_provider():
            return TestAttributesProvider()
        tree._get_attributes_provider = dummy_provider
        return tree

    def test_get_attributes(self):
        tree = self.get_tree_with_attributes()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([], list(tree.get_attributes([])))
        self.assertEqual([{'a': 'True'}], list(tree.get_attributes(['foo'])))
        self.assertEqual([{'b': None, 'a': 'True'}],
            list(tree.get_attributes(['foo'], ['b', 'a'])))
