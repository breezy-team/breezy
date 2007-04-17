# Copyright (C) 2006, 2007 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
#          and others
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


"""Branch implementation tests for bzr.

These test the conformance of all the branch variations to the expected API.
Specific tests for individual formats are in the tests/test_branch file 
rather than in tests/branch_implementations/*.py.
"""

from bzrlib import (
    errors,
    tests,
    )
from bzrlib.branch import (BranchFormat,
                           BranchTestProviderAdapter,
                           _legacy_formats,
                           )
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir


class TestCaseWithBranch(TestCaseWithBzrDir):
    """This helper will be adapted for each branch_implementation test."""

    def setUp(self):
        super(TestCaseWithBranch, self).setUp()
        self.branch = None

    def get_branch(self):
        if self.branch is None:
            self.branch = self.make_branch('')
        return self.branch

    def make_branch(self, relpath, format=None):
        repo = self.make_repository(relpath, format=format)
        # fixme RBC 20060210 this isnt necessarily a fixable thing,
        # Skipped is the wrong exception to raise.
        try:
            return self.branch_format.initialize(repo.bzrdir)
        except errors.UninitializableFormat:
            raise tests.TestSkipped('Uninitializable branch format')

    def make_repository(self, relpath, shared=False, format=None):
        made_control = self.make_bzrdir(relpath, format=format)
        return made_control.create_repository(shared=shared)

    def create_tree_with_merge(self):
        """Create a branch with a simple ancestry.

        The graph should look like:
            digraph H {
                "rev-1" -> "rev-2" -> "rev-3";
                "rev-1" -> "rev-1.1.1" -> "rev-3";
            }

        Or in ASCII:
            1 - 2 - 3
              \    /
               1.1.1
        """
        tree = self.make_branch_and_memory_tree('tree')
        tree.lock_write()
        try:
            tree.add('')
            tree.commit('first', rev_id='rev-1')
            tree.commit('second', rev_id='rev-2')
            # Uncommit that last commit
            tree.branch.set_last_revision_info(1, 'rev-1')
            tree.set_parent_ids(['rev-1'])
            tree.commit('alt-second', rev_id='rev-1.1.1')
            tree.branch.set_last_revision_info(2, 'rev-2')
            tree.set_parent_ids(['rev-2', 'rev-1.1.1'])
            tree.commit('third', rev_id='rev-3')
        finally:
            tree.unlock()

        return tree


def test_suite():
    result = tests.TestSuite()
    test_branch_implementations = [
        'bzrlib.tests.branch_implementations.test_bound_sftp',
        'bzrlib.tests.branch_implementations.test_branch',
        'bzrlib.tests.branch_implementations.test_break_lock',
        'bzrlib.tests.branch_implementations.test_create_checkout',
        'bzrlib.tests.branch_implementations.test_commit',
        'bzrlib.tests.branch_implementations.test_hooks',
        'bzrlib.tests.branch_implementations.test_http',
        'bzrlib.tests.branch_implementations.test_last_revision_info',
        'bzrlib.tests.branch_implementations.test_locking',
        'bzrlib.tests.branch_implementations.test_parent',
        'bzrlib.tests.branch_implementations.test_permissions',
        'bzrlib.tests.branch_implementations.test_pull',
        'bzrlib.tests.branch_implementations.test_push',
        'bzrlib.tests.branch_implementations.test_revision_history',
        'bzrlib.tests.branch_implementations.test_revision_id_to_revno',
        'bzrlib.tests.branch_implementations.test_tags',
        'bzrlib.tests.branch_implementations.test_uncommit',
        'bzrlib.tests.branch_implementations.test_update',
        ]
    # Generate a list of branch formats and their associated bzrdir formats to
    # use.
    combinations = [(format, format._matchingbzrdir) for format in 
         BranchFormat._formats.values() + _legacy_formats]
    adapter = BranchTestProviderAdapter(
        tests.default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        combinations)
    loader = tests.TestLoader()
    tests.adapt_modules(test_branch_implementations, adapter, loader, result)
    return result
