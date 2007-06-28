# Copyright (C) 2007 Canonical Ltd
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

"""Tests for the core Hooks logic."""

from bzrlib.hooks import (
    Hooks,
    )
from bzrlib.errors import (
    UnknownHook,
    )

from bzrlib.tests import TestCase


class TestHooks(TestCase):

    def test_install_hook_raises_unknown_hook(self):
        """install_hook should raise UnknownHook if a hook is unknown."""
        hooks = Hooks()
        self.assertRaises(UnknownHook, hooks.install_hook, 'silly', None)

    def test_install_hook_appends_known_hook(self):
        """install_hook should append the callable for known hooks."""
        hooks = Hooks()
        hooks['set_rh'] = []
        hooks.install_hook('set_rh', None)
        self.assertEqual(hooks['set_rh'], [None])

    def test_name_hook_and_retrieve_name(self):
        """name_hook puts the name in the names mapping."""
        hooks = Hooks()
        hooks['set_rh'] = []
        hooks.install_hook('set_rh', None)
        hooks.name_hook(None, 'demo')
        self.assertEqual("demo", hooks.get_hook_name(None))

    def test_get_unnamed_hook_name_is_unnamed(self):
        hooks = Hooks()
        hooks['set_rh'] = []
        hooks.install_hook('set_rh', None)
        self.assertEqual("No hook name", hooks.get_hook_name(None))
