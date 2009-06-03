# Copyright (C) 2009 Canonical Ltd
# -*- coding: utf-8 -*-
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


"""InterBranch implementation tests for bzr.

These test the conformance of all the interbranch variations to the
expected API including generally applicable corner cases.
Specific tests for individual formats are in the tests for the formats
itself rather than in tests/per_interbranch/*.py.
"""


from bzrlib import (
    branchbuilder,
    memorytree,
    )
from bzrlib.branch import (
                           GenericInterBranch,
                           InterBranch,
                           )
from bzrlib.bzrdir import (
    BzrDirFormat,
    BzrDirMetaFormat1,
    )
from bzrlib.errors import (
    FileExists,
    NotBranchError,
    UninitializableFormat,
    )
from bzrlib.tests import (
    TestCaseWithTransport,
    multiply_tests,
    )
from bzrlib.transport import get_transport


def make_scenarios(test_list):
    """Transform the input test list to a list of scenarios.

    :param formats: A list of tuples:
        (interbranch_class, branch_format_from, branch_format_to).
    """
    result = []
    for interbranch_class, branch_format_from, branch_format_to in test_list:
        id = '%s,%s,%s' % (interbranch_class.__name__,
                            branch_format_from.__class__.__name__,
                            branch_format_to.__class__.__name__)
        scenario = (id,
            {
             "branch_format_from": branch_format_from,
             "interbranch_class": interbranch_class,
             "branch_format_to": branch_format_to,
             })
        result.append(scenario)
    return result


def default_test_list():
    """Generate the default list of interbranch permutations to test."""
    result = []
    # test the default InterBranch between format 6 and the current
    # default format.
    for optimiser_class in InterBranch._optimisers:
        format_from_test, format_to_test = \
            optimiser_class._get_branch_formats_to_test()
        if format_to_test is not None:
            result.append((optimiser_class,
                           format_from_test, format_to_test))
    # if there are specific combinations we want to use, we can add them
    # here.
    return result


class TestCaseWithInterBranch(TestCaseWithTransport):

    def make_from_branch(self, relpath):
        repo = self.make_repository(relpath)
        return self.branch_format_from.initialize(repo.bzrdir)

    def make_from_branch_and_memory_tree(self, relpath):
        """Create a branch on the default transport and a MemoryTree for it."""
        b = self.make_from_branch(relpath)
        return memorytree.MemoryTree.create_on_branch(b)

    def make_from_branch_and_tree(self, relpath):
        """Create a branch on the default transport and a working tree for it."""
        b = self.make_from_branch(relpath)
        return b.bzrdir.create_workingtree()

    def make_from_branch_builder(self, relpath):
        default_format = BzrDirFormat.get_default_format()
        format = BzrDirMetaFormat1()
        format.set_branch_format(self.branch_format_from)
        format.repository_format = default_format.repository_format
        format.workingtree_format = default_format.workingtree_format
        return branchbuilder.BranchBuilder(self.get_transport(relpath),
            format=format)

    def make_to_branch(self, relpath):
        repo = self.make_repository(relpath)
        return self.branch_format_to.initialize(repo.bzrdir)

    def make_to_branch_and_memory_tree(self, relpath):
        """Create a branch on the default transport and a MemoryTree for it."""
        b = self.make_to_branch(relpath)
        return memorytree.MemoryTree.create_on_branch(b)

    def make_to_branch_and_tree(self, relpath):
        """Create a branch on the default transport and a working tree for it."""
        b = self.make_to_branch(relpath)
        return b.bzrdir.create_workingtree()

    def sprout_to(self, origdir, to_url):
        """Sprout a bzrdir, using to_format for the new branch."""
        newbranch = self.make_to_branch(to_url)
        origbranch = origdir.open_branch()
        newbranch.repository.fetch(origbranch.repository)
        origbranch.copy_content_into(newbranch)
        newbranch.bzrdir.create_workingtree()
        return newbranch.bzrdir

    def sprout_from(self, origdir, to_url):
        """Sprout a bzrdir, using from_format for the new bzrdir."""
        newbranch = self.make_from_branch(to_url)
        origbranch = origdir.open_branch()
        newbranch.repository.fetch(origbranch.repository)
        origbranch.copy_content_into(newbranch)
        newbranch.bzrdir.create_workingtree()
        return newbranch.bzrdir


def load_tests(standard_tests, module, loader):
    submod_tests = loader.loadTestsFromModuleNames([
        'bzrlib.tests.per_interbranch.test_pull',
        'bzrlib.tests.per_interbranch.test_push',
        'bzrlib.tests.per_interbranch.test_update_revisions',
        ])
    scenarios = make_scenarios(default_test_list())
    return multiply_tests(submod_tests, scenarios, standard_tests)
