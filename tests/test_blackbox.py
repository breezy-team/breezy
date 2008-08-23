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

import os

from bzrlib.tests import KnownFailure
from bzrlib.tests.blackbox import ExternalBase

from bzrlib.plugins.git import (
    tests,
    )


class TestGitBlackBox(ExternalBase):

    def simple_commit(self):
        # Create a git repository with a revision.
        tests.run_git('init')
        builder = tests.GitBranchBuilder()
        builder.set_file('a', 'text for a\n', False)
        builder.commit('Joe Foo <joe@foo.com>', u'<The commit message>')
        builder.finish()

    def test_info(self):
        self.simple_commit()
        output, error = self.run_bzr(['info'])
        self.assertEqual(error, '')
        self.assertTrue("Repository tree (format: git)" in output)

    def test_branch(self):
        os.mkdir("gitbranch")
        os.chdir("gitbranch")
        tests.run_git('init')
        builder = tests.GitBranchBuilder()
        builder.set_file('a', 'text for a\n', False)
        builder.commit('Joe Foo <joe@foo.com>', u'<The commit message>')
        builder.finish()

        os.chdir("..")
        output, error = self.run_bzr(['branch', 'gitbranch', 'bzrbranch'])
        self.assertEqual(error, 'Branched 1 revision(s).\n')
        self.assertEqual(output, '')

    def test_branch_ls(self):
        self.simple_commit()
        output, error = self.run_bzr(['ls', '-r-1'])
        self.assertEqual(error, '')
        self.assertEqual(output, "a\n")

    def test_info_verbose(self):
        self.simple_commit()

        output, error = self.run_bzr(['info', '-v'])
        self.assertEqual(error, '')
        self.assertTrue("Repository tree (format: git)" in output)
        self.assertTrue("control: Local Git Repository" in output)
        self.assertTrue("branch: Git Branch" in output)
        self.assertTrue("repository: Git Repository" in output)

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
        self.simple_commit()

        tests.run_git("tag", "foo")

        output, error = self.run_bzr(['tags'])
        self.assertEquals(error, '')
        self.assertEquals(output, "foo                  1\n")

    def test_tag(self):
        raise KnownFailure("setting tags not supported by git-python yet")
        self.simple_commit()

        output, error = self.run_bzr(["tag", "bar"])

        self.assertEquals(error, '')
        self.assertEquals(output, '')

