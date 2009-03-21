# Copyright (C) 2005-2009 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib import (
    osutils,
    )
from bzrlib.tests import (
    TestCase,
    )

from versionedfiles import (
    VirtualInventoryTexts,
    VirtualRevisionTexts,
    VirtualSignatureTexts,
    )


class BasicTextsTests:

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


class VirtualRevisionTextsTests(TestCase, BasicTextsTests):

    def _make_parents_provider(self):
        return self

    def setUp(self):
        self.texts = VirtualRevisionTexts(self)

    def get_parent_map(self, keys):
        raise NotImplementedError


class VirtualInventoryTextsTests(TestCase, BasicTextsTests):

    def _make_parents_provider(self):
        return self

    def get_inventory_xml(self, key):
        return "FOO"

    def get_parent_map(self, keys):
        return {("A",): (("B",))}

    def setUp(self):
        self.texts = VirtualInventoryTexts(self)

    def test_get_sha1s(self):
        self.assertEquals({("A",): osutils.sha_strings(["FOO"])}, self.texts.get_sha1s([("A",)]))


class VirtualSignatureTextsTests(TestCase, BasicTextsTests):

    def _make_parents_provider(self):
        return self

    def setUp(self):
        self.texts = VirtualSignatureTexts(self)

    def get_parent_map(self, keys):
        raise NotImplementedError

