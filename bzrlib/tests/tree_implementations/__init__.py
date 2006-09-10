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


"""Tree implementation tests for bzr.

These test the conformance of all the tree variations to the expected API.
Specific tests for individual variations are in other places such as:
 - tests/test_tree.py
 - tests/test_revision.py
 - tests/test_workingtree.py
 - tests/workingtree_implementations/*.py.
"""

from bzrlib import (
    errors,
    transform,
    )
from bzrlib.transport import get_transport
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestCaseWithTransport,
                          TestLoader,
                          TestSuite,
                          )
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.tree import RevisionTree
from bzrlib.workingtree import (WorkingTreeFormat,
                                WorkingTreeTestProviderAdapter,
                                _legacy_formats,
                                )


def return_parameter(something):
    """A trivial thunk to return its input."""
    return something


def revision_tree_from_workingtree(tree):
    """Create a revision tree from a working tree."""
    revid = tree.commit('save tree', allow_pointless=True)
    return tree.branch.repository.revision_tree(revid)


class TestTreeImplementationSupport(TestCaseWithTransport):

    def test_revision_tree_from_workingtree(self):
        tree = self.make_branch_and_tree('.')
        tree = revision_tree_from_workingtree(tree)
        self.assertIsInstance(tree, RevisionTree)


class TestCaseWithTree(TestCaseWithBzrDir):

    def make_branch_and_tree(self, relpath):
        made_control = self.make_bzrdir(relpath, format=
            self.workingtree_format._matchingbzrdir)
        made_control.create_repository()
        made_control.create_branch()
        return self.workingtree_format.initialize(made_control)

    def _convert_tree(self, tree, converter=None):
        """helper to convert using the converter or a supplied one."""
        # convert that to the final shape
        if converter is None:
            converter = self.workingtree_to_test_tree
        return converter(tree)

    def get_tree_no_parents_no_content(self, empty_tree, converter=None):
        """Make a tree with no parents and no contents from empty_tree.
        
        :param empty_tree: A working tree with no content and no parents to
            modify.
        """
        empty_tree.set_root_id('empty-root-id')
        return self._convert_tree(empty_tree, converter)

    def _make_abc_tree(self, tree):
        """setup an abc content tree."""
        files = ['a', 'b/', 'b/c']
        self.build_tree(files, line_endings='binary', 
                        transport=tree.bzrdir.root_transport)
        tree.set_root_id('root-id')
        tree.add(files, ['a-id', 'b-id', 'c-id'])

    def get_tree_no_parents_abc_content(self, tree, converter=None):
        """return a test tree with a, b/, b/c contents."""
        self._make_abc_tree(tree)
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_2(self, tree, converter=None):
        """return a test tree with a, b/, b/c contents.
        
        This variation changes the content of 'a' to foobar\n.
        """
        self._make_abc_tree(tree)
        f = open(tree.basedir + '/a', 'wb')
        try:
            f.write('foobar\n')
        finally:
            f.close()
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_3(self, tree, converter=None):
        """return a test tree with a, b/, b/c contents.
        
        This variation changes the executable flag of b/c to True.
        """
        self._make_abc_tree(tree)
        tt = transform.TreeTransform(tree)
        trans_id = tt.trans_id_tree_path('b/c')
        tt.set_executability(True, trans_id)
        tt.apply()
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_4(self, tree, converter=None):
        """return a test tree with d, b/, b/c contents.
        
        This variation renames a to d.
        """
        self._make_abc_tree(tree)
        tree.rename_one('a', 'd')
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_5(self, tree, converter=None):
        """return a test tree with d, b/, b/c contents.
        
        This variation renames a to d and alters its content to 'bar\n'.
        """
        self._make_abc_tree(tree)
        tree.rename_one('a', 'd')
        f = open(tree.basedir + '/d', 'wb')
        try:
            f.write('bar\n')
        finally:
            f.close()
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_6(self, tree, converter=None):
        """return a test tree with a, b/, e contents.
        
        This variation renames b/c to e, and makes it executable.
        """
        self._make_abc_tree(tree)
        tt = transform.TreeTransform(tree)
        trans_id = tt.trans_id_tree_path('b/c')
        parent_trans_id = tt.trans_id_tree_path('')
        tt.adjust_path('e', parent_trans_id, trans_id)
        tt.set_executability(True, trans_id)
        tt.apply()
        return self._convert_tree(tree, converter)


class TreeTestProviderAdapter(WorkingTreeTestProviderAdapter):
    """Generate test suites for each Tree implementation in bzrlib.

    Currently this covers all working tree formats, and RevisionTree by 
    committing a working tree to create the revision tree.
    """

    def adapt(self, test):
        result = super(TreeTestProviderAdapter, self).adapt(test)
        for adapted_test in result:
            # for working tree adapted tests, preserve the tree
            adapted_test.workingtree_to_test_tree = return_parameter
        default_format = WorkingTreeFormat.get_default_format()
        revision_tree_test = self._clone_test(
            test,
            default_format._matchingbzrdir, 
            default_format,
            RevisionTree.__name__)
        revision_tree_test.workingtree_to_test_tree = revision_tree_from_workingtree
        result.addTest(revision_tree_test)
        return result


def test_suite():
    result = TestSuite()
    test_tree_implementations = [
        'bzrlib.tests.tree_implementations.test_test_trees',
        ]
    adapter = TreeTestProviderAdapter(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        [(format, format._matchingbzrdir) for format in 
         WorkingTreeFormat._formats.values() + _legacy_formats])
    loader = TestLoader()
    adapt_modules(test_tree_implementations, adapter, loader, result)
    result.addTests(loader.loadTestsFromModuleNames(['bzrlib.tests.tree_implementations']))
    return result
