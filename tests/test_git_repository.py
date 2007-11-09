# Copyright (C) 2007 Canonical Ltd
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

"""Tests for interfacing with a Git Repository"""

import subprocess

from bzrlib import repository

from bzrlib.plugins.git import tests
from bzrlib.plugins.git.gitlib import (
    git_repository,
    ids,
    model,
    )


class TestGitRepository(tests.TestCaseInTempDir):

    _test_needs_features = [tests.GitCommandFeature]

    def test_open_existing(self):
        tests.run_git('init')

        repo = repository.Repository.open('.')
        self.assertIsInstance(repo, git_repository.GitRepository)

    def test_has_git_model(self):
        tests.run_git('init')

        repo = repository.Repository.open('.')
        self.assertIsInstance(repo._git, model.GitModel)

    def test_revision_graph(self):
        tests.run_git('init')
        self.build_tree(['a'])
        tests.run_git('add', 'a')
        tests.run_git('commit', '-m', 'a')
        tests.run_git('branch', 'foo')
        self.build_tree_contents([('a', 'new a\n')])
        tests.run_git('commit', '-a', '-m', 'new a')
        tests.run_git('checkout', 'foo')
        self.build_tree(['b'])
        tests.run_git('add', 'b')
        tests.run_git('commit', '-m', 'b')
        tests.run_git('merge', 'master')

        revisions = tests.run_git('rev-list', '--topo-order', 'HEAD')
        revisions = [ids.convert_revision_id_git_to_bzr(r)
                     for r in revisions.splitlines()]
        graph = {revisions[0]:[revisions[2], revisions[1]],
                 revisions[1]:[revisions[3]],
                 revisions[2]:[revisions[3]],
                 revisions[3]:[],
                }

        repo = repository.Repository.open('.')
        self.assertEqual(graph, repo.get_revision_graph(revisions[0]))
        self.assertEqual({revisions[3]:[]},
                         repo.get_revision_graph(revisions[3]))
