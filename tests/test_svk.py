# Copyright (C) 2005-2008 Jelmer Vernooij <jelmer@samba.org>
 
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

from bzrlib.tests import TestCase
from svk import parse_svk_feature

class SvkTests(TestCase):
    def test_parse_svk_feature_root(self):
        self.assertEqual(("auuid", "", 6), 
                 parse_svk_feature("auuid:/:6"))

    def test_svk_revid_map_nested(self):
        self.assertEqual(("auuid", "bp", 6),
                         parse_svk_feature("auuid:/bp:6"))


