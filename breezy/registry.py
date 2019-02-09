# Copyright (C) 2006-2010 Canonical Ltd
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

"""Classes to provide name-to-object registry-like support."""

from __future__ import absolute_import

from .pyutils import get_named_object

from .sixish import viewitems


class _ObjectGetter(object):
    """Maintain a reference to an object, and return the object on request.

    This is used by Registry to make plain objects function similarly
    to lazily imported objects.

    Objects can be any sort of python object (class, function, module,
    instance, etc)
    """

    __slots__ = ['_obj']

    def __init__(self, obj):
        self._obj = obj

    def get_module(self):
        """Get the module the object was loaded from."""
        return self._obj.__module__

    def get_obj(self):
        """Get the object that was saved at creation time"""
        return self._obj


class _LazyObjectGetter(_ObjectGetter):
    """Keep a record of a possible object.

    When requested, load and return it.
    """

    __slots__ = ['_module_name', '_member_name', '_imported']

    def __init__(self, module_name, member_name):
        self._module_name = module_name
        self._member_name = member_name
        self._imported = False
        super(_LazyObjectGetter, self).__init__(None)

    def get_module(self):
        """Get the module the referenced object will be loaded from.
        """
        return self._module_name

    def get_obj(self):
        """Get the referenced object.

        Upon first request, the object will be imported. Future requests will
        return the imported object.
        """
        if not self._imported:
            self._obj = get_named_object(self._module_name, self._member_name)
            self._imported = True
        return super(_LazyObjectGetter, self).get_obj()

    def __repr__(self):
        return "<%s.%s object at %x, module=%r attribute=%r imported=%r>" % (
            self.__class__.__module__, self.__class__.__name__, id(self),
            self._module_name, self._member_name, self._imported)


