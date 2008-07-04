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

"""Subversion core library tests."""

from bzrlib.tests import TestCase
from bzrlib.plugins.svn import core, properties

class TestProperties(TestCase):
    def setUp(self):
        super(TestProperties, self).setUp()

    def test_time_from_cstring(self):
        self.assertEquals(1225704780716938L, properties.time_from_cstring("2008-11-03T09:33:00.716938Z"))

    def test_time_to_cstring(self):
        self.assertEquals("2008-11-03T09:33:00.716938Z", properties.time_to_cstring(1225704780716938L))


class TestExternalsParser(TestCase):
    def test_parse_root_relative_externals(self):
        self.assertRaises(NotImplementedError, properties.parse_externals_description, 
                    "http://example.com", "third-party/skins              ^/foo")

    def test_parse_scheme_relative_externals(self):
        self.assertRaises(NotImplementedError, properties.parse_externals_description, 
                    "http://example.com", "third-party/skins              //foo")

    def test_parse_externals(self):
        self.assertEqual({
            'third-party/sounds': (None, "http://sounds.red-bean.com/repos"),
            'third-party/skins': (None, "http://skins.red-bean.com/repositories/skinproj"),
            'third-party/skins/toolkit': (21, "http://svn.red-bean.com/repos/skin-maker")},
            properties.parse_externals_description("http://example.com",
"""third-party/sounds             http://sounds.red-bean.com/repos
third-party/skins              http://skins.red-bean.com/repositories/skinproj
third-party/skins/toolkit -r21 http://svn.red-bean.com/repos/skin-maker"""))

    def test_parse_comment(self):
        self.assertEqual({
            'third-party/sounds': (None, "http://sounds.red-bean.com/repos")
                },
            properties.parse_externals_description("http://example.com/",
"""

third-party/sounds             http://sounds.red-bean.com/repos
#third-party/skins              http://skins.red-bean.com/repositories/skinproj
#third-party/skins/toolkit -r21 http://svn.red-bean.com/repos/skin-maker"""))

    def test_parse_relative(self):
        self.assertEqual({
            'third-party/sounds': (None, "http://example.com/branches/other"),
                },
            properties.parse_externals_description("http://example.com/trunk",
"third-party/sounds             ../branches/other"))

    def test_parse_repos_root_relative(self):
        self.assertEqual({
            'third-party/sounds': (None, "http://example.com/bar/bla/branches/other"),
                },
            properties.parse_externals_description("http://example.com/trunk",
"third-party/sounds             /bar/bla/branches/other"))

    def test_parse_invalid_missing_url(self):
        """No URL specified."""
        self.assertRaises(properties.InvalidExternalsDescription, 
            lambda: properties.parse_externals_description("http://example.com/", "bla"))
            
    def test_parse_invalid_too_much_data(self):
        """No URL specified."""
        self.assertRaises(properties.InvalidExternalsDescription, 
            lambda: properties.parse_externals_description(None, "bla -R40 http://bla/"))
 

class MergeInfoPropertyParserTests(TestCase):
    def test_simple_range(self):
        self.assertEquals({"/trunk": [(1,2,True)]}, properties.parse_mergeinfo_property("/trunk:1-2\n"))

    def test_simple_range_uninheritable(self):
        self.assertEquals({"/trunk": [(1,2,False)]}, properties.parse_mergeinfo_property("/trunk:1-2*\n"))

    def test_simple_individual(self):
        self.assertEquals({"/trunk": [(1,1,True)]}, properties.parse_mergeinfo_property("/trunk:1\n"))

    def test_empty(self):
        self.assertEquals({}, properties.parse_mergeinfo_property(""))
       

class MergeInfoPropertyCreatorTests(TestCase):
    def test_simple_range(self):
        self.assertEquals("/trunk:1-2\n", properties.generate_mergeinfo_property({"/trunk": [(1,2,True)]}))

    def test_simple_individual(self):
        self.assertEquals("/trunk:1\n", properties.generate_mergeinfo_property({"/trunk": [(1,1,True)]}))

    def test_empty(self):
        self.assertEquals("", properties.generate_mergeinfo_property({}))


class RevnumRangeTests(TestCase):
    def test_add_revnum_empty(self):
        self.assertEquals([(1,1,True)], properties.range_add_revnum([], 1))

    def test_add_revnum_before(self):
        self.assertEquals([(2,2,True), (8,8,True)], properties.range_add_revnum([(2,2,True)], 8))

    def test_add_revnum_included(self):
        self.assertEquals([(1,3,True)], properties.range_add_revnum([(1,3,True)], 2))
        
    def test_add_revnum_after(self):
        self.assertEquals([(1,3,True),(5,5,True)], properties.range_add_revnum([(1,3,True)], 5))

    def test_add_revnum_extend_before(self):
        self.assertEquals([(1,3,True)], properties.range_add_revnum([(2,3,True)], 1))

    def test_add_revnum_extend_after(self):
        self.assertEquals([(1,3,True)], properties.range_add_revnum([(1,2,True)], 3))

    def test_revnum_includes_empty(self):
        self.assertFalse(properties.range_includes_revnum([], 2))

    def test_revnum_includes_oor(self):
        self.assertFalse(properties.range_includes_revnum([(1,3,True), (4,5, True)], 10))

    def test_revnum_includes_in(self):
        self.assertTrue(properties.range_includes_revnum([(1,3,True), (4,5, True)], 2))


class MergeInfoIncludeTests(TestCase):
    def test_includes_individual(self):
        self.assertTrue(properties.mergeinfo_includes_revision({"/trunk": [(1,1,True)]}, "/trunk", 1))

    def test_includes_range(self):
        self.assertTrue(properties.mergeinfo_includes_revision({"/trunk": [(1,5,True)]}, "/trunk", 3))

    def test_includes_invalid_path(self):
        self.assertFalse(properties.mergeinfo_includes_revision({"/somepath": [(1,5,True)]}, "/trunk", 3))

    def test_includes_invalid_revnum(self):
        self.assertFalse(properties.mergeinfo_includes_revision({"/trunk": [(1,5,True)]}, "/trunk", 30))
