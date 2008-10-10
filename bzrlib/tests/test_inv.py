# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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


from bzrlib import errors, inventory, osutils
from bzrlib.inventory import (CHKInventory, Inventory, ROOT_ID, InventoryFile,
    InventoryDirectory, InventoryEntry, TreeReference)
from bzrlib.tests import TestCase, TestCaseWithTransport


class TestInventoryEntry(TestCase):

    def test_file_kind_character(self):
        file = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        self.assertEqual(file.kind_character(), '')

    def test_dir_kind_character(self):
        dir = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        self.assertEqual(dir.kind_character(), '/')

    def test_link_kind_character(self):
        dir = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        self.assertEqual(dir.kind_character(), '')

    def test_dir_detect_changes(self):
        left = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        left.text_sha1 = 123
        left.executable = True
        left.symlink_target='foo'
        right = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        right.text_sha1 = 321
        right.symlink_target='bar'
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))

    def test_file_detect_changes(self):
        left = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        left.text_sha1 = 123
        right = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        right.text_sha1 = 123
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))
        left.executable = True
        self.assertEqual((False, True), left.detect_changes(right))
        self.assertEqual((False, True), right.detect_changes(left))
        right.text_sha1 = 321
        self.assertEqual((True, True), left.detect_changes(right))
        self.assertEqual((True, True), right.detect_changes(left))

    def test_symlink_detect_changes(self):
        left = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        left.text_sha1 = 123
        left.executable = True
        left.symlink_target='foo'
        right = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        right.text_sha1 = 321
        right.symlink_target='foo'
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))
        left.symlink_target = 'different'
        self.assertEqual((True, False), left.detect_changes(right))
        self.assertEqual((True, False), right.detect_changes(left))

    def test_file_has_text(self):
        file = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        self.failUnless(file.has_text())

    def test_directory_has_text(self):
        dir = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        self.failIf(dir.has_text())

    def test_link_has_text(self):
        link = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        self.failIf(link.has_text())

    def test_make_entry(self):
        self.assertIsInstance(inventory.make_entry("file", "name", ROOT_ID),
            inventory.InventoryFile)
        self.assertIsInstance(inventory.make_entry("symlink", "name", ROOT_ID),
            inventory.InventoryLink)
        self.assertIsInstance(inventory.make_entry("directory", "name", ROOT_ID),
            inventory.InventoryDirectory)

    def test_make_entry_non_normalized(self):
        orig_normalized_filename = osutils.normalized_filename

        try:
            osutils.normalized_filename = osutils._accessible_normalized_filename
            entry = inventory.make_entry("file", u'a\u030a', ROOT_ID)
            self.assertEqual(u'\xe5', entry.name)
            self.assertIsInstance(entry, inventory.InventoryFile)

            osutils.normalized_filename = osutils._inaccessible_normalized_filename
            self.assertRaises(errors.InvalidNormalization,
                    inventory.make_entry, 'file', u'a\u030a', ROOT_ID)
        finally:
            osutils.normalized_filename = orig_normalized_filename


class TestDescribeChanges(TestCase):

    def test_describe_change(self):
        # we need to test the following change combinations:
        # rename
        # reparent
        # modify
        # gone
        # added
        # renamed/reparented and modified
        # change kind (perhaps can't be done yet?)
        # also, merged in combination with all of these?
        old_a = InventoryFile('a-id', 'a_file', ROOT_ID)
        old_a.text_sha1 = '123132'
        old_a.text_size = 0
        new_a = InventoryFile('a-id', 'a_file', ROOT_ID)
        new_a.text_sha1 = '123132'
        new_a.text_size = 0

        self.assertChangeDescription('unchanged', old_a, new_a)

        new_a.text_size = 10
        new_a.text_sha1 = 'abcabc'
        self.assertChangeDescription('modified', old_a, new_a)

        self.assertChangeDescription('added', None, new_a)
        self.assertChangeDescription('removed', old_a, None)
        # perhaps a bit questionable but seems like the most reasonable thing...
        self.assertChangeDescription('unchanged', None, None)

        # in this case it's both renamed and modified; show a rename and 
        # modification:
        new_a.name = 'newfilename'
        self.assertChangeDescription('modified and renamed', old_a, new_a)

        # reparenting is 'renaming'
        new_a.name = old_a.name
        new_a.parent_id = 'somedir-id'
        self.assertChangeDescription('modified and renamed', old_a, new_a)

        # reset the content values so its not modified
        new_a.text_size = old_a.text_size
        new_a.text_sha1 = old_a.text_sha1
        new_a.name = old_a.name

        new_a.name = 'newfilename'
        self.assertChangeDescription('renamed', old_a, new_a)

        # reparenting is 'renaming'
        new_a.name = old_a.name
        new_a.parent_id = 'somedir-id'
        self.assertChangeDescription('renamed', old_a, new_a)

    def assertChangeDescription(self, expected_change, old_ie, new_ie):
        change = InventoryEntry.describe_change(old_ie, new_ie)
        self.assertEqual(expected_change, change)


