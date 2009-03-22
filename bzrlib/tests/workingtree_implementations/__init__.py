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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""WorkingTree implementation tests for bzr.

These test the conformance of all the workingtre variations to the expected API.
Specific tests for individual formats are in the tests/test_workingtree file
rather than in tests/workingtree_implementations/*.py.
"""

import bzrlib.errors as errors
from bzrlib.transport import get_transport
from bzrlib.tests import (
                          default_transport,
                          multiply_tests,
                          )
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.workingtree import (WorkingTreeFormat,
                                _legacy_formats,
                                )


def make_scenarios(transport_server, transport_readonly_server, formats):
    """Create a scenario for the specified converter

    :param workingtree_format: The particular workingtree format to test.
    :param bzrdir_format: The bzrdir format to test.
    :return: a (name, options) tuple, where options is a dict of values
        to be used as members of the TestCase.
    """
    result = []
    for workingtree_format in formats:
        result.append((workingtree_format.__class__.__name__,
            make_scenario(transport_server, transport_readonly_server,
            workingtree_format)))
    return result


def make_scenario(transport_server, transport_readonly_server,
    workingtree_format):
    return {
        "transport_server": transport_server,
        "transport_readonly_server": transport_readonly_server,
        "bzrdir_format": workingtree_format._matchingbzrdir,
        "workingtree_format": workingtree_format,
        }


class TestCaseWithWorkingTree(TestCaseWithBzrDir):

    def make_branch_and_tree(self, relpath, format=None):
        made_control = self.make_bzrdir(relpath, format=format)
        made_control.create_repository()
        made_control.create_branch()
        return self.workingtree_format.initialize(made_control)


def load_tests(standard_tests, module, loader):
    test_workingtree_implementations = [
        'bzrlib.tests.workingtree_implementations.test_add_reference',
        'bzrlib.tests.workingtree_implementations.test_add',
        'bzrlib.tests.workingtree_implementations.test_basis_inventory',
        'bzrlib.tests.workingtree_implementations.test_basis_tree',
        'bzrlib.tests.workingtree_implementations.test_break_lock',
        'bzrlib.tests.workingtree_implementations.test_changes_from',
        'bzrlib.tests.workingtree_implementations.test_content_filters',
        'bzrlib.tests.workingtree_implementations.test_commit',
        'bzrlib.tests.workingtree_implementations.test_executable',
        'bzrlib.tests.workingtree_implementations.test_flush',
        'bzrlib.tests.workingtree_implementations.test_get_file_with_stat',
        'bzrlib.tests.workingtree_implementations.test_get_file_mtime',
        'bzrlib.tests.workingtree_implementations.test_get_parent_ids',
        'bzrlib.tests.workingtree_implementations.test_inv',
        'bzrlib.tests.workingtree_implementations.test_is_control_filename',
        'bzrlib.tests.workingtree_implementations.test_is_ignored',
        'bzrlib.tests.workingtree_implementations.test_locking',
        'bzrlib.tests.workingtree_implementations.test_merge_from_branch',
        'bzrlib.tests.workingtree_implementations.test_mkdir',
        'bzrlib.tests.workingtree_implementations.test_move',
        'bzrlib.tests.workingtree_implementations.test_nested_specifics',
        'bzrlib.tests.workingtree_implementations.test_parents',
        'bzrlib.tests.workingtree_implementations.test_paths2ids',
        'bzrlib.tests.workingtree_implementations.test_pull',
        'bzrlib.tests.workingtree_implementations.test_put_file',
        'bzrlib.tests.workingtree_implementations.test_readonly',
        'bzrlib.tests.workingtree_implementations.test_read_working_inventory',
        'bzrlib.tests.workingtree_implementations.test_remove',
        'bzrlib.tests.workingtree_implementations.test_rename_one',
        'bzrlib.tests.workingtree_implementations.test_revision_tree',
        'bzrlib.tests.workingtree_implementations.test_set_root_id',
        'bzrlib.tests.workingtree_implementations.test_smart_add',
        'bzrlib.tests.workingtree_implementations.test_uncommit',
        'bzrlib.tests.workingtree_implementations.test_unversion',
        'bzrlib.tests.workingtree_implementations.test_views',
        'bzrlib.tests.workingtree_implementations.test_walkdirs',
        'bzrlib.tests.workingtree_implementations.test_workingtree',
        ]

    scenarios = make_scenarios(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        WorkingTreeFormat._formats.values() + _legacy_formats)

    # add the tests for the sub modules
    return multiply_tests(
        loader.loadTestsFromModuleNames(test_workingtree_implementations),
        scenarios, standard_tests)
