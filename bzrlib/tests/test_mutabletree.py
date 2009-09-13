# Copyright (C) 2008 Canonical Ltd
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

"""Tests for MutableTree.

Most functionality of MutableTree is tested as part of WorkingTree.
"""

from bzrlib.tests import TestCase
from bzrlib.mutabletree import MutableTree, MutableTreeHooks

class TestHooks(TestCase):

    def test_constructor(self):
        """Check that creating a MutableTreeHooks instance has the right
        defaults."""
        hooks = MutableTreeHooks()
        self.assertTrue("start_commit" in hooks,
                        "start_commit not in %s" % hooks)
        self.assertTrue("post_commit" in hooks,
                        "post_commit not in %s" % hooks)

    def test_installed_hooks_are_MutableTreeHooks(self):
        """The installed hooks object should be a MutableTreeHooks."""
        # the installed hooks are saved in self._preserved_hooks.
        self.assertIsInstance(self._preserved_hooks[MutableTree][1],
                              MutableTreeHooks)


