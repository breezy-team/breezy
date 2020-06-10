# Copyright (C) 2010 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
#          Jelmer Vernooij <jelmer.vernooij@canonical.com>
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


"""BzrDir implementation tests for bzr.

These test the conformance of all the bzrdir variations to the expected API.
Specific tests for individual formats are in the tests/test_bzrdir.py file
rather than in tests/per_branch/*.py. Generic control directory tests not
specific to BzrDir are in tests/per_controldir/*.py.
"""

from breezy.bzr.bzrdir import BzrDirFormat
from breezy.controldir import ControlDirFormat
from breezy.tests import (
    default_transport,
    multiply_tests,
    test_server,
    TestCaseWithTransport,
    )
from breezy.tests.per_controldir import make_scenarios
from breezy.transport import memory


class TestCaseWithBzrDir(TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithBzrDir, self).setUp()
        self.controldir = None

    def get_bzrdir(self):
        if self.controldir is None:
            self.controldir = self.make_controldir(None)
        return self.controldir

    def get_default_format(self):
        return self.bzrdir_format


def load_tests(loader, standard_tests, pattern):
    test_per_bzrdir = [
        'breezy.bzr.tests.per_bzrdir.test_bzrdir',
        ]
    submod_tests = loader.loadTestsFromModuleNames(test_per_bzrdir)
    formats = [format for format in ControlDirFormat.known_formats()
               if isinstance(format, BzrDirFormat)]
    scenarios = make_scenarios(
        default_transport,
        None,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        formats)
    # This will always add scenarios using the smart server.
    from breezy.bzr.remote import RemoteBzrDirFormat
    # test the remote server behaviour when backed with a MemoryTransport
    # Once for the current version
    scenarios.extend(make_scenarios(
        memory.MemoryServer,
        test_server.SmartTCPServer_for_testing,
        test_server.ReadonlySmartTCPServer_for_testing,
        [(RemoteBzrDirFormat())],
        name_suffix='-default'))
    # And once with < 1.6 - the 'v2' protocol.
    scenarios.extend(make_scenarios(
        memory.MemoryServer,
        test_server.SmartTCPServer_for_testing_v2_only,
        test_server.ReadonlySmartTCPServer_for_testing_v2_only,
        [(RemoteBzrDirFormat())],
        name_suffix='-v2'))
    # add the tests for the sub modules
    return multiply_tests(submod_tests, scenarios, standard_tests)
