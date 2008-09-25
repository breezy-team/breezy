# Copyright (C) 2008 Canonical Ltd
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


"""Repository implementation tests for CHK support.

These tests check the conformance of the chk index some repositories support.
All repository formats are tested - those that do not suppport chk indices
have the test_unsupported tests run; the others have the test_supported tests
run.
"""

from bzrlib import (
    repository,
    remote,
    )
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import (
                          adapt_modules,
                          adapt_tests,
                          TestScenarioApplier,
                          TestSuite,
                          )
from bzrlib.tests.per_repository import (
    all_repository_format_scenarios,
    TestCaseWithRepository,
    )


def load_tests(standard_tests, module, loader):
    supported = []
    notsupported = []
    for test_name, scenario_info in all_repository_format_scenarios():
        # For remote repositories, we need at least one chk
        # capable format to test it:
        # if isinstance(format, remote.RemoteRepositoryFormat):
        #     scenario_info['bzrdir_format'].repository_format = 
        if scenario_info['repository_format'].supports_chks:
            supported.append((test_name, scenario_info))
        else:
            notsupported.append((test_name, scenario_info))
    adapter = TestScenarioApplier()

    module_list = [
        'bzrlib.tests.per_repository_chk.test_supported',
        ]
    unsupported_list = [
        'bzrlib.tests.per_repository_chk.test_unsupported',
        ]
    result = TestSuite()
    # Any tests in this module are unparameterised.
    result.addTest(standard_tests)
    # Supported formats get the supported tests
    adapter.scenarios = supported
    adapt_modules(module_list, adapter, loader, result)
    # Unsupported formats get the unsupported tetss
    adapter.scenarios = notsupported
    adapt_modules(unsupported_list, adapter, loader, result)
    return result
