# Copyright (C) 2010 Canonical Ltd
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


"""BzrDir implementation tests for colocated branch support.

These tests check the conformance of the colocated branches support.
All bzrdir formats are tested - those that do not suppport colocated branches
have the test_unsupported tests run; the others have the test_supported tests
run.
"""

from breezy.tests import default_transport, multiply_tests, test_server
from breezy.tests.per_controldir import make_scenarios
from breezy.transport import memory

from ...controldir import ControlDirFormat


def load_tests(loader, standard_tests, pattern):
    colo_supported_formats = []
    colo_unsupported_formats = []
    # This will always add scenarios using the smart server.
    from ...bzr.remote import RemoteBzrDirFormat

    for format in ControlDirFormat.known_formats():
        if isinstance(format, RemoteBzrDirFormat):
            continue
        if format.colocated_branches:
            colo_supported_formats.append(format)
        else:
            colo_unsupported_formats.append(format)
    supported_scenarios = make_scenarios(
        default_transport, None, None, colo_supported_formats
    )
    unsupported_scenarios = make_scenarios(
        default_transport, None, None, colo_unsupported_formats
    )
    # test the remote server behaviour when backed with a MemoryTransport
    # Once for the current version
    unsupported_scenarios.extend(
        make_scenarios(
            memory.MemoryServer,
            test_server.SmartTCPServer_for_testing,
            test_server.ReadonlySmartTCPServer_for_testing,
            [(RemoteBzrDirFormat())],
            name_suffix="-default",
        )
    )
    # And once with < 1.6 - the 'v2' protocol.
    unsupported_scenarios.extend(
        make_scenarios(
            memory.MemoryServer,
            test_server.SmartTCPServer_for_testing_v2_only,
            test_server.ReadonlySmartTCPServer_for_testing_v2_only,
            [(RemoteBzrDirFormat())],
            name_suffix="-v2",
        )
    )

    result = loader.suiteClass()
    supported_tests = loader.loadTestsFromName(
        "breezy.tests.per_controldir_colo.test_supported"
    )
    unsupported_tests = loader.loadTestsFromName(
        "breezy.tests.per_controldir_colo.test_unsupported"
    )
    multiply_tests(supported_tests, supported_scenarios, result)
    multiply_tests(unsupported_tests, unsupported_scenarios, result)
    return result
