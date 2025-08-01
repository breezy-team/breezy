# Copyright (C) 2007 Canonical Ltd
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

"""OS Lock implementation tests for bzr.

These test the conformance of all the lock variations to the expected API.
"""

from breezy import _transport_rs, tests


class TestCaseWithLock(tests.TestCaseWithTransport):
    pass


def make_scenarios():
    result = []
    result.append(
        (
            "default",
            {
                "write_lock": _transport_rs.WriteLock,
                "read_lock": _transport_rs.ReadLock,
            },
        )
    )
    return result


def load_tests(loader, standard_tests, pattern):
    submod_tests = loader.suiteClass()
    for module_name in [
        "breezy.tests.per_lock.test_lock",
        "breezy.tests.per_lock.test_temporary_write_lock",
    ]:
        submod_tests.addTest(loader.loadTestsFromName(module_name))
    scenarios = make_scenarios()
    # add the tests for the sub modules
    return tests.multiply_tests(submod_tests, scenarios, standard_tests)
