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


"""Support for plugin hooking logic."""
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
        errors,
        )
""")


class Hooks(dict):
    """A dictionary mapping hook name to a list of callables.
    
    e.g. ['FOO'] Is the list of items to be called when the
    FOO hook is triggered.
    """

    def __init__(self):
        dict.__init__(self)
        self._callable_names = {}

    def get_hook_name(self, a_callable):
        """Get the name for a_callable for UI display.

        If no name has been registered, the string 'No hook name' is returned.
        """
        return self._callable_names.get(a_callable, "No hook name")

    def install_hook(self, hook_name, a_callable):
        """Install a_callable in to the hook hook_name.

        :param hook_name: A hook name. See the __init__ method of BranchHooks
            for the complete list of hooks.
        :param a_callable: The callable to be invoked when the hook triggers.
            The exact signature will depend on the hook - see the __init__ 
            method of BranchHooks for details on each hook.
        """
        try:
            self[hook_name].append(a_callable)
        except KeyError:
            raise errors.UnknownHook(self.__class__.__name__, hook_name)

    def name_hook(self, a_callable, name):
        """Associate name with a_callable to show users what is running."""
        self._callable_names[a_callable] = name
