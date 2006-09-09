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


class Registry(object):
    """A class that registers objects to a name."""

    def __init__(self):
        """Create a new Registry."""
        self._default_key = None
        # Map from key => (is_lazy, info)
        self._dict = {}

    def register(self, key, object):
        """Register a new object to a name.

        :param key: This is the key to use to request the object later.
        :param object: The object to register.
        """
        self._dict[key] = (False, object)

    __setitem__ = register

    def register_lazy(self, key, module_name, member_name):
        """Register a new object to be loaded on request.

        :param module_name: The python path to the module. Such as 'os.path'.
        :param member_name: The member of the module to return, if empty or 
                None get() will return the module itself.
        """
        self._dict[key] = (True, (module_name, member_name))

    def get(self, key=None):
        """Return the object register()'ed to the given key.

        May raise ImportError if the object was registered lazily and
        there are any problems, or AttributeError if the module does not 
        have the supplied member.

        :param key: The key to obtain the object for. If no object has been
            registered to that key, the object registered for self.default_key
            will be returned instead, if it exists. Otherwise KeyError will be
            raised.
        :return: The previously registered object.
        """
        if key is None:
            if self.default_key is None:
                raise KeyError('Key is None, and no default key is set')
            else:
                key = self.default_key
        return self._get_one(key)

    __getitem__ = get

    def _get_one(self, key):
        """Attempt to return a single entry.

        This will import the entry if it is lazy, and replace the registry
        with the imported object.

        This may raise KeyError if the given key doesn't exist, or ImportError
        or AttributeError.
        """
        is_lazy, info_or_object = self._dict[key]
        if not is_lazy:
            # We have a real object to return
            return info_or_object

        module_name, member_name = info_or_object
        obj = __import__(module_name, globals(), locals(), [member_name])
        if member_name:
            obj = getattr(obj, member_name)
        self._dict[key] = (False, obj)
        return obj

    def remove(self, key):
        """Remove a registered entry.

        This is mostly for the test suite, but it can be used by others
        """
        del self._dict[key]

    __delitem__ = remove

    def __contains__(self, key):
        return key in self._dict

    def __len__(self):
        return len(self._dict)

    def keys(self):
        """Get a list of registered entries"""
        return sorted(self._dict.keys())

    def iterkeys(self):
        return self._dict.iterkeys()

    def iteritems(self):
        for key in self._dict.iterkeys():
            yield key, self._get_one(key)

    def items(self):
        return list(self.iteritems())

    def itervalues(self):
        for key in self._dict.iterkeys():
            yield self._get_one(key)

    def values(self):
        return list(self.itervalues())

    def _set_default_key(self, key):
        if not self._dict.has_key(key):
            raise KeyError('No object registered under key %s.' % key)
        else:
            self._default_key = key

    def _get_default_key(self):
        return self._default_key

    default_key = property(_get_default_key, _set_default_key,
                            doc="Current value of the default key."
                                "Can be set to any existing key.")
