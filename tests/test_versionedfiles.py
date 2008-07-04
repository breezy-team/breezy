# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib import osutils
from bzrlib.graph import DictParentsProvider
from bzrlib.tests import TestCase

from bzrlib.plugins.svn.versionedfiles import (SvnTexts, VirtualRevisionTexts, 
                                               VirtualInventoryTexts, VirtualSignatureTexts,
                                               VirtualVersionedFiles)


class BasicSvnTextsTests:
    def test_add_lines(self):
        self.assertRaises(NotImplementedError, 
                self.texts.add_lines, "foo", [], [])

    def test_add_mpdiffs(self):
        self.assertRaises(NotImplementedError, 
                self.texts.add_mpdiffs, [])

    def test_check(self):
        self.assertTrue(self.texts.check())

    def test_insert_record_stream(self):
        self.assertRaises(NotImplementedError, self.texts.insert_record_stream,
                          [])


class SvnTextsTests(TestCase,BasicSvnTextsTests):
    def setUp(self):
        self.texts = SvnTexts(self)


class VirtualTextsTests(TestCase,BasicSvnTextsTests):
    def get_parent_map(self, keys):
        return DictParentsProvider(self.parent_map).get_parent_map(keys)

    def get_lines(self, key):
        (k,) = key
        if not k in self.lines:
            return None
        return self.lines[k]

    def test_get_parent_map(self):
        self.parent_map = {"G": ("A", "B")}
        self.assertEquals({("G",): (("A",),("B",))}, self.texts.get_parent_map([("G",)]))

    def test_get_sha1s(self):
        self.lines = {"A": ["FOO"]}
        self.assertEquals({("A",): osutils.sha_strings(["FOO"])}, 
                self.texts.get_sha1s([("A",), ("B",)]))

    def test_get_record_stream(self):
        self.lines = {"A": ["FOO"]}
        it = self.texts.get_record_stream([("A",)], "unordered", True)
        record = it.next()
        self.assertEquals("FOO", record.get_bytes_as("fulltext"))

    def setUp(self):
        self.texts = VirtualVersionedFiles(self.get_parent_map, self.get_lines)


class VirtualRevisionTextsTests(TestCase,BasicSvnTextsTests):
    def setUp(self):
        self.texts = VirtualRevisionTexts(self)

    def get_parent_map(self, keys):
        raise NotImplementedError


class VirtualInventoryTextsTests(TestCase,BasicSvnTextsTests):
    def get_inventory_xml(self, key):
        return "FOO"

    def get_parent_map(self, keys):
        return {("A",): (("B",))}

    def setUp(self):
        self.texts = VirtualInventoryTexts(self)

    def test_get_sha1s(self):
        self.assertEquals({("A",): osutils.sha_strings(["FOO"])}, self.texts.get_sha1s([("A",)]))


class VirtualSignatureTextsTests(TestCase,BasicSvnTextsTests):
    def setUp(self):
        self.texts = VirtualSignatureTexts(self)

    def get_parent_map(self, keys):
        raise NotImplementedError

