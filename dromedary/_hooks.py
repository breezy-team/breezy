# Copyright (C) 2007-2011 Canonical Ltd
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

"""Minimal standalone hooks implementation for dromedary."""


class HookPoint:
    """A named hook point that maintains a list of callbacks."""

    def __init__(self, name, doc):
        self.name = name
        self.__doc__ = doc
        self._callbacks = []

    def __iter__(self):
        return iter(self._callbacks)

    def __len__(self):
        return len(self._callbacks)

    def __repr__(self):
        return f"<HookPoint({self.name!r}), callbacks={self._callbacks!r}>"


class Hooks(dict):
    """A dict mapping hook names to HookPoint instances."""

    def __init__(self):
        dict.__init__(self)
        self._callable_names = {}

    def add_hook(self, name, doc, introduced, deprecated=None):
        """Register a new hook point."""
        self[name] = HookPoint(name, doc)

    def install_named_hook(self, hook_name, a_callable, name):
        """Install a callable on the named hook point."""
        try:
            hook = self[hook_name]
        except KeyError:
            raise KeyError(f"Unknown hook: {hook_name!r}")
        hook._callbacks.append(a_callable)
        if name is not None:
            self._callable_names[a_callable] = name

    def uninstall_named_hook(self, hook_name, label):
        """Remove a callable from the named hook point by label."""
        hook = self[hook_name]
        for i, cb in enumerate(hook._callbacks):
            if self._callable_names.get(cb) == label:
                del hook._callbacks[i]
                del self._callable_names[cb]
                return
        raise KeyError(f"No hook named {label!r} on {hook_name!r}")

    def get_hook_name(self, a_callable):
        """Return the name associated with a callable, or a repr."""
        return self._callable_names.get(a_callable, repr(a_callable))
