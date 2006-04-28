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


"""InterRepository implementation tests for bzr.

These test the conformance of all the interrepository variations to the
expected API including generally applicable corner cases.
Specific tests for individual formats are in the tests/test_repository.py file 
rather than in tests/interrepository_implementations/*.py.
"""

from bzrlib.repository import (_legacy_formats,
                               InterRepositoryTestProviderAdapter,
                               )
                            
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestLoader,
                          TestSuite,
                          )


def test_suite():
    result = TestSuite()
    test_interrepository_implementations = [
        'bzrlib.tests.interrepository_implementations.test_interrepository',
        ]
    adapter = InterRepositoryTestProviderAdapter(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        InterRepositoryTestProviderAdapter.default_test_list()
        )
    loader = TestLoader()
    adapt_modules(test_interrepository_implementations, adapter, loader, result)
    return result
