# Copyright (C) 2005 Canonical Ltd
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

from cStringIO import StringIO

from bzrlib import (
    errors, 
    inventory, 
    xml7,
    )
from bzrlib.tests import TestCase
from bzrlib.inventory import Inventory, InventoryEntry
from bzrlib.xml4 import serializer_v4
import bzrlib.xml5

_working_inventory_v4 = """<inventory file_id="TREE_ROOT">
<entry file_id="bar-20050901064931-73b4b1138abc9cd2" kind="file" name="bar" parent_id="TREE_ROOT" />
<entry file_id="foo-20050801201819-4139aa4a272f4250" kind="directory" name="foo" parent_id="TREE_ROOT" />
<entry file_id="bar-20050824000535-6bc48cfad47ed134" kind="file" name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" />
</inventory>"""


_revision_v4 = """<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;"
    inventory_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    timestamp="1125907235.212"
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
    timestamp="1125907235.212"
    timezone="36000">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92"/>
</parents>
</revision>
"""

_revision_v5_utc = """\
<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    timestamp="1125907235.212"
    timezone="0">
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
      revision="mbp@foo-123123"/>
<directory name="subdir"
           file_id="foo-20050801201819-4139aa4a272f4250"
           parent_id="TREE_ROOT" 
           revision="mbp@foo-00"/>
<file executable="yes" file_id="bar-20050824000535-6bc48cfad47ed134" 
      name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" 
      revision="mbp@foo-00"/>
</inventory>
"""

_basis_inv_v5 = """<inventory revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92">
<file file_id="bar-20050901064931-73b4b1138abc9cd2" 
      name="bar" parent_id="TREE_ROOT" 
      revision="mbp@foo-123123"/>
<directory name="subdir"
           file_id="foo-20050801201819-4139aa4a272f4250"
           parent_id="TREE_ROOT" 
           revision="mbp@foo-00"/>
<file file_id="bar-20050824000535-6bc48cfad47ed134" 
      name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" 
      revision="mbp@foo-00"/>
</inventory>
"""


# DO NOT REFLOW THIS. Its the exact revision we want.
_expected_rev_v5 = """<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;" format="5" inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41" revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9" timestamp="1125907235.212" timezone="36000">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92" />
</parents>
</revision>
"""


# DO NOT REFLOW THIS. Its the exact inventory we want.
_expected_inv_v5 = """<inventory format="5">
<file file_id="bar-20050901064931-73b4b1138abc9cd2" name="bar" revision="mbp@foo-123123" />
<directory file_id="foo-20050801201819-4139aa4a272f4250" name="subdir" revision="mbp@foo-00" />
<file executable="yes" file_id="bar-20050824000535-6bc48cfad47ed134" name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" revision="mbp@foo-00" />
</inventory>
"""


_expected_inv_v5_root = """<inventory file_id="f&lt;" format="5" revision_id="mother!">
<file file_id="bar-20050901064931-73b4b1138abc9cd2" name="bar" parent_id="f&lt;" revision="mbp@foo-123123" />
<directory file_id="foo-20050801201819-4139aa4a272f4250" name="subdir" parent_id="f&lt;" revision="mbp@foo-00" />
<file executable="yes" file_id="bar-20050824000535-6bc48cfad47ed134" name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" revision="mbp@foo-00" />
</inventory>
"""

