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

import os

from bzrlib import gpg, tests

class TestMergeDirective(tests.TestCaseWithTransport):

    def test_merge_directive(self):
        tree1 = self.make_branch_and_tree('tree1')
        self.build_tree_contents([('tree1/file', 'a\nb\nc\nd\n')])
        tree1.add('file')
        tree1.commit('foo')
        tree2=tree1.bzrdir.sprout('tree2').open_workingtree()
        self.build_tree_contents([('tree1/file', 'a\nb\nc\nd\ne\n')])
        tree1.commit('bar')
        os.chdir('tree1')
        self.run_bzr_error(('No submit branch',), 'merge-directive', retcode=3)
        self.run_bzr('merge-directive', '../tree2')
        md_text = self.run_bzr('merge-directive')[0]
        self.assertContainsRe(md_text, "Bazaar revision bundle")
        self.assertNotContainsRe(md_text, 'source_branch:')
        self.assertContainsRe(md_text, "\\+e")
        self.run_bzr_error(('No public branch',), 'merge-directive', '--diff',
                           retcode=3)
        self.run_bzr('merge-directive', '--diff', '../tree2', '.')
        md_text = self.run_bzr('merge-directive', '--diff')[0]
        self.assertNotContainsRe(md_text, "Bazaar revision bundle")
        self.assertContainsRe(md_text, "\\+e")
        md_text = self.run_bzr('merge-directive', '--plain')[0]
        self.assertNotContainsRe(md_text, "\\+e")
        md_text = self.run_bzr('merge-directive')[0]
        self.assertContainsRe(md_text, 'source_branch:')
        old_strategy = gpg.GPGStrategy
        gpg.GPGStrategy = gpg.LoopbackGPGStrategy
        try:
            md_text = self.run_bzr('merge-directive', '--sign')[0]
        finally:
            gpg.GPGStrategy = old_strategy
        self.assertContainsRe(md_text, '^-----BEGIN PSEUDO-SIGNED CONTENT')
        md_text = self.run_bzr('merge-directive', '-r', '-2')[0]
        self.assertNotContainsRe(md_text, "\\+e")
