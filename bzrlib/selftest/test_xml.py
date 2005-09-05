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

from cStringIO import StringIO

from bzrlib.selftest import TestCase
from bzrlib.inventory import Inventory, InventoryEntry
from bzrlib.xml import serializer_v4

_working_inventory_v4 = """<inventory file_id="TREE_ROOT">
<entry file_id="bar-20050901064931-73b4b1138abc9cd2" kind="file" name="bar" parent_id="TREE_ROOT" />
<entry file_id="foo-20050801201819-4139aa4a272f4250" kind="directory" name="foo" parent_id="TREE_ROOT" />
<entry file_id="bar-20050824000535-6bc48cfad47ed134" kind="file" name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" />
</inventory>"""

class TestSerializer(TestCase):
    """Test XML serialization"""
    def test_canned_inventory(self):
        """Test unpacked a canned inventory v4 file."""
        inp = StringIO(_working_inventory_v4)
        inv = serializer_v4.read_inventory(inp)
        self.assertEqual(len(inv), 4)
        self.assert_('bar-20050901064931-73b4b1138abc9cd2' in inv)
