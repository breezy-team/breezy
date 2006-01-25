# Copyright (C) 2005 by Canonical Ltd

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
from bzrlib.missing import find_unmerged
from bzrlib.branch import Branch
from bzrlib.builtins import merge
from bzrlib.tests import TestCaseInTempDir
import os

class TestMissing(TestCaseInTempDir):
    def test_find_unmerged(self):
        os.mkdir('original')
        os.mkdir('puller')
        os.mkdir('merger')
        original = Branch.initialize('original')
        puller = Branch.initialize('puller')
        merger = Branch.initialize('merger')
        self.assertEqual(find_unmerged(original, puller), ([], []))
        original.working_tree().commit('a', rev_id='a')
        self.assertEqual(find_unmerged(original, puller), ([(1, u'a')], []))
        puller.pull(original)
        self.assertEqual(find_unmerged(original, puller), ([], []))
        merger.pull(original)
        original.working_tree().commit('b', rev_id='b')
        original.working_tree().commit('c', rev_id='c')
        self.assertEqual(find_unmerged(original, puller), ([(2, u'b'), 
                                                            (3, u'c')], []))

        puller.pull(original)
        self.assertEqual(find_unmerged(original, puller), ([], []))
        self.assertEqual(find_unmerged(original, merger), ([(2, u'b'), 
                                                            (3, u'c')], []))
        merge(['original', -1], [None, None], this_dir='merger')
        self.assertEqual(find_unmerged(original, merger), ([(2, u'b'), 
                                                            (3, u'c')], []))
        merger.working_tree().commit('d', rev_id='d')
        self.assertEqual(find_unmerged(original, merger), ([], [(2, 'd')]))
