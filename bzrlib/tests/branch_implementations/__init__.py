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

from bzrlib.branch import (BranchFormat,
                           BranchTestProviderAdapter,
                           _legacy_formats,
                           )
from bzrlib.tests import (
                          adapt_modules,
                          TestLoader,
                          TestSuite,
                          )


def test_suite():
    result = TestSuite()
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
        'bzrlib.tests.branch_implementations.test_tags',
        'bzrlib.tests.branch_implementations.test_uncommit',
        'bzrlib.tests.branch_implementations.test_update',
        ]
    # Generate a list of branch formats and their associated bzrdir formats to
    # use.
    combinations = [(format, format._matchingbzrdir) for format in 
         BranchFormat._formats.values() + _legacy_formats]
    # TODO: To usefully test the SmartServer, we need to specify the bzrdir
    # format, branch format, and also the transport.
    adapter = BranchTestProviderAdapter(
        # None here will cause the default vfs transport server to be used.
        None,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        combinations)
    loader = TestLoader()
    adapt_modules(test_branch_implementations, adapter, loader, result)


    from bzrlib.smart.server import (
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        )
    from bzrlib.remote import RemoteBranchFormat, RemoteBzrDirFormat
    from bzrlib.transport.memory import MemoryServer
    adapt_to_smart_server = BranchTestProviderAdapter(
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        [(RemoteBranchFormat(), RemoteBzrDirFormat())],
        MemoryServer
        )
    adapt_modules(test_branch_implementations,
                  adapt_to_smart_server,
                  loader,
                  result)

    return result
