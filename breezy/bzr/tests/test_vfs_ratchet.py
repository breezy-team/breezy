# Copyright (C) 2006-2012, 2016 Canonical Ltd
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


"""Tests to verify that blackbox commands don't use more VFS calls."""

from ... import branch, gpg
from ...tests import fixtures
from . import TestCaseWithTransport
from .matchers import ContainsNoVfsCalls


class TestSmartServerCommit(TestCaseWithTransport):
    def test_commit_to_lightweight(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        for count in range(9):
            t.commit(message="commit %d" % count)
        out, err = self.run_bzr(
            ["checkout", "--lightweight", self.get_url("from"), "target"]
        )
        self.reset_smart_call_log()
        self.build_tree(["target/afile"])
        self.run_bzr(["add", "target/afile"])
        out, err = self.run_bzr(["commit", "-m", "do something", "target"])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(211, self.hpss_calls)
        self.assertLength(2, self.hpss_connections)
        self.expectFailure(
            "commit still uses VFS calls",
            self.assertThat,
            self.hpss_calls,
            ContainsNoVfsCalls,
        )


class TestSmartServerAnnotate(TestCaseWithTransport):
    def test_simple_annotate(self):
        self.setup_smart_server_with_call_log()
        wt = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/hello.txt", b"my helicopter\n")])
        wt.add(["hello.txt"])
        wt.commit("commit", committer="test@user")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["annotate", "-d", self.get_url("branch"), "hello.txt"])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(9, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerBranching(TestCaseWithTransport):
    def test_branch_from_trivial_branch_to_same_server_branch_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        for count in range(9):
            t.commit(message="commit %d" % count)
        self.reset_smart_call_log()
        out, err = self.run_bzr(
            ["branch", self.get_url("from"), self.get_url("target")]
        )
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(2, self.hpss_connections)
        self.assertLength(34, self.hpss_calls)
        self.expectFailure(
            "branching to the same branch requires VFS access",
            self.assertThat,
            self.hpss_calls,
            ContainsNoVfsCalls,
        )

    def test_branch_from_trivial_branch_streaming_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        for count in range(9):
            t.commit(message="commit %d" % count)
        self.reset_smart_call_log()
        out, err = self.run_bzr(["branch", self.get_url("from"), "local-target"])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
        self.assertLength(11, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)

    def test_branch_from_trivial_stacked_branch_streaming_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("trunk")
        for count in range(8):
            t.commit(message="commit %d" % count)
        tree2 = t.branch.controldir.sprout("feature", stacked=True).open_workingtree()
        local_tree = t.branch.controldir.sprout("local-working").open_workingtree()
        local_tree.commit("feature change")
        local_tree.branch.push(tree2.branch)
        self.reset_smart_call_log()
        out, err = self.run_bzr(["branch", self.get_url("feature"), "local-target"])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(16, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)

    def test_branch_from_branch_with_tags(self):
        self.setup_smart_server_with_call_log()
        builder = self.make_branch_builder("source")
        source, rev1, rev2 = fixtures.build_branch_with_non_ancestral_rev(builder)
        source.get_config_stack().set("branch.fetch_tags", True)
        source.tags.set_tag("tag-a", rev2)
        source.tags.set_tag("tag-missing", b"missing-rev")
        # Now source has a tag not in its ancestry.  Make a branch from it.
        self.reset_smart_call_log()
        out, err = self.run_bzr(["branch", self.get_url("source"), "target"])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(11, self.hpss_calls)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
        self.assertLength(1, self.hpss_connections)

    def test_branch_to_stacked_from_trivial_branch_streaming_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        for count in range(9):
            t.commit(message="commit %d" % count)
        self.reset_smart_call_log()
        out, err = self.run_bzr(
            ["branch", "--stacked", self.get_url("from"), "local-target"]
        )
        # XXX: the number of hpss calls for this case isn't deterministic yet,
        # so we can't easily assert about the number of calls.
        # self.assertLength(XXX, self.hpss_calls)
        # We can assert that none of the calls were readv requests for rix
        # files, though (demonstrating that at least get_parent_map calls are
        # not using VFS RPCs).
        readvs_of_rix_files = [
            c
            for c in self.hpss_calls
            if c.call.method == "readv" and c.call.args[-1].endswith(".rix")
        ]
        self.assertLength(1, self.hpss_connections)
        self.assertLength(0, readvs_of_rix_files)
        self.expectFailure(
            "branching to stacked requires VFS access",
            self.assertThat,
            self.hpss_calls,
            ContainsNoVfsCalls,
        )

    def test_branch_from_branch_with_ghosts(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        for count in range(9):
            t.commit(message="commit %d" % count)
        t.set_parent_ids([t.last_revision(), b"ghost"])
        t.commit(message="add commit with parent")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["branch", self.get_url("from"), "local-target"])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
        self.assertLength(12, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)


class TestSmartServerBreakLock(TestCaseWithTransport):
    def test_simple_branch_break_lock(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        t.branch.lock_write()
        self.reset_smart_call_log()
        out, err = self.run_bzr(["break-lock", "--force", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
        self.assertLength(1, self.hpss_connections)
        self.assertLength(5, self.hpss_calls)


class TestSmartServerCat(TestCaseWithTransport):
    def test_simple_branch_cat(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["cat", f"{self.get_url('branch')}/foo"])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(9, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerCheckout(TestCaseWithTransport):
    def test_heavyweight_checkout(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        for count in range(9):
            t.commit(message="commit %d" % count)
        self.reset_smart_call_log()
        out, err = self.run_bzr(["checkout", self.get_url("from"), "target"])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(11, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)

    def test_lightweight_checkout(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        for count in range(9):
            t.commit(message="commit %d" % count)
        self.reset_smart_call_log()
        out, err = self.run_bzr(
            ["checkout", "--lightweight", self.get_url("from"), "target"]
        )
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(13, self.hpss_calls)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerConfig(TestCaseWithTransport):
    def test_simple_branch_config(self):
        self.setup_smart_server_with_call_log()
        self.make_branch_and_tree("branch")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["config", "-d", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(5, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerInfo(TestCaseWithTransport):
    def test_simple_branch_info(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["info", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(10, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)

    def test_verbose_branch_info(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["info", "-v", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(14, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerExport(TestCaseWithTransport):
    def test_simple_export(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["export", "foo.tar.gz", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(8, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerLog(TestCaseWithTransport):
    def test_standard_log(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["log", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
        self.assertLength(1, self.hpss_connections)
        self.assertLength(9, self.hpss_calls)

    def test_verbose_log(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["log", "-v", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(10, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)

    def test_per_file(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["log", "-v", self.get_url("branch") + "/foo"])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(14, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerLs(TestCaseWithTransport):
    def test_simple_ls(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["ls", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(6, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerPack(TestCaseWithTransport):
    def test_simple_pack(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["pack", self.get_url("branch")])
        # This figure represent the amount of HPSS calls to perform this use
        # case. It is entirely ok to reduce this number if a test fails due to
        # rpc_count # being too low. If rpc_count increases, more network
        # roundtrips have become necessary for this use case. Please do not
        # adjust this number upwards without agreement from bzr's network
        # support maintainers.
        self.assertLength(6, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerPush(TestCaseWithTransport):
    def test_push_smart_non_stacked_streaming_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        t.commit(allow_pointless=True, message="first commit")
        self.reset_smart_call_log()
        self.run_bzr(["push", self.get_url("to-one")], working_dir="from")
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(9, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)

    def test_push_smart_stacked_streaming_acceptance(self):
        self.setup_smart_server_with_call_log()
        parent = self.make_branch_and_tree("parent", format="1.9")
        parent.commit(message="first commit")
        local = parent.controldir.sprout("local").open_workingtree()
        local.commit(message="local commit")
        self.reset_smart_call_log()
        self.run_bzr(
            ["push", "--stacked", "--stacked-on", "../parent", self.get_url("public")],
            working_dir="local",
        )
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(15, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
        remote = branch.Branch.open("public")
        self.assertEndsWith(remote.get_stacked_on_url(), "/parent")

    def test_push_smart_tags_streaming_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        rev_id = t.commit(allow_pointless=True, message="first commit")
        t.branch.tags.set_tag("new-tag", rev_id)
        self.reset_smart_call_log()
        self.run_bzr(["push", self.get_url("to-one")], working_dir="from")
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(11, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)

    def test_push_smart_incremental_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        t.commit(allow_pointless=True, message="first commit")
        t.commit(allow_pointless=True, message="second commit")
        self.run_bzr(["push", self.get_url("to-one"), "-r1"], working_dir="from")
        self.reset_smart_call_log()
        self.run_bzr(["push", self.get_url("to-one")], working_dir="from")
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(11, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerReconcile(TestCaseWithTransport):
    def test_simple_reconcile(self):
        self.setup_smart_server_with_call_log()
        self.make_branch("branch")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["reconcile", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(10, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerRevno(TestCaseWithTransport):
    def test_simple_branch_revno(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["revno", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
        self.assertLength(1, self.hpss_connections)
        self.assertLength(6, self.hpss_calls)

    def test_simple_branch_revno_lookup(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        revid1 = t.commit("message")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(
            ["revno", "-rrevid:" + revid1.decode("utf-8"), self.get_url("branch")]
        )
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(5, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerRemoveBranch(TestCaseWithTransport):
    def test_simple_remove_branch(self):
        self.setup_smart_server_with_call_log()
        self.make_branch("branch")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["rmbranch", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(5, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerSend(TestCaseWithTransport):
    def test_send(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        local = t.controldir.sprout("local-branch").open_workingtree()
        self.build_tree_contents([("branch/foo", b"thenewcontents")])
        local.commit("anothermessage")
        self.reset_smart_call_log()
        out, err = self.run_bzr(
            ["send", "-o", "x.diff", self.get_url("branch")], working_dir="local-branch"
        )
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(7, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerInitRepository(TestCaseWithTransport):
    def test_init_repo_smart_acceptance(self):
        # The amount of hpss calls made on init-shared-repo to a smart server
        # should be fixed.
        self.setup_smart_server_with_call_log()
        self.run_bzr(["init-shared-repo", self.get_url("repo")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(11, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerSignMyCommits(TestCaseWithTransport):
    def monkey_patch_gpg(self):
        """Monkey patch the gpg signing strategy to be a loopback.

        This also registers the cleanup, so that we will revert to
        the original gpg strategy when done.
        """
        # monkey patch gpg signing mechanism
        self.overrideAttr(gpg, "GPGStrategy", gpg.LoopbackGPGStrategy)

    def test_sign_single_commit(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        self.monkey_patch_gpg()
        out, err = self.run_bzr(["sign-my-commits", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(15, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerSwitch(TestCaseWithTransport):
    def test_switch_lightweight(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        for count in range(9):
            t.commit(message="commit %d" % count)
        out, err = self.run_bzr(
            ["checkout", "--lightweight", self.get_url("from"), "target"]
        )
        self.reset_smart_call_log()
        self.run_bzr(["switch", self.get_url("from")], working_dir="target")
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(21, self.hpss_calls)
        self.assertLength(3, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerTags(TestCaseWithTransport):
    def test_set_tag(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["tag", "-d", self.get_url("branch"), "tagname"])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(9, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)

    def test_show_tags(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        t.branch.tags.set_tag("sometag", b"rev1")
        t.branch.tags.set_tag("sometag", b"rev2")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["tags", "-d", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(6, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerUncommit(TestCaseWithTransport):
    def test_uncommit(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("from")
        for count in range(2):
            t.commit(message="commit %d" % count)
        self.reset_smart_call_log()
        out, err = self.run_bzr(["uncommit", "--force", self.get_url("from")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(14, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)


class TestSmartServerVerifySignatures(TestCaseWithTransport):
    def monkey_patch_gpg(self):
        """Monkey patch the gpg signing strategy to be a loopback.

        This also registers the cleanup, so that we will revert to
        the original gpg strategy when done.
        """
        # monkey patch gpg signing mechanism
        self.overrideAttr(gpg, "GPGStrategy", gpg.LoopbackGPGStrategy)

    def test_verify_signatures(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.monkey_patch_gpg()
        out, err = self.run_bzr(["sign-my-commits", self.get_url("branch")])
        self.reset_smart_call_log()
        self.run_bzr("sign-my-commits")
        self.run_bzr(["verify-signatures", self.get_url("branch")])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(10, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
