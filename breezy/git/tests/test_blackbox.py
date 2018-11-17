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

from __future__ import absolute_import

from dulwich.repo import (
    Repo as GitRepo,
    )

import os

from ...controldir import (
    ControlDir,
    )

from ...tests.blackbox import ExternalBase
from ...workingtree import WorkingTree

from .. import (
    tests,
    )


class TestGitBlackBox(ExternalBase):

    def simple_commit(self):
        # Create a git repository with a revision.
        repo = GitRepo.init(self.test_dir)
        builder = tests.GitBranchBuilder()
        builder.set_file('a', b'text for a\n', False)
        r1 = builder.commit(b'Joe Foo <joe@foo.com>', u'<The commit message>')
        return repo, builder.finish()[r1]

    def test_nick(self):
        r = GitRepo.init(self.test_dir)
        dir = ControlDir.open(self.test_dir)
        dir.create_branch()
        output, error = self.run_bzr(['nick'])
        self.assertEqual("master\n", output)

    def test_branches(self):
        self.simple_commit()
        output, error = self.run_bzr(['branches'])
        self.assertEqual("* master\n", output)

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
        builder.set_file(b'a', b'text for a\n', False)
        builder.commit(b'Joe Foo <joe@foo.com>', b'<The commit message>')
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
        builder.set_file(b'a', b'text for a\n', False)
        builder.commit(b'Joe Foo <joe@foo.com>', b'<The commit message>')
        builder.finish()
        os.chdir('..')

        output, error = self.run_bzr(['checkout', 'gitbranch', 'bzrbranch'])
        self.assertEqual(error,
                         'Fetching from Git to Bazaar repository. '
                         'For better performance, fetch into a Git repository.\n')
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
        self.assertTrue("branch: Local Git Branch" in output)
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
        self.assertEqual(b"", output)
        self.assertTrue(error.endswith(b"Created new branch.\n"))

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
        git_repo.refs[b"refs/tags/foo"] = commit_sha1

        output, error = self.run_bzr(['tags'])
        self.assertEqual(error, '')
        self.assertEqual(output, "foo                  1\n")

    def test_tag(self):
        self.simple_commit()

        output, error = self.run_bzr(["tag", "bar"])

        # bzr <= 2.2 emits this message in the output stream
        # bzr => 2.3 emits this message in the error stream
        self.assertEqual(error + output, 'Created tag bar.\n')

    def test_init_repo(self):
        output, error = self.run_bzr(["init", "--format=git", "bla.git"])
        self.assertEqual(error, '')
        self.assertEqual(output, 'Created a standalone tree (format: git)\n')

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
        r.do_commit(ref=b"refs/heads/abranch",
                    committer=b"Joe <joe@example.com>", message=b"Dummy")
        r.do_commit(ref=b"refs/heads/bbranch",
                    committer=b"Joe <joe@example.com>", message=b"Dummy")
        self.run_bzr(["git-import", "a", "b"])
        self.assertEqual(
            set([".bzr", "abranch", "bbranch"]), set(os.listdir("b")))

    def test_git_import(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        r.stage("file")
        r.do_commit(ref=b"refs/heads/abranch",
                    committer=b"Joe <joe@example.com>", message=b"Dummy")
        r.do_commit(ref=b"refs/heads/bbranch",
                    committer=b"Joe <joe@example.com>", message=b"Dummy")
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEqual(set([".bzr"]), set(os.listdir("b")))
        self.assertEqual(set(["abranch", "bbranch"]),
                         set(ControlDir.open("b").get_branches().keys()))

    def test_git_import_incremental(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        r.stage("file")
        r.do_commit(ref=b"refs/heads/abranch",
                    committer=b"Joe <joe@example.com>", message=b"Dummy")
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEqual(set([".bzr"]), set(os.listdir("b")))
        b = ControlDir.open("b")
        self.assertEqual(["abranch"], list(b.get_branches().keys()))

    def test_git_import_tags(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        r.stage("file")
        cid = r.do_commit(ref=b"refs/heads/abranch",
                          committer=b"Joe <joe@example.com>", message=b"Dummy")
        r[b"refs/tags/atag"] = cid
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEqual(set([".bzr"]), set(os.listdir("b")))
        b = ControlDir.open("b")
        self.assertEqual(["abranch"], list(b.get_branches().keys()))
        self.assertEqual(["atag"],
                         list(b.open_branch("abranch").tags.get_tag_dict().keys()))

    def test_git_import_colo(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        r.stage("file")
        r.do_commit(ref=b"refs/heads/abranch",
                    committer=b"Joe <joe@example.com>", message=b"Dummy")
        r.do_commit(ref=b"refs/heads/bbranch",
                    committer=b"Joe <joe@example.com>", message=b"Dummy")
        self.make_controldir("b", format="development-colo")
        self.run_bzr(["git-import", "--colocated", "a", "b"])
        self.assertEqual(
            set([b.name for b in ControlDir.open("b").list_branches()]),
            set(["abranch", "bbranch"]))

    def test_git_refs_from_git(self):
        r = GitRepo.init("a", mkdir=True)
        self.build_tree(["a/file"])
        r.stage("file")
        cid = r.do_commit(ref=b"refs/heads/abranch",
                          committer=b"Joe <joe@example.com>", message=b"Dummy")
        r[b"refs/tags/atag"] = cid
        (stdout, stderr) = self.run_bzr(["git-refs", "a"])
        self.assertEqual(stderr, "")
        self.assertEqual(stdout,
                         'refs/heads/abranch -> ' + cid.decode('ascii') + '\n'
                         'refs/tags/atag -> ' + cid.decode('ascii') + '\n')

    def test_git_refs_from_bzr(self):
        tree = self.make_branch_and_tree('a')
        self.build_tree(["a/file"])
        tree.add(["file"])
        revid = tree.commit(
            committer=b"Joe <joe@example.com>", message=b"Dummy")
        tree.branch.tags.set_tag("atag", revid)
        (stdout, stderr) = self.run_bzr(["git-refs", "a"])
        self.assertEqual(stderr, "")
        self.assertTrue("refs/tags/atag -> " in stdout)
        self.assertTrue("HEAD -> " in stdout)

    def test_check(self):
        r = GitRepo.init("gitr", mkdir=True)
        self.build_tree_contents([("gitr/foo", b"hello from git")])
        r.stage("foo")
        r.do_commit(b"message", committer=b"Somebody <user@example.com>")
        out, err = self.run_bzr(["check", "gitr"])
        self.maxDiff = None
        self.assertEqual(out, '')
        self.assertTrue(err.endswith, '3 objects\n')


class ShallowTests(ExternalBase):

    def setUp(self):
        super(ShallowTests, self).setUp()
        # Smoke test for "bzr log" in a git repository with shallow depth.
        self.repo = GitRepo.init('gitr', mkdir=True)
        self.build_tree_contents([("gitr/foo", b"hello from git")])
        self.repo.stage("foo")
        self.repo.do_commit(
            b"message", committer=b"Somebody <user@example.com>",
            commit_timestamp=1526330165, commit_timezone=0,
            author_timestamp=1526330165, author_timezone=0,
            merge_heads=[b'aa' * 20])

    def test_log_shallow(self):
        # Check that bzr log does not fail and includes the revision.
        output, error = self.run_bzr(['log', 'gitr'], retcode=3)
        self.assertEqual(
            error, 'brz: ERROR: Further revision history missing.\n')
        self.assertEqual(output,
                         '------------------------------------------------------------\n'
                         'revision-id: git-v1:' + self.repo.head().decode('ascii') + '\n'
                         'git commit: ' + self.repo.head().decode('ascii') + '\n'
                         'committer: Somebody <user@example.com>\n'
                         'timestamp: Mon 2018-05-14 20:36:05 +0000\n'
                         'message:\n'
                         '  message\n')

    def test_version_info_rio(self):
        output, error = self.run_bzr(['version-info', '--rio', 'gitr'])
        self.assertEqual(error, '')
        self.assertNotIn('revno:', output)

    def test_version_info_python(self):
        output, error = self.run_bzr(['version-info', '--python', 'gitr'])
        self.assertEqual(error, '')
        self.assertNotIn('revno:', output)

    def test_version_info_custom_with_revno(self):
        output, error = self.run_bzr(
            ['version-info', '--custom',
             '--template=VERSION_INFO r{revno})\n', 'gitr'], retcode=3)
        self.assertEqual(
            error, 'brz: ERROR: Variable {revno} is not available.\n')
        self.assertEqual(output, 'VERSION_INFO r')

    def test_version_info_custom_without_revno(self):
        output, error = self.run_bzr(
            ['version-info', '--custom', '--template=VERSION_INFO \n',
             'gitr'])
        self.assertEqual(error, '')
        self.assertEqual(output, 'VERSION_INFO \n')


class SwitchTests(ExternalBase):

    def test_switch_branch(self):
        # Create a git repository with a revision.
        repo = GitRepo.init(self.test_dir)
        builder = tests.GitBranchBuilder()
        builder.set_branch(b'refs/heads/oldbranch')
        builder.set_file('a', b'text for a\n', False)
        builder.commit(b'Joe Foo <joe@foo.com>', u'<The commit message>')
        builder.set_branch(b'refs/heads/newbranch')
        builder.reset()
        builder.set_file('a', b'text for new a\n', False)
        builder.commit(b'Joe Foo <joe@foo.com>', u'<The commit message>')
        builder.finish()

        repo.refs.set_symbolic_ref(b'HEAD', b'refs/heads/newbranch')

        repo.reset_index()

        output, error = self.run_bzr('switch oldbranch')
        self.assertEqual(output, '')
        self.assertTrue(error.startswith('Updated to revision 1.\n'), error)

        self.assertFileEqual("text for a\n", 'a')
        tree = WorkingTree.open('.')
        with tree.lock_read():
            basis_tree = tree.basis_tree()
            with basis_tree.lock_read():
                self.assertEqual([], list(tree.iter_changes(basis_tree)))


class GrepTests(ExternalBase):

    def test_simple_grep(self):
        tree = self.make_branch_and_tree('.', format='git')
        self.build_tree_contents([('a', 'text for a\n')])
        tree.add(['a'])
        output, error = self.run_bzr('grep text')
        self.assertEqual(output, 'a:text for a\n')
        self.assertEqual(error, '')
