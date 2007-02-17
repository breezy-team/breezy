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


_revision_utf8_v5 = """<revision committer="Erik B&#229;gfors &lt;erik@foo.net&gt;"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="erik@b&#229;gfors-02"
    timestamp="1125907235.212"
    timezone="36000">
<message>Include &#181;nicode characters
</message>
<parents>
<revision_ref revision_id="erik@b&#229;gfors-01"/>
</parents>
</revision>
"""

_inventory_utf8_v5 = """<inventory file_id="TRE&#233;_ROOT" format="5"
                                   revision_id="erik@b&#229;gfors-02">
<file file_id="b&#229;r-01"
      name="b&#229;r" parent_id="TREE_ROOT"
      revision="erik@b&#229;gfors-01"/>
<directory name="s&#181;bdir"
           file_id="s&#181;bdir-01"
           parent_id="TREE_ROOT"
           revision="erik@b&#229;gfors-01"/>
<file executable="yes" file_id="b&#229;r-02"
      name="b&#229;r" parent_id="s&#181;bdir-01"
      revision="erik@b&#229;gfors-02"/>
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

    def test_revision_ids_are_utf8(self):
        """Parsed revision_ids should all be utf-8 strings, not unicode."""
        s_v5 = bzrlib.xml5.serializer_v5
        rev = s_v5.read_revision_from_string(_revision_utf8_v5)
        self.assertEqual('erik@b\xc3\xa5gfors-02', rev.revision_id)
        self.assertIsInstance(rev.revision_id, str)
        self.assertEqual(['erik@b\xc3\xa5gfors-01'], rev.parent_ids)
        for parent_id in rev.parent_ids:
            self.assertIsInstance(parent_id, str)
        self.assertEqual(u'Include \xb5nicode characters\n', rev.message)
        self.assertIsInstance(rev.message, unicode)

        # ie.revision should either be None or a utf-8 revision id
        inv = s_v5.read_inventory_from_string(_inventory_utf8_v5)
        rev_id_1 = u'erik@b\xe5gfors-01'.encode('utf8')
        rev_id_2 = u'erik@b\xe5gfors-02'.encode('utf8')
        fid_root = u'TRE\xe9_ROOT'
        fid_bar1 = u'b\xe5r-01'
        fid_sub = u's\xb5bdir-01'
        fid_bar2 = u'b\xe5r-02'
        expected = [(u'', fid_root, None, None),
                    (u'b\xe5r', fid_bar1, fid_root, rev_id_1),
                    (u's\xb5bdir', fid_sub, fid_root, rev_id_1),
                    (u's\xb5bdir/b\xe5r', fid_bar2, fid_sub, rev_id_2),
                   ]
        self.assertEqual(rev_id_2, inv.revision_id)
        self.assertIsInstance(inv.revision_id, str)

        actual = list(inv.iter_entries_by_dir())
        for ((exp_path, exp_file_id, exp_parent_id, exp_rev_id),
             (act_path, act_ie)) in zip(expected, actual):
            self.assertEqual(exp_path, act_path)
            self.assertIsInstance(act_path, unicode)
            self.assertEqual(exp_file_id, act_ie.file_id)
            self.assertIsInstance(act_ie.file_id, unicode)
            self.assertEqual(exp_parent_id, act_ie.parent_id)
            if exp_parent_id is not None:
                self.assertIsInstance(act_ie.parent_id, unicode)
            self.assertEqual(exp_rev_id, act_ie.revision)
            if exp_rev_id is not None:
                self.assertIsInstance(act_ie.revision, str)

        self.assertEqual(len(expected), len(actual))


class TestEncodeAndEscape(TestCase):
    """Whitebox testing of the _encode_and_escape function."""

    def setUp(self):
        # Keep the cache clear before and after the test
        bzrlib.xml5._ensure_utf8_re()
        bzrlib.xml5._clear_cache()
        self.addCleanup(bzrlib.xml5._clear_cache)

    def test_simple_ascii(self):
        # _encode_and_escape always appends a final ", because these parameters
        # are being used in xml attributes, and by returning it now, we have to
        # do fewer string operations later.
        val = bzrlib.xml5._encode_and_escape('foo bar')
        self.assertEqual('foo bar"', val)
        # The second time should be cached
        val2 = bzrlib.xml5._encode_and_escape('foo bar')
        self.assertIs(val2, val)

    def test_ascii_with_xml(self):
        self.assertEqual('&amp;&apos;&quot;&lt;&gt;"',
                         bzrlib.xml5._encode_and_escape('&\'"<>'))

    def test_utf8_with_xml(self):
        # u'\xb5\xe5&\u062c'
        utf8_str = '\xc2\xb5\xc3\xa5&\xd8\xac'
        self.assertEqual('&#181;&#229;&amp;&#1580;"',
                         bzrlib.xml5._encode_and_escape(utf8_str))

    def test_unicode(self):
        uni_str = u'\xb5\xe5&\u062c'
        self.assertEqual('&#181;&#229;&amp;&#1580;"',
                         bzrlib.xml5._encode_and_escape(uni_str))
