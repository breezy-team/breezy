# Copyright (C) 2005 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Tests for the IdentityMap class."""

# import system imports here

#import bzrlib specific imports here
import bzrlib.errors as errors
from bzrlib.tests import TestCase
import bzrlib.identitymap as identitymap


class TestIdentityMap(TestCase):

    def test_symbols(self):
        from bzrlib.identitymap import IdentityMap

    def test_construct(self):
        identitymap.IdentityMap()

    def test_add_weave(self):
        map = identitymap.IdentityMap()
        weave = "foo"
        map.add_weave("id", weave)
        self.assertEqual(weave, map.find_weave("id"))

    def test_double_add_weave(self):
        map = identitymap.IdentityMap()
        weave = "foo"
        map.add_weave("id", weave)
        self.assertRaises(errors.BzrError, map.add_weave, "id", weave)
        self.assertEqual(weave, map.find_weave("id"))
 
    def test_remove_object(self):
        map = identitymap.IdentityMap()
        weave = "foo"
        map.add_weave("id", weave)
        map.remove_object(weave)
        map.add_weave("id", weave)
        rev_history = [1]
        map.add_revision_history(rev_history)
        map.remove_object(rev_history)

    def test_add_revision_history(self):
        map = identitymap.IdentityMap()
        rev_history = [1,2,3]
        map.add_revision_history(rev_history)
        self.assertEqual(rev_history, map.find_revision_history())

    def test_double_add_revision_history(self):
        map = identitymap.IdentityMap()
        revision_history = [1]
        map.add_revision_history(revision_history)
        self.assertRaises(errors.BzrError,
                          map.add_revision_history,
                          revision_history)
        self.assertEqual(revision_history, map.find_revision_history())

 
class TestNullIdentityMap(TestCase):

    def test_symbols(self):
        from bzrlib.identitymap import NullIdentityMap

    def test_construct(self):
        identitymap.NullIdentityMap()

    def test_add_weave(self):
        map = identitymap.NullIdentityMap()
        weave = "foo"
        map.add_weave("id", weave)
        self.assertEqual(None, map.find_weave("id"))

    def test_double_add_weave(self):
        map = identitymap.NullIdentityMap()
        weave = "foo"
        map.add_weave("id", weave)
        map.add_weave("id", weave)
        self.assertEqual(None, map.find_weave("id"))
        
    def test_null_identity_map_has_no_remove(self):
        map = identitymap.NullIdentityMap()
        self.assertEqual(None, getattr(map, 'remove_object', None))

    def test_add_revision_history(self):
        map = identitymap.NullIdentityMap()
        rev_history = [1,2,3]
        map.add_revision_history(rev_history)
        self.assertEqual(None, map.find_revision_history())

    def test_double_add_revision_history(self):
        map = identitymap.NullIdentityMap()
        revision_history = [1]
        map.add_revision_history(revision_history)
        map.add_revision_history(revision_history)
        self.assertEqual(None, map.find_revision_history())
