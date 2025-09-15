# Copyright (C) 2007, 2009-2012 Canonical Ltd
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

import os
import smtplib

from breezy import gpg, merge_directive, tests, workingtree

EMAIL1 = """From: "J. Random Hacker" <jrandom@example.com>
Subject: bar
To: pqm@example.com
User-Agent: Bazaar \\(.*\\)

# Bazaar merge directive format 2 \\(Bazaar 0.90\\)
# revision_id: bar-id
# target_branch: ../tree2
# testament_sha1: .*
# timestamp: .*
# source_branch: .
#"""


class TestMergeDirective(tests.TestCaseWithTransport):
    def prepare_merge_directive(self):
        self.tree1 = self.make_branch_and_tree("tree1")
        self.build_tree_contents([("tree1/file", b"a\nb\nc\nd\n")])
        self.tree1.branch.get_config_stack().set(
            "email", "J. Random Hacker <jrandom@example.com>"
        )
        self.tree1.add("file")
        self.tree1.commit("foo", rev_id=b"foo-id")
        self.tree2 = self.tree1.controldir.sprout("tree2").open_workingtree()
        self.build_tree_contents([("tree1/file", b"a\nb\nc\nd\ne\n")])
        self.tree1.commit("bar", rev_id=b"bar-id")
        os.chdir("tree1")
        return self.tree1, self.tree2

    def test_merge_directive(self):
        self.prepare_merge_directive()
        md_text = self.run_bzr("merge-directive ../tree2")[0]
        self.assertContainsRe(md_text, "\\+e")
        md_text = self.run_bzr("merge-directive -r -2 ../tree2")[0]
        self.assertNotContainsRe(md_text, "\\+e")
        md_text = self.run_bzr("merge-directive -r -1..-2 ../tree2")[0].encode("utf-8")
        md2 = merge_directive.MergeDirective.from_lines(md_text.splitlines(True))
        self.assertEqual(b"foo-id", md2.revision_id)
        self.assertEqual(b"bar-id", md2.base_revision_id)

    def test_submit_branch(self):
        self.prepare_merge_directive()
        self.run_bzr_error(("No submit branch",), "merge-directive", retcode=3)
        self.run_bzr("merge-directive ../tree2")

    def test_public_branch(self):
        self.prepare_merge_directive()
        self.run_bzr_error(
            ("No public branch",), "merge-directive --diff ../tree2", retcode=3
        )
        md_text = self.run_bzr("merge-directive ../tree2")[0]
        self.assertNotContainsRe(md_text, "source_branch:")
        self.run_bzr("merge-directive --diff ../tree2 .")
        self.run_bzr("merge-directive --diff")[0]
        self.assertNotContainsRe(md_text, "source_branch:")

    def test_patch_types(self):
        self.prepare_merge_directive()
        md_text = self.run_bzr("merge-directive ../tree2")[0]
        self.assertContainsRe(md_text, "# Begin bundle")
        self.assertContainsRe(md_text, "\\+e")
        md_text = self.run_bzr("merge-directive ../tree2 --diff .")[0]
        self.assertNotContainsRe(md_text, "# Begin bundle")
        self.assertContainsRe(md_text, "\\+e")
        md_text = self.run_bzr("merge-directive --plain")[0]
        self.assertNotContainsRe(md_text, "\\+e")

    def test_message(self):
        self.prepare_merge_directive()
        md_text = self.run_bzr("merge-directive ../tree2")[0]
        self.assertNotContainsRe(md_text, "message: Message for merge")
        md_text = self.run_bzr("merge-directive -m Message_for_merge")[0]
        self.assertContainsRe(md_text, "message: Message_for_merge")

    def test_signing(self):
        self.prepare_merge_directive()
        old_strategy = gpg.GPGStrategy
        gpg.GPGStrategy = gpg.LoopbackGPGStrategy
        try:
            md_text = self.run_bzr("merge-directive --sign ../tree2")[0]
        finally:
            gpg.GPGStrategy = old_strategy
        self.assertContainsRe(md_text, "^-----BEGIN PSEUDO-SIGNED CONTENT")

    def run_bzr_fakemail(self, *args, **kwargs):
        sendmail_calls = []

        def sendmail(self, from_, to, message):
            sendmail_calls.append((self, from_, to, message))

        connect_calls = []

        def connect(self, host="localhost", port=0):
            connect_calls.append((self, host, port))
            return (220, "Ok")

        def has_extn(self, extension):
            return False

        def ehlo(self):
            return (200, "Ok")

        old_sendmail = smtplib.SMTP.sendmail
        smtplib.SMTP.sendmail = sendmail
        old_connect = smtplib.SMTP.connect
        smtplib.SMTP.connect = connect
        old_ehlo = smtplib.SMTP.ehlo
        smtplib.SMTP.ehlo = ehlo
        old_has_extn = smtplib.SMTP.has_extn
        smtplib.SMTP.has_extn = has_extn
        try:
            result = self.run_bzr(*args, **kwargs)
        finally:
            smtplib.SMTP.sendmail = old_sendmail
            smtplib.SMTP.connect = old_connect
            smtplib.SMTP.ehlo = old_ehlo
            smtplib.SMTP.has_extn = old_has_extn
        return result + (connect_calls, sendmail_calls)

    def test_mail_default(self):
        _tree1, _tree2 = self.prepare_merge_directive()
        md_text, _errr, connect_calls, sendmail_calls = self.run_bzr_fakemail(
            [
                "merge-directive",
                "--mail-to",
                "pqm@example.com",
                "--plain",
                "../tree2",
                ".",
            ]
        )
        self.assertEqual("", md_text)
        self.assertEqual(1, len(connect_calls))
        call = connect_calls[0]
        self.assertEqual(("localhost", 0), call[1:3])
        self.assertEqual(1, len(sendmail_calls))
        call = sendmail_calls[0]
        self.assertEqual(("jrandom@example.com", ["pqm@example.com"]), call[1:3])
        self.assertContainsRe(call[3], EMAIL1)

    def test_pull_raw(self):
        self.prepare_merge_directive()
        self.tree1.commit("baz", rev_id=b"baz-id")
        md_text = self.run_bzr(
            [
                "merge-directive",
                self.tree2.basedir,
                "-r",
                "2",
                self.tree1.basedir,
                "--plain",
            ]
        )[0]
        self.build_tree_contents([("../directive", md_text)])
        os.chdir("../tree2")
        self.run_bzr("pull ../directive")
        wt = workingtree.WorkingTree.open(".")
        self.assertEqual(b"bar-id", wt.last_revision())

    def test_pull_user_r(self):
        """If the user supplies -r, an error is emitted."""
        self.prepare_merge_directive()
        self.tree1.commit("baz", rev_id=b"baz-id")
        md_text = self.run_bzr(
            ["merge-directive", self.tree2.basedir, self.tree1.basedir, "--plain"]
        )[0]
        self.build_tree_contents([("../directive", md_text)])
        os.chdir("../tree2")
        self.run_bzr_error(
            ("Cannot use -r with merge directives or bundles",),
            "pull -r 2 ../directive",
        )

    def test_pull_bundle(self):
        self.prepare_merge_directive()
        self.tree1.commit("baz", rev_id=b"baz-id")
        md_text = self.run_bzr(
            ["merge-directive", self.tree2.basedir, "-r", "2", "/dev/null", "--bundle"]
        )[0]
        self.build_tree_contents([("../directive", md_text)])
        os.chdir("../tree2")
        self.run_bzr("pull ../directive")
        wt = workingtree.WorkingTree.open(".")
        self.assertEqual(b"bar-id", wt.last_revision())

    def test_merge_raw(self):
        self.prepare_merge_directive()
        self.tree1.commit("baz", rev_id=b"baz-id")
        md_text = self.run_bzr(
            [
                "merge-directive",
                self.tree2.basedir,
                "-r",
                "2",
                self.tree1.basedir,
                "--plain",
            ]
        )[0]
        self.build_tree_contents([("../directive", md_text)])
        os.chdir("../tree2")
        self.run_bzr("merge ../directive")
        wt = workingtree.WorkingTree.open(".")
        self.assertEqual(b"bar-id", wt.get_parent_ids()[1])

    def test_merge_user_r(self):
        """If the user supplies -r, an error is emitted."""
        self.prepare_merge_directive()
        self.tree1.commit("baz", rev_id=b"baz-id")
        md_text = self.run_bzr(
            ["merge-directive", self.tree2.basedir, self.tree1.basedir, "--plain"]
        )[0]
        self.build_tree_contents([("../directive", md_text)])
        os.chdir("../tree2")
        self.run_bzr_error(
            ("Cannot use -r with merge directives or bundles",),
            "merge -r 2 ../directive",
        )

    def test_merge_bundle(self):
        self.prepare_merge_directive()
        self.tree1.commit("baz", rev_id=b"baz-id")
        md_text = self.run_bzr(
            ["merge-directive", self.tree2.basedir, "-r", "2", "/dev/null", "--bundle"]
        )[0]
        self.build_tree_contents([("../directive", md_text)])
        os.chdir("../tree2")
        self.run_bzr("merge ../directive")
        wt = workingtree.WorkingTree.open(".")
        self.assertEqual(b"bar-id", wt.get_parent_ids()[1])

    def test_mail_uses_config(self):
        tree1, _tree2 = self.prepare_merge_directive()
        br = tree1.branch
        br.get_config_stack().set("smtp_server", "bogushost")
        _md_text, _errr, connect_calls, _sendmail_calls = self.run_bzr_fakemail(
            "merge-directive --mail-to pqm@example.com --plain ../tree2 ."
        )
        call = connect_calls[0]
        self.assertEqual(("bogushost", 0), call[1:3])

    def test_no_common_ancestor(self):
        foo = self.make_branch_and_tree("foo")
        foo.commit("rev1")
        self.make_branch_and_tree("bar")
        self.run_bzr("merge-directive ../bar", working_dir="foo")

    def test_no_commits(self):
        self.make_branch_and_tree("foo")
        self.make_branch_and_tree("bar")
        self.run_bzr_error(
            ("No revisions to bundle.",), "merge-directive ../bar", working_dir="foo"
        )

    def test_encoding_exact(self):
        tree1, _tree2 = self.prepare_merge_directive()
        tree1.commit("messag\xe9")
        self.run_bzr("merge-directive ../tree2")  # no exception raised

    def test_merge_directive_directory(self):
        """Test --directory option."""
        import re

        re_timestamp = re.compile(r"^# timestamp: .*", re.M)
        self.prepare_merge_directive()
        md1 = self.run_bzr("merge-directive ../tree2")[0]
        md1 = re_timestamp.sub("# timestamp: XXX", md1)
        os.chdir("..")
        md2 = self.run_bzr("merge-directive --directory tree1 tree2")[0]
        md2 = re_timestamp.sub("# timestamp: XXX", md2)
        self.assertEqualDiff(md1.replace("../tree2", "tree2"), md2)
