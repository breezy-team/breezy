# Copyright (C) 2006-2012, 2016 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
#          and others
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


"""Branch implementation tests for bzr.

These test the conformance of all the branch variations to the expected API.
Specific tests for individual formats are in the `tests/test_branch` file
rather than in `tests/per_branch/*.py`.
"""

from breezy import errors, tests
from breezy.tests import test_server
from breezy.transport import memory

from ...branch import format_registry
from ...bzr.remote import RemoteBranchFormat
from ..per_controldir.test_controldir import TestCaseWithControlDir


def make_scenarios(
    transport_server,
    transport_readonly_server,
    formats,
    vfs_transport_factory=None,
    name_suffix="",
):
    """Transform the input formats to a list of scenarios.

    :param formats: A list of (branch_format, bzrdir_format).
    """
    result = []
    for branch_format, bzrdir_format in formats:
        # some branches don't have separate format objects.
        # so we have a conditional here to handle them.
        scenario_name = getattr(
            branch_format, "__name__", branch_format.__class__.__name__
        )
        scenario_name += name_suffix
        scenario = (
            scenario_name,
            {
                "transport_server": transport_server,
                "transport_readonly_server": transport_readonly_server,
                "bzrdir_format": bzrdir_format,
                "branch_format": branch_format,
            },
        )
        result.append(scenario)
    return result


class TestCaseWithBranch(TestCaseWithControlDir):
    """This helper will be parameterised in each per_branch test."""

    def setUp(self):
        super().setUp()
        self.branch = None

    def get_branch(self):
        if self.branch is None:
            self.branch = self.make_branch("abranch")
        return self.branch

    def get_default_format(self):
        format = self.bzrdir_format
        self.assertEqual(format.get_branch_format(), self.branch_format)
        return format

    def make_branch(self, relpath, format=None):
        try:
            return super().make_branch(relpath, format)
        except errors.UninitializableFormat as err:
            raise tests.TestNotApplicable("Uninitializable branch format") from err

    def create_tree_with_merge(self):
        """Create a branch with a simple ancestry.

        The graph should look like:
            digraph H {
                "1" -> "2" -> "3";
                "1" -> "1.1.1" -> "3";
            }

        Or in ASCII:
            1
            |\
            2 1.1.1
            |/
            3
        """
        revmap = {}
        tree = self.make_branch_and_memory_tree("tree")
        with tree.lock_write():
            tree.add("")
            revmap["1"] = tree.commit("first")
            revmap["1.1.1"] = tree.commit("second")
            # Uncommit that last commit and switch to the other line
            tree.branch.set_last_revision_info(1, revmap["1"])
            tree.set_parent_ids([revmap["1"]])
            revmap["2"] = tree.commit("alt-second")
            tree.set_parent_ids([revmap["2"], revmap["1.1.1"]])
            revmap["3"] = tree.commit("third")

        return tree, revmap


def branch_scenarios():
    # Generate a list of branch formats and their associated bzrdir formats to
    # use.
    combinations = [
        (format, format._matchingcontroldir) for format in format_registry._get_all()
    ]
    scenarios = make_scenarios(
        # None here will cause the default vfs transport server to be used.
        None,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        combinations,
    )
    # Add RemoteBranch tests, which need a special server.
    remote_branch_format = RemoteBranchFormat()
    scenarios.extend(
        make_scenarios(
            test_server.SmartTCPServer_for_testing,
            test_server.ReadonlySmartTCPServer_for_testing,
            [(remote_branch_format, remote_branch_format._matchingcontroldir)],
            memory.MemoryServer,
            name_suffix="-default",
        )
    )
    # Also add tests for RemoteBranch with HPSS protocol v2 (i.e. bzr <1.6)
    # server.
    scenarios.extend(
        make_scenarios(
            test_server.SmartTCPServer_for_testing_v2_only,
            test_server.ReadonlySmartTCPServer_for_testing_v2_only,
            [(remote_branch_format, remote_branch_format._matchingcontroldir)],
            memory.MemoryServer,
            name_suffix="-v2",
        )
    )
    return scenarios


def load_tests(loader, standard_tests, pattern):
    per_branch_mod_names = [
        "branch",
        "break_lock",
        "check",
        "config",
        "create_checkout",
        "create_clone",
        "commit",
        "dotted_revno_to_revision_id",
        "get_rev_id",
        "get_revision_id_to_revno_map",
        "hooks",
        "http",
        "iter_merge_sorted_revisions",
        "last_revision_info",
        "locking",
        "parent",
        "permissions",
        "pull",
        "push",
        "reconcile",
        "revision_id_to_dotted_revno",
        "revision_id_to_revno",
        "sprout",
        "stacking",
        "tags",
        "uncommit",
        "update",
    ]
    sub_tests = loader.suiteClass()
    for name in per_branch_mod_names:
        sub_tests.addTest(
            loader.loadTestsFromName("breezy.tests.per_branch.test_" + name)
        )
    return tests.multiply_tests(sub_tests, branch_scenarios(), standard_tests)
