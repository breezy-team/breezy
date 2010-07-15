# Copyright (C) 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


from bzrlib.tests import TestCaseWithTransport


class TestTreeShape(TestCaseWithTransport):

    def test_build_tree(self):
        """Test tree-building test helper"""
        self.build_tree_contents([
            ('foo', 'new contents'),
            ('.bzr/',),
            ('.bzr/README', 'hello'),
            ])
        self.failUnlessExists('foo')
        self.failUnlessExists('.bzr/README')
        self.assertFileEqual('hello', '.bzr/README')