class TestCHKInventory(TestCaseWithTransport):
    
    def get_chk_bytes(self):
        # The eassiest way to get a CHK store is a development3 repository and
        # then work with the chk_bytes attribute directly.
        repo = self.make_repository(".", format="development3")
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.abort_write_group)
        return repo.chk_bytes

    def read_bytes(self, chk_bytes, key):
        stream = chk_bytes.get_record_stream([key], 'unordered', True)
        return stream.next().get_bytes_as("fulltext")

    def test_deserialise_gives_CHKInventory(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        new_inv = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        self.assertEqual("revid", new_inv.revision_id)
        self.assertEqual("directory", new_inv.root.kind)
        self.assertEqual(inv.root.file_id, new_inv.root.file_id)
        self.assertEqual(inv.root.parent_id, new_inv.root.parent_id)
        self.assertEqual(inv.root.name, new_inv.root.name)
        self.assertEqual("rootrev", new_inv.root.revision)

    def test_deserialise_wrong_revid(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        self.assertRaises(ValueError, CHKInventory.deserialise, chk_bytes,
            bytes, ("revid2",))

    def test_captures_rev_root_byid(self):
        inv = Inventory()
        inv.revision_id = "foo"
        inv.root.revision = "bar"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        self.assertEqual([
            'chkinventory:\n',
            'revision_id: foo\n',
            'root_id: TREE_ROOT\n',
            'id_to_entry: sha1:dc696b0cf291ac0d66bdcda3070f755494a586fc\n'
            ],
            chk_inv.to_lines())

    def test_directory_children_on_demand(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        new_inv = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        root_entry = new_inv[inv.root.file_id]
        self.assertEqual(None, root_entry._children)
        self.assertEqual(['file'], root_entry.children.keys())
        file_direct = new_inv["fileid"]
        file_found = root_entry.children['file']
        self.assertEqual(file_direct.kind, file_found.kind)
        self.assertEqual(file_direct.file_id, file_found.file_id)
        self.assertEqual(file_direct.parent_id, file_found.parent_id)
        self.assertEqual(file_direct.name, file_found.name)
        self.assertEqual(file_direct.revision, file_found.revision)
        self.assertEqual(file_direct.text_sha1, file_found.text_sha1)
        self.assertEqual(file_direct.text_size, file_found.text_size)
        self.assertEqual(file_direct.executable, file_found.executable)

    def test___iter__(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        new_inv = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        fileids = list(new_inv.__iter__())
        fileids.sort()
        self.assertEqual([inv.root.file_id, "fileid"], fileids)

    def test__len__(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        self.assertEqual(2, len(chk_inv))

    def test___getitem__(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        new_inv = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        root_entry = new_inv[inv.root.file_id]
        file_entry = new_inv["fileid"]
        self.assertEqual("directory", root_entry.kind)
        self.assertEqual(inv.root.file_id, root_entry.file_id)
        self.assertEqual(inv.root.parent_id, root_entry.parent_id)
        self.assertEqual(inv.root.name, root_entry.name)
        self.assertEqual("rootrev", root_entry.revision)
        self.assertEqual("file", file_entry.kind)
        self.assertEqual("fileid", file_entry.file_id)
        self.assertEqual(inv.root.file_id, file_entry.parent_id)
        self.assertEqual("file", file_entry.name)
        self.assertEqual("filerev", file_entry.revision)
        self.assertEqual("ffff", file_entry.text_sha1)
        self.assertEqual(1, file_entry.text_size)
        self.assertEqual(True, file_entry.executable)

    def test_has_id_true(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        self.assertTrue(chk_inv.has_id('fileid'))
        self.assertTrue(chk_inv.has_id(inv.root.file_id))

    def test_has_id_not(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        self.assertFalse(chk_inv.has_id('fileid'))

    def test_create_by_apply_delta_empty_add_child(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        chk_bytes = self.get_chk_bytes()
        base_inv = CHKInventory.from_inventory(chk_bytes, inv)
        a_entry = InventoryFile("A-id", "A", inv.root.file_id)
        a_entry.revision = "filerev"
        a_entry.executable = True
        a_entry.text_sha1 = "ffff"
        a_entry.text_size = 1
        inv.add(a_entry)
        inv.revision_id = "expectedid"
        reference_inv = CHKInventory.from_inventory(chk_bytes, inv)
        delta = [(None, "A",  "A-id", a_entry)]
        new_inv = base_inv.create_by_apply_delta(delta, "expectedid")
        # new_inv should be the same as reference_inv.
        self.assertEqual(reference_inv.revision_id, new_inv.revision_id)
        self.assertEqual(reference_inv.root_id, new_inv.root_id)
        self.assertEqual(reference_inv.id_to_entry._root_node._key,
            new_inv.id_to_entry._root_node._key)
