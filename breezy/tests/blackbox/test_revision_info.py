# Copyright (C) 2005-2010, 2016 Canonical Ltd
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


from breezy.tests import TestCaseWithTransport


class TestRevisionInfo(TestCaseWithTransport):
    def check_output(self, output, *args):
        """Verify that the expected output matches what brz says.

        The output is supplied first, so that you can supply a variable
        number of arguments to bzr.
        """
        self.assertEqual(self.run_bzr(*args)[0], output)

    def test_revision_info(self):
        """Test that 'brz revision-info' reports the correct thing."""
        wt = self.make_branch_and_tree(".")

        # Make history with a non-mainline rev
        wt.commit("Commit one", rev_id=b"a@r-0-1")
        wt.commit("Commit two", rev_id=b"a@r-0-1.1.1")
        wt.set_parent_ids([b"a@r-0-1", b"a@r-0-1.1.1"])
        wt.branch.set_last_revision_info(1, b"a@r-0-1")
        wt.commit("Commit three", rev_id=b"a@r-0-2")

        # This is expected to work even if the working tree is removed
        wt.controldir.destroy_workingtree()

        # Expected return values
        values = {
            "1": "1 a@r-0-1\n",
            "1.1.1": "1.1.1 a@r-0-1.1.1\n",
            "2": "2 a@r-0-2\n",
        }

        # Make sure with no arg it defaults to the head
        self.check_output(values["2"], "revision-info")

        # Check the results of just specifying a numeric revision
        self.check_output(values["1"], "revision-info 1")
        self.check_output(values["1.1.1"], "revision-info 1.1.1")
        self.check_output(values["2"], "revision-info 2")
        self.check_output(values["1"] + values["2"], "revision-info 1 2")
        self.check_output(
            "    " + values["1"] + values["1.1.1"] + "    " + values["2"],
            "revision-info 1 1.1.1 2",
        )
        self.check_output(values["2"] + values["1"], "revision-info 2 1")

        # Check as above, only using the '--revision' syntax

        self.check_output(values["1"], "revision-info -r 1")
        self.check_output(values["1.1.1"], "revision-info --revision 1.1.1")
        self.check_output(values["2"], "revision-info -r 2")
        self.check_output(values["1"] + values["2"], "revision-info -r 1..2")
        self.check_output(
            "    " + values["1"] + values["1.1.1"] + "    " + values["2"],
            "revision-info -r 1..1.1.1..2",
        )
        self.check_output(values["2"] + values["1"], "revision-info -r 2..1")

        # Now try some more advanced revision specifications

        self.check_output(values["1"], "revision-info -r revid:a@r-0-1")
        self.check_output(values["1.1.1"], "revision-info --revision revid:a@r-0-1.1.1")

    def test_revision_info_explicit_branch_dir(self):
        """Test that 'brz revision-info' honors the '-d' option."""
        wt = self.make_branch_and_tree("branch")

        wt.commit("Commit one", rev_id=b"a@r-0-1")
        self.check_output("1 a@r-0-1\n", "revision-info -d branch")

    def test_revision_info_tree(self):
        # Make branch and checkout
        wt = self.make_branch_and_tree("branch")
        wt.commit("Commit one", rev_id=b"a@r-0-1")

        # Make checkout and move the branch forward
        wt.branch.create_checkout("checkout", lightweight=True)
        wt.commit("Commit two", rev_id=b"a@r-0-2")

        # Make sure the checkout gives the right answer for branch and
        # tree
        self.check_output("2 a@r-0-2\n", "revision-info -d checkout")
        self.check_output("1 a@r-0-1\n", "revision-info --tree -d checkout")

    def test_revision_info_tree_no_working_tree(self):
        # Make branch with no tree
        self.make_branch("branch")

        # Try getting the --tree revision-info
        out, err = self.run_bzr("revision-info --tree -d branch", retcode=3)
        self.assertEqual("", out)
        self.assertEqual('brz: ERROR: No WorkingTree exists for "branch".\n', err)

    def test_revision_info_not_in_history(self):
        builder = self.make_branch_builder("branch")
        builder.start_series()
        builder.build_snapshot(
            None, [("add", ("", b"root-id", "directory", None))], revision_id=b"A-id"
        )
        builder.build_snapshot([b"A-id"], [], revision_id=b"B-id")
        builder.build_snapshot([b"A-id"], [], revision_id=b"C-id")
        builder.finish_series()
        self.check_output(
            "  1 A-id\n??? B-id\n  2 C-id\n",
            "revision-info -d branch revid:A-id revid:B-id revid:C-id",
        )
