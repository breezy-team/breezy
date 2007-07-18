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

import sys

from bzrlib.tests import TestCaseInTempDir, Feature
from bzrlib.win32utils import glob_expand


# Features
# --------

class _Win32Feature(Feature):

    def _probe(self):
        return sys.platform != 'win32'
    
    def feature_name(self):
        return 'Win32 platform'

Win32Feature = _Win32Feature()


# Tests
# -----
   
class TestWin32UtilsGlobExpand(TestCaseInTempDir):

    def setUp(self):
        super(TestWin32UtilsGlobExpand, self).setUp()
        self.requireFeature(Win32Feature)
   
    def test_empty_tree(self):
        self.build_tree([])
        self._run_testset([
            [['a'], ['a']],
            [['?'], ['?']],
            [['*'], ['*']],
            [['a', 'a'], ['a', 'a']]])
        
    def test_tree1(self):
        self.build_tree(['a', 'a1', 'a2', 'a11', 'a.1',
                         'b', 'b1', 'b2', 'b3',
                         'c/', 'c/c1', 'c/c2', 
                         'd/', 'd/d1', 'd/d2', 'd/e/', 'd/e/e1'])
        self._run_testset([
            # no wildcards
            [['a'], ['a']],
            [['a', 'a' ], ['a', 'a']],
            [['A'], ['A']],
                
            [['d'], ['d']],
            [['d/'], ['d/']],
            [['d\\'], ['d/']],
               
            # wildcards
            [['a*'], ['a', 'a1', 'a2', 'a11', 'a.1']],
            [['?'], ['a', 'b', 'c', 'd']],
            [['a?'], ['a1', 'a2']],
            [['a??'], ['a11', 'a.1']],
            [['b[1-2]'], ['b1', 'b2']],
            [['A?'], ['a1', 'a2']],
               
            [['d/*'], ['d/d1', 'd/d2', 'd/e']],
            [['d\\*'], ['d/d1', 'd/d2', 'd/e']],
            [['?\\*'], ['c/c1', 'c/c2', 'd/d1', 'd/d2', 'd/e']],
            [['*\\*'], ['c/c1', 'c/c2', 'd/d1', 'd/d2', 'd/e']],
            [['*/'], ['c/', 'd/']],
            [['*\\'], ['c/', 'd/']]])
        
    def _run_testset(self, testset):
        for pattern, expected in testset:
            result = glob_expand(pattern)
            expected.sort()
            result.sort()
            self.assertEqual(expected, result, 'pattern %s' % pattern)

