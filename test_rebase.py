# Copyright (C) 2006-2007 by Jelmer Vernooij
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

from bzrlib.errors import UnknownFormatError
from bzrlib.tests import TestCase

from rebase import marshall_rebase_plan, unmarshall_rebase_plan

class RebasePlanReadWriterTests(TestCase):
    def test_simple_marshall_rebase_plan(self):
        self.assertEqualDiff(
"""# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
""", marshall_rebase_plan((1, "bla"), 
                          {"oldrev": ("newrev", ["newparent1", "newparent2"])}))

    def test_simple_unmarshall_rebase_plan(self):
        self.assertEquals(((1, "bla"), 
                          {"oldrev": ("newrev", ["newparent1", "newparent2"])}),
                         unmarshall_rebase_plan("""# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
"""))

    def test_unmarshall_rebase_plan_formatunknown(self):
        self.assertRaises(UnknownFormatError,
                         unmarshall_rebase_plan, """# Bazaar rebase plan x
1 bla
oldrev newrev newparent1 newparent2
""")
