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
    """A class that registers objects to a name.

    This is designed such that you can register objects in a lazy fashion,
    so that they can be imported later. While still having the help text
    available right away.
    """

    def __init__(self):
        """Create a new Registry."""
        self._default_key = None
        # Map from key => (is_lazy, info)
        self._dict = {}
        self._help_dict = {}
        self._info_dict = {}

    def register(self, key, object, help=None, info=None,
                 override_existing=False):
        """Register a new object to a name.

        :param key: This is the key to use to request the object later.
        :param object: The object to register.
        :param help: Help text for this entry. This may be a string or
                a callable. If it is a callable, it should take two
                parameters, this registry and the key that the help was
                registered under.
        :param info: More information for this entry. Registry.get_info()
                can be used to get this information. It is meant as an
                opaque storage location.
        :param override_existing: If True, replace the existing object
                with the new one. If False, if there is already something
                registered with the same key, raise a KeyError
        """
        if not override_existing:
            if key in self._dict:
                raise KeyError('Key %r already registered' % key)
        self._dict[key] = (False, object)
        self._add_help_and_info(key, help=help, info=info)

    def register_lazy(self, key, module_name, member_name,
                      help=None, info=None,
                      override_existing=False):
        """Register a new object to be loaded on request.

        :param module_name: The python path to the module. Such as 'os.path'.
        :param member_name: The member of the module to return, if empty or 
                None get() will return the module itself.
        :param help: Help text for this entry. This may be a string or
                a callable.
        :param info: More information for this entry. Registry 
        :param override_existing: If True, replace the existing object
                with the new one. If False, if there is already something
                registered with the same key, raise a KeyError
        """
        if not override_existing:
            if key in self._dict:
                raise KeyError('Key %r already registered' % key)
        self._dict[key] = (True, (module_name, member_name))
        self._add_help_and_info(key, help=help, info=info)

    def _add_help_and_info(self, key, help=None, info=None):
        """Add the help and information about this key"""
        self._help_dict[key] = help
        self._info_dict[key] = info

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
        return self._get_one(self._get_key_or_default(key))

    def _get_key_or_default(self, key=None):
        """Return either 'key' or the default key if key is None"""
        if key is not None:
            return key
        if self.default_key is None:
            raise KeyError('Key is None, and no default key is set')
        else:
            return self.default_key

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

    def get_help(self, key=None):
        """Get the help text associated with the given key"""
        the_help = self._help_dict[self._get_key_or_default(key)]
        if callable(the_help):
            return the_help(self, key)
        return the_help

    def get_info(self, key=None):
        """Get the extra information associated with the given key"""
        return self._info_dict[self._get_key_or_default(key)]

    def remove(self, key):
        """Remove a registered entry.

        This is mostly for the test suite, but it can be used by others
        """
        del self._dict[key]

    def __contains__(self, key):
        return key in self._dict

    def keys(self):
        """Get a list of registered entries"""
        return sorted(self._dict.keys())

    def iteritems(self):
        for key in self._dict.iterkeys():
            yield key, self._get_one(key)

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