class Registry(object):
    """A class that registers objects to a name.

    There are many places that want to collect related objects and access them
    by a key. This class is designed to allow registering the mapping from key
    to object. It goes one step further, and allows registering a name to a
    hypothetical object which has not been imported yet. It also supports
    adding additional information at registration time so that decisions can be
    made without having to import the object (which may be expensive).

    The functions 'get', 'get_info', and 'get_help' also support a
    'default_key' (settable through my_registry.default_key = XXX, XXX must
    already be registered.) Calling my_registry.get() or my_registry.get(None),
    will return the entry for the default key.
    """

    def __init__(self):
        """Create a new Registry."""
        self._default_key = None
        # Map from key => (is_lazy, info)
        self._dict = {}
        self._aliases = {}
        self._help_dict = {}
        self._info_dict = {}

    def aliases(self):
        """Return a set of the format names which are aliases."""
        return dict(viewitems(self._aliases))

    def alias_map(self):
        ret = {}
        for alias, target in viewitems(self._aliases):
            ret.setdefault(target, []).append(alias)
        return ret

    def register(self, key, obj, help=None, info=None,
                 override_existing=False):
        """Register a new object to a name.

        :param key: This is the key to use to request the object later.
        :param obj: The object to register.
        :param help: Help text for this entry. This may be a string or
                a callable. If it is a callable, it should take two
                parameters (registry, key): this registry and the key that
                the help was registered under.
        :param info: More information for this entry. Registry.get_info()
                can be used to get this information. Registry treats this as an
                opaque storage location (it is defined by the caller).
        :param override_existing: Raise KeyErorr if False and something has
                already been registered for that key. If True, ignore if there
                is an existing key (always register the new value).
        """
        if not override_existing:
            if key in self._dict:
                raise KeyError('Key %r already registered' % key)
        self._dict[key] = _ObjectGetter(obj)
        self._add_help_and_info(key, help=help, info=info)

    def register_lazy(self, key, module_name, member_name,
                      help=None, info=None,
                      override_existing=False):
        """Register a new object to be loaded on request.

        :param key: This is the key to use to request the object later.
        :param module_name: The python path to the module. Such as 'os.path'.
        :param member_name: The member of the module to return.  If empty or
                None, get() will return the module itself.
        :param help: Help text for this entry. This may be a string or
                a callable.
        :param info: More information for this entry. Registry.get_info()
                can be used to get this information. Registry treats this as an
                opaque storage location (it is defined by the caller).
        :param override_existing: If True, replace the existing object
                with the new one. If False, if there is already something
                registered with the same key, raise a KeyError
        """
        if not override_existing:
            if key in self._dict:
                raise KeyError('Key %r already registered' % key)
        self._dict[key] = _LazyObjectGetter(module_name, member_name)
        self._add_help_and_info(key, help=help, info=info)

    def register_alias(self, key, target, info=None):
        """Register an alias.

        :param key: Alias name
        :param target: Target key name
        """
        if key in self._dict and key not in self._aliases:
            raise KeyError('Key %r already registered and not an alias' % key)
        self._dict[key] = self._dict[target]
        self._aliases[key] = target
        if info is None:
            info = self._info_dict[target]
        self._add_help_and_info(key, help=self._help_dict[target], info=info)

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
        :raises ImportError: If the object was registered lazily, and there are
            problems during import.
        :raises AttributeError: If registered lazily, and the module does not
            contain the registered member.
        """
        return self._dict[self._get_key_or_default(key)].get_obj()

    def _get_module(self, key):
        """Return the module the object will be or was loaded from.

        :param key: The key to obtain the module for.
        :return: The name of the module
        """
        return self._dict[key].get_module()

    def get_prefix(self, fullname):
        """Return an object whose key is a prefix of the supplied value.

        :fullname: The name to find a prefix for
        :return: a tuple of (object, remainder), where the remainder is the
            portion of the name that did not match the key.
        """
        for key in self.keys():
            if fullname.startswith(key):
                return self.get(key), fullname[len(key):]

    def _get_key_or_default(self, key=None):
        """Return either 'key' or the default key if key is None"""
        if key is not None:
            return key
        if self.default_key is None:
            raise KeyError('Key is None, and no default key is set')
        else:
            return self.default_key

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
        return sorted(self._dict)

    def iteritems(self):
        for key in self._dict:
            yield key, self._dict[key].get_obj()

    def items(self):
        # We should not use the iteritems() implementation below (see bug
        # #430510)
        return [(key, self._dict[key].get_obj()) for key in self.keys()]

    def _set_default_key(self, key):
        if key not in self._dict:
            raise KeyError('No object registered under key %s.' % key)
        else:
            self._default_key = key

    def _get_default_key(self):
        return self._default_key

    default_key = property(_get_default_key, _set_default_key,
                           doc="Current value of the default key."
                           " Can be set to any existing key.")


class FormatRegistry(Registry):
    """Registry specialised for handling formats."""

    def __init__(self, other_registry=None):
        Registry.__init__(self)
        self._other_registry = other_registry

    def register(self, key, obj, help=None, info=None,
                 override_existing=False):
        Registry.register(self, key, obj, help=help, info=info,
                          override_existing=override_existing)
        if self._other_registry is not None:
            self._other_registry.register(key, obj, help=help,
                                          info=info, override_existing=override_existing)

    def register_lazy(self, key, module_name, member_name,
                      help=None, info=None,
                      override_existing=False):
        # Overridden to allow capturing registrations to two seperate
        # registries in a single call.
        Registry.register_lazy(self, key, module_name, member_name,
                               help=help, info=info, override_existing=override_existing)
        if self._other_registry is not None:
            self._other_registry.register_lazy(key, module_name, member_name,
                                               help=help, info=info, override_existing=override_existing)

    def remove(self, key):
        Registry.remove(self, key)
        if self._other_registry is not None:
            self._other_registry.remove(key)

    def get(self, format_string):
        r = Registry.get(self, format_string)
        if callable(r):
            r = r()
        return r
