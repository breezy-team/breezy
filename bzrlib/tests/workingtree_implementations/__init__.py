# Copyright (C) 2006 by Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""WorkingTree implementation tests for bzr.

These test the conformance of all the workingtre variations to the expected API.
Specific tests for individual formats are in the tests/test_workingtree file 
rather than in tests/workingtree_implementations/*.py.
"""

import bzrlib.errors as errors
from bzrlib.transport import get_transport
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestLoader,
                          TestSuite,
                          )
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.workingtree import (WorkingTreeFormat,
                                WorkingTreeTestProviderAdapter,
                                _legacy_formats,
                                )


class TestCaseWithWorkingTree(TestCaseWithBzrDir):

    def make_branch_and_tree(self, relpath, format=None):
        made_control = self.make_bzrdir(relpath, format=format)
        made_control.create_repository()
        made_control.create_branch()
        return self.workingtree_format.initialize(made_control)


def test_suite():
    result = TestSuite()
    test_workingtree_implementations = [
        'bzrlib.tests.workingtree_implementations.test_basis_inventory',
        'bzrlib.tests.workingtree_implementations.test_is_control_filename',
        'bzrlib.tests.workingtree_implementations.test_pull',
        'bzrlib.tests.workingtree_implementations.test_workingtree',
        ]
    adapter = WorkingTreeTestProviderAdapter(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        [(format, format._matchingbzrdir) for format in 
         WorkingTreeFormat._formats.values() + _legacy_formats])
    loader = TestLoader()
    adapt_modules(test_workingtree_implementations, adapter, loader, result)
    return result
