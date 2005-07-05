# Copyright (C) 2004, 2005 by Canonical Ltd

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


from bzrlib.selftest import InTempDir, TestBase
from bzrlib.merge3 import Merge3

class NoChanges(TestBase):
    """No conflicts because nothing changed"""
    def runTest(self):
        m3 = Merge3(['aaa', 'bbb'],
                    ['aaa', 'bbb'],
                    ['aaa', 'bbb'])

        self.assertEquals(m3.find_unconflicted(),
                          [(0, 2)])

        self.assertEquals(list(m3.find_sync_regions()),
                          [(0, 2,
                            0, 2,
                            0, 2),
                           (2,2, 2,2, 2,2)])

        self.assertEquals(list(m3.merge_regions()),
                          [('unchanged', 0, 2)])

        self.assertEquals(list(m3.merge_groups()),
                          [('unchanged', ['aaa', 'bbb'])])


class FrontInsert(TestBase):
    def runTest(self):
        m3 = Merge3(['zz'],
                    ['aaa', 'bbb', 'zz'],
                    ['zz'])

        # todo: should use a sentinal at end as from get_matching_blocks
        # to match without zz
        self.assertEquals(list(m3.find_sync_regions()),
                          [(0,1, 2,3, 0,1),
                           (1,1, 3,3, 1,1),])

        self.assertEquals(list(m3.merge_regions()),
                          [('a', 0, 2),
                           ('unchanged', 0, 1)])

        self.assertEquals(list(m3.merge_groups()),
                          [('a', ['aaa', 'bbb']),
                           ('unchanged', ['zz'])])
        
    

class NullInsert(TestBase):
    def runTest(self):
        m3 = Merge3([],
                    ['aaa', 'bbb'],
                    [])

        # todo: should use a sentinal at end as from get_matching_blocks
        # to match without zz
        self.assertEquals(list(m3.find_sync_regions()),
                          [(0,0, 2,2, 0,0)])

        self.assertEquals(list(m3.merge_regions()),
                          [('a', 0, 2)])

        self.assertEquals(list(m3.merge_lines()),
                          ['aaa', 'bbb'])
        
    

class NoConflicts(TestBase):
    """No conflicts because only one side changed"""
    def runTest(self):
        m3 = Merge3(['aaa', 'bbb'],
                    ['aaa', '111', 'bbb'],
                    ['aaa', 'bbb'])

        self.assertEquals(m3.find_unconflicted(),
                          [(0, 1), (1, 2)])

        self.assertEquals(list(m3.find_sync_regions()),
                          [(0,1, 0,1, 0,1),
                           (1,2, 2,3, 1,2),
                           (2,2, 3,3, 2,2),])

        self.assertEquals(list(m3.merge_regions()),
                          [('unchanged', 0, 1),
                           ('a', 1, 2),
                           ('unchanged', 1, 2),])



class InsertAgreement(TestBase):
    def runTest(self):
        m3 = Merge3(['aaa\n', 'bbb\n'],
                    ['aaa\n', '222\n', 'bbb\n'],
                    ['aaa\n', '222\n', 'bbb\n'])

        self.assertEquals(''.join(m3.merge_lines()),
                          'aaa\n222\nbbb\n')



class InsertClash(TestBase):
    """Both try to insert lines in the same place."""
    def runTest(self):
        m3 = Merge3(['aaa\n', 'bbb\n'],
                    ['aaa\n', '111\n', 'bbb\n'],
                    ['aaa\n', '222\n', 'bbb\n'])

        self.assertEquals(m3.find_unconflicted(),
                          [(0, 1), (1, 2)])

        self.assertEquals(list(m3.find_sync_regions()),
                          [(0,1, 0,1, 0,1),
                           (1,2, 2,3, 2,3),
                           (2,2, 3,3, 3,3),])

        self.assertEquals(list(m3.merge_regions()),
                          [('unchanged', 0,1),
                           ('conflict', 1,1, 1,2, 1,2),
                           ('unchanged', 1,2)])

        self.assertEquals(list(m3.merge_groups()),
                          [('unchanged', ['aaa\n']),
                           ('conflict', [], ['111\n'], ['222\n']),
                           ('unchanged', ['bbb\n']),
                           ])

        ml = m3.merge_lines(name_a='a',
                            name_b='b',
                            start_marker='<<',
                            mid_marker='--',
                            end_marker='>>')
        self.assertEquals(''.join(ml),
'''aaa
<< a
111
--
222
>> b
bbb
''')



class ReplaceClash(TestBase):
    """Both try to insert lines in the same place."""
    def runTest(self):
        m3 = Merge3(['aaa', '000', 'bbb'],
                    ['aaa', '111', 'bbb'],
                    ['aaa', '222', 'bbb'])

        self.assertEquals(m3.find_unconflicted(),
                          [(0, 1), (2, 3)])

        self.assertEquals(list(m3.find_sync_regions()),
                          [(0,1, 0,1, 0,1),
                           (2,3, 2,3, 2,3),
                           (3,3, 3,3, 3,3),])



class ReplaceMulti(TestBase):
    """Replacement with regions of different size."""
    def runTest(self):
        m3 = Merge3(['aaa', '000', '000', 'bbb'],
                    ['aaa', '111', '111', '111', 'bbb'],
                    ['aaa', '222', '222', '222', '222', 'bbb'])

        self.assertEquals(m3.find_unconflicted(),
                          [(0, 1), (3, 4)])


        self.assertEquals(list(m3.find_sync_regions()),
                          [(0,1, 0,1, 0,1),
                           (3,4, 4,5, 5,6),
                           (4,4, 5,5, 6,6),])

        
        
