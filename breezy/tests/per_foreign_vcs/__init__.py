# Copyright (C) 2009, 2010 Canonical Ltd
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


"""Tests specific to foreign branch implementations."""

from breezy import foreign, tests


def vcs_scenarios():
    scenarios = []
    for _name, vcs in foreign.foreign_vcs_registry.items():
        scenarios.append(
            (
                vcs.__class__.__name__,
                {
                    "branch_factory": vcs.branch_format.get_foreign_tests_branch_factory(),
                    "repository_factory": vcs.repository_format.get_foreign_tests_repository_factory(),
                    "branch_format": vcs.branch_format,
                    "repository_format": vcs.repository_format,
                },
            )
        )
    return scenarios


def load_tests(loader, standard_tests, pattern):
    result = loader.suiteClass()
    per_vcs_mod_names = [
        "branch",
        "repository",
    ]
    sub_tests = loader.loadTestsFromModuleNames(
        ["breezy.tests.per_foreign_vcs.test_" + name for name in per_vcs_mod_names]
    )
    tests.multiply_tests(sub_tests, vcs_scenarios(), result)
    return result
