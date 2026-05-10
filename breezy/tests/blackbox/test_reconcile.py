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

from bzrformats import inventory

from breezy import controldir, tests
from breezy.repository import WriteGroup


class TrivialTest(tests.TestCaseWithTransport):
    def test_trivial_reconcile(self):
        t = controldir.ControlDir.create_standalone_workingtree(".")
        (out, err) = self.run_bzr("reconcile")
        if t.branch.repository._reconcile_backsup_inventory:
            does_backup_text = "Inventory ok.\n"
        else:
            does_backup_text = ""
        self.assertEqualDiff(
            out,
            f"Reconciling branch {t.branch.base}\n"
            "revision_history ok.\n"
            f"Reconciling repository {t.controldir.root_transport.base}\n"
            f"{does_backup_text}"
            "Reconciliation complete.\n",
        )
        self.assertEqualDiff(err, "")

    def test_does_something_reconcile(self):
        t = controldir.ControlDir.create_standalone_workingtree(".")
        # an empty inventory with no revision will trigger reconciliation.
        repo = t.branch.repository
        inv = inventory.Inventory(revision_id=b"missing")
        # bzrformats InventoryEntry attributes are read-only, so build
        # a fresh root with the desired revision and swap it in.
        root = inv.root
        inv.delete(root.file_id)
        inv.add(
            inventory.InventoryDirectory(
                file_id=root.file_id,
                name=root.name,
                parent_id=None,
                revision=b"missing",
            )
        )
        repo.lock_write()
        with repo.lock_write(), WriteGroup(repo):
            repo.add_inventory(b"missing", inv, [])
        (out, err) = self.run_bzr("reconcile")
        if repo._reconcile_backsup_inventory:
            does_backup_text = "Backup Inventory created.\nInventory regenerated.\n"
        else:
            does_backup_text = ""
        expected = (
            f"Reconciling branch {t.branch.base}\n"
            "revision_history ok.\n"
            f"Reconciling repository {t.controldir.root_transport.base}\n"
            f"{does_backup_text}"
            "Reconciliation complete.\n"
        )
        self.assertEqualDiff(expected, out)
        self.assertEqualDiff(err, "")
