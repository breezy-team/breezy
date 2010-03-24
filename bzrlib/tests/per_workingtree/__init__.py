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


def workingtree_formats():
    """The known working tree formats."""
    return (workingtree.WorkingTreeFormat._formats.values() +
        workingtree._legacy_formats)


def load_tests(standard_tests, module, loader):
    test_names = [
        'add_reference',
        'add',
        'annotate_iter',
        'basis_inventory',
        'basis_tree',
        'break_lock',
        'changes_from',
        'check',
        'content_filters',
        'commit',
        'eol_conversion',
        'executable',
        'flush',
        'get_file_mtime',
        'get_parent_ids',
        'inv',
        'is_control_filename',
        'is_ignored',
        'locking',
        'merge_from_branch',
        'mkdir',
        'move',
        'nested_specifics',
        'parents',
        'paths2ids',
        'pull',
        'put_file',
        'readonly',
        'read_working_inventory',
        'remove',
        'rename_one',
        'revision_tree',
        'set_root_id',
        'smart_add',
        'uncommit',
        'unversion',
        'views',
        'walkdirs',
        'workingtree',
        ]
    test_workingtree_implementations = [
        'bzrlib.tests.per_workingtree.test_' + name for
        name in test_names]

    scenarios = make_scenarios(
        tests.default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        workingtree_formats()
        )

    # add the tests for the sub modules
    return tests.multiply_tests(
        loader.loadTestsFromModuleNames(test_workingtree_implementations),
        scenarios, standard_tests)
