# Copyright (C) 2006-2010 Canonical Ltd
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


"""InterTree implementation tests for bzr.

These test the conformance of all the InterTree variations to the expected API.
Specific tests for individual variations are in other places such as:
 - tests/test_workingtree.py
"""

import breezy
from breezy import (
    revisiontree,
    tests,
    )
from breezy.bzr import (
    inventorytree,
    )
from breezy.tests import (
    default_transport,
    multiply_tests,
    )
from breezy.tests.per_tree import (
    return_parameter,
    revision_tree_from_workingtree,
    TestCaseWithTree,
    )
from breezy.tree import InterTree
from breezy.bzr.workingtree_3 import WorkingTreeFormat3
from breezy.bzr.workingtree_4 import WorkingTreeFormat4


def return_provided_trees(test_case, source, target):
    """Return the source and target tree unaltered."""
    return source, target


class TestCaseWithTwoTrees(TestCaseWithTree):

    def not_applicable_if_cannot_represent_unversioned(self, tree):
        if isinstance(tree, revisiontree.RevisionTree):
            # The locked test trees conversion could not preserve the
            # unversioned file status. This is normal (e.g. InterDirstateTree
            # falls back to InterTree if the basis is not a
            # DirstateRevisionTree, and revision trees cannot have unversioned
            # files.
            raise tests.TestNotApplicable('cannot represent unversioned files')

    def not_applicable_if_missing_in(self, relpath, tree):
        if not tree.is_versioned(relpath):
            # The locked test trees conversion could not preserve the missing
            # file status. This is normal (e.g. InterDirstateTree falls back
            # to InterTree if the basis is not a DirstateRevisionTree, and
            # revision trees cannot have missing files.
            raise tests.TestNotApplicable('cannot represent missing files')

    def make_to_branch_and_tree(self, relpath):
        """Make a to_workingtree_format branch and tree."""
        made_control = self.make_controldir(relpath,
                                            format=self.workingtree_format_to._matchingcontroldir)
        made_control.create_repository()
        made_control.create_branch()
        return self.workingtree_format_to.initialize(made_control)


def make_scenarios(transport_server, transport_readonly_server, formats):
    """Transform the input formats to a list of scenarios.

    :param formats: A list of tuples:.
        (intertree_class,
         workingtree_format,
         workingtree_format_to,
         mutable_trees_to_test_trees)
    """
    result = []
    for (label, intertree_class,
         workingtree_format,
         workingtree_format_to,
         mutable_trees_to_test_trees) in formats:
        scenario = (label, {
            "transport_server": transport_server,
            "transport_readonly_server": transport_readonly_server,
            "bzrdir_format": workingtree_format._matchingcontroldir,
            "workingtree_format": workingtree_format,
            "intertree_class": intertree_class,
            "workingtree_format_to": workingtree_format_to,
            # mutable_trees_to_test_trees takes two trees and converts them to,
            # whatever relationship the optimiser under test requires.,
            "mutable_trees_to_test_trees": mutable_trees_to_test_trees,
            # workingtree_to_test_tree is set to disable changing individual,
            # trees: instead the mutable_trees_to_test_trees helper is used.,
            "_workingtree_to_test_tree": return_parameter,
            })
        result.append(scenario)
    return result


def mutable_trees_to_preview_trees(test_case, source, target):
    preview = target.preview_transform()
    test_case.addCleanup(preview.finalize)
    return source, preview.get_preview_tree()


def mutable_trees_to_revision_trees(test_case, source, target):
    """Convert both trees to repository based revision trees."""
    return (revision_tree_from_workingtree(test_case, source),
            revision_tree_from_workingtree(test_case, target))


def load_tests(loader, standard_tests, pattern):
    default_tree_format = WorkingTreeFormat3()
    submod_tests = loader.loadTestsFromModuleNames([
        'breezy.tests.per_intertree.test_compare',
        'breezy.tests.per_intertree.test_file_content_matches',
        'breezy.tests.per_intertree.test_find_path',
        ])
    test_intertree_permutations = [
        # test InterTree with two default-format working trees.
        (inventorytree.InterInventoryTree.__name__,
         inventorytree.InterInventoryTree,
         default_tree_format, default_tree_format,
         return_provided_trees)]
    for optimiser in InterTree.iter_optimisers():
        if optimiser is inventorytree.InterCHKRevisionTree:
            # XXX: we shouldn't use an Intertree object to detect inventories
            # -- vila 20090311
            chk_tree_format = WorkingTreeFormat4()
            chk_tree_format._get_matchingcontroldir = \
                lambda: breezy.controldir.format_registry.make_controldir('2a')
            test_intertree_permutations.append(
                (inventorytree.InterInventoryTree.__name__ + "(CHKInventory)",
                 inventorytree.InterInventoryTree,
                 chk_tree_format,
                 chk_tree_format,
                 mutable_trees_to_revision_trees))
        elif optimiser is breezy.bzr.workingtree_4.InterDirStateTree:
            # Its a little ugly to be conditional here, but less so than having
            # the optimiser listed twice.
            # Add once, compiled version
            test_intertree_permutations.append(
                (optimiser.__name__ + "(C)",
                 optimiser,
                 optimiser._matching_from_tree_format,
                 optimiser._matching_to_tree_format,
                 optimiser.make_source_parent_tree_compiled_dirstate))
            # python version
            test_intertree_permutations.append(
                (optimiser.__name__ + "(PY)",
                 optimiser,
                 optimiser._matching_from_tree_format,
                 optimiser._matching_to_tree_format,
                 optimiser.make_source_parent_tree_python_dirstate))
        elif (optimiser._matching_from_tree_format is not None and
              optimiser._matching_to_tree_format is not None):
            test_intertree_permutations.append(
                (optimiser.__name__,
                 optimiser,
                 optimiser._matching_from_tree_format,
                 optimiser._matching_to_tree_format,
                 optimiser._test_mutable_trees_to_test_trees))
    # PreviewTree does not have an InterTree optimiser class.
    test_intertree_permutations.append(
        (inventorytree.InterInventoryTree.__name__ + "(PreviewTree)",
         inventorytree.InterInventoryTree,
         default_tree_format,
         default_tree_format,
         mutable_trees_to_preview_trees))
    scenarios = make_scenarios(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        test_intertree_permutations)
    # add the tests for the sub modules to the standard tests.
    return multiply_tests(submod_tests, scenarios, standard_tests)
