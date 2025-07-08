# Copyright (C) 2006-2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""ControlDir implementation tests for bzr.

These test the conformance of all the controldir variations to the expected API.
Specific tests for individual formats are in the tests/test_bzrdir.py file
rather than in tests/per_branch/*.py.
"""

from breezy.tests import (
    TestCaseWithTransport,
    default_transport,
    multiply_tests,
    test_server,
)
from breezy.transport import memory

from ...controldir import ControlDirFormat


def make_scenarios(
    vfs_factory, transport_server, transport_readonly_server, formats, name_suffix=""
):
    """Transform the input to a list of scenarios.

    :param formats: A list of bzrdir_format objects.
    :param vfs_server: A factory to create a Transport Server which has
        all the VFS methods working, and is writable.
    """
    result = []
    for format in formats:
        scenario_name = format.__class__.__name__
        scenario_name += name_suffix
        scenario = (
            scenario_name,
            {
                "vfs_transport_factory": vfs_factory,
                "transport_server": transport_server,
                "transport_readonly_server": transport_readonly_server,
                "bzrdir_format": format,
            },
        )
        result.append(scenario)
    return result


class TestCaseWithControlDir(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.controldir = None

    def get_bzrdir(self):
        if self.controldir is None:
            self.controldir = self.make_controldir(None)
        return self.controldir

    def get_default_format(self):
        return self.bzrdir_format


def load_tests(loader, standard_tests, pattern):
    test_per_controldir = [
        "breezy.tests.per_controldir.test_controldir",
        "breezy.tests.per_controldir.test_format",
        "breezy.tests.per_controldir.test_push",
    ]
    submod_tests = loader.suiteClass()
    for module_name in test_per_controldir:
        submod_tests.addTest(loader.loadTestsFromName(module_name))
    formats = ControlDirFormat.known_formats()
    scenarios = make_scenarios(
        default_transport,
        None,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        formats,
    )
    # This will always add scenarios using the smart server.
    from ...bzr.remote import RemoteBzrDirFormat

    # test the remote server behaviour when backed with a MemoryTransport
    # Once for the current version
    scenarios.extend(
        make_scenarios(
            memory.MemoryServer,
            test_server.SmartTCPServer_for_testing,
            test_server.ReadonlySmartTCPServer_for_testing,
            [(RemoteBzrDirFormat())],
            name_suffix="-default",
        )
    )
    # And once with < 1.6 - the 'v2' protocol.
    scenarios.extend(
        make_scenarios(
            memory.MemoryServer,
            test_server.SmartTCPServer_for_testing_v2_only,
            test_server.ReadonlySmartTCPServer_for_testing_v2_only,
            [(RemoteBzrDirFormat())],
            name_suffix="-v2",
        )
    )
    # add the tests for the sub modules
    return multiply_tests(submod_tests, scenarios, standard_tests)
