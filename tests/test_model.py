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
from bzrlib.plugins.git.gitlib import (
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

    def test_ancestors(self):
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
        revisions = revisions.splitlines()
        graph = {revisions[0]:[revisions[2], revisions[1]],
                 revisions[1]:[revisions[3]],
                 revisions[2]:[revisions[3]],
                 revisions[3]:[],
                }

        themodel = model.GitModel('.git')
        self.assertEqual(graph, themodel.ancestry([revisions[0]]))
