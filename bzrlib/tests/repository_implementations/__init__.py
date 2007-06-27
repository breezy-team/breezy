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


"""Repository implementation tests for bzr.

These test the conformance of all the repository variations to the expected API.
Specific tests for individual formats are in the tests/test_repository.py file 
rather than in tests/branch_implementations/*.py.
"""

from bzrlib import (
    repository,
    )
from bzrlib.repository import (
    RepositoryTestProviderAdapter,
    )
from bzrlib.repofmt import (
    weaverepo,
    )
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestLoader,
                          TestSuite,
                          )
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.transport.memory import MemoryServer


class TestCaseWithRepository(TestCaseWithBzrDir):

    def make_repository(self, relpath, format=None):
        if format is None:
            # Create a repository of the type we are trying to test.
            made_control = self.make_bzrdir(relpath)
            repo = self.repository_format.initialize(made_control)
            if getattr(self, "repository_to_test_repository"):
                repo = self.repository_to_test_repository(repo)
            return repo
        else:
            return super(TestCaseWithRepository, self).make_repository(
                relpath, format)



def test_suite():
    result = TestSuite()
    test_repository_implementations = [
        'bzrlib.tests.repository_implementations.test_break_lock',
        'bzrlib.tests.repository_implementations.test_commit_builder',
        'bzrlib.tests.repository_implementations.test_fileid_involved',
        'bzrlib.tests.repository_implementations.test_iter_reverse_revision_history',
        'bzrlib.tests.repository_implementations.test_reconcile',
        'bzrlib.tests.repository_implementations.test_repository',
        'bzrlib.tests.repository_implementations.test_revision',
        'bzrlib.tests.repository_implementations.test_statistics',
        ]

    from bzrlib.smart.server import (
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        )
    from bzrlib.remote import RemoteBzrDirFormat, RemoteRepositoryFormat

    registry = repository.format_registry
    all_formats = [registry.get(k) for k in registry.keys()]
    all_formats.extend(weaverepo._legacy_formats)
    adapter = RepositoryTestProviderAdapter(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        [(format, format._matchingbzrdir) for format in all_formats])
    loader = TestLoader()
    adapt_modules(test_repository_implementations, adapter, loader, result)

    adapt_to_smart_server = RepositoryTestProviderAdapter(
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        [(RemoteRepositoryFormat(), RemoteBzrDirFormat())],
        MemoryServer
        )
    adapt_modules(test_repository_implementations,
                  adapt_to_smart_server,
                  loader,
                  result)

    return result
