# Copyright (C) 2006-2011 Canonical Ltd
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

This test the conformance of all the workingtre variations to the expected API.
Specific tests for individual formats are in the tests/test_workingtree file
rather than in tests/per_workingtree/*.py.
"""

from breezy import (
    branchbuilder,
    tests,
    transport,
    workingtree,
    )
from breezy.transport import memory
from breezy.tests import (
    per_controldir,
    test_server,
    )


def make_scenarios(transport_server, transport_readonly_server, formats,
                   remote_server=None, remote_readonly_server=None,
                   remote_backing_server=None):
    result = []
    for workingtree_format in formats:
        result.append((workingtree_format.__class__.__name__,
                       make_scenario(transport_server,
                                     transport_readonly_server,
                                     workingtree_format)))
    default_wt_format = workingtree.format_registry.get_default()
    if remote_server is None:
        remote_server = test_server.SmartTCPServer_for_testing
    if remote_readonly_server is None:
        remote_readonly_server = test_server.ReadonlySmartTCPServer_for_testing
    if remote_backing_server is None:
        remote_backing_server = memory.MemoryServer
    scenario = make_scenario(remote_server, remote_readonly_server,
                             default_wt_format)
    scenario['repo_is_remote'] = True
    scenario['vfs_transport_factory'] = remote_backing_server
    result.append((default_wt_format.__class__.__name__ + ',remote', scenario))
    return result


def make_scenario(transport_server, transport_readonly_server,
                  workingtree_format):
    return {
        "transport_server": transport_server,
        "transport_readonly_server": transport_readonly_server,
        "bzrdir_format": workingtree_format._matchingcontroldir,
        "workingtree_format": workingtree_format,
        }


def wt_scenarios():
    """Returns the scenarios for all registered working trees.

    This can used by plugins that want to define tests against these working
    trees.
    """
    scenarios = make_scenarios(
        tests.default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        workingtree.format_registry._get_all()
        )
    return scenarios


class TestCaseWithWorkingTree(per_controldir.TestCaseWithControlDir):

    def make_branch_and_tree(self, relpath, format=None):
        made_control = self.make_controldir(relpath, format=format)
        made_control.create_repository()
        b = made_control.create_branch()
        if getattr(self, 'repo_is_remote', False):
            # If the repo is remote, then we just create a local lightweight
            # checkout
            # XXX: This duplicates a lot of Branch.create_checkout, but we know
            #      we want a) lightweight, and b) a specific WT format. We also
            #      know that nothing should already exist, etc.
            t = transport.get_transport(relpath)
            t.ensure_base()
            bzrdir_format = self.workingtree_format.get_controldir_for_branch()
            wt_dir = bzrdir_format.initialize_on_transport(t)
            branch_ref = wt_dir.set_branch_reference(b)
            wt = wt_dir.create_workingtree(None, from_branch=branch_ref)
        else:
            wt = self.workingtree_format.initialize(made_control)
        return wt

    def make_branch_builder(self, relpath, format=None):
        if format is None:
            format = self.workingtree_format.get_controldir_for_branch()
        builder = branchbuilder.BranchBuilder(self.get_transport(relpath),
                                              format=format)
        return builder


def load_tests(loader, standard_tests, pattern):
    test_names = [
        'add_reference',
        'add',
        'annotate_iter',
        'basis_inventory',
        'basis_tree',
        'break_lock',
        'canonical_path',
        'changes_from',
        'check',
        'check_state',
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
        'shelf_manager',
        'smart_add',
        'symlinks',
        'transform',
        'uncommit',
        'unversion',
        'views',
        'walkdirs',
        'workingtree',
        ]
    test_workingtree_implementations = [
        'breezy.tests.per_workingtree.test_' + name for
        name in test_names]

    scenarios = wt_scenarios()

    # add the tests for the sub modules
    return tests.multiply_tests(
        loader.loadTestsFromModuleNames(test_workingtree_implementations),
        scenarios, standard_tests)


class TestWtScenarios(tests.TestCase):

    def test_protect_wt_scenarios(self):
        # Just make sure we don't accidentally delete the helper again
        scenarios = wt_scenarios()
