# Copyright (C) 2008, 2009 Canonical Ltd
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


"""Repository implementation tests for CHK support.

These tests check the conformance of the chk index some repositories support.
All repository formats are tested - those that do not suppport chk indices
have the test_unsupported tests run; the others have the test_supported tests
run.
"""

from breezy import repository
from breezy.bzr import remote
from breezy.tests import multiply_tests
from breezy.tests.per_repository import (
    TestCaseWithRepository,
    all_repository_format_scenarios,
)

from ...groupcompress_repo import RepositoryFormat2a
from ...knitpack_repo import RepositoryFormatKnitPack5


class TestCaseWithRepositoryCHK(TestCaseWithRepository):
    def make_repository(self, path, format=None):
        TestCaseWithRepository.make_repository(self, path, format=format)
        return repository.Repository.open(self.get_transport(path).base)


def load_tests(loader, standard_tests, pattern):
    supported_scenarios = []
    unsupported_scenarios = []
    for test_name, scenario_info in all_repository_format_scenarios():
        format = scenario_info["repository_format"]
        # For remote repositories, we test both with, and without a backing chk
        # capable format: change the format we use to create the repo to direct
        # formats, and then the overridden make_repository in
        # TestCaseWithRepositoryCHK will give a re-opened RemoteRepository
        # with the chosen backing format.
        if isinstance(format, remote.RemoteRepositoryFormat):
            with_support = dict(scenario_info)
            with_support["repository_format"] = RepositoryFormat2a()
            supported_scenarios.append((test_name + "(Supported)", with_support))
            no_support = dict(scenario_info)
            no_support["repository_format"] = RepositoryFormatKnitPack5()
            unsupported_scenarios.append((test_name + "(Not Supported)", no_support))
        elif format.supports_chks:
            supported_scenarios.append((test_name, scenario_info))
        else:
            unsupported_scenarios.append((test_name, scenario_info))
    result = loader.suiteClass()
    supported_tests = loader.loadTestsFromName(
        "breezy.bzr.tests.per_repository_chk.test_supported"
    )
    unsupported_tests = loader.loadTestsFromName(
        "breezy.bzr.tests.per_repository_chk.test_unsupported"
    )
    multiply_tests(supported_tests, supported_scenarios, result)
    multiply_tests(unsupported_tests, unsupported_scenarios, result)
    return result
