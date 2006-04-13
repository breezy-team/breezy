# Copyright (C) 2006 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Test "bzr init"""

import os

from bzrlib.bzrdir import BzrDirMetaFormat1
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestInit(ExternalBase):

    def test_init_with_format(self):
        """Verify bzr init --format constructs something plausible"""
        t = self.get_transport()
        self.runbzr('init --format metadir')
        self.assertIsDirectory('.bzr', t)
        self.assertIsDirectory('.bzr/checkout', t)
        self.assertIsDirectory('.bzr/checkout/lock', t)

    def test_init_at_repository_root(self):
        # bzr init at the root of a repository should create a branch
        # and working tree even when creation of working trees is disabled.
        t = self.get_transport()
        t.mkdir('repo')
        format = BzrDirMetaFormat1()
        newdir = format.initialize(t.abspath('repo'))
        repo = newdir.create_repository(shared=True)
        repo.set_make_working_trees(False)
        out, err = self.run_bzr('init', 'repo')
        self.assertEqual('', out)
        self.assertEqual('', err)
        newdir.open_branch()
        newdir.open_workingtree()
        
    def test_init_branch(self):
        out, err = self.run_bzr('init')
        self.assertEqual('', out)
        self.assertEqual('', err)

        # Can it handle subdirectories of branches too ?
        out, err = self.run_bzr('init', 'subdir1')
        self.assertEqual('', out)
        self.assertEqual('', err)
        WorkingTree.open('subdir1')
        
        out, err = self.run_bzr('init', 'subdir2/nothere', retcode=3)
        self.assertEqual('', out)
        self.failUnless(err.startswith(
            'bzr: ERROR: exceptions.OSError: '
            '[Errno 2] No such file or directory: '))
        
        os.mkdir('subdir2')
        out, err = self.run_bzr('init', 'subdir2')
        self.assertEqual('', out)
        self.assertEqual('', err)
        # init an existing branch.
        out, err = self.run_bzr('init', 'subdir2', retcode=3)
        self.assertEqual('', out)
        self.failUnless(err.startswith('bzr: ERROR: Already a branch:'))
