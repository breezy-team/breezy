# Copyright (C) 2005, 2006 by Canonical Ltd
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
#

"""Tests of the 'bzr add' command."""

import os

from bzrlib import ignores

from bzrlib.tests.blackbox import ExternalBase


class TestAdd(ExternalBase):
        
    def test_add_reports(self):
        """add command prints the names of added files."""
        ignores.set_user_ignores(['./.bazaar'])

        self.runbzr('init')
        self.build_tree(['top.txt', 'dir/', 'dir/sub.txt', 'CVS'])
        self.build_tree_contents([('.bzrignore', 'CVS\n')])
        out = self.run_bzr_captured(['add'], retcode=0)[0]
        # the ordering is not defined at the moment
        results = sorted(out.rstrip('\n').split('\n'))
        self.assertEquals(['If you wish to add some of these files, please'\
                           ' add them by name.',
                           'added .bzrignore',
                           'added dir',
                           'added dir/sub.txt',
                           'added top.txt',
                           'ignored 2 file(s).'],
                          results)
        out = self.run_bzr_captured(['add', '-v'], retcode=0)[0]
        results = sorted(out.rstrip('\n').split('\n'))
        self.assertEquals(['If you wish to add some of these files, please'\
                           ' add them by name.',
                           'ignored .bazaar matching "./.bazaar"',
                           'ignored CVS matching "CVS"'],
                          results)

    def test_add_quiet_is(self):
        """add -q does not print the names of added files."""
        self.runbzr('init')
        self.build_tree(['top.txt', 'dir/', 'dir/sub.txt'])
        out = self.run_bzr_captured(['add', '-q'], retcode=0)[0]
        # the ordering is not defined at the moment
        results = sorted(out.rstrip('\n').split('\n'))
        self.assertEquals([''], results)

    def test_add_in_unversioned(self):
        """Try to add a file in an unversioned directory.

        "bzr add" should add the parent(s) as necessary.
        """
        ignores.set_user_ignores(['./.bazaar'])

        self.runbzr('init')
        self.build_tree(['inertiatic/', 'inertiatic/esp'])
        self.assertEquals(self.capture('unknowns'), 'inertiatic\n')
        self.run_bzr('add', 'inertiatic/esp')
        self.assertEquals(self.capture('unknowns'), '')

        # Multiple unversioned parents
        self.build_tree(['veil/', 'veil/cerpin/', 'veil/cerpin/taxt'])
        self.assertEquals(self.capture('unknowns'), 'veil\n')
        self.run_bzr('add', 'veil/cerpin/taxt')
        self.assertEquals(self.capture('unknowns'), '')

        # Check whacky paths work
        self.build_tree(['cicatriz/', 'cicatriz/esp'])
        self.assertEquals(self.capture('unknowns'), 'cicatriz\n')
        self.run_bzr('add', 'inertiatic/../cicatriz/esp')
        self.assertEquals(self.capture('unknowns'), '')

    def test_add_in_versioned(self):
        """Try to add a file in a versioned directory.

        "bzr add" should do this happily.
        """
        ignores.set_user_ignores(['./.bazaar'])

        self.runbzr('init')
        self.build_tree(['inertiatic/', 'inertiatic/esp'])
        self.assertEquals(self.capture('unknowns'), 'inertiatic\n')
        self.run_bzr('add', '--no-recurse', 'inertiatic')
        self.assertEquals(self.capture('unknowns'), 'inertiatic/esp\n')
        self.run_bzr('add', 'inertiatic/esp')
        self.assertEquals(self.capture('unknowns'), '')

    def test_subdir_add(self):
        """Add in subdirectory should add only things from there down"""
        from bzrlib.workingtree import WorkingTree

        ignores.set_user_ignores(['./.bazaar'])
        eq = self.assertEqual
        ass = self.assertTrue
        chdir = os.chdir
        
        t = self.make_branch_and_tree('.')
        b = t.branch
        self.build_tree(['src/', 'README'])
        
        eq(sorted(t.unknowns()),
           ['README', 'src'])
        
        self.run_bzr('add', 'src')
        
        self.build_tree(['src/foo.c'])
        
        chdir('src')
        self.run_bzr('add')
        
        self.assertEquals(self.capture('unknowns'), 'README\n')
        eq(len(t.read_working_inventory()), 3)
                
        chdir('..')
        self.run_bzr('add')
        self.assertEquals(self.capture('unknowns'), '')
        self.run_bzr('check')

    def test_add_missing(self):
        """bzr add foo where foo is missing should error."""
        self.make_branch_and_tree('.')
        self.run_bzr('add', 'missing-file', retcode=3)
