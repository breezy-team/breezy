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
                          TestCaseWithTransport,
                          TestLoader,
                          TestSuite,
                          )
from bzrlib.workingtree import (WorkingTreeFormat,
                                WorkingTreeTestProviderAdapter,
                                _legacy_formats,
                                )


class TestCaseWithWorkingTree(TestCaseWithTransport):

    def make_bzrdir(self, relpath):
        # todo factor out into bzrdir-using-implementations-tests-base-class
        try:
            url = self.get_url(relpath)
            segments = url.split('/')
            if segments and segments[-1] not in ('', '.'):
                parent = '/'.join(segments[:-1])
                t = get_transport(parent)
                try:
                    t.mkdir(segments[-1])
                except errors.FileExists:
                    pass
            return self.bzrdir_format.initialize(url)
        except errors.UninitializableFormat:
            raise TestSkipped("Format %s is not initializable.")

    def make_branch_and_tree(self, relpath):
        made_control = self.make_bzrdir(relpath)
        made_control.create_repository()
        made_control.create_branch()
        return self.workingtree_format.initialize(made_control)


def test_suite():
    result = TestSuite()
    test_workingtree_implementations = [
        'bzrlib.tests.workingtree_implementations.test_is_control_filename',
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
