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
from bzrlib.plugins.git import (
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
        builder = tests.GitBranchBuilder()
        file_handle = builder.set_file('a', 'text for a\n', False)
        commit1_handle = builder.commit('Joe Foo <joe@foo.com>', u'message')
        file2_handle = builder.set_file('a', 'new a\n', False)
        commit2_handle = builder.commit('Joe Foo <joe@foo.com>', u'new a')
        file3_handle = builder.set_file('b', 'text for b\n', False)
        commit3_handle = builder.commit('Jerry Bar <jerry@foo.com>', u'b',
                                        base=commit1_handle)
        commit4_handle = builder.commit('Jerry Bar <jerry@foo.com>', u'merge',
                                        base=commit3_handle,
                                        merge=[commit2_handle],)

        mapping = builder.finish()
        commit1_id = mapping[commit1_handle]
        commit2_id = mapping[commit2_handle]
        commit3_id = mapping[commit3_handle]
        commit4_id = mapping[commit4_handle]

        revisions = tests.run_git('rev-list', '--topo-order',
                                  commit4_id)
        revisions = revisions.splitlines()
        self.assertEqual([commit4_id, commit2_id, commit3_id, commit1_id],
                         revisions)
        bzr_revisions = [ids.convert_revision_id_git_to_bzr(r) for r in revisions]
        graph = {bzr_revisions[0]:[bzr_revisions[2], bzr_revisions[1]],
                 bzr_revisions[1]:[bzr_revisions[3]],
                 bzr_revisions[2]:[bzr_revisions[3]],
                 bzr_revisions[3]:[],
                }

        repo = repository.Repository.open('.')
        self.assertEqual(graph, repo.get_revision_graph(bzr_revisions[0]))
        self.assertEqual({bzr_revisions[3]:[]},
                         repo.get_revision_graph(bzr_revisions[3]))
