# Copyright (C) 2007-2020 Jelmer Vernoij <jelmer@jelmer.uk>
# Copyright (C) 2006, 2007 Canonical Ltd
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

"""The basic test suite for bzr."""

from ... import tests

TestCase = tests.TestCase
TestCaseInTempDir = tests.TestCaseInTempDir
TestCaseWithTransport = tests.TestCaseWithTransport
TestCaseWithMemoryTransport = tests.TestCaseWithMemoryTransport


def load_tests(loader, basic_tests, pattern):
    suite = loader.suiteClass()
    # add the tests for this module
    suite.addTests(basic_tests)

    prefix = __name__ + "."

    testmod_names = [
        "blackbox",
        "per_bzrdir",
        "per_pack_repository",
        "per_repository_chk",
        "per_repository_vf",
        "test_annotate",
        "test_bundle",
        "test_bzrdir",
        "test_conflicts",
        "test_generate_ids",
        "test_lockable_files",
        "test_matchers",
        "test_read_bundle",
        "test_remote",
        "test_repository",
        "test_smart",
        "test_smart_request",
        "test_smart_signals",
        "test_smart_transport",
        "test_serializer",
        "test_tag",
        "test_testament",
        "test_transform",
        "test_vf_search",
        "test_vfs_ratchet",
        "test_workingtree",
        "test_workingtree_4",
    ]

    # add the tests for the sub modules
    suite.addTests(
        loader.loadTestsFromModuleNames(
            [prefix + module_name for module_name in testmod_names]
        )
    )
    return suite
