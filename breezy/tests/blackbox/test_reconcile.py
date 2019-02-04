# Copyright (C) 2006 Canonical Ltd
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

"""Black box tests for the reconcile command."""


from breezy import (
    controldir,
    tests,
    )
from breezy.bzr import (
    inventory,
    )
from breezy.tests.matchers import ContainsNoVfsCalls


class TrivialTest(tests.TestCaseWithTransport):

    def test_trivial_reconcile(self):
        t = controldir.ControlDir.create_standalone_workingtree('.')
        (out, err) = self.run_bzr('reconcile')
        if t.branch.repository._reconcile_backsup_inventory:
            does_backup_text = "Inventory ok.\n"
        else:
            does_backup_text = ""
        self.assertEqualDiff(out, "Reconciling branch %s\n"
                                  "revision_history ok.\n"
                                  "Reconciling repository %s\n"
                                  "%s"
                                  "Reconciliation complete.\n" %
                                  (t.branch.base,
                                   t.controldir.root_transport.base,
                                   does_backup_text))
        self.assertEqualDiff(err, "")

    def test_does_something_reconcile(self):
        t = controldir.ControlDir.create_standalone_workingtree('.')
        # an empty inventory with no revision will trigger reconciliation.
        repo = t.branch.repository
        inv = inventory.Inventory(revision_id=b'missing')
        inv.root.revision = b'missing'
        repo.lock_write()
        repo.start_write_group()
        repo.add_inventory(b'missing', inv, [])
        repo.commit_write_group()
        repo.unlock()
        (out, err) = self.run_bzr('reconcile')
        if repo._reconcile_backsup_inventory:
            does_backup_text = (
                "Backup Inventory created.\n"
                "Inventory regenerated.\n")
        else:
            does_backup_text = ""
        expected = ("Reconciling branch %s\n"
                    "revision_history ok.\n"
                    "Reconciling repository %s\n"
                    "%s"
                    "Reconciliation complete.\n" %
                    (t.branch.base,
                     t.controldir.root_transport.base,
                     does_backup_text))
        self.assertEqualDiff(expected, out)
        self.assertEqualDiff(err, "")


class TestSmartServerReconcile(tests.TestCaseWithTransport):

    def test_simple_reconcile(self):
        self.setup_smart_server_with_call_log()
        self.make_branch('branch')
        self.reset_smart_call_log()
        out, err = self.run_bzr(['reconcile', self.get_url('branch')])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(10, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
