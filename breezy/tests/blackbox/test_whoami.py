# Copyright (C) 2006, 2007, 2009-2012, 2016 Canonical Ltd
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


"""Black-box tests for brz whoami."""

from breezy import branch, config, errors, tests

from ..test_bedding import override_whoami


class TestWhoami(tests.TestCaseWithTransport):
    def assertWhoAmI(self, expected, *cmd_args, **kwargs):
        out, err = self.run_bzr(("whoami",) + cmd_args, **kwargs)
        self.assertEqual("", err)
        lines = out.splitlines()
        self.assertLength(1, lines)
        if isinstance(expected, bytes):
            expected = expected.decode(kwargs.get("encoding", "ascii"))
        self.assertEqual(expected, lines[0].rstrip())

    def test_whoami_no_args_no_conf(self):
        # this should always identify something, if only "john@localhost"
        out = self.run_bzr("whoami")[0]
        self.assertTrue(len(out) > 0)
        self.assertEqual(1, out.count("@"))

    def test_whoami_email_no_args(self):
        out = self.run_bzr("whoami --email")[0]
        self.assertTrue(len(out) > 0)
        self.assertEqual(1, out.count("@"))

    def test_whoami_email_arg(self):
        # whoami --email is mutually exclusive with any arguments
        out = self.run_bzr("whoami --email 'foo <foo@example.com>'", 3)[0]
        self.assertEqual("", out)

    def set_branch_email(self, b, email):
        b.get_config_stack().set("email", email)

    def test_whoami_branch(self):
        """Branch specific user identity works."""
        self.make_branch_and_tree(".")
        b = branch.Branch.open(".")
        self.set_branch_email(b, "Branch Identity <branch@identi.ty>")
        self.assertWhoAmI("Branch Identity <branch@identi.ty>")
        self.assertWhoAmI("branch@identi.ty", "--email")

        # Verify that the environment variable overrides the value
        # in the file
        self.overrideEnv("BRZ_EMAIL", "Different ID <other@environ.ment>")
        self.assertWhoAmI("Different ID <other@environ.ment>")
        self.assertWhoAmI("other@environ.ment", "--email")

    def test_whoami_utf8(self):
        """Verify that an identity can be in utf-8."""
        self.run_bzr(
            ["whoami", "Branch Identity \u20ac <branch@identi.ty>"], encoding="utf-8"
        )
        self.assertWhoAmI(
            b"Branch Identity \xe2\x82\xac <branch@identi.ty>", encoding="utf-8"
        )
        self.assertWhoAmI("branch@identi.ty", "--email")

    def test_whoami_ascii(self):
        """Verify that whoami doesn't totally break when in utf-8, using an ascii
        encoding.
        """
        self.make_branch_and_tree(".")
        b = branch.Branch.open(".")
        self.set_branch_email(b, "Branch Identity \u20ac <branch@identi.ty>")
        self.assertWhoAmI("Branch Identity ? <branch@identi.ty>", encoding="ascii")
        self.assertWhoAmI("branch@identi.ty", "--email", encoding="ascii")

    def test_warning(self):
        """Verify that a warning is displayed if no email is given."""
        self.make_branch_and_tree(".")
        display = self.run_bzr(["whoami", "Branch Identity"])[1]
        self.assertEqual(
            '"Branch Identity" does not seem to contain an '
            "email address.  This is allowed, but not "
            "recommended.\n",
            display,
        )

    def test_whoami_not_set(self):
        """Ensure whoami error if username is not set and not inferred."""
        override_whoami(self)
        _out, err = self.run_bzr(["whoami"], 3)
        self.assertContainsRe(err, "Unable to determine your name")

    def test_whoami_directory(self):
        """Test --directory option."""
        wt = self.make_branch_and_tree("subdir")
        self.set_branch_email(wt.branch, "Branch Identity <branch@identi.ty>")
        self.assertWhoAmI("Branch Identity <branch@identi.ty>", "--directory", "subdir")
        self.run_bzr(
            [
                "whoami",
                "--directory",
                "subdir",
                "--branch",
                "Changed Identity <changed@identi.ty>",
            ]
        )
        # Refresh wt as 'whoami' modified it
        wt = wt.controldir.open_workingtree()
        c = wt.branch.get_config_stack()
        self.assertEqual("Changed Identity <changed@identi.ty>", c.get("email"))

    def test_whoami_remote_directory(self):
        """Test --directory option with a remote directory."""
        wt = self.make_branch_and_tree("subdir")
        self.set_branch_email(wt.branch, "Branch Identity <branch@identi.ty>")
        url = self.get_readonly_url() + "/subdir"
        self.assertWhoAmI("Branch Identity <branch@identi.ty>", "--directory", url)
        url = self.get_url("subdir")
        self.run_bzr(
            [
                "whoami",
                "--directory",
                url,
                "--branch",
                "Changed Identity <changed@identi.ty>",
            ]
        )
        # The identity has been set in the branch config (but not the global
        # config)
        c = branch.Branch.open(url).get_config_stack()
        self.assertEqual("Changed Identity <changed@identi.ty>", c.get("email"))
        # Ensuring that the value does not come from the breezy.conf file
        # itself requires some isolation setup
        override_whoami(self)
        global_conf = config.GlobalStack()
        self.assertRaises(errors.NoWhoami, global_conf.get, "email")

    def test_whoami_nonbranch_directory(self):
        """Test --directory mentioning a non-branch directory."""
        self.build_tree(["subdir/"])
        _out, err = self.run_bzr("whoami --directory subdir", retcode=3)
        self.assertContainsRe(err, "ERROR: Not a branch")
