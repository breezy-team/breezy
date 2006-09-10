# Copyright (C) 2006 by Canonical Ltd
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

"""Functionality to create lazy evaluation objects.

This includes waiting to import a module until it is actually used.
"""

import sys


class ScopeReplacer(object):
    """A lazy object that will replace itself in the appropriate scope.

    This object sits, ready to create the real object the first time it is
    needed.
    """

    __slots__ = ('_scope', '_factory', '_name')

    def __init__(self, scope, factory, name):
        """Create a temporary object in the specified scope.
        Once used, a real object will be placed in the scope.

        :param scope: The scope the object should appear in
        :param factory: A callable that will create the real object.
            It will be passed (self, scope, name)
        :param name: The variable name in the given scope.
        """
        self._scope = scope
        self._factory = factory
        self._name = name
        scope[name] = self

    def _replace(self):
        """Actually replace self with other in the given scope"""
        factory = object.__getattribute__(self, '_factory')
        scope = object.__getattribute__(self, '_scope')
        name = object.__getattribute__(self, '_name')
        obj = factory(self, scope, name)
        scope[name] = obj
        return obj

    def _cleanup(self):
        """Stop holding on to all the extra stuff"""
        del self._factory
        del self._scope
        del self._name

    def __getattribute__(self, attr):
        obj = object.__getattribute__(self, '_replace')()
        object.__getattribute__(self, '_cleanup')()
        return getattr(obj, attr)

    def __call__(self, *args, **kwargs):
        obj = object.__getattribute__(self, '_replace')()
        object.__getattribute__(self, '_cleanup')()
        return obj(*args, **kwargs)


