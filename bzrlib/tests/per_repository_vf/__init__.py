# Copyright (C) 2011 Canonical Ltd
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


"""Implementation tests for VersionedFile-based repositories.

For more generic per-repository tests, see bzrlib.tests.per_repository.
"""

from bzrlib.tests import (
    multiply_tests,
    )
from bzrlib.tests.per_repository import (
    all_repository_format_scenarios,
    TestCaseWithRepository,
    )


def load_tests(standard_tests, module, loader):
    scenarios = []
    for test_name, scenario_info in all_repository_format_scenarios():
        format = scenario_info['repository_format']
        if format.supports_full_versioned_files:
            scenarios.append((test_name, scenario_info))
    result = loader.suiteClass()
    tests = loader.loadTestsFromModuleNames([
        'bzrlib.tests.per_repository_vf.test_repository'])
    multiply_tests(tests, scenarios, result)
    return result
