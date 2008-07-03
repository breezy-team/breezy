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
        self.assertRaises(InvalidExternalsDescription, 
            lambda: properties.parse_externals_description("http://example.com/", "bla"))
            
    def test_parse_invalid_too_much_data(self):
        """No URL specified."""
        self.assertRaises(InvalidExternalsDescription, 
            lambda: properties.parse_externals_description(None, "bla -R40 http://bla/"))
 

class MergeInfoPropertyParserTests(TestCase):
    def test_simple_range(self):
        self.assertEquals({"/trunk": [(1,2)]}, properties.parse_mergeinfo_property("/trunk:1-2\n"))

    def test_simple_individual(self):
        self.assertEquals({"/trunk": [(1,1)]}, properties.parse_mergeinfo_property("/trunk:1\n"))

    def test_empty(self):
        self.assertEquals({}, properties.parse_mergeinfo_property(""))
       
