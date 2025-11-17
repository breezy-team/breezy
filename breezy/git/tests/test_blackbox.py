# Copyright (C) 2007 David Allouche <ddaa@ddaa.net>
# Copyright (C) 2007-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Black-box tests for bzr-git."""

import os

from dulwich.repo import Repo as GitRepo

from ...controldir import ControlDir
from ...tests.blackbox import ExternalBase
from ...tests.features import PluginLoadedFeature
from ...tests.script import TestCaseWithTransportAndScript
from ...workingtree import WorkingTree
from .. import tests


class TestGitBlackBox(ExternalBase):
    def simple_commit(self):
        # Create a git repository with a revision.
        repo = GitRepo.init(self.test_dir)
        builder = tests.GitBranchBuilder()
        builder.set_file("a", b"text for a\n", False)
        r1 = builder.commit(b"Joe Foo <joe@foo.com>", "<The commit message>")
        return repo, builder.finish()[r1]

    def test_add(self):
        GitRepo.init(self.test_dir)
        dir = ControlDir.open(self.test_dir)
        dir.create_branch()
        self.build_tree(["a", "b"])
        output, error = self.run_bzr(["add", "a"])
        self.assertEqual("adding a\n", output)
        self.assertEqual("", error)
        output, error = self.run_bzr(["add", "--file-ids-from=../othertree", "b"])
        self.assertEqual("adding b\n", output)
        self.assertEqual(
            "Ignoring --file-ids-from, since the tree does not support "
            "setting file ids.\n",
            error,
        )

    def test_nick(self):
        GitRepo.init(self.test_dir)
        dir = ControlDir.open(self.test_dir)
        dir.create_branch()
        output, _error = self.run_bzr(["nick"])
        self.assertEqual("master\n", output)

    def test_branches(self):
        self.simple_commit()
        output, _error = self.run_bzr(["branches"])
        self.assertEqual("* master\n", output)

    def test_info(self):
        self.simple_commit()
        output, error = self.run_bzr(["info"])
        self.assertEqual(error, "")
        self.assertEqual(
            output,
            "Standalone tree (format: git)\n"
            "Location:\n"
            "            light checkout root: .\n"
            "  checkout of co-located branch: master\n",
        )

    def test_ignore(self):
        self.simple_commit()
        output, error = self.run_bzr(["ignore", "foo"])
        self.assertEqual(error, "")
        self.assertEqual(output, "")
        self.assertFileEqual("foo\n", ".gitignore")

    def test_cat_revision(self):
        self.simple_commit()
        output, error = self.run_bzr(["cat-revision", "-r-1"], retcode=3)
        self.assertContainsRe(
            error,
            "brz: ERROR: Repository .* does not support access to raw revision texts",
        )
        self.assertEqual(output, "")

    def test_branch(self):
        os.mkdir("gitbranch")
        GitRepo.init(os.path.join(self.test_dir, "gitbranch"))
        os.chdir("gitbranch")
        builder = tests.GitBranchBuilder()
        builder.set_file(b"a", b"text for a\n", False)
        builder.commit(b"Joe Foo <joe@foo.com>", b"<The commit message>")
        builder.finish()
        os.chdir("..")

        _output, error = self.run_bzr(["branch", "gitbranch", "bzrbranch"])
        errlines = error.splitlines(False)
        self.assertTrue(
            "Branched 1 revision(s)." in errlines or "Branched 1 revision." in errlines,
            errlines,
        )

    def test_checkout(self):
        os.mkdir("gitbranch")
        GitRepo.init(os.path.join(self.test_dir, "gitbranch"))
        os.chdir("gitbranch")
        builder = tests.GitBranchBuilder()
        builder.set_file(b"a", b"text for a\n", False)
        builder.commit(b"Joe Foo <joe@foo.com>", b"<The commit message>")
        builder.finish()
        os.chdir("..")

        output, error = self.run_bzr(["checkout", "gitbranch", "bzrbranch"])
        self.assertEqual(
            error,
            "Fetching from Git to Bazaar repository. "
            "For better performance, fetch into a Git repository.\n",
        )
        self.assertEqual(output, "")

    def test_branch_ls(self):
        self.simple_commit()
        output, error = self.run_bzr(["ls", "-r-1"])
        self.assertEqual(error, "")
        self.assertEqual(output, "a\n")

    def test_init(self):
        self.run_bzr("init --format=git repo")

    def test_info_verbose(self):
        self.simple_commit()

        output, error = self.run_bzr(["info", "-v"])
        self.assertEqual(error, "")
        self.assertTrue("Standalone tree (format: git)" in output)
        self.assertTrue("control: Local Git Repository" in output)
        self.assertTrue("branch: Local Git Branch" in output)
        self.assertTrue("repository: Git Repository" in output)

    def test_push_roundtripping(self):
        self.knownFailure("roundtripping is not yet supported")
        self.with_roundtripping()
        os.mkdir("bla")
        GitRepo.init(os.path.join(self.test_dir, "bla"))
        self.run_bzr(["init", "foo"])
        self.run_bzr(["commit", "--unchanged", "-m", "bla", "foo"])
        # when roundtripping is supported
        output, error = self.run_bzr(["push", "-d", "foo", "bla"])
        self.assertEqual(b"", output)
        self.assertTrue(error.endswith(b"Created new branch.\n"))

    def test_push_without_calculate_revnos(self):
        self.run_bzr(["init", "--git", "bla"])
        self.run_bzr(["init", "--git", "foo"])
        self.run_bzr(["commit", "--unchanged", "-m", "bla", "foo"])
        output, error = self.run_bzr(
            ["push", "-Ocalculate_revnos=no", "-d", "foo", "bla"]
        )
        self.assertEqual("", output)
        self.assertContainsRe(error, "Pushed up to revision id git(.*).\n")

    def test_merge(self):
        self.run_bzr(["init", "--git", "orig"])
        self.build_tree_contents([("orig/a", "orig contents\n")])
        self.run_bzr(["add", "orig/a"])
        self.run_bzr(["commit", "-m", "add orig", "orig"])
        self.run_bzr(["clone", "orig", "other"])
        self.build_tree_contents([("other/a", "new contents\n")])
        self.run_bzr(["commit", "-m", "modify", "other"])
        self.build_tree_contents([("orig/b", "more\n")])
        self.run_bzr(["add", "orig/b"])
        self.build_tree_contents([("orig/a", "new contents\n")])
        self.run_bzr(["commit", "-m", "more", "orig"])
        self.run_bzr(["merge", "-d", "orig", "other"])

    def test_push_lossy_non_mainline(self):
        self.run_bzr(["init", "--git", "bla"])
        self.run_bzr(["init", "foo"])
        self.run_bzr(["commit", "--unchanged", "-m", "bla", "foo"])
        self.run_bzr(["branch", "foo", "foo1"])
        self.run_bzr(["commit", "--unchanged", "-m", "bla", "foo1"])
        self.run_bzr(["commit", "--unchanged", "-m", "bla", "foo"])
        self.run_bzr(["merge", "-d", "foo", "foo1"])
        self.run_bzr(["commit", "--unchanged", "-m", "merge", "foo"])
        output, error = self.run_bzr(["push", "--lossy", "-r1.1.1", "-d", "foo", "bla"])
        self.assertEqual("", output)
        self.assertEqual(
            "Pushing from a Bazaar to a Git repository. For better "
            "performance, push into a Bazaar repository.\n"
            "All changes applied successfully.\n"
            "Pushed up to revision 2.\n",
            error,
        )

    def test_push_lossy_non_mainline_incremental(self):
        self.run_bzr(["init", "--git", "bla"])
        self.run_bzr(["init", "foo"])
        self.run_bzr(["commit", "--unchanged", "-m", "bla", "foo"])
        self.run_bzr(["commit", "--unchanged", "-m", "bla", "foo"])
        output, error = self.run_bzr(["push", "--lossy", "-d", "foo", "bla"])
        self.assertEqual("", output)
        self.assertEqual(
            "Pushing from a Bazaar to a Git repository. For better "
            "performance, push into a Bazaar repository.\n"
            "All changes applied successfully.\n"
            "Pushed up to revision 2.\n",
            error,
        )
        self.run_bzr(["commit", "--unchanged", "-m", "bla", "foo"])
        output, error = self.run_bzr(["push", "--lossy", "-d", "foo", "bla"])
        self.assertEqual("", output)
        self.assertEqual(
            "Pushing from a Bazaar to a Git repository. For better "
            "performance, push into a Bazaar repository.\n"
            "All changes applied successfully.\n"
            "Pushed up to revision 3.\n",
            error,
        )

    def test_log(self):
        # Smoke test for "bzr log" in a git repository.
        self.simple_commit()

        # Check that bzr log does not fail and includes the revision.
        output, error = self.run_bzr(["log"])
        self.assertEqual(error, "")
        self.assertTrue(
            "<The commit message>" in output,
            "Commit message was not found in output:\n{}".format(output),
        )

    def test_log_verbose(self):
        # Smoke test for "bzr log -v" in a git repository.
        self.simple_commit()

        # Check that bzr log does not fail and includes the revision.
        output, _error = self.run_bzr(["log", "-v"])
        self.assertContainsRe(output, "revno: 1")

    def test_log_without_revno(self):
        # Smoke test for "bzr log -v" in a git repository.
        self.simple_commit()

        # Check that bzr log does not fail and includes the revision.
        output, _error = self.run_bzr(["log", "-Ocalculate_revnos=no"])
        self.assertNotContainsRe(output, "revno: 1")

    def test_commit_without_revno(self):
        GitRepo.init(self.test_dir)
        output, error = self.run_bzr(
            ["commit", "-Ocalculate_revnos=yes", "--unchanged", "-m", "one"]
        )
        self.assertContainsRe(error, "Committed revision 1.")
        _output, error = self.run_bzr(
            ["commit", "-Ocalculate_revnos=no", "--unchanged", "-m", "two"]
        )
        self.assertNotContainsRe(error, "Committed revision 2.")
        self.assertContainsRe(error, "Committed revid .*.")

    def test_log_file(self):
        # Smoke test for "bzr log" in a git repository.
        GitRepo.init(self.test_dir)
        builder = tests.GitBranchBuilder()
        builder.set_file("a", b"text for a\n", False)
        r1 = builder.commit(b"Joe Foo <joe@foo.com>", "First")
        builder.set_file("a", b"text 3a for a\n", False)
        r2a = builder.commit(b"Joe Foo <joe@foo.com>", "Second a", base=r1)
        builder.set_file("a", b"text 3b for a\n", False)
        r2b = builder.commit(b"Joe Foo <joe@foo.com>", "Second b", base=r1)
        builder.set_file("a", b"text 4 for a\n", False)
        builder.commit(b"Joe Foo <joe@foo.com>", "Third", merge=[r2a], base=r2b)
        builder.finish()

        # Check that bzr log does not fail and includes the revision.
        output, error = self.run_bzr(["log", "-n2", "a"])
        self.assertEqual(error, "")
        self.assertIn("Second a", output)
        self.assertIn("Second b", output)
        self.assertIn("First", output)
        self.assertIn("Third", output)

    def test_tags(self):
        git_repo, commit_sha1 = self.simple_commit()
        git_repo.refs[b"refs/tags/foo"] = commit_sha1

        output, error = self.run_bzr(["tags"])
        self.assertEqual(error, "")
        self.assertEqual(output, "foo                  1\n")

    def test_tag(self):
        self.simple_commit()

        output, error = self.run_bzr(["tag", "bar"])

        # bzr <= 2.2 emits this message in the output stream
        # bzr => 2.3 emits this message in the error stream
        self.assertEqual(error + output, "Created tag bar.\n")

    def test_init_repo(self):
        output, error = self.run_bzr(["init", "--format=git", "bla.git"])
        self.assertEqual(error, "")
        self.assertEqual(output, "Created a standalone tree (format: git)\n")

    def test_diff_format(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a"])
        tree.add(["a"])
        output, error = self.run_bzr(["diff", "--format=git"], retcode=1)
        self.assertEqual(error, "")
        # Some older versions of Dulwich (< 0.19.12) formatted diffs slightly
        # differently.
        from dulwich import __version__ as dulwich_version

        if dulwich_version < (0, 19, 12):
            self.assertEqual(
                output,
                "diff --git /dev/null b/a\n"
                "old mode 0\n"
                "new mode 100644\n"
                "index 0000000..c197bd8 100644\n"
                "--- /dev/null\n"
                "+++ b/a\n"
                "@@ -0,0 +1 @@\n"
                "+contents of a\n",
            )
        else:
            self.assertEqual(
                output,
                "diff --git a/a b/a\n"
                "old file mode 0\n"
                "new file mode 100644\n"
                "index 0000000..c197bd8 100644\n"
                "--- /dev/null\n"
                "+++ b/a\n"
                "@@ -0,0 +1 @@\n"
                "+contents of a\n",
            )

    def test_git_import_uncolocated(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        wt = r.get_worktree()
        wt.stage("file")
        wt.commit(
            ref=b"refs/heads/abranch",
            committer=b"Joe <joe@example.com>",
            message=b"Dummy",
        )
        wt.commit(
            ref=b"refs/heads/bbranch",
            committer=b"Joe <joe@example.com>",
            message=b"Dummy",
        )
        self.run_bzr(["git-import", "a", "b"])
        self.assertEqual({".bzr", "abranch", "bbranch"}, set(os.listdir("b")))

    def test_git_import(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        wt = r.get_worktree()
        wt.stage("file")
        wt.commit(
            ref=b"refs/heads/abranch",
            committer=b"Joe <joe@example.com>",
            message=b"Dummy",
        )
        wt.commit(
            ref=b"refs/heads/bbranch",
            committer=b"Joe <joe@example.com>",
            message=b"Dummy",
        )
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEqual({".bzr"}, set(os.listdir("b")))
        self.assertEqual(
            {"abranch", "bbranch"}, set(ControlDir.open("b").branch_names())
        )

    def test_git_import_incremental(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        wt = r.get_worktree()
        wt.stage("file")
        wt.commit(
            ref=b"refs/heads/abranch",
            committer=b"Joe <joe@example.com>",
            message=b"Dummy",
        )
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEqual({".bzr"}, set(os.listdir("b")))
        b = ControlDir.open("b")
        self.assertEqual(["abranch"], b.branch_names())

    def test_git_import_tags(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        wt = r.get_worktree()
        wt.stage("file")
        cid = wt.commit(
            ref=b"refs/heads/abranch",
            committer=b"Joe <joe@example.com>",
            message=b"Dummy",
        )
        r[b"refs/tags/atag"] = cid
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEqual({".bzr"}, set(os.listdir("b")))
        b = ControlDir.open("b")
        self.assertEqual(["abranch"], b.branch_names())
        self.assertEqual(
            ["atag"], list(b.open_branch("abranch").tags.get_tag_dict().keys())
        )

    def test_git_import_colo(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        wt = r.get_worktree()
        wt.stage("file")
        wt.commit(
            ref=b"refs/heads/abranch",
            committer=b"Joe <joe@example.com>",
            message=b"Dummy",
        )
        wt.commit(
            ref=b"refs/heads/bbranch",
            committer=b"Joe <joe@example.com>",
            message=b"Dummy",
        )
        self.make_controldir("b", format="development-colo")
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEqual(
            {b.name for b in ControlDir.open("b").list_branches()},
            {"abranch", "bbranch"},
        )

    def test_git_refs_from_git(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        wt = r.get_worktree()
        wt.stage("file")
        cid = wt.commit(
            ref=b"refs/heads/abranch",
            committer=b"Joe <joe@example.com>",
            message=b"Dummy",
        )
        r[b"refs/tags/atag"] = cid
        (stdout, stderr) = self.run_bzr(["git-refs", "a"])
        self.assertEqual(stderr, "")
        self.assertEqual(
            stdout,
            "refs/heads/abranch -> " + cid.decode("ascii") + "\n"
            "refs/tags/atag -> " + cid.decode("ascii") + "\n",
        )

    def test_git_refs_from_bzr(self):
        tree = self.make_branch_and_tree("a")
        self.build_tree(["a/file"])
        tree.add(["file"])
        revid = tree.commit(committer=b"Joe <joe@example.com>", message=b"Dummy")
        tree.branch.tags.set_tag("atag", revid)
        (stdout, stderr) = self.run_bzr(["git-refs", "a"])
        self.assertEqual(stderr, "")
        self.assertTrue("refs/tags/atag -> " in stdout)
        self.assertTrue("HEAD -> " in stdout)

    def test_check(self):
        r = GitRepo.init("gitr", mkdir=True)
        self.build_tree_contents([("gitr/foo", b"hello from git")])
        wt = r.get_worktree()
        wt.stage("foo")
        wt.commit(b"message", committer=b"Somebody <user@example.com>")
        out, err = self.run_bzr(["check", "gitr"])
        self.maxDiff = None
        self.assertEqual(out, "")
        self.assertTrue(err.endswith, "3 objects\n")

    def test_local_whoami(self):
        GitRepo.init("gitr", mkdir=True)
        self.build_tree_contents(
            [
                (
                    "gitr/.git/config",
                    """\
[user]
  email = some@example.com
  name = Test User
""",
                )
            ]
        )
        out, err = self.run_bzr(["whoami", "-d", "gitr"])
        self.assertEqual(out, "Test User <some@example.com>\n")
        self.assertEqual(err, "")

        self.build_tree_contents(
            [
                (
                    "gitr/.git/config",
                    """\
[user]
  email = some@example.com
""",
                )
            ]
        )
        out, err = self.run_bzr(["whoami", "-d", "gitr"])
        self.assertEqual(out, "some@example.com\n")
        self.assertEqual(err, "")

    def test_local_signing_key(self):
        GitRepo.init("gitr", mkdir=True)
        self.build_tree_contents(
            [
                (
                    "gitr/.git/config",
                    """\
[user]
  email = some@example.com
  name = Test User
  signingkey = D729A457
""",
                )
            ]
        )
        out, err = self.run_bzr(["config", "-d", "gitr", "gpg_signing_key"])
        self.assertEqual(out, "D729A457\n")
        self.assertEqual(err, "")


class ShallowTests(ExternalBase):
    def setUp(self):
        super().setUp()
        # Smoke test for "bzr log" in a git repository with shallow depth.
        self.repo = GitRepo.init("gitr", mkdir=True)
        self.build_tree_contents([("gitr/foo", b"hello from git")])
        wt = self.repo.get_worktree()
        wt.stage("foo")
        wt.commit(
            b"message",
            committer=b"Somebody <user@example.com>",
            author=b"Somebody <user@example.com>",
            commit_timestamp=1526330165,
            commit_timezone=0,
            author_timestamp=1526330165,
            author_timezone=0,
            merge_heads=[b"aa" * 20],
        )

    def test_log_shallow(self):
        # Check that bzr log does not fail and includes the revision.
        output, error = self.run_bzr(["log", "gitr"], retcode=3)
        self.assertEqual(error, "brz: ERROR: Further revision history missing.\n")
        self.assertEqual(
            output,
            "------------------------------------------------------------\n"
            "revision-id: git-v1:" + self.repo.head().decode("ascii") + "\n"
            "git commit: " + self.repo.head().decode("ascii") + "\n"
            "committer: Somebody <user@example.com>\n"
            "timestamp: Mon 2018-05-14 20:36:05 +0000\n"
            "message:\n"
            "  message\n",
        )

    def test_version_info_rio(self):
        output, error = self.run_bzr(["version-info", "--rio", "gitr"])
        self.assertEqual(error, "")
        self.assertNotIn("revno:", output)

    def test_version_info_python(self):
        output, error = self.run_bzr(["version-info", "--python", "gitr"])
        self.assertEqual(error, "")
        self.assertNotIn("revno:", output)

    def test_version_info_custom_with_revno(self):
        output, error = self.run_bzr(
            ["version-info", "--custom", "--template=VERSION_INFO r{revno})\n", "gitr"],
            retcode=3,
        )
        self.assertEqual(error, "brz: ERROR: Variable {revno} is not available.\n")
        self.assertEqual(output, "VERSION_INFO r")

    def test_version_info_custom_without_revno(self):
        output, error = self.run_bzr(
            ["version-info", "--custom", "--template=VERSION_INFO \n", "gitr"]
        )
        self.assertEqual(error, "")
        self.assertEqual(output, "VERSION_INFO \n")


class SwitchTests(ExternalBase):
    def test_switch_branch(self):
        # Create a git repository with a revision.
        repo = GitRepo.init(self.test_dir)
        builder = tests.GitBranchBuilder()
        builder.set_branch(b"refs/heads/oldbranch")
        builder.set_file("a", b"text for a\n", False)
        builder.commit(b"Joe Foo <joe@foo.com>", "<The commit message>")
        builder.set_branch(b"refs/heads/newbranch")
        builder.reset()
        builder.set_file("a", b"text for new a\n", False)
        builder.commit(b"Joe Foo <joe@foo.com>", "<The commit message>")
        builder.finish()

        repo.refs.set_symbolic_ref(b"HEAD", b"refs/heads/newbranch")

        repo.get_worktree().reset_index()

        output, error = self.run_bzr("switch oldbranch")
        self.assertEqual(output, "")
        self.assertTrue(error.startswith("Updated to revision 1.\n"), error)

        self.assertFileEqual("text for a\n", "a")
        tree = WorkingTree.open(".")
        with tree.lock_read():
            basis_tree = tree.basis_tree()
            with basis_tree.lock_read():
                self.assertEqual([], list(tree.iter_changes(basis_tree)))

    def test_branch_with_nested_trees(self):
        orig = self.make_branch_and_tree("source", format="git")
        subtree = self.make_branch_and_tree("source/subtree", format="git")
        self.build_tree(["source/subtree/a"])
        self.build_tree_contents(
            [
                (
                    "source/.gitmodules",
                    """\
[submodule "subtree"]
    path = subtree
    url = {}
""".format(subtree.user_url),
                )
            ]
        )
        subtree.add(["a"])
        subtree.commit("add subtree contents")
        orig.add_reference(subtree)
        orig.add([".gitmodules"])
        orig.commit("add subtree")

        self.run_bzr("branch source target")

        target = WorkingTree.open("target")
        target_subtree = WorkingTree.open("target/subtree")
        self.assertTreesEqual(orig, target)
        self.assertTreesEqual(subtree, target_subtree)


class SwitchScriptTests(TestCaseWithTransportAndScript):
    def test_switch_preserves(self):
        # See https://bugs.launchpad.net/brz/+bug/1820606
        self.run_script("""
$ brz init --git r
Created a standalone tree (format: git)
$ cd r
$ echo original > file.txt
$ brz add
adding file.txt
$ brz ci -q -m "Initial"
$ echo "entered on master branch" > file.txt
$ brz stat
modified:
  file.txt
$ brz switch -b other
2>Tree is up to date at revision 1.
2>Switched to branch other
$ cat file.txt
entered on master branch
""")


class GrepTests(ExternalBase):
    def test_simple_grep(self):
        tree = self.make_branch_and_tree(".", format="git")
        self.build_tree_contents([("a", "text for a\n")])
        tree.add(["a"])
        output, error = self.run_bzr("grep text")
        self.assertEqual(output, "a:text for a\n")
        self.assertEqual(error, "")


class ReconcileTests(ExternalBase):
    def test_simple_reconcile(self):
        tree = self.make_branch_and_tree(".", format="git")
        self.build_tree_contents([("a", "text for a\n")])
        tree.add(["a"])
        output, error = self.run_bzr("reconcile")
        self.assertContainsRe(
            output,
            "Reconciling branch file://.*\n"
            "Reconciling repository file://.*\n"
            "Reconciliation complete.\n",
        )
        self.assertEqual(error, "")


class StatusTests(ExternalBase):
    def test_empty_dir(self):
        tree = self.make_branch_and_tree(".", format="git")
        self.build_tree(["a/", "a/foo"])
        self.build_tree_contents([(".gitignore", "foo\n")])
        tree.add([".gitignore"])
        tree.commit("add ignore")
        output, error = self.run_bzr("st")
        self.assertEqual(output, "")
        self.assertEqual(error, "")


class StatsTests(ExternalBase):
    def test_simple_stats(self):
        self.requireFeature(PluginLoadedFeature("stats"))
        tree = self.make_branch_and_tree(".", format="git")
        self.build_tree_contents([("a", "text for a\n")])
        tree.add(["a"])
        tree.commit("a commit", committer="Somebody <somebody@example.com>")
        output, _error = self.run_bzr("stats")
        self.assertEqual(output, "   1 Somebody <somebody@example.com>\n")


class GitObjectsTests(ExternalBase):
    def run_simple(self, format):
        tree = self.make_branch_and_tree(".", format=format)
        self.build_tree(["a/", "a/foo"])
        tree.add(["a"])
        tree.commit("add a")
        output, error = self.run_bzr("git-objects")
        shas = list(output.splitlines())
        self.assertEqual([40, 40], [len(s) for s in shas])
        self.assertEqual(error, "")

        output, error = self.run_bzr("git-object {}".format(shas[0]))
        self.assertEqual("", error)

    def test_in_native(self):
        self.run_simple(format="git")

    def test_in_bzr(self):
        self.run_simple(format="2a")


class GitApplyTests(ExternalBase):
    def test_apply(self):
        self.make_branch_and_tree(".")

        with open("foo.patch", "w") as f:
            f.write("""\
From bdefb25fab801e6af0a70e965f60cb48f2b759fa Mon Sep 17 00:00:00 2001
From: Dmitry Bogatov <KAction@debian.org>
Date: Fri, 8 Feb 2019 23:28:30 +0000
Subject: [PATCH] Add fixed for out-of-date-standards-version

---
 message           | 3 +++
 1 files changed, 14 insertions(+)
 create mode 100644 message

diff --git a/message b/message
new file mode 100644
index 0000000..05ec0b1
--- /dev/null
+++ b/message
@@ -0,0 +1,3 @@
+Update standards version, no changes needed.
+Certainty: certain
+Fixed-Lintian-Tags: out-of-date-standards-version
""")
        _output, error = self.run_bzr("git-apply foo.patch")
        self.assertContainsRe(error, "Committing to: .*\nCommitted revision 1.\n")
