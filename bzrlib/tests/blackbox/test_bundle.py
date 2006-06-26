# Copyright (C) 2006 by Canonical Ltd
# Authors: Aaron Bentley
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


import os
from StringIO import StringIO

from bzrlib.bundle.serializer import read_bundle
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseInTempDir


class TestBundle(TestCaseInTempDir):

    def test_uses_parent(self):
        """Parent location is used as a basis by default"""
        
        parent_tree = BzrDir.create_standalone_workingtree('parent')
        parent_tree.commit('initial commit', rev_id='revision1')
        os.chdir('parent')
        errmsg = self.run_bzr('bundle', retcode=3)[1]
        self.assertContainsRe(errmsg, 'No base branch known or specified')
        branch_tree = parent_tree.bzrdir.sprout('../branch').open_workingtree()
        branch_tree.commit('next commit', rev_id='revision2')
        branch_tree.commit('last commit', rev_id='revision3')
        os.chdir('../branch')
        stdout, stderr = self.run_bzr('bundle')
        self.assertEqual(stderr.count('Using saved location'), 1)
        br = read_bundle(StringIO(stdout))
        self.assertEqual(br.revisions[0].revision_id, 'revision3')
        self.assertEqual(len(br.revisions), 2)
        self.assertEqual(br.revisions[1].revision_id, 'revision2')

    def test_uses_submit(self):
        """Submit location can be used and set"""
        
        submit_tree = BzrDir.create_standalone_workingtree('submit')
        submit_tree.commit('initial commit', rev_id='revision1')
        parent_tree = submit_tree.bzrdir.sprout('parent').open_workingtree()
        parent_tree.commit('next commit', rev_id='revision2')
        branch_tree = parent_tree.bzrdir.sprout('branch').open_workingtree()
        branch_tree.commit('last commit', rev_id='revision3')
        os.chdir('branch')
        br = read_bundle(StringIO(self.run_bzr('bundle')[0]))
        self.assertEqual(br.revisions[0].revision_id, 'revision3')
        self.assertEqual(len(br.revisions), 1)
        br = read_bundle(StringIO(self.run_bzr('bundle', '../submit')[0]))
        self.assertEqual(len(br.revisions), 2)
        # submit location should be auto-remembered
        br = read_bundle(StringIO(self.run_bzr('bundle')[0]))
        self.assertEqual(len(br.revisions), 2)
        self.run_bzr('bundle', '../parent')
        br = read_bundle(StringIO(self.run_bzr('bundle')[0]))
        self.assertEqual(len(br.revisions), 2)
        self.run_bzr('bundle', '../parent', '--remember')
        br = read_bundle(StringIO(self.run_bzr('bundle')[0]))
        self.assertEqual(len(br.revisions), 1)
        err = self.run_bzr('bundle', '--remember', retcode=3)[1]
        self.assertContainsRe(err, 
                              '--remember requires a branch to be specified.')
