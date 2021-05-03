# Copyright (C) 2009 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Test the BranchMapper methods."""

from .... import tests

from .. import (
    branch_mapper,
    )

from . import (
    FastimportFeature,
    )


class TestBranchMapper(tests.TestCase):

    _test_needs_features = [FastimportFeature]

    def test_git_to_bzr(self):
        m = branch_mapper.BranchMapper()
        for git, bzr in {
                b'refs/heads/master': 'trunk',
                b'refs/heads/foo': 'foo',
                b'refs/tags/master': 'trunk.tag',
                b'refs/tags/foo': 'foo.tag',
                b'refs/remotes/origin/master': 'trunk.remote',
                b'refs/remotes/origin/foo': 'foo.remote',
                }.items():
            self.assertEqual(m.git_to_bzr(git), bzr)

    def test_git_to_bzr_with_slashes(self):
        m = branch_mapper.BranchMapper()
        for git, bzr in {
                b'refs/heads/master/slave': 'master/slave',
                b'refs/heads/foo/bar': 'foo/bar',
                b'refs/tags/master/slave': 'master/slave.tag',
                b'refs/tags/foo/bar': 'foo/bar.tag',
                b'refs/remotes/origin/master/slave': 'master/slave.remote',
                b'refs/remotes/origin/foo/bar': 'foo/bar.remote',
                }.items():
            self.assertEqual(m.git_to_bzr(git), bzr)

    def test_git_to_bzr_for_trunk(self):
        # As 'master' in git is mapped to trunk in bzr, we need to handle
        # 'trunk' in git in a sensible way.
        m = branch_mapper.BranchMapper()
        for git, bzr in {
                b'refs/heads/trunk': 'git-trunk',
                b'refs/tags/trunk': 'git-trunk.tag',
                b'refs/remotes/origin/trunk': 'git-trunk.remote',
                b'refs/heads/git-trunk': 'git-git-trunk',
                b'refs/tags/git-trunk': 'git-git-trunk.tag',
                b'refs/remotes/origin/git-trunk': 'git-git-trunk.remote',
                }.items():
            self.assertEqual(m.git_to_bzr(git), bzr)
