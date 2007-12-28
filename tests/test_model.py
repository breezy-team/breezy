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

"""Test the model for interacting with the git process, etc."""

from bzrlib.plugins.git import tests
from bzrlib.plugins.git import (
    errors,
    model,
    )


class TestModel(tests.TestCaseInTempDir):

    def test_no_head(self):
        tests.run_git('init')
        themodel = model.GitModel('.git')
        self.assertIs(None, themodel.get_head())

    def test_no_repository(self):
        themodel = model.GitModel('.git')
        self.assertRaises(errors.GitCommandError, themodel.get_head)

    def test_get_revision_graph(self):
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

        graph = {revisions[0]:[revisions[2], revisions[1]],
                 revisions[1]:[revisions[3]],
                 revisions[2]:[revisions[3]],
                 revisions[3]:[],
                }

        themodel = model.GitModel('.git')
        self.assertEqual(revisions[0], themodel.get_head())
        self.assertEqual(graph, themodel.get_revision_graph([revisions[0]]))

    def test_get_inventory(self):
        # Create a git repository with some interesting files in a revision.
        tests.run_git('init')
        builder = tests.GitBranchBuilder()
        builder.set_file('data', 'text\n', False)
        builder.set_file('data-multi\nline', 'text\n', False)
        builder.set_file(u'data-unic\xb5de', 'text\n', False)
        builder.set_file('executable', 'content', True)
        builder.set_link('link', 'broken')
        builder.set_file('subdir/subfile', 'subdir text\n', False)
        commit_handle = builder.commit('Joe Foo <joe@foo.com>', u'message')
        mapping = builder.finish()
        commit_id = mapping[commit_handle]

        # Get the corresponding git inventory.
        themodel = model.GitModel('.git')
        git_inventory = list(themodel.get_inventory(commit_id))
        self.assertEqual(git_inventory,
            [('100644', 'blob', '8e27be7d6154a1f68ea9160ef0e18691d20560dc',
              u'data'),
             ('100644', 'blob', '8e27be7d6154a1f68ea9160ef0e18691d20560dc',
              u'data-multi\nline'),
             ('100644', 'blob', '8e27be7d6154a1f68ea9160ef0e18691d20560dc',
              u'data-unic\xb5de'),
             ('100755', 'blob', '6b584e8ece562ebffc15d38808cd6b98fc3d97ea',
              u'executable'),
             ('120000', 'blob', '86a410dd1d337c4f9f59e2aa35bc188f18ad08e4',
              u'link'),
             ('040000', 'tree', 'ccf7f8fa4e6eee68d761f36556d9896938b32e7f',
              u'subdir'),
             ('100644', 'blob', '0ddb53cbe2dd209f550dd8d7f1287a5ed9b1ee8b',
              u'subdir/subfile')])
