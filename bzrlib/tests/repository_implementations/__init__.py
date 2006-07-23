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


"""BzrDir implementation tests for bzr.

These test the conformance of all the repository variations to the expected API.
Specific tests for individual formats are in the tests/test_repository.py file 
rather than in tests/branch_implementations/*.py.
"""

from bzrlib.repository import (_legacy_formats,
                               RepositoryFormat,
                               RepositoryTestProviderAdapter,
                               )
                            
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestLoader,
                          TestSuite,
                          )


def test_suite():
    result = TestSuite()
    test_repository_implementations = [
        'bzrlib.tests.repository_implementations.test_break_lock',
        'bzrlib.tests.repository_implementations.test_commit_builder',
        'bzrlib.tests.repository_implementations.test_fileid_involved',
        'bzrlib.tests.repository_implementations.test_reconcile',
        'bzrlib.tests.repository_implementations.test_repository',
        ]

    from bzrlib.transport.smart import SmartTCPServer_for_testing
    from bzrlib.remote import RemoteBzrDirFormat, RemoteRepositoryFormat
    from bzrlib.repository import RepositoryFormatKnit1
    transport_server = SmartTCPServer_for_testing
    smart_server_suite = TestSuite()
    adapt_to_smart_server = RepositoryTestProviderAdapter(transport_server, None,
            [(RemoteRepositoryFormat, RemoteBzrDirFormat)])
    adapt_modules(test_repository_implementations,
                  adapt_to_smart_server, 
                  TestLoader(),
                  smart_server_suite)
    result.addTests(smart_server_suite)

    ## adapter = RepositoryTestProviderAdapter(
    ##     default_transport,
    ##     # None here will cause a readonly decorator to be created
    ##     # by the TestCaseWithTransport.get_readonly_transport method.
    ##     None,
    ##     [(format, format._matchingbzrdir) for format in 
    ##      RepositoryFormat._formats.values() + _legacy_formats])
    ## loader = TestLoader()
    ## adapt_modules(test_repository_implementations, adapter, loader, result)
    return result
