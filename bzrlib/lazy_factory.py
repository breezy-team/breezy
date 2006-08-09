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

"""LazyFactory lets you register objects to be loaded by request

Basically, formats are registered by some sort of key. In the future
that object can be requested, and the factory will import the appropriate
module, and return the requested member object.
"""


class LazyFactory(object):
    """A factory which registers objects which will be load on request."""

    def __init__(self, first_is_default=False):
        """Create a new Lazy Factory.

        :param first_is_default: If True, then the first object to be registered
            will also be registered against the key None, and will be returned
            by default from .get()
        """
        self._first_is_default = first_is_default
        self._dict = {}

    def register(self, key, module_name, member_name):
        """Register a new object to be loaded on request.

        :param key: This is the key to use to request the object later.
        :param module_name: The python path to the module. Such as 'os.path'
        :param member_name: The member of the module to return, if empty or None
            get() will return the module itself.
        :return: if something used to be registered, its information will be
            returned.
        """
        old_info = self._dict.get(key)
        if self._first_is_default and not self._dict:
            self._dict[None] = (module_name, member_name)
        self._dict[key] = (module_name, member_name)

    def get(self, key=None):
        """Load the module and return the object specified by the given key.

        This may raise KeyError if the key is not present.
        May also raise ImportError if there are any problems
        Or AttributeError if the module does not have the supplied member

        :param key: The key registered by register()
        :return: The module/klass/function/object specified earlier
        """
        module_name, member_name = self._dict[key]
        module = __import__(module_name, globals(), locals(), [member_name])
        if member_name:
            return getattr(module, member_name)
        return module

    def keys(self, include_none=False):
        """Get a list of registered entries"""
        keys = self._dict.keys()
        if not include_none and None in self._dict:
            keys.remove(None)
        return keys
