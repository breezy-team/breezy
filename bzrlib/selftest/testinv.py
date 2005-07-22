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

from bzrlib.selftest import TestBase

from bzrlib.inventory import Inventory, InventoryEntry

class TestIsWithin(TestBase):
    def runTest(self):
        from bzrlib.osutils import is_inside_any
        
        for dirs, fn in [(['src', 'doc'], 'src/foo.c'),
                         (['src'], 'src/foo.c'),
                         (['src'], 'src'),
                         ]:
            self.assert_(is_inside_any(dirs, fn))
            
            
class TestInventoryIds(TestBase):
    def runTest(self):
        """Test detection of files within selected directories."""
        inv = Inventory()
        
        for args in [('src', 'directory', 'src-id'), 
                     ('doc', 'directory', 'doc-id'), 
                     ('src/hello.c', 'file'),
                     ('src/bye.c', 'file', 'bye-id'),
                     ('Makefile', 'file')]:
            inv.add_path(*args)
            
        self.assertEqual(inv.path2id('src'), 'src-id')
        self.assertEqual(inv.path2id('src/bye.c'), 'bye-id')
        
        self.assert_('src-id' in inv)
