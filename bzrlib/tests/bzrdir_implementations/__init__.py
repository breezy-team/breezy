# Copyright (C) 2006 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""BzrDir implementation tests for bzr.

These test the conformance of all the bzrdir variations to the expected API.
Specific tests for individual formats are in the tests/test_bzrdir.py file 
rather than in tests/branch_implementations/*.py.
"""

from bzrlib.bzrdir import BzrDirFormat
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestCaseWithTransport,
                          TestLoader,
                          TestScenarioApplier,
                          TestSuite,
                          )
from bzrlib.transport.memory import MemoryServer


class BzrDirTestProviderAdapter(TestScenarioApplier):
    """A tool to generate a suite testing multiple bzrdir formats at once.

    This is done by copying the test once for each transport and injecting
    the transport_server, transport_readonly_server, and bzrdir_format
    classes into each copy. Each copy is also given a new id() to make it
    easy to identify.
    """

    def __init__(self, vfs_factory, transport_server, transport_readonly_server,
        formats):
        """Create an object to adapt tests.

        :param vfs_server: A factory to create a Transport Server which has
            all the VFS methods working, and is writable.
        """
        self._vfs_factory = vfs_factory
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self.scenarios = self.formats_to_scenarios(formats)
    
    def formats_to_scenarios(self, formats):
        """Transform the input formats to a list of scenarios.

        :param formats: A list of bzrdir_format objects.
        """
        result = []
        for format in formats:
            scenario = (format.__class__.__name__, {
                "vfs_transport_factory":self._vfs_factory,
                "transport_server":self._transport_server,
                "transport_readonly_server":self._transport_readonly_server,
                "bzrdir_format":format,
                })
            result.append(scenario)
        return result


class TestCaseWithBzrDir(TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithBzrDir, self).setUp()
        self.bzrdir = None

    def get_bzrdir(self):
        if self.bzrdir is None:
            self.bzrdir = self.make_bzrdir(None)
        return self.bzrdir

    def make_bzrdir(self, relpath, format=None):
        return super(TestCaseWithBzrDir, self).make_bzrdir(
            relpath, format=self.bzrdir_format)


def test_suite():
    result = TestSuite()
    test_bzrdir_implementations = [
        'bzrlib.tests.bzrdir_implementations.test_bzrdir',
        ]
    formats = BzrDirFormat.known_formats()
    adapter = BzrDirTestProviderAdapter(
        default_transport,
        None,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        formats)
    loader = TestLoader()
    adapt_modules(test_bzrdir_implementations, adapter, loader, result)

    # This will always add the tests for smart server transport, regardless of
    # the --transport option the user specified to 'bzr selftest'.
    from bzrlib.smart.server import SmartTCPServer_for_testing, ReadonlySmartTCPServer_for_testing
    from bzrlib.remote import RemoteBzrDirFormat

    # test the remote server behaviour using a MemoryTransport
    smart_server_suite = TestSuite()
    adapt_to_smart_server = BzrDirTestProviderAdapter(
        MemoryServer,
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        [(RemoteBzrDirFormat())])
    adapt_modules(test_bzrdir_implementations,
                  adapt_to_smart_server,
                  TestLoader(),
                  smart_server_suite)
    result.addTests(smart_server_suite)

    return result
