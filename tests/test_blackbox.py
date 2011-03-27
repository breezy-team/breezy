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

from bzrlib.bzrdir import (
    BzrDir,
    )

from bzrlib.tests.blackbox import ExternalBase
from bzrlib.tests import KnownFailure

from bzrlib.plugins.git import (
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
        GitRepo.init(self.test_dir)
        dir = BzrDir.open(self.test_dir)
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
        self.assertEqual(error, 'Branched 1 revision(s).\n')

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
        self.run_bzr("init --git repo") 

    def test_info_verbose(self):
        self.simple_commit()

        output, error = self.run_bzr(['info', '-v'])
        self.assertEqual(error, '')
        self.assertTrue("Standalone tree (format: git)" in output)
        self.assertTrue("control: Local Git Repository" in output)
        self.assertTrue("branch: Git Branch" in output)
        self.assertTrue("repository: Git Repository" in output)

    def test_push(self):
        os.mkdir("bla")
        GitRepo.init(os.path.join(self.test_dir, "bla"))
        self.run_bzr(['init', 'foo'])
        self.run_bzr(['commit', '--unchanged', '-m', 'bla', 'foo'])
        output, error = self.run_bzr(['push', '-d', 'foo', 'bla'], retcode=3)
        raise KnownFailure("roundtripping is not supported")

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
        output, error = self.run_bzr(["init", "--git", "bla.git"])
        self.assertEquals(error, '')
        self.assertEquals(output, 'Created a standalone tree (format: git)\n')