_expected_inv_v7 = """<inventory format="7" revision_id="rev_outer">
<directory file_id="tree-root-321" name="" revision="rev_outer" />
<directory file_id="dir-id" name="dir" parent_id="tree-root-321" revision="rev_outer" />
<file file_id="file-id" name="file" parent_id="tree-root-321" revision="rev_outer" />
<symlink file_id="link-id" name="link" parent_id="tree-root-321" revision="rev_outer" />
<tree-reference file_id="nested-id" name="nested" parent_id="tree-root-321" revision="rev_outer" reference_revision="rev_inner" />
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
        eq(len(rev.parent_ids), 1)
        eq(rev.parent_ids[0],
           "mbp@sourcefrog.net-20050905063503-43948f59fa127d92")

    def test_unpack_revision_5(self):
        """Test unpacking a canned revision v5"""
        inp = StringIO(_revision_v5)
        rev = bzrlib.xml5.serializer_v5.read_revision(inp)
        eq = self.assertEqual
        eq(rev.committer,
           "Martin Pool <mbp@sourcefrog.net>")
        eq(len(rev.parent_ids), 1)
        eq(rev.timezone, 36000)
        eq(rev.parent_ids[0],
           "mbp@sourcefrog.net-20050905063503-43948f59fa127d92")

    def test_unpack_revision_5_utc(self):
        inp = StringIO(_revision_v5_utc)
        rev = bzrlib.xml5.serializer_v5.read_revision(inp)
        eq = self.assertEqual
        eq(rev.committer,
           "Martin Pool <mbp@sourcefrog.net>")
        eq(len(rev.parent_ids), 1)
        eq(rev.timezone, 0)
        eq(rev.parent_ids[0],
           "mbp@sourcefrog.net-20050905063503-43948f59fa127d92")

    def test_unpack_inventory_5(self):
        """Unpack canned new-style inventory"""
        inp = StringIO(_committed_inv_v5)
        inv = bzrlib.xml5.serializer_v5.read_inventory(inp)
        eq = self.assertEqual
        eq(len(inv), 4)
        ie = inv['bar-20050824000535-6bc48cfad47ed134']
        eq(ie.kind, 'file')
        eq(ie.revision, 'mbp@foo-00')
        eq(ie.name, 'bar')
        eq(inv[ie.parent_id].kind, 'directory')

    def test_unpack_basis_inventory_5(self):
        """Unpack canned new-style inventory"""
        inp = StringIO(_basis_inv_v5)
        inv = bzrlib.xml5.serializer_v5.read_inventory(inp)
        eq = self.assertEqual
        eq(len(inv), 4)
        eq(inv.revision_id, 'mbp@sourcefrog.net-20050905063503-43948f59fa127d92')
        ie = inv['bar-20050824000535-6bc48cfad47ed134']
        eq(ie.kind, 'file')
        eq(ie.revision, 'mbp@foo-00')
        eq(ie.name, 'bar')
        eq(inv[ie.parent_id].kind, 'directory')

    def test_repack_inventory_5(self):
        inp = StringIO(_committed_inv_v5)
        inv = bzrlib.xml5.serializer_v5.read_inventory(inp)
        outp = StringIO()
        bzrlib.xml5.serializer_v5.write_inventory(inv, outp)
        self.assertEqualDiff(_expected_inv_v5, outp.getvalue())
        inv2 = bzrlib.xml5.serializer_v5.read_inventory(StringIO(outp.getvalue()))
        self.assertEqual(inv, inv2)
    
    def assertRoundTrips(self, xml_string):
        inp = StringIO(xml_string)
        inv = bzrlib.xml5.serializer_v5.read_inventory(inp)
        outp = StringIO()
        bzrlib.xml5.serializer_v5.write_inventory(inv, outp)
        self.assertEqualDiff(xml_string, outp.getvalue())
        inv2 = bzrlib.xml5.serializer_v5.read_inventory(StringIO(outp.getvalue()))
        self.assertEqual(inv, inv2)

    def tests_serialize_inventory_v5_with_root(self):
        self.assertRoundTrips(_expected_inv_v5_root)

    def check_repack_revision(self, txt):
        """Check that repacking a revision yields the same information"""
        inp = StringIO(txt)
        rev = bzrlib.xml5.serializer_v5.read_revision(inp)
        outp = StringIO()
        bzrlib.xml5.serializer_v5.write_revision(rev, outp)
        outfile_contents = outp.getvalue()
        rev2 = bzrlib.xml5.serializer_v5.read_revision(StringIO(outfile_contents))
        self.assertEqual(rev, rev2)

    def test_repack_revision_5(self):
        """Round-trip revision to XML v5"""
        self.check_repack_revision(_revision_v5)

    def test_repack_revision_5_utc(self):
        self.check_repack_revision(_revision_v5_utc)

    def test_pack_revision_5(self):
        """Pack revision to XML v5"""
        # fixed 20051025, revisions should have final newline
        rev = bzrlib.xml5.serializer_v5.read_revision_from_string(_revision_v5)
        outp = StringIO()
        bzrlib.xml5.serializer_v5.write_revision(rev, outp)
        outfile_contents = outp.getvalue()
        self.assertEqual(outfile_contents[-1], '\n')
        self.assertEqualDiff(outfile_contents, bzrlib.xml5.serializer_v5.write_revision_to_string(rev))
        self.assertEqualDiff(outfile_contents, _expected_rev_v5)

    def test_empty_property_value(self):
        """Create an empty property value check that it serializes correctly"""
        s_v5 = bzrlib.xml5.serializer_v5
        rev = s_v5.read_revision_from_string(_revision_v5)
        outp = StringIO()
        props = {'empty':'', 'one':'one'}
        rev.properties = props
        txt = s_v5.write_revision_to_string(rev)
        new_rev = s_v5.read_revision_from_string(txt)
        self.assertEqual(props, new_rev.properties)

    def test_roundtrip_inventory_v7(self):
        inv = Inventory('tree-root-321', revision_id='rev_outer')
        inv.add(inventory.TreeReference('nested-id', 'nested', 'tree-root-321',
                                        'rev_outer', 'rev_inner'))
        inv.add(inventory.InventoryFile('file-id', 'file', 'tree-root-321'))
        inv.add(inventory.InventoryDirectory('dir-id', 'dir', 
                                             'tree-root-321'))
        inv.add(inventory.InventoryLink('link-id', 'link', 'tree-root-321'))
        inv['tree-root-321'].revision = 'rev_outer'
        inv['dir-id'].revision = 'rev_outer'
        inv['file-id'].revision = 'rev_outer'
        inv['link-id'].revision = 'rev_outer'
        txt = xml7.serializer_v7.write_inventory_to_string(inv)
        self.assertEqualDiff(_expected_inv_v7, txt)
        inv2 = xml7.serializer_v7.read_inventory_from_string(txt)
        self.assertEqual(5, len(inv2))
        for path, ie in inv.iter_entries():
            self.assertEqual(ie, inv2[ie.file_id])

    def test_wrong_format_v7(self):
        """Can't accidentally open a file with wrong serializer"""
        s_v6 = bzrlib.xml6.serializer_v6
        s_v7 = xml7.serializer_v7
        self.assertRaises(errors.UnexpectedInventoryFormat, 
                          s_v7.read_inventory_from_string, _expected_inv_v5)
        self.assertRaises(errors.UnexpectedInventoryFormat, 
                          s_v6.read_inventory_from_string, _expected_inv_v7)

    def test_tree_reference(self):
        s_v5 = bzrlib.xml5.serializer_v5
        s_v6 = bzrlib.xml6.serializer_v6
        s_v7 = xml7.serializer_v7
        inv = Inventory('tree-root-321')
        inv.add(inventory.TreeReference('nested-id', 'nested', 'tree-root-321',
                                        'rev-outer', 'rev-inner'))
        self.assertRaises(errors.UnsupportedInventoryKind, 
                          s_v5.write_inventory_to_string, inv)
        self.assertRaises(errors.UnsupportedInventoryKind, 
                          s_v6.write_inventory_to_string, inv)
        txt = s_v7.write_inventory_to_string(inv)
        inv2 = s_v7.read_inventory_from_string(txt)
        self.assertEqual('tree-root-321', inv2['nested-id'].parent_id)
        self.assertEqual('rev-outer', inv2['nested-id'].revision)
        self.assertEqual('rev-inner', inv2['nested-id'].reference_revision)
        self.assertRaises(errors.UnsupportedInventoryKind, 
                          s_v6.read_inventory_from_string,
                          txt.replace('format="7"', 'format="6"'))
        self.assertRaises(errors.UnsupportedInventoryKind, 
                          s_v5.read_inventory_from_string,
                          txt.replace('format="7"', 'format="5"'))
