# Copyright (C) 2005-2012, 2016 Canonical Ltd
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


"""Black-box tests for brz pull."""

import os
import sys

from breezy import branch, debug, osutils, tests, uncommit, urlutils, workingtree
from breezy.bzr import remote
from breezy.directory_service import directories
from breezy.tests import fixtures, script


class TestPull(tests.TestCaseWithTransport):
    def example_branch(self, path="."):
        tree = self.make_branch_and_tree(path)
        self.build_tree_contents(
            [
                (osutils.pathjoin(path, "hello"), b"foo"),
                (osutils.pathjoin(path, "goodbye"), b"baz"),
            ]
        )
        tree.add("hello")
        tree.commit(message="setup")
        tree.add("goodbye")
        tree.commit(message="setup")
        return tree

    def test_pull(self):
        """Pull changes from one branch to another."""
        a_tree = self.example_branch("a")
        base_rev = a_tree.branch.last_revision()
        self.run_bzr("pull", retcode=3, working_dir="a")
        self.run_bzr("missing", retcode=3, working_dir="a")
        self.run_bzr("missing .", working_dir="a")
        self.run_bzr("missing", working_dir="a")
        # this will work on windows because we check for the same branch
        # in pull - if it fails, it is a regression
        self.run_bzr("pull", working_dir="a")
        self.run_bzr("pull /", retcode=3, working_dir="a")
        if sys.platform not in ("win32", "cygwin"):
            self.run_bzr("pull", working_dir="a")

        b_tree = a_tree.controldir.sprout("b").open_workingtree()
        self.run_bzr("pull", working_dir="b")
        os.mkdir("b/subdir")
        b_tree.add("subdir")
        new_rev = b_tree.commit(message="blah", allow_pointless=True)

        a = branch.Branch.open("a")
        b = branch.Branch.open("b")
        self.assertEqual(a.last_revision(), base_rev)
        self.assertEqual(b.last_revision(), new_rev)

        self.run_bzr("pull ../b", working_dir="a")
        self.assertEqual(a.last_revision(), b.last_revision())
        a_tree.commit(message="blah2", allow_pointless=True)
        b_tree.commit(message="blah3", allow_pointless=True)
        # no overwrite
        self.run_bzr("pull ../a", retcode=3, working_dir="b")
        b_tree.controldir.sprout("overwriteme")
        self.run_bzr("pull --overwrite ../a", working_dir="overwriteme")
        overwritten = branch.Branch.open("overwriteme")
        self.assertEqual(overwritten.last_revision(), a.last_revision())
        a_tree.merge_from_branch(b_tree.branch)
        a_tree.commit(message="blah4", allow_pointless=True)

        self.run_bzr("pull ../../a", working_dir="b/subdir")
        self.assertEqual(a.last_revision(), b.last_revision())
        sub_tree = workingtree.WorkingTree.open_containing("b/subdir")[0]
        sub_tree.commit(message="blah5", allow_pointless=True)
        sub_tree.commit(message="blah6", allow_pointless=True)
        self.run_bzr("pull ../a", working_dir="b")
        a_tree.commit(message="blah7", allow_pointless=True)
        a_tree.merge_from_branch(b_tree.branch)
        a_tree.commit(message="blah8", allow_pointless=True)
        self.run_bzr("pull ../b", working_dir="a")
        self.run_bzr("pull ../b", working_dir="a")

    def test_pull_dash_d(self):
        self.example_branch("a")
        self.make_branch_and_tree("b")
        self.make_branch_and_tree("c")
        # pull into that branch
        self.run_bzr("pull -d b a")
        # pull into a branch specified by a url
        c_url = urlutils.local_path_to_url("c")
        self.assertStartsWith(c_url, "file://")
        self.run_bzr(["pull", "-d", c_url, "a"])

    def test_pull_revision(self):
        """Pull some changes from one branch to another."""
        a_tree = self.example_branch("a")
        self.build_tree_contents([("a/hello2", b"foo"), ("a/goodbye2", b"baz")])
        a_tree.add("hello2")
        a_tree.commit(message="setup")
        a_tree.add("goodbye2")
        a_tree.commit(message="setup")

        a_tree.controldir.sprout(
            "b", revision_id=a_tree.branch.get_rev_id(1)
        ).open_workingtree()
        self.run_bzr("pull -r 2", working_dir="b")
        a = branch.Branch.open("a")
        b = branch.Branch.open("b")
        self.assertEqual(a.revno(), 4)
        self.assertEqual(b.revno(), 2)
        self.run_bzr("pull -r 3", working_dir="b")
        self.assertEqual(b.revno(), 3)
        self.run_bzr("pull -r 4", working_dir="b")
        self.assertEqual(a.last_revision(), b.last_revision())

    def test_pull_tags(self):
        """Tags are updated by pull, and revisions named in those tags are
        fetched.
        """
        # Make a source, sprout a target off it
        builder = self.make_branch_builder("source")
        source, _rev1, rev2 = fixtures.build_branch_with_non_ancestral_rev(builder)
        source.get_config_stack().set("branch.fetch_tags", True)
        target_bzrdir = source.controldir.sprout("target")
        source.tags.set_tag("tag-a", rev2)
        # Pull from source
        self.run_bzr("pull -d target source")
        target = target_bzrdir.open_branch()
        # The tag is present, and so is its revision.
        self.assertEqual(rev2, target.tags.lookup_tag("tag-a"))
        target.repository.get_revision(rev2)

    def test_overwrite_uptodate(self):
        # Make sure pull --overwrite overwrites
        # even if the target branch has merged
        # everything already.
        a_tree = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/foo", b"original\n")])
        a_tree.add("foo")
        a_tree.commit(message="initial commit")

        b_tree = a_tree.controldir.sprout("b").open_workingtree()

        self.build_tree_contents([("a/foo", b"changed\n")])
        a_tree.commit(message="later change")

        self.build_tree_contents([("a/foo", b"a third change")])
        a_tree.commit(message="a third change")

        self.assertEqual(a_tree.branch.last_revision_info()[0], 3)

        b_tree.merge_from_branch(a_tree.branch)
        b_tree.commit(message="merge")

        self.assertEqual(b_tree.branch.last_revision_info()[0], 2)

        self.run_bzr("pull --overwrite ../a", working_dir="b")
        (last_revinfo_b) = b_tree.branch.last_revision_info()
        self.assertEqual(last_revinfo_b[0], 3)
        self.assertEqual(last_revinfo_b[1], a_tree.branch.last_revision())

    def test_overwrite_children(self):
        # Make sure pull --overwrite sets the revision-history
        # to be identical to the pull source, even if we have convergence
        a_tree = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/foo", b"original\n")])
        a_tree.add("foo")
        a_tree.commit(message="initial commit")

        b_tree = a_tree.controldir.sprout("b").open_workingtree()

        self.build_tree_contents([("a/foo", b"changed\n")])
        a_tree.commit(message="later change")

        self.build_tree_contents([("a/foo", b"a third change")])
        a_tree.commit(message="a third change")

        self.assertEqual(a_tree.branch.last_revision_info()[0], 3)

        b_tree.merge_from_branch(a_tree.branch)
        b_tree.commit(message="merge")

        self.assertEqual(b_tree.branch.last_revision_info()[0], 2)

        self.build_tree_contents([("a/foo", b"a fourth change\n")])
        a_tree.commit(message="a fourth change")

        rev_info_a = a_tree.branch.last_revision_info()
        self.assertEqual(rev_info_a[0], 4)

        # With convergence, we could just pull over the
        # new change, but with --overwrite, we want to switch our history
        self.run_bzr("pull --overwrite ../a", working_dir="b")
        rev_info_b = b_tree.branch.last_revision_info()
        self.assertEqual(rev_info_b[0], 4)
        self.assertEqual(rev_info_b, rev_info_a)

    def test_pull_remember(self):
        """Pull changes from one branch to another and test parent location."""
        t = self.get_transport()
        tree_a = self.make_branch_and_tree("branch_a")
        branch_a = tree_a.branch
        self.build_tree(["branch_a/a"])
        tree_a.add("a")
        tree_a.commit("commit a")
        tree_b = branch_a.controldir.sprout("branch_b").open_workingtree()
        branch_b = tree_b.branch
        tree_c = branch_a.controldir.sprout("branch_c").open_workingtree()
        branch_c = tree_c.branch
        self.build_tree(["branch_a/b"])
        tree_a.add("b")
        tree_a.commit("commit b")
        # reset parent
        parent = branch_b.get_parent()
        branch_b = branch.Branch.open("branch_b")
        branch_b.set_parent(None)
        self.assertEqual(None, branch_b.get_parent())
        # test pull for failure without parent set
        out = self.run_bzr("pull", retcode=3, working_dir="branch_b")
        self.assertEqual(
            out, ("", "brz: ERROR: No pull location known or specified.\n")
        )
        # test implicit --remember when no parent set, this pull conflicts
        self.build_tree(["branch_b/d"])
        tree_b.add("d")
        tree_b.commit("commit d")
        out = self.run_bzr("pull ../branch_a", retcode=3, working_dir="branch_b")
        self.assertEqual(
            out,
            (
                "",
                "brz: ERROR: These branches have diverged."
                " Use the missing command to see how.\n"
                "Use the merge command to reconcile them.\n",
            ),
        )
        tree_b = tree_b.controldir.open_workingtree()
        branch_b = tree_b.branch
        self.assertEqual(parent, branch_b.get_parent())
        # test implicit --remember after resolving previous failure
        uncommit.uncommit(branch=branch_b, tree=tree_b)
        t.delete("branch_b/d")
        self.run_bzr("pull", working_dir="branch_b")
        # Refresh the branch object as 'pull' modified it
        branch_b = branch_b.controldir.open_branch()
        self.assertEqual(branch_b.get_parent(), parent)
        # test explicit --remember
        self.run_bzr("pull ../branch_c --remember", working_dir="branch_b")
        # Refresh the branch object as 'pull' modified it
        branch_b = branch_b.controldir.open_branch()
        self.assertEqual(branch_c.controldir.root_transport.base, branch_b.get_parent())

    def test_pull_bundle(self):
        from breezy.bzr.testament import Testament

        # Build up 2 trees and prepare for a pull
        tree_a = self.make_branch_and_tree("branch_a")
        with open("branch_a/a", "wb") as f:
            f.write(b"hello")
        tree_a.add("a")
        tree_a.commit("message")

        tree_b = tree_a.controldir.sprout("branch_b").open_workingtree()

        # Make a change to 'a' that 'b' can pull
        with open("branch_a/a", "wb") as f:
            f.write(b"hey there")
        tree_a.commit("message")

        # Create the bundle for 'b' to pull
        self.run_bzr("bundle ../branch_b -o ../bundle", working_dir="branch_a")

        out, err = self.run_bzr("pull ../bundle", working_dir="branch_b")
        self.assertEqual(out, "Now on revision 2.\n")
        self.assertEqual(err, " M  a\nAll changes applied successfully.\n")

        self.assertEqualDiff(
            tree_a.branch.last_revision(), tree_b.branch.last_revision()
        )

        testament_a = Testament.from_revision(
            tree_a.branch.repository, tree_a.get_parent_ids()[0]
        )
        testament_b = Testament.from_revision(
            tree_b.branch.repository, tree_b.get_parent_ids()[0]
        )
        self.assertEqualDiff(testament_a.as_text(), testament_b.as_text())

        # it is legal to attempt to pull an already-merged bundle
        out, err = self.run_bzr("pull ../bundle", working_dir="branch_b")
        self.assertEqual(err, "")
        self.assertEqual(out, "No revisions or tags to pull.\n")

    def test_pull_verbose_no_files(self):
        """Pull --verbose should not list modified files."""
        tree_a = self.make_branch_and_tree("tree_a")
        self.build_tree(["tree_a/foo"])
        tree_a.add("foo")
        tree_a.commit("bar")
        self.make_branch_and_tree("tree_b")
        out = self.run_bzr("pull --verbose -d tree_b tree_a")[0]
        self.assertContainsRe(out, "bar")
        self.assertNotContainsRe(out, "added:")
        self.assertNotContainsRe(out, "foo")

    def test_pull_quiet(self):
        """Check that brz pull --quiet does not print anything."""
        tree_a = self.make_branch_and_tree("tree_a")
        self.build_tree(["tree_a/foo"])
        tree_a.add("foo")
        revision_id = tree_a.commit("bar")
        tree_b = tree_a.controldir.sprout("tree_b").open_workingtree()
        out, err = self.run_bzr("pull --quiet -d tree_b")
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        self.assertEqual(tree_b.last_revision(), revision_id)
        self.build_tree(["tree_a/moo"])
        tree_a.add("moo")
        revision_id = tree_a.commit("quack")
        out, err = self.run_bzr("pull --quiet -d tree_b")
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        self.assertEqual(tree_b.last_revision(), revision_id)

    def test_pull_from_directory_service(self):
        source = self.make_branch_and_tree("source")
        source.commit("commit 1")
        target = source.controldir.sprout("target").open_workingtree()
        source_last = source.commit("commit 2")

        class FooService:
            """A directory service that always returns source."""

            def look_up(self, name, url, purpose=None):
                return "source"

        directories.register("foo:", FooService, "Testing directory service")
        self.addCleanup(directories.remove, "foo:")
        self.run_bzr("pull foo:bar -d target")
        self.assertEqual(source_last, target.last_revision())

    def test_pull_verbose_defaults_to_long(self):
        self.example_branch("source")
        self.make_branch_and_tree("target")
        out = self.run_bzr("pull -v source -d target")[0]
        self.assertContainsRe(out, r"revno: 1\ncommitter: .*\nbranch nick: source")
        self.assertNotContainsRe(out, r"\n {4}1 .*\n {6}setup\n")

    def test_pull_verbose_uses_default_log(self):
        self.example_branch("source")
        target = self.make_branch_and_tree("target")
        target.branch.get_config_stack().set("log_format", "short")
        out = self.run_bzr("pull -v source -d target")[0]
        self.assertContainsRe(out, r"\n {4}1 .*\n {6}setup\n")
        self.assertNotContainsRe(out, r"revno: 1\ncommitter: .*\nbranch nick: source")

    def test_pull_smart_bound_branch(self):
        self.setup_smart_server_with_call_log()
        parent = self.make_branch_and_tree("parent")
        parent.commit(message="first commit")
        child = parent.controldir.sprout("child").open_workingtree()
        child.commit(message="second commit")
        parent.branch.create_checkout("checkout")
        self.run_bzr(["pull", self.get_url("child")], working_dir="checkout")

    def test_pull_smart_stacked_streaming_acceptance(self):
        """'brz pull -r 123' works on stacked, smart branches, even when the
        revision specified by the revno is only present in the fallback
        repository.

        See <https://launchpad.net/bugs/380314>
        """
        self.setup_smart_server_with_call_log()
        # Make a stacked-on branch with two commits so that the
        # revision-history can't be determined just by looking at the parent
        # field in the revision in the stacked repo.
        parent = self.make_branch_and_tree("parent", format="1.9")
        parent.commit(message="first commit")
        parent.commit(message="second commit")
        local = parent.controldir.sprout("local").open_workingtree()
        local.commit(message="local commit")
        local.branch.create_clone_on_transport(
            self.get_transport("stacked"), stacked_on=self.get_url("parent")
        )
        self.make_branch_and_tree("empty", format="1.9")
        self.reset_smart_call_log()
        self.run_bzr(["pull", "-r", "1", self.get_url("stacked")], working_dir="empty")
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(20, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        remote = branch.Branch.open("stacked")
        self.assertEndsWith(remote.get_stacked_on_url(), "/parent")

    def test_pull_cross_format_warning(self):
        """You get a warning for probably slow cross-format pulls."""
        # this is assumed to be going through InterDifferingSerializer
        from_tree = self.make_branch_and_tree("from", format="2a")
        self.make_branch_and_tree("to", format="1.14-rich-root")
        from_tree.commit(message="first commit")
        _out, err = self.run_bzr(["pull", "-d", "to", "from"])
        self.assertContainsRe(err, "(?m)Doing on-the-fly conversion")

    def test_pull_cross_format_warning_no_IDS(self):
        """You get a warning for probably slow cross-format pulls."""
        # this simulates what would happen across the network, where
        # interdifferingserializer is not active

        debug.debug_flags.add("IDS_never")
        # TestCase take care of restoring them

        from_tree = self.make_branch_and_tree("from", format="2a")
        self.make_branch_and_tree("to", format="1.14-rich-root")
        from_tree.commit(message="first commit")
        _out, err = self.run_bzr(["pull", "-d", "to", "from"])
        self.assertContainsRe(err, "(?m)Doing on-the-fly conversion")

    def test_pull_cross_format_from_network(self):
        self.setup_smart_server_with_call_log()
        from_tree = self.make_branch_and_tree("from", format="2a")
        self.make_branch_and_tree("to", format="1.14-rich-root")
        self.assertIsInstance(from_tree.branch, remote.RemoteBranch)
        from_tree.commit(message="first commit")
        _out, err = self.run_bzr(
            ["pull", "-d", "to", from_tree.branch.controldir.root_transport.base]
        )
        self.assertContainsRe(err, "(?m)Doing on-the-fly conversion")

    def test_pull_to_experimental_format_warning(self):
        """You get a warning for pulling into experimental formats."""
        from_tree = self.make_branch_and_tree("from", format="development-subtree")
        self.make_branch_and_tree("to", format="development-subtree")
        from_tree.commit(message="first commit")
        _out, err = self.run_bzr(["pull", "-d", "to", "from"])
        self.assertContainsRe(err, "(?m)Fetching into experimental format")

    def test_pull_cross_to_experimental_format_warning(self):
        """You get a warning for pulling into experimental formats."""
        from_tree = self.make_branch_and_tree("from", format="2a")
        self.make_branch_and_tree("to", format="development-subtree")
        from_tree.commit(message="first commit")
        _out, err = self.run_bzr(["pull", "-d", "to", "from"])
        self.assertContainsRe(err, "(?m)Fetching into experimental format")

    def test_pull_show_base(self):
        """Brz pull supports --show-base.

        see https://bugs.launchpad.net/bzr/+bug/202374
        """
        # create two trees with conflicts, setup conflict, check that
        # conflicted file looks correct
        a_tree = self.example_branch("a")
        a_tree.controldir.sprout("b").open_workingtree()

        with open(osutils.pathjoin("a", "hello"), "w") as f:
            f.write("fee")
        a_tree.commit("fee")

        with open(osutils.pathjoin("b", "hello"), "w") as f:
            f.write("fie")

        _out, err = self.run_bzr(["pull", "-d", "b", "a", "--show-base"])

        # check for message here
        self.assertEqual(
            err, " M  hello\nText conflict in hello\n1 conflicts encountered.\n"
        )

        with open(osutils.pathjoin("b", "hello")) as f:
            self.assertEqualDiff(
                "<<<<<<< TREE\n"
                "fie||||||| BASE-REVISION\n"
                "foo=======\n"
                "fee>>>>>>> MERGE-SOURCE\n",
                f.read(),
            )

    def test_pull_warns_about_show_base_when_no_working_tree(self):
        """--show-base is useless if there's no working tree.

        see https://bugs.launchpad.net/bzr/+bug/1022160
        """
        self.make_branch("from")
        self.make_branch("to")
        out = self.run_bzr(["pull", "-d", "to", "from", "--show-base"])
        self.assertEqual(
            out,
            (
                "No revisions or tags to pull.\n",
                "No working tree, ignoring --show-base\n",
            ),
        )

    def test_pull_tag_conflicts(self):
        """Pulling tags with conflicts will change the exit code."""
        # create a branch, see that --show-base fails
        from_tree = self.make_branch_and_tree("from")
        from_tree.branch.tags.set_tag("mytag", b"somerevid")
        to_tree = self.make_branch_and_tree("to")
        to_tree.branch.tags.set_tag("mytag", b"anotherrevid")
        out = self.run_bzr(["pull", "-d", "to", "from"], retcode=1)
        self.assertEqual(
            out, ("No revisions to pull.\nConflicting tags:\n    mytag\n", "")
        )

    def test_pull_tag_notification(self):
        """Pulling tags with conflicts will change the exit code."""
        # create a branch, see that --show-base fails
        from_tree = self.make_branch_and_tree("from")
        from_tree.branch.tags.set_tag("mytag", b"somerevid")
        self.make_branch_and_tree("to")
        out = self.run_bzr(["pull", "-d", "to", "from"])
        self.assertEqual(out, ("1 tag(s) updated.\n", ""))

    def test_overwrite_tags(self):
        """--overwrite-tags only overwrites tags, not revisions."""
        from_tree = self.make_branch_and_tree("from")
        from_tree.branch.tags.set_tag("mytag", b"somerevid")
        to_tree = self.make_branch_and_tree("to")
        to_tree.branch.tags.set_tag("mytag", b"anotherrevid")
        revid1 = to_tree.commit("my commit")
        out = self.run_bzr(["pull", "-d", "to", "from"], retcode=1)
        self.assertEqual(
            out, ("No revisions to pull.\nConflicting tags:\n    mytag\n", "")
        )
        out = self.run_bzr(["pull", "-d", "to", "--overwrite-tags", "from"])
        self.assertEqual(out, ("1 tag(s) updated.\n", ""))

        self.assertEqual(to_tree.branch.tags.lookup_tag("mytag"), b"somerevid")
        self.assertEqual(to_tree.branch.last_revision(), revid1)

    def test_pull_tag_overwrite(self):
        """Pulling tags with --overwrite only reports changed tags."""
        # create a branch, see that --show-base fails
        from_tree = self.make_branch_and_tree("from")
        from_tree.branch.tags.set_tag("mytag", b"somerevid")
        to_tree = self.make_branch_and_tree("to")
        to_tree.branch.tags.set_tag("mytag", b"somerevid")
        out = self.run_bzr(["pull", "--overwrite", "-d", "to", "from"])
        self.assertEqual(out, ("No revisions or tags to pull.\n", ""))


class TestPullOutput(script.TestCaseWithTransportAndScript):
    def test_pull_log_format(self):
        self.run_script("""
            $ brz init trunk
            Created a standalone tree (format: 2a)
            $ cd trunk
            $ echo foo > file
            $ brz add
            adding file
            $ brz commit -m 'we need some foo'
            2>Committing to:...trunk/
            2>added file
            2>Committed revision 1.
            $ cd ..
            $ brz init feature
            Created a standalone tree (format: 2a)
            $ cd feature
            $ brz pull -v ../trunk -Olog_format=line
            Now on revision 1.
            Added Revisions:
            1: jrandom@example.com ...we need some foo
            2>+N  file
            2>All changes applied successfully.
            """)
