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

from bzrlib.bzrdir import BzrDirFormat
from bzrlib.tests import (
    default_transport,
    multiply_tests,
    )
from bzrlib.tests.per_controldir import (
    TestCaseWithBzrDir,
    make_scenarios,
    )


def load_tests(standard_tests, module, loader):
    colo_supported_formats = []
    colo_unsupported_formats = []
    for format in BzrDirFormat.known_formats():
        if format.colocated_branches:
            colo_supported_formats.append(format)
        else:
            colo_unsupported_formats.append(format)
    supported_scenarios = make_scenarios(default_transport, None, None,
        colo_supported_formats)
    unsupported_scenarios = make_scenarios(default_transport, None, None,
        colo_unsupported_formats)
    result = loader.suiteClass()
    supported_tests = loader.loadTestsFromModuleNames([
        'bzrlib.tests.per_controldir_colo.test_supported'])
    unsupported_tests = loader.loadTestsFromModuleNames([
        'bzrlib.tests.per_controldir_colo.test_unsupported'])
    multiply_tests(supported_tests, supported_scenarios, result)
    multiply_tests(unsupported_tests, unsupported_scenarios, result)
    return result
