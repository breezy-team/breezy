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

"""Classes to provide name-to-object registry-like support."""


_marker = object()


class Registry(object):
    """A class that registers objects to a name."""

    def __init__(self, first_is_default=False):
        """Create a new Registry.

        :param first_is_default: If True, then the first key to be registered
            will be set as the default key for get() to use.
        """
        self._first_is_default = first_is_default
        self._default_key = None
        self._dict = {}

    def register(self, key, object):
        """Register a new object to a name.

        :param key: This is the key to use to request the object later.
        :param object: The object to register.
        """
        if self._first_is_default and not self._dict:
            self._default_key = key
        self._dict[key] = object

    def get(self, key=_marker, fallback_key=_marker):
        """Return the object register()'ed by the given key.

        This may raise KeyError if the key is not present.

        :param key: The key to obtain the object for; if not given, :param
            fallback_key: will be used.
        :param fallback_key: Key to use if an object for :param key: can't be
            found; defaults to self.default_key. Set it to None if you'd like
            to ensure an exception is raised for non-found keys.
        :return: The previously registered object.
        """
        if fallback_key is _marker:
            fallback_key = self.default_key

        if key is _marker:
            return self._dict[fallback_key]
        else:
            try:
                return self._dict[key]
            except KeyError:
                return self._dict[fallback_key]

    def keys(self):
        """Get a list of registered entries"""
        return sorted(self._dict.keys())

    def _set_default_key(self, key):
        if not self._dict.has_key(key):
            raise KeyError('No object registered under key %s.' % key)
        else:
            self._default_key = key

    def _get_default_key(self):
        return self._default_key

    default_key = property(_get_default_key, _set_default_key)
    """Current value of the default key. Can be set to any existing key."""


class LazyImportRegistry(Registry):
    """A class to register modules/members to be loaded on request."""

    def register(self, key, module_name, member_name):
        """Register a new object to be loaded on request.

        :param module_name: The python path to the module. Such as 'os.path'.
        :param member_name: The member of the module to return, if empty or None
            get() will return the module itself.
        """
        Registry.register(self, key, (module_name, member_name))

    def get(self, key=None, default_key=_marker):
        """Load the module and return the object specified by the given key.

        May raise ImportError if there are any problems, or AttributeError if
        the module does not have the supplied member.
        """
        module_name, member_name = Registry.get(self, key, default_key)
        module = __import__(module_name, globals(), locals(), [member_name])
        if member_name:
            return getattr(module, member_name)
        return module
