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


import os


from bzrlib import tests
from bzrlib.tests import (
    features,
    )


class TestTreeShape(tests.TestCaseWithTransport):

    def test_build_tree(self):
        """Test tree-building test helper"""
        self.build_tree_contents([
            ('foo', 'new contents'),
            ('.bzr/',),
            ('.bzr/README', 'hello'),
            ])
        self.assertPathExists('foo')
        self.assertPathExists('.bzr/README')
        self.assertFileEqual('hello', '.bzr/README')

    def test_build_tree_symlink(self):
        self.requireFeature(features.SymlinkFeature)
        self.build_tree_contents([('link@', 'target')])
        self.assertEqual('target',
            os.readlink('link'))
