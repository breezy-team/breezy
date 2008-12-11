# test_pack.py -- Tests for the handling of git packs.
# Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
# Copyright (C) 2008 Jelmer Vernooij <jelmer@samba.org>
# 
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; version 2
# of the License, or (at your option) any later version of the license.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.

import os
import unittest

from dulwich.pack import (
        PackIndex,
        PackData,
        hex_to_sha,
        multi_ord,
        write_pack_index,
        write_pack,
        )

pack1_sha = 'bc63ddad95e7321ee734ea11a7a62d314e0d7481'

a_sha = '6f670c0fb53f9463760b7295fbb814e965fb20c8'
tree_sha = 'b2a2766a2879c209ab1176e7e778b81ae422eeaa'
commit_sha = 'f18faa16531ac570a3fdc8c7ca16682548dafd12'

class PackTests(unittest.TestCase):
  """Base class for testing packs"""

  datadir = os.path.join(os.path.dirname(__file__), 'data/packs')

  def get_pack_index(self, sha):
    """Returns a PackIndex from the datadir with the given sha"""
    return PackIndex(os.path.join(self.datadir, 'pack-%s.idx' % sha))

  def get_pack_data(self, sha):
    """Returns a PackData object from the datadir with the given sha"""
    return PackData(os.path.join(self.datadir, 'pack-%s.pack' % sha))


class PackIndexTests(PackTests):
  """Class that tests the index of packfiles"""

  def test_object_index(self):
    """Tests that the correct object offset is returned from the index."""
    p = self.get_pack_index(pack1_sha)
    self.assertEqual(p.object_index(pack1_sha), None)
    self.assertEqual(p.object_index(a_sha), 178)
    self.assertEqual(p.object_index(tree_sha), 138)
    self.assertEqual(p.object_index(commit_sha), 12)


class TestPackData(PackTests):
  """Tests getting the data from the packfile."""

  def test_create_pack(self):
    p = self.get_pack_data(pack1_sha)

  def test_get_object_at(self):
    """Tests random access for non-delta objects"""
    p = self.get_pack_data(pack1_sha)
    idx = self.get_pack_index(pack1_sha)
    obj = p.get_object_at(idx.object_index(a_sha))
    self.assertEqual(obj._type, 'blob')
    self.assertEqual(obj.sha().hexdigest(), a_sha)
    obj = p.get_object_at(idx.object_index(tree_sha))
    self.assertEqual(obj._type, 'tree')
    self.assertEqual(obj.sha().hexdigest(), tree_sha)
    obj = p.get_object_at(idx.object_index(commit_sha))
    self.assertEqual(obj._type, 'commit')
    self.assertEqual(obj.sha().hexdigest(), commit_sha)

  def test_pack_len(self):
    p = self.get_pack_data(pack1_sha)
    self.assertEquals(3, len(p))

  def test_index_len(self):
    p = self.get_pack_index(pack1_sha)
    self.assertEquals(3, len(p))

  def test_get_stored_checksum(self):
    p = self.get_pack_index(pack1_sha)
    self.assertEquals("\xf2\x84\x8e*\xd1o2\x9a\xe1\xc9.;\x95\xe9\x18\x88\xda\xa5\xbd\x01", str(p.get_stored_checksums()[1]))
    self.assertEquals( 'r\x19\x80\xe8f\xaf\x9a_\x93\xadgAD\xe1E\x9b\x8b\xa3\xe7\xb7' , str(p.get_stored_checksums()[0]))

  def test_check(self):
    p = self.get_pack_index(pack1_sha)
    self.assertEquals(True, p.check())

  def test_iterentries(self):
    p = self.get_pack_index(pack1_sha)
    self.assertEquals([('og\x0c\x0f\xb5?\x94cv\x0br\x95\xfb\xb8\x14\xe9e\xfb \xc8', 178, None), ('\xb2\xa2vj(y\xc2\t\xab\x11v\xe7\xe7x\xb8\x1a\xe4"\xee\xaa', 138, None), ('\xf1\x8f\xaa\x16S\x1a\xc5p\xa3\xfd\xc8\xc7\xca\x16h%H\xda\xfd\x12', 12, None)], list(p.iterentries()))


class TestHexToSha(unittest.TestCase):

    def test_simple(self):
        self.assertEquals('\xab\xcd\x0e', hex_to_sha("abcde"))


class TestMultiOrd(unittest.TestCase):

    def test_simple(self):
        self.assertEquals(418262508645L, multi_ord("abcde", 0, 5))


class TestPackIndexWriting(unittest.TestCase):

    def test_empty(self):
        pack_checksum = 'r\x19\x80\xe8f\xaf\x9a_\x93\xadgAD\xe1E\x9b\x8b\xa3\xe7\xb7'
        write_pack_index("empty.idx", [], pack_checksum)
        idx = PackIndex("empty.idx")
        self.assertTrue(idx.check())
        self.assertEquals(idx.get_stored_checksums()[0], pack_checksum)
        self.assertEquals(0, len(idx))
