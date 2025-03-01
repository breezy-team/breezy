# Copyright (C) 2008, 2009, 2010, 2016 Canonical Ltd
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

"""Tests for the view command"""

from breezy.tests import TestCaseWithTransport


class TestViewUI(TestCaseWithTransport):
    def test_view_command_help(self):
        out, err = self.run_bzr("help view")
        self.assertContainsRe(out, "Manage filtered views")

    def test_define_view(self):
        wt = self.make_branch_and_tree(".")
        # Check definition of a new view
        out, err = self.run_bzr("view a b c")
        self.assertEqual(out, "Using 'my' view: a, b, c\n")
        out, err = self.run_bzr("view e f --name foo")
        self.assertEqual(out, "Using 'foo' view: e, f\n")
        # Check re-definition of an existing view
        out, err = self.run_bzr("view p q")
        self.assertEqual(out, "Using 'foo' view: p, q\n")
        out, err = self.run_bzr("view r s --name my")
        self.assertEqual(out, "Using 'my' view: r, s\n")
        # Check attempts to define the 'off' view are prevented
        out, err = self.run_bzr("view a --name off", retcode=3)
        self.assertContainsRe(err, "Cannot change the 'off' pseudo view")

    def test_list_view(self):
        wt = self.make_branch_and_tree(".")
        # Check list of the current view
        out, err = self.run_bzr("view")
        self.assertEqual(out, "No current view.\n")
        self.run_bzr("view a b c")
        out, err = self.run_bzr("view")
        self.assertEqual(out, "'my' view is: a, b, c\n")
        # Check list of a named view
        self.run_bzr("view e f --name foo")
        out, err = self.run_bzr("view --name my")
        self.assertEqual(out, "'my' view is: a, b, c\n")
        out, err = self.run_bzr("view --name foo")
        self.assertEqual(out, "'foo' view is: e, f\n")
        # Check list of all views
        out, err = self.run_bzr("view --all")
        self.assertEqual(
            out.splitlines(),
            [
                "Views defined:",
                "=> foo                  e, f",
                "   my                   a, b, c",
            ],
        )
        # Check list of an unknown view
        out, err = self.run_bzr("view --name bar", retcode=3)
        self.assertContainsRe(err, "No such view")

    def test_delete_view(self):
        wt = self.make_branch_and_tree(".")
        # Check delete of the current view
        out, err = self.run_bzr("view --delete", retcode=3)
        self.assertContainsRe(err, "No current view to delete")
        self.run_bzr("view a b c")
        out, err = self.run_bzr("view --delete")
        self.assertEqual(out, "Deleted 'my' view.\n")
        # Check delete of a named view
        self.run_bzr("view e f --name foo")
        out, err = self.run_bzr("view --name foo --delete")
        self.assertEqual(out, "Deleted 'foo' view.\n")
        # Check delete of all views
        out, err = self.run_bzr("view --delete --all")
        self.assertEqual(out, "Deleted all views.\n")
        # Check delete of an unknown view
        out, err = self.run_bzr("view --delete --name bar", retcode=3)
        self.assertContainsRe(err, "No such view")
        # Check bad usage is reported to the user
        out, err = self.run_bzr("view --delete --switch x", retcode=3)
        self.assertContainsRe(err, "Both --delete and --switch specified")
        out, err = self.run_bzr("view --delete a b c", retcode=3)
        self.assertContainsRe(err, "Both --delete and a file list specified")

    def test_switch_view(self):
        wt = self.make_branch_and_tree(".")
        # Check switching to a named view
        self.run_bzr("view a b c")
        self.run_bzr("view e f --name foo")
        out, err = self.run_bzr("view --switch my")
        self.assertEqual(out, "Using 'my' view: a, b, c\n")
        # Check switching off the current view does not delete it
        out, err = self.run_bzr("view --switch off")
        self.assertEqual(out, "Disabled 'my' view.\n")
        # Check error reporting when attempt to switch off again
        out, err = self.run_bzr("view --switch off", retcode=3)
        self.assertContainsRe(err, "No current view to disable")
        # Check bad usage is reported to the user
        out, err = self.run_bzr("view --switch x --all", retcode=3)
        self.assertContainsRe(err, "Both --switch and --all specified")
