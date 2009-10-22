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
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test the BranchMapper methods."""

from bzrlib import tests

from bzrlib.plugins.fastimport import (
    branch_mapper,
    )


class TestBranchMapper(tests.TestCase):

    def test_git_to_bzr(self):
        m = branch_mapper.BranchMapper()
        git_refs = [
            'refs/heads/master',
            'refs/heads/foo',
            'refs/tags/master',
            'refs/tags/foo',
            'refs/remotes/origin/master',
            'refs/remotes/origin/foo',
            ]
        git_to_bzr_map = m.git_to_bzr(git_refs)
        self.assertEqual(git_to_bzr_map, {
            'refs/heads/master':                'trunk',
            'refs/heads/foo':                   'foo',
            'refs/tags/master':                 'trunk.tag',
            'refs/tags/foo':                    'foo.tag',
            'refs/remotes/origin/master':       'trunk.remote',
            'refs/remotes/origin/foo':          'foo.remote',
            })

    def test_git_to_bzr_with_slashes(self):
        m = branch_mapper.BranchMapper()
        git_refs = [
            'refs/heads/master/slave',
            'refs/heads/foo/bar',
            'refs/tags/master/slave',
            'refs/tags/foo/bar',
            'refs/remotes/origin/master/slave',
            'refs/remotes/origin/foo/bar',
            ]
        git_to_bzr_map = m.git_to_bzr(git_refs)
        self.assertEqual(git_to_bzr_map, {
            'refs/heads/master/slave':              'master/slave',
            'refs/heads/foo/bar':                   'foo/bar',
            'refs/tags/master/slave':               'master/slave.tag',
            'refs/tags/foo/bar':                    'foo/bar.tag',
            'refs/remotes/origin/master/slave':     'master/slave.remote',
            'refs/remotes/origin/foo/bar':          'foo/bar.remote',
            })

    def test_git_to_bzr_for_trunk(self):
        # As 'master' in git is mapped to trunk in bzr, we need to handle
        # 'trunk' in git in a sensible way.
        m = branch_mapper.BranchMapper()
        git_refs = [
            'refs/heads/trunk',
            'refs/tags/trunk',
            'refs/remotes/origin/trunk',
            'refs/heads/git-trunk',
            'refs/tags/git-trunk',
            'refs/remotes/origin/git-trunk',
            ]
        git_to_bzr_map = m.git_to_bzr(git_refs)
        self.assertEqual(git_to_bzr_map, {
            'refs/heads/trunk':             'git-trunk',
            'refs/tags/trunk':              'git-trunk.tag',
            'refs/remotes/origin/trunk':    'git-trunk.remote',
            'refs/heads/git-trunk':         'git-git-trunk',
            'refs/tags/git-trunk':          'git-git-trunk.tag',
            'refs/remotes/origin/git-trunk':'git-git-trunk.remote',
            })
