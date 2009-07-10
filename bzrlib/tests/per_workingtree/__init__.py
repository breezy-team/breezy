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


"""WorkingTree implementation tests for bzr.

These test the conformance of all the workingtre variations to the expected API.
Specific tests for individual formats are in the tests/test_workingtree file
rather than in tests/per_workingtree/*.py.
"""

from bzrlib import (
    errors,
    tests,
    workingtree,
    )
from bzrlib.tests import per_bzrdir


def make_scenarios(transport_server, transport_readonly_server, formats):
    result = []
    for workingtree_format in formats:
        result.append((workingtree_format.__class__.__name__,
                       make_scenario(transport_server,
                                     transport_readonly_server,
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


class TestCaseWithWorkingTree(per_bzrdir.TestCaseWithBzrDir):

    def make_branch_and_tree(self, relpath, format=None):
        made_control = self.make_bzrdir(relpath, format=format)
        made_control.create_repository()
        made_control.create_branch()
        return self.workingtree_format.initialize(made_control)


def load_tests(standard_tests, module, loader):
    per_test_workingtree = [
        'bzrlib.tests.per_workingtree.test_add_reference',
        'bzrlib.tests.per_workingtree.test_add',
        'bzrlib.tests.per_workingtree.test_annotate_iter',
        'bzrlib.tests.per_workingtree.test_basis_inventory',
        'bzrlib.tests.per_workingtree.test_basis_tree',
        'bzrlib.tests.per_workingtree.test_break_lock',
        'bzrlib.tests.per_workingtree.test_changes_from',
        'bzrlib.tests.per_workingtree.test_content_filters',
        'bzrlib.tests.per_workingtree.test_commit',
        'bzrlib.tests.per_workingtree.test_eol_conversion',
        'bzrlib.tests.per_workingtree.test_executable',
        'bzrlib.tests.per_workingtree.test_flush',
        'bzrlib.tests.per_workingtree.test_get_file_mtime',
        'bzrlib.tests.per_workingtree.test_get_parent_ids',
        'bzrlib.tests.per_workingtree.test_inv',
        'bzrlib.tests.per_workingtree.test_is_control_filename',
        'bzrlib.tests.per_workingtree.test_is_ignored',
        'bzrlib.tests.per_workingtree.test_locking',
        'bzrlib.tests.per_workingtree.test_merge_from_branch',
        'bzrlib.tests.per_workingtree.test_mkdir',
        'bzrlib.tests.per_workingtree.test_move',
        'bzrlib.tests.per_workingtree.test_nested_specifics',
        'bzrlib.tests.per_workingtree.test_parents',
        'bzrlib.tests.per_workingtree.test_paths2ids',
        'bzrlib.tests.per_workingtree.test_pull',
        'bzrlib.tests.per_workingtree.test_put_file',
        'bzrlib.tests.per_workingtree.test_readonly',
        'bzrlib.tests.per_workingtree.test_read_working_inventory',
        'bzrlib.tests.per_workingtree.test_remove',
        'bzrlib.tests.per_workingtree.test_rename_one',
        'bzrlib.tests.per_workingtree.test_revision_tree',
        'bzrlib.tests.per_workingtree.test_set_root_id',
        'bzrlib.tests.per_workingtree.test_smart_add',
        'bzrlib.tests.per_workingtree.test_uncommit',
        'bzrlib.tests.per_workingtree.test_unversion',
        'bzrlib.tests.per_workingtree.test_views',
        'bzrlib.tests.per_workingtree.test_walkdirs',
        'bzrlib.tests.per_workingtree.test_workingtree',
        ]

    scenarios = make_scenarios(
        tests.default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        workingtree.WorkingTreeFormat._formats.values()
        + workingtree._legacy_formats)

    # add the tests for the sub modules
    return tests.multiply_tests(
        loader.loadTestsFromModuleNames(per_test_workingtree),
        scenarios, standard_tests)
