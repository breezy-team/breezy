# Copyright (C) 2005, 2006 Canonical Ltd
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

from bzrlib.tests.blackbox import ExternalBase


class TestAdd(ExternalBase):
        
    def test_add_reports(self):
        """add command prints the names of added files."""
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
                           'ignored 1 file(s).'],
                          results)
        out = self.run_bzr_captured(['add', '-v'], retcode=0)[0]
        results = sorted(out.rstrip('\n').split('\n'))
        self.assertEquals(['If you wish to add some of these files, please'\
                           ' add them by name.',
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

    def test_add_from(self):
        base_tree = self.make_branch_and_tree('base')
        self.build_tree(['base/a', 'base/b/', 'base/b/c'])
        base_tree.add(['a', 'b', 'b/c'])
        base_tree.commit('foo')

        new_tree = self.make_branch_and_tree('new')
        self.build_tree(['new/a', 'new/b/', 'new/b/c', 'd'])

        os.chdir('new')
        out, err = self.run_bzr('add', '--file-ids-from', '../base')
        self.assertEqual('', err)
        self.assertEqualDiff('added a w/ file id from a\n'
                             'added b w/ file id from b\n'
                             'added b/c w/ file id from b/c\n',
                             out)

        new_tree.read_working_inventory()
        self.assertEqual(base_tree.path2id('a'), new_tree.path2id('a'))
        self.assertEqual(base_tree.path2id('b'), new_tree.path2id('b'))
        self.assertEqual(base_tree.path2id('b/c'), new_tree.path2id('b/c'))

    def test_add_from_subdir(self):
        base_tree = self.make_branch_and_tree('base')
        self.build_tree(['base/a', 'base/b/', 'base/b/c', 'base/b/d'])
        base_tree.add(['a', 'b', 'b/c', 'b/d'])
        base_tree.commit('foo')

        new_tree = self.make_branch_and_tree('new')
        self.build_tree(['new/c', 'new/d'])

        os.chdir('new')
        out, err = self.run_bzr('add', '--file-ids-from', '../base/b')
        self.assertEqual('', err)
        self.assertEqualDiff('added c w/ file id from b/c\n'
                             'added d w/ file id from b/d\n',
                             out)

        new_tree.read_working_inventory()
        self.assertEqual(base_tree.path2id('b/c'), new_tree.path2id('c'))
        self.assertEqual(base_tree.path2id('b/d'), new_tree.path2id('d'))

    def test_add_dry_run(self):
        # ensure that --dry-run actually don't add anything
        base_tree = self.make_branch_and_tree('.')
        self.build_tree(['spam'])
        out = self.run_bzr_captured(['add', '--dry-run'], retcode=0)[0]
        self.assertEquals('added spam\n', out)
        out = self.run_bzr_captured(['added'], retcode=0)[0]
        self.assertEquals('', out)
