# Copyright (C) 2006 by Canonical Ltd
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


"""InterTree implementation tests for bzr.

These test the conformance of all the InterTree variations to the expected API.
Specific tests for individual variations are in other places such as:
 - tests/test_workingtree.py
"""

import bzrlib.errors as errors
from bzrlib.transport import get_transport
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestLoader,
                          TestSuite,
                          )
from bzrlib.tests.tree_implementations import (
    return_parameter,
    revision_tree_from_workingtree,
    TestCaseWithTree,
    )
from bzrlib.tree import InterTree
from bzrlib.workingtree import (WorkingTreeFormat,
                                WorkingTreeTestProviderAdapter,
                                )


class TestCaseWithTwoTrees(TestCaseWithTree):

    def make_to_branch_and_tree(self, relpath):
        """Make a to_workingtree_format branch and tree."""
        made_control = self.make_bzrdir(relpath, 
            format=self.workingtree_format_to._matchingbzrdir)
        made_control.create_repository()
        made_control.create_branch()
        return self.workingtree_format_to.initialize(made_control)

    def get_to_tree_no_parents_no_content(self, empty_tree):
        return super(TestCaseWithTwoTrees, self).get_tree_no_parents_no_content(empty_tree, converter=self.workingtree_to_test_tree_to)

    def get_to_tree_no_parents_abc_content(self, empty_tree):
        return super(TestCaseWithTwoTrees, self).get_tree_no_parents_abc_content(empty_tree, converter=self.workingtree_to_test_tree_to)

    def get_to_tree_no_parents_abc_content_2(self, empty_tree):
        return super(TestCaseWithTwoTrees, self).get_tree_no_parents_abc_content_2(empty_tree, converter=self.workingtree_to_test_tree_to)

    def get_to_tree_no_parents_abc_content_3(self, empty_tree):
        return super(TestCaseWithTwoTrees, self).get_tree_no_parents_abc_content_3(empty_tree, converter=self.workingtree_to_test_tree_to)

    def get_to_tree_no_parents_abc_content_4(self, empty_tree):
        return super(TestCaseWithTwoTrees, self).get_tree_no_parents_abc_content_4(empty_tree, converter=self.workingtree_to_test_tree_to)

    def get_to_tree_no_parents_abc_content_5(self, empty_tree):
        return super(TestCaseWithTwoTrees, self).get_tree_no_parents_abc_content_5(empty_tree, converter=self.workingtree_to_test_tree_to)

    def get_to_tree_no_parents_abc_content_6(self, empty_tree):
        return super(TestCaseWithTwoTrees, self).get_tree_no_parents_abc_content_6(empty_tree, converter=self.workingtree_to_test_tree_to)


class InterTreeTestProviderAdapter(WorkingTreeTestProviderAdapter):
    """Generate test suites for each InterTree implementation in bzrlib."""

    def adapt(self, test):
        result = TestSuite()
        for (intertree_class,
            workingtree_format,
            workingtree_to_test_tree,
            workingtree_format_to,
            workingtree_to_test_tree_to) in self._formats:
            new_test = self._clone_test(
                test,
                workingtree_format._matchingbzrdir,
                workingtree_format,
                intertree_class.__name__)
            new_test.intertree_class = intertree_class
            new_test.workingtree_to_test_tree = workingtree_to_test_tree
            new_test.workingtree_format_to = workingtree_format_to
            new_test.workingtree_to_test_tree_to = workingtree_to_test_tree_to
            result.addTest(new_test)
        return result


def test_suite():
    result = TestSuite()
    loader = TestLoader()
    # load the tests of the infrastructure for these tests
    result.addTests(loader.loadTestsFromModuleNames(['bzrlib.tests.intertree_implementations']))

    default_tree_format = WorkingTreeFormat.get_default_format()
    test_intertree_implementations = [
        'bzrlib.tests.intertree_implementations.test_compare',
        ]
    test_intertree_permutations = [
        # test InterTree with two default-format working trees.
        (InterTree, default_tree_format, return_parameter,
         default_tree_format, return_parameter)]
    for optimiser in InterTree._optimisers:
        test_intertree_permutations.append(
            (optimiser,
             optimiser._matching_from_tree_format, optimiser._from_tree_converter,
             optimiser._matching_to_tree_format, optimiser._to_tree_converter))
    adapter = InterTreeTestProviderAdapter(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        test_intertree_permutations)
    adapt_modules(test_intertree_implementations, adapter, loader, result)
    return result
