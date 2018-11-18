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

For more generic per-repository tests, see breezy.tests.per_repository.
"""

from breezy.tests.per_repository import (
    all_repository_format_scenarios,
    TestCaseWithRepository,
    )


def all_repository_vf_format_scenarios():
    scenarios = []
    for test_name, scenario_info in all_repository_format_scenarios():
        format = scenario_info['repository_format']
        if format.supports_full_versioned_files:
            scenarios.append((test_name, scenario_info))
    return scenarios


def load_tests(loader, basic_tests, pattern):
    testmod_names = [
        'test_add_inventory_by_delta',
        'test_check',
        'test_check_reconcile',
        'test_find_text_key_references',
        'test__generate_text_key_index',
        'test_fetch',
        'test_fileid_involved',
        'test_merge_directive',
        'test_reconcile',
        'test_refresh_data',
        'test_repository',
        'test_write_group',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
        ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests
