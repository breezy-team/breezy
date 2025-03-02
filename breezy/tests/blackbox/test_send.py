# Copyright (C) 2006-2012, 2016 Canonical Ltd
# Authors: Aaron Bentley
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

from io import BytesIO

from ... import branch, merge_directive, tests
from ...bzr.bundle import serializer
from ...controldir import ControlDir
from ...transport import memory
from .. import scenarios

load_tests = scenarios.load_tests_apply_scenarios


class TestSendMixin:
    _default_command = ["send", "-o-"]
    _default_wd = "branch"

    def run_send(self, args, cmd=None, rc=0, wd=None, err_re=None):
        if cmd is None:
            cmd = self._default_command
        if wd is None:
            wd = self._default_wd
        if err_re is None:
            err_re = []
        return self.run_bzr(
            cmd + args, retcode=rc, working_dir=wd, error_regexes=err_re
        )

    def get_MD(self, args, cmd=None, wd="branch"):
        md = self.run_send(args, cmd=cmd, wd=wd)[0]
        out = BytesIO(md.encode("utf-8"))
        return merge_directive.MergeDirective.from_lines(out)

    def assertBundleContains(self, revs, args, cmd=None, wd="branch"):
        md = self.get_MD(args, cmd=cmd, wd=wd)
        br = serializer.read_bundle(BytesIO(md.get_raw_bundle()))
        self.assertEqual(set(revs), {r.revision_id for r in br.revisions})


class TestSend(tests.TestCaseWithTransport, TestSendMixin):
    def setUp(self):
        super().setUp()
        grandparent_tree = ControlDir.create_standalone_workingtree("grandparent")
        self.build_tree_contents([("grandparent/file1", b"grandparent")])
        grandparent_tree.add("file1")
        grandparent_tree.commit("initial commit", rev_id=b"rev1")

        parent_bzrdir = grandparent_tree.controldir.sprout("parent")
        parent_tree = parent_bzrdir.open_workingtree()
        parent_tree.commit("next commit", rev_id=b"rev2")

        branch_tree = parent_tree.controldir.sprout("branch").open_workingtree()
        self.build_tree_contents([("branch/file1", b"branch")])
        branch_tree.commit("last commit", rev_id=b"rev3")

    def assertFormatIs(self, fmt_string, md):
        self.assertEqual(fmt_string, md.get_raw_bundle().splitlines()[0])

    def test_uses_parent(self):
        """Parent location is used as a basis by default."""
        errmsg = self.run_send([], rc=3, wd="grandparent")[1]
        self.assertContainsRe(errmsg, "No submit branch known or specified")
        stdout, stderr = self.run_send([])
        self.assertEqual(stderr.count("Using saved parent location"), 1)
        self.assertBundleContains([b"rev3"], [])

    def test_bundle(self):
        """Bundle works like send, except -o is not required."""
        errmsg = self.run_send([], cmd=["bundle"], rc=3, wd="grandparent")[1]
        self.assertContainsRe(errmsg, "No submit branch known or specified")
        stdout, stderr = self.run_send([], cmd=["bundle"])
        self.assertEqual(stderr.count("Using saved parent location"), 1)
        self.assertBundleContains([b"rev3"], [], cmd=["bundle"])

    def test_uses_submit(self):
        """Submit location can be used and set."""
        self.assertBundleContains([b"rev3"], [])
        self.assertBundleContains([b"rev3", b"rev2"], ["../grandparent"])
        # submit location should be auto-remembered
        self.assertBundleContains([b"rev3", b"rev2"], [])

        self.run_send(["../parent"])
        # We still point to ../grandparent
        self.assertBundleContains([b"rev3", b"rev2"], [])
        # Remember parent now
        self.run_send(["../parent", "--remember"])
        # Now we point to parent
        self.assertBundleContains([b"rev3"], [])

        err = self.run_send(["--remember"], rc=3)[1]
        self.assertContainsRe(err, "--remember requires a branch to be specified.")

    def test_revision_branch_interaction(self):
        self.assertBundleContains([b"rev3", b"rev2"], ["../grandparent"])
        self.assertBundleContains([b"rev2"], ["../grandparent", "-r-2"])
        self.assertBundleContains([b"rev3", b"rev2"], ["../grandparent", "-r-2..-1"])
        md = self.get_MD(["-r-2..-1"])
        self.assertEqual(b"rev2", md.base_revision_id)
        self.assertEqual(b"rev3", md.revision_id)

    def test_output(self):
        # check output for consistency
        # win32 stdout converts LF to CRLF,
        # which would break patch-based bundles
        self.assertBundleContains([b"rev3"], [])

    def test_no_common_ancestor(self):
        foo = self.make_branch_and_tree("foo")
        foo.commit("rev a")
        bar = self.make_branch_and_tree("bar")
        bar.commit("rev b")
        self.run_send(["--from", "foo", "../bar"], wd="foo")

    def test_content_options(self):
        """--no-patch and --no-bundle should work and be independant."""
        md = self.get_MD([])
        self.assertIsNot(None, md.bundle)
        self.assertIsNot(None, md.patch)

        md = self.get_MD(["--format=0.9"])
        self.assertIsNot(None, md.bundle)
        self.assertIsNot(None, md.patch)

        md = self.get_MD(["--no-patch"])
        self.assertIsNot(None, md.bundle)
        self.assertIs(None, md.patch)
        self.run_bzr_error(
            ["Format 0.9 does not permit bundle with no patch"],
            ["send", "--no-patch", "--format=0.9", "-o-"],
            working_dir="branch",
        )
        md = self.get_MD(["--no-bundle", ".", "."])
        self.assertIs(None, md.bundle)
        self.assertIsNot(None, md.patch)

        md = self.get_MD(["--no-bundle", "--format=0.9", "../parent", "."])
        self.assertIs(None, md.bundle)
        self.assertIsNot(None, md.patch)

        md = self.get_MD(["--no-bundle", "--no-patch", ".", "."])
        self.assertIs(None, md.bundle)
        self.assertIs(None, md.patch)

        md = self.get_MD(
            ["--no-bundle", "--no-patch", "--format=0.9", "../parent", "."]
        )
        self.assertIs(None, md.bundle)
        self.assertIs(None, md.patch)

    def test_from_option(self):
        self.run_bzr("send", retcode=3)
        md = self.get_MD(["--from", "branch"])
        self.assertEqual(b"rev3", md.revision_id)
        md = self.get_MD(["-f", "branch"])
        self.assertEqual(b"rev3", md.revision_id)

    def test_output_option(self):
        stdout = self.run_bzr("send -f branch --output file1")[0]
        self.assertEqual("", stdout)
        md_file = open("file1", "rb")
        self.addCleanup(md_file.close)
        self.assertContainsRe(md_file.read(), b"rev3")
        stdout = self.run_bzr("send -f branch --output -")[0]
        self.assertContainsRe(stdout, "rev3")

    def test_note_revisions(self):
        stderr = self.run_send([])[1]
        self.assertEndsWith(stderr, "\nBundling 1 revision.\n")

    def test_mailto_option(self):
        b = branch.Branch.open("branch")
        b.get_config_stack().set("mail_client", "editor")
        self.run_bzr_error(
            ("No mail-to address \\(--mail-to\\) or output \\(-o\\) specified",),
            "send -f branch",
        )
        b.get_config_stack().set("mail_client", "bogus")
        self.run_send([])
        self.run_bzr_error(
            ('Bad value "bogus" for option "mail_client"',),
            "send -f branch --mail-to jrandom@example.org",
        )
        b.get_config_stack().set("submit_to", "jrandom@example.org")
        self.run_bzr_error(
            ('Bad value "bogus" for option "mail_client"',), "send -f branch"
        )

    def test_mailto_child_option(self):
        """Make sure that child_submit_to is used."""
        b = branch.Branch.open("branch")
        b.get_config_stack().set("mail_client", "bogus")
        parent = branch.Branch.open("parent")
        parent.get_config_stack().set("child_submit_to", "somebody@example.org")
        self.run_bzr_error(
            ('Bad value "bogus" for option "mail_client"',), "send -f branch"
        )

    def test_format(self):
        md = self.get_MD(["--format=4"])
        self.assertIs(merge_directive.MergeDirective2, md.__class__)
        self.assertFormatIs(b"# Bazaar revision bundle v4", md)

        md = self.get_MD(["--format=0.9"])
        self.assertFormatIs(b"# Bazaar revision bundle v0.9", md)

        md = self.get_MD(["--format=0.9"], cmd=["bundle"])
        self.assertFormatIs(b"# Bazaar revision bundle v0.9", md)
        self.assertIs(merge_directive.MergeDirective, md.__class__)

        self.run_bzr_error(
            ["Bad value .* for option .format."], "send -f branch -o- --format=0.999"
        )[0]

    def test_format_child_option(self):
        br = branch.Branch.open("parent")
        conf = br.get_config_stack()
        conf.set("child_submit_format", "4")
        md = self.get_MD([])
        self.assertIs(merge_directive.MergeDirective2, md.__class__)

        conf.set("child_submit_format", "0.9")
        md = self.get_MD([])
        self.assertFormatIs(b"# Bazaar revision bundle v0.9", md)

        md = self.get_MD([], cmd=["bundle"])
        self.assertFormatIs(b"# Bazaar revision bundle v0.9", md)
        self.assertIs(merge_directive.MergeDirective, md.__class__)

        conf.set("child_submit_format", "0.999")
        self.run_bzr_error(["No such send format '0.999'"], "send -f branch -o-")[0]

    def test_message_option(self):
        self.run_bzr("send", retcode=3)
        md = self.get_MD([])
        self.assertIs(None, md.message)
        md = self.get_MD(["-m", "my message"])
        self.assertEqual("my message", md.message)

    def test_omitted_revision(self):
        md = self.get_MD(["-r-2.."])
        self.assertEqual(b"rev2", md.base_revision_id)
        self.assertEqual(b"rev3", md.revision_id)
        md = self.get_MD(["-r..3", "--from", "branch", "grandparent"], wd=".")
        self.assertEqual(b"rev1", md.base_revision_id)
        self.assertEqual(b"rev3", md.revision_id)

    def test_nonexistant_branch(self):
        self.vfs_transport_factory = memory.MemoryServer
        location = self.get_url("absentdir/")
        out, err = self.run_bzr(["send", "--from", location], retcode=3)
        self.assertEqual(out, "")
        self.assertEqual(err, 'brz: ERROR: Not a branch: "{}".\n'.format(location))


class TestSendStrictMixin(TestSendMixin):
    def make_parent_and_local_branches(self):
        # Create a 'parent' branch as the base
        self.parent_tree = ControlDir.create_standalone_workingtree("parent")
        self.build_tree_contents([("parent/file", b"parent")])
        self.parent_tree.add("file")
        parent = self.parent_tree.commit("first commit")
        # Branch 'local' from parent and do a change
        local_bzrdir = self.parent_tree.controldir.sprout("local")
        self.local_tree = local_bzrdir.open_workingtree()
        self.build_tree_contents([("local/file", b"local")])
        local = self.local_tree.commit("second commit")
        return parent, local

    _default_command = ["send", "-o-", "../parent"]
    _default_wd = "local"
    _default_sent_revs = None
    _default_errors = [
        'Working tree ".*/local/" has uncommitted changes \\(See brz status\\)\\.',
    ]
    _default_additional_error = "Use --no-strict to force the send.\n"
    _default_additional_warning = "Uncommitted changes will not be sent."

    def set_config_send_strict(self, value):
        br = branch.Branch.open("local")
        br.get_config_stack().set("send_strict", value)

    def assertSendFails(self, args):
        out, err = self.run_send(args, rc=3, err_re=self._default_errors)
        self.assertContainsRe(err, self._default_additional_error)

    def assertSendSucceeds(self, args, revs=None, with_warning=False):
        if with_warning:
            err_re = self._default_errors
        else:
            err_re = []
        if revs is None:
            revs = self._default_sent_revs or [self.local]
        out, err = self.run_send(args, err_re=err_re)
        if len(revs) == 1:
            bundling_revs = f"Bundling {len(revs)} revision.\n"
        else:
            bundling_revs = f"Bundling {len(revs)} revisions.\n"
        if with_warning:
            self.assertContainsRe(err, self._default_additional_warning)
            self.assertEndsWith(err, bundling_revs)
        else:
            self.assertEqual(bundling_revs, err)
        md = merge_directive.MergeDirective.from_lines(BytesIO(out.encode("utf-8")))
        self.assertEqual(self.parent, md.base_revision_id)
        br = serializer.read_bundle(BytesIO(md.get_raw_bundle()))
        self.assertEqual(set(revs), {r.revision_id for r in br.revisions})


class TestSendStrictWithoutChanges(tests.TestCaseWithTransport, TestSendStrictMixin):
    def setUp(self):
        super().setUp()
        self.parent, self.local = self.make_parent_and_local_branches()

    def test_send_without_workingtree(self):
        ControlDir.open("local").destroy_workingtree()
        self.assertSendSucceeds([])

    def test_send_default(self):
        self.assertSendSucceeds([])

    def test_send_strict(self):
        self.assertSendSucceeds(["--strict"])

    def test_send_no_strict(self):
        self.assertSendSucceeds(["--no-strict"])

    def test_send_config_var_strict(self):
        self.set_config_send_strict("true")
        self.assertSendSucceeds([])

    def test_send_config_var_no_strict(self):
        self.set_config_send_strict("false")
        self.assertSendSucceeds([])


class TestSendStrictWithChanges(tests.TestCaseWithTransport, TestSendStrictMixin):
    # These are textually the same as test_push.strict_push_change_scenarios,
    # but since the functions are reimplemented here, the definitions are left
    # here too.
    scenarios = [
        ("uncommitted", {"_changes_type": "_uncommitted_changes"}),
        ("pending_merges", {"_changes_type": "_pending_merges"}),
        ("out-of-sync-trees", {"_changes_type": "_out_of_sync_trees"}),
    ]

    _changes_type = None  # Set by load_tests

    def setUp(self):
        super().setUp()
        # load tests set _changes_types to the name of the method we want to
        # call now
        do_changes_func = getattr(self, self._changes_type)
        do_changes_func()

    def _uncommitted_changes(self):
        self.parent, self.local = self.make_parent_and_local_branches()
        # Make a change without committing it
        self.build_tree_contents([("local/file", b"modified")])

    def _pending_merges(self):
        self.parent, self.local = self.make_parent_and_local_branches()
        # Create 'other' branch containing a new file
        other_bzrdir = self.parent_tree.controldir.sprout("other")
        other_tree = other_bzrdir.open_workingtree()
        self.build_tree_contents([("other/other-file", b"other")])
        other_tree.add("other-file")
        other_tree.commit("other commit", rev_id=b"other")
        # Merge and revert, leaving a pending merge
        self.local_tree.merge_from_branch(other_tree.branch)
        self.local_tree.revert(filenames=["other-file"], backups=False)

    def _out_of_sync_trees(self):
        self.parent, self.local = self.make_parent_and_local_branches()
        self.run_bzr(["checkout", "--lightweight", "local", "checkout"])
        # Make a change and commit it
        self.build_tree_contents([("local/file", b"modified in local")])
        self.local_tree.commit("modify file", rev_id=b"modified-in-local")
        # Exercise commands from the checkout directory
        self._default_wd = "checkout"
        self._default_errors = [
            "Working tree is out of date, please run 'brz update'\\.",
        ]
        self._default_sent_revs = [b"modified-in-local", self.local]

    def test_send_default(self):
        self.assertSendSucceeds([], with_warning=True)

    def test_send_with_revision(self):
        self.assertSendSucceeds(
            ["-r", "revid:" + self.local.decode("utf-8")], revs=[self.local]
        )

    def test_send_no_strict(self):
        self.assertSendSucceeds(["--no-strict"])

    def test_send_strict_with_changes(self):
        self.assertSendFails(["--strict"])

    def test_send_respect_config_var_strict(self):
        self.set_config_send_strict("true")
        self.assertSendFails([])
        self.assertSendSucceeds(["--no-strict"])

    def test_send_bogus_config_var_ignored(self):
        self.set_config_send_strict("I'm unsure")
        self.assertSendSucceeds([], with_warning=True)

    def test_send_no_strict_command_line_override_config(self):
        self.set_config_send_strict("true")
        self.assertSendFails([])
        self.assertSendSucceeds(["--no-strict"])

    def test_send_strict_command_line_override_config(self):
        self.set_config_send_strict("false")
        self.assertSendSucceeds([])
        self.assertSendFails(["--strict"])


class TestBundleStrictWithoutChanges(TestSendStrictWithoutChanges):
    _default_command = ["bundle-revisions", "../parent"]
