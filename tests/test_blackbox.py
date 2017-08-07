# Copyright (C) 2007 David Allouche <ddaa@ddaa.net>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Black-box tests for bzr-git."""

from dulwich.repo import (
    Repo as GitRepo,
    )

import os

from .... import (
    version_info as breezy_version,
    )
from ....controldir import (
    ControlDir,
    )

from ....tests.blackbox import ExternalBase

from .. import (
    tests,
    )


class TestGitBlackBox(ExternalBase):

    def simple_commit(self):
        # Create a git repository with a revision.
        repo = GitRepo.init(self.test_dir)
        builder = tests.GitBranchBuilder()
        builder.set_file('a', 'text for a\n', False)
        r1 = builder.commit('Joe Foo <joe@foo.com>', u'<The commit message>')
        return repo, builder.finish()[r1]

    def test_nick(self):
        r = GitRepo.init(self.test_dir)
        del r["HEAD"]
        dir = ControlDir.open(self.test_dir)
        dir.create_branch()
        output, error = self.run_bzr(['nick'])
        self.assertEquals("HEAD\n", output)

    def test_info(self):
        self.simple_commit()
        output, error = self.run_bzr(['info'])
        self.assertEqual(error, '')
        self.assertTrue("Standalone tree (format: git)" in output)

    def test_branch(self):
        os.mkdir("gitbranch")
        GitRepo.init(os.path.join(self.test_dir, "gitbranch"))
        os.chdir('gitbranch')
        builder = tests.GitBranchBuilder()
        builder.set_file('a', 'text for a\n', False)
        builder.commit('Joe Foo <joe@foo.com>', u'<The commit message>')
        builder.finish()
        os.chdir('..')

        output, error = self.run_bzr(['branch', 'gitbranch', 'bzrbranch'])
        self.assertTrue(
            (error == 'Branched 1 revision(s).\n') or
            (error == 'Branched 1 revision.\n'),
            error)

    def test_checkout(self):
        os.mkdir("gitbranch")
        GitRepo.init(os.path.join(self.test_dir, "gitbranch"))
        os.chdir('gitbranch')
        builder = tests.GitBranchBuilder()
        builder.set_file('a', 'text for a\n', False)
        builder.commit('Joe Foo <joe@foo.com>', u'<The commit message>')
        builder.finish()
        os.chdir('..')

        output, error = self.run_bzr(['checkout', 'gitbranch', 'bzrbranch'])
        self.assertEqual(error, '')
        self.assertEqual(output, '')

    def test_branch_ls(self):
        self.simple_commit()
        output, error = self.run_bzr(['ls', '-r-1'])
        self.assertEqual(error, '')
        self.assertEqual(output, "a\n")

    def test_init(self):
        self.run_bzr("init --format=git repo")

    def test_info_verbose(self):
        self.simple_commit()

        output, error = self.run_bzr(['info', '-v'])
        self.assertEqual(error, '')
        self.assertTrue("Standalone tree (format: git)" in output)
        self.assertTrue("control: Local Git Repository" in output)
        self.assertTrue("branch: Git Branch" in output)
        self.assertTrue("repository: Git Repository" in output)

    def test_push_roundtripping(self):
        self.knownFailure("roundtripping is not yet supported")
        self.with_roundtripping()
        os.mkdir("bla")
        GitRepo.init(os.path.join(self.test_dir, "bla"))
        self.run_bzr(['init', 'foo'])
        self.run_bzr(['commit', '--unchanged', '-m', 'bla', 'foo'])
        # when roundtripping is supported
        output, error = self.run_bzr(['push', '-d', 'foo', 'bla'])
        self.assertEquals("", output)
        self.assertTrue(error.endswith("Created new branch.\n"))

    def test_log(self):
        # Smoke test for "bzr log" in a git repository.
        self.simple_commit()

        # Check that bzr log does not fail and includes the revision.
        output, error = self.run_bzr(['log'])
        self.assertEqual(error, '')
        self.assertTrue(
            '<The commit message>' in output,
            "Commit message was not found in output:\n%s" % (output,))

    def test_log_verbose(self):
        # Smoke test for "bzr log -v" in a git repository.
        self.simple_commit()

        # Check that bzr log does not fail and includes the revision.
        output, error = self.run_bzr(['log', '-v'])
 
    def test_tags(self):
        git_repo, commit_sha1 = self.simple_commit()
        git_repo.refs["refs/tags/foo"] = commit_sha1

        output, error = self.run_bzr(['tags'])
        self.assertEquals(error, '')
        self.assertEquals(output, "foo                  1\n")

    def test_tag(self):
        self.simple_commit()

        output, error = self.run_bzr(["tag", "bar"])

        # bzr <= 2.2 emits this message in the output stream
        # bzr => 2.3 emits this message in the error stream
        self.assertEquals(error + output, 'Created tag bar.\n')

    def test_init_repo(self):
        output, error = self.run_bzr(["init", "--format=git", "bla.git"])
        self.assertEquals(error, '')
        self.assertEquals(output, 'Created a standalone tree (format: git)\n')

    def test_diff_format(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'])
        output, error = self.run_bzr(['diff', '--format=git'], retcode=1)
        self.assertEqual(error, '')
        self.assertEqual(output,
            'diff --git /dev/null b/a\n'
            'old mode 0\n'
            'new mode 100644\n'
            'index 0000000..c197bd8 100644\n'
            '--- /dev/null\n'
            '+++ b/a\n'
            '@@ -0,0 +1 @@\n'
            '+contents of a\n')

    def test_git_import_uncolocated(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        r.stage("file")
        r.do_commit(ref="refs/heads/abranch", committer="Joe <joe@example.com>", message="Dummy")
        r.do_commit(ref="refs/heads/bbranch", committer="Joe <joe@example.com>", message="Dummy")
        self.run_bzr(["git-import", "a", "b"])
        self.assertEquals(set([".bzr", "abranch", "bbranch"]), set(os.listdir("b")))

    def test_git_import(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        r.stage("file")
        r.do_commit(ref="refs/heads/abranch", committer="Joe <joe@example.com>", message="Dummy")
        r.do_commit(ref="refs/heads/bbranch", committer="Joe <joe@example.com>", message="Dummy")
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEquals(set([".bzr"]), set(os.listdir("b")))
        self.assertEquals(set(["abranch", "bbranch"]),
                set(ControlDir.open("b").get_branches().keys()))

    def test_git_import_incremental(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        r.stage("file")
        r.do_commit(ref="refs/heads/abranch", committer="Joe <joe@example.com>", message="Dummy")
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEquals(set([".bzr"]), set(os.listdir("b")))
        b = ControlDir.open("b")
        self.assertEquals(["abranch"], b.get_branches().keys())

    def test_git_import_tags(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        r.stage("file")
        cid = r.do_commit(ref="refs/heads/abranch", committer="Joe <joe@example.com>", message="Dummy")
        r["refs/tags/atag"] = cid
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEquals(set([".bzr"]), set(os.listdir("b")))
        b = ControlDir.open("b")
        self.assertEquals(["abranch"], b.get_branches().keys())
        self.assertEquals(["atag"],
                b.open_branch("abranch").tags.get_tag_dict().keys())

    def test_git_import_colo(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        r.stage("file")
        r.do_commit(ref="refs/heads/abranch", committer="Joe <joe@example.com>", message="Dummy")
        r.do_commit(ref="refs/heads/bbranch", committer="Joe <joe@example.com>", message="Dummy")
        self.make_controldir("b", format="development-colo")
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEquals(
            set([b.name for b in ControlDir.open("b").list_branches()]),
            set(["abranch", "bbranch"]))

    def test_git_refs_from_git(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        r.stage("file")
        cid = r.do_commit(ref="refs/heads/abranch", committer="Joe <joe@example.com>", message="Dummy")
        r["refs/tags/atag"] = cid
        (stdout, stderr) = self.run_bzr(["git-refs", "a"])
        self.assertEquals(stderr, "")
        self.assertEquals(stdout,
            'refs/tags/atag -> ' + cid + '\n'
            'refs/heads/abranch -> ' + cid + '\n')

    def test_git_refs_from_bzr(self):
        tree = self.make_branch_and_tree('a')
        self.build_tree(["a/file"])
        tree.add(["file"])
        revid = tree.commit(committer="Joe <joe@example.com>", message="Dummy")
        tree.branch.tags.set_tag("atag", revid)
        (stdout, stderr) = self.run_bzr(["git-refs", "a"])
        self.assertEquals(stderr, "")
        self.assertTrue("refs/tags/atag -> " in stdout)
        self.assertTrue("HEAD -> " in stdout)

    def test_dpush(self):
        r = GitRepo.init("gitr", mkdir=True)
        self.build_tree_contents([("gitr/foo", "hello from git")])
        r.stage("foo")
        r.do_commit("message", committer="Somebody <user@example.com>")
        self.run_bzr(["branch", "gitr", "bzrb"])
        self.build_tree_contents([("bzrb/foo", "hello from bzr")])
        self.run_bzr(["commit", "-m", "msg", "bzrb"])
        self.run_bzr(["dpush", "-d", "bzrb", "gitr"])

    def test_dpush_from_bound(self):
        r = GitRepo.init("gitr", mkdir=True)
        self.build_tree_contents([("gitr/foo", "hello from git")])
        r.stage("foo")
        r.do_commit("message", committer="Somebody <user@example.com>")
        self.run_bzr(["branch", "gitr", "bzrm"])
        self.run_bzr(["checkout", "bzrm", "bzrb"])
        self.build_tree_contents([("bzrb/foo", "hello from bzr")])
        self.run_bzr(["commit", "-m", "msg", "bzrb"])
        self.run_bzr(["dpush", "-d", "bzrb", "gitr"])
