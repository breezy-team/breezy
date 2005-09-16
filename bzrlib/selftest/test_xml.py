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
from bzrlib.xml4 import serializer_v4
from bzrlib.xml5 import serializer_v5

_working_inventory_v4 = """<inventory file_id="TREE_ROOT">
<entry file_id="bar-20050901064931-73b4b1138abc9cd2" kind="file" name="bar" parent_id="TREE_ROOT" />
<entry file_id="foo-20050801201819-4139aa4a272f4250" kind="directory" name="foo" parent_id="TREE_ROOT" />
<entry file_id="bar-20050824000535-6bc48cfad47ed134" kind="file" name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" />
</inventory>"""


_revision_v4 = """<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;"
    inventory_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    timestamp="1125907235.211783886"
    timezone="36000">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92" revision_sha1="7bdf4cc8c5bdac739f8cf9b10b78cf4b68f915ff" />
</parents>
</revision>
"""

_revision_v5 = """<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    timestamp="1125907235.211783886"
    timezone="36000">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92"/>
</parents>
</revision>
"""

_committed_inv_v5 = """<inventory>
<file file_id="bar-20050901064931-73b4b1138abc9cd2" 
      name="bar" parent_id="TREE_ROOT" 
      text_version="mbp@foo-123123" name_version="mbp@foo-123123"
      />
<directory name="subdir"
           file_id="foo-20050801201819-4139aa4a272f4250"
           parent_id="TREE_ROOT" 
           name_version="mbp@foo-00"/>
<file file_id="bar-20050824000535-6bc48cfad47ed134" 
      name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" 
      name_version="mbp@foo-00"
      text_version="mbp@foo-123123"/>
</inventory>
"""

class TestSerializer(TestCase):
    """Test XML serialization"""
    def test_canned_inventory(self):
        """Test unpacked a canned inventory v4 file."""
        inp = StringIO(_working_inventory_v4)
        inv = serializer_v4.read_inventory(inp)
        self.assertEqual(len(inv), 4)
        self.assert_('bar-20050901064931-73b4b1138abc9cd2' in inv)

    def test_unpack_revision(self):
        """Test unpacking a canned revision v4"""
        inp = StringIO(_revision_v4)
        rev = serializer_v4.read_revision(inp)
        eq = self.assertEqual
        eq(rev.committer,
           "Martin Pool <mbp@sourcefrog.net>")
        eq(rev.inventory_id,
           "mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9")
        eq(len(rev.parents), 1)
        eq(rev.parents[0].revision_id,
           "mbp@sourcefrog.net-20050905063503-43948f59fa127d92")

    def test_unpack_revision_5(self):
        """Test unpacking a canned revision v5"""
        inp = StringIO(_revision_v5)
        rev = serializer_v5.read_revision(inp)
        eq = self.assertEqual
        eq(rev.committer,
           "Martin Pool <mbp@sourcefrog.net>")
        eq(len(rev.parents), 1)
        eq(rev.timezone, 36000)
        eq(rev.parents[0].revision_id,
           "mbp@sourcefrog.net-20050905063503-43948f59fa127d92")

    def test_unpack_inventory_5(self):
        """Unpack canned new-style inventory"""
        inp = StringIO(_committed_inv_v5)
        inv = serializer_v5.read_inventory(inp)
        eq = self.assertEqual
        eq(len(inv), 4)
        ie = inv['bar-20050824000535-6bc48cfad47ed134']
        eq(ie.kind, 'file')
        eq(ie.text_version, 'mbp@foo-123123')
        eq(ie.name_version, 'mbp@foo-00')
        eq(ie.name, 'bar')
        eq(inv[ie.parent_id].kind, 'directory')

    def test_repack_inventory_5(self):
        inp = StringIO(_committed_inv_v5)
        inv = serializer_v5.read_inventory(inp)
        outp = StringIO()
        serializer_v5.write_inventory(inv, outp)
        inv2 = serializer_v5.read_inventory(StringIO(outp.getvalue()))
        self.assertEqual(inv, inv2)

    def test_repack_revision_5(self):
        inp = StringIO(_revision_v5)
        rev = serializer_v5.read_revision(inp)
        outp = StringIO()
        serializer_v5.write_revision(rev, outp)
        rev2 = serializer_v5.read_revision(StringIO(outp.getvalue()))
        self.assertEqual(rev, rev2)

