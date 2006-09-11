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


class ImportReplacer(ScopeReplacer):
    """This is designed to replace only a portion of an import list.

    It will replace itself with a module, and then make children
    entries also ImportReplacer objects.

    At present, this only supports 'import foo.bar.baz' syntax.
    """

    # Intentially a long semi-unique name that won't likely exist
    # elsewhere. (We can't use isinstance because that accesses __class__
    # which causes the __getattribute__ to trigger)
    __slots__ = ('_import_replacer_children', '_member', '_module_path')

    def __init__(self, scope, name, module_path, member=None, children=[]):
        """Upon request import 'module_path' as the name 'module_name'.
        When imported, prepare children to also be imported.

        :param scope: The scope that objects should be imported into.
            Typically this is globals()
        :param name: The variable name. Often this is the same as the 
            module_path. 'bzrlib'
        :param module_path: A list for the fully specified module path
            ['bzrlib', 'foo', 'bar']
        :param member: The member inside the module to import, often this is
            None, indicating the module is being imported.
        :param children: Children entries to be imported later.
            This should be a list of children specifications.
            [('foo', 'bzrlib.foo', [('bar', 'bzrlib.foo.bar'),])]
        Examples:
            import foo => name='foo' module_path='foo',
                          member=None, children=[]
            import foo.bar => name='foo' module_path='foo', member=None,
                              children=[('bar', ['foo', 'bar'], [])]
            from foo import bar => name='bar' module_path='foo', member='bar'
                                   children=[]
            from foo import bar, baz would get translated into 2 import
            requests. On for 'name=bar' and one for 'name=baz'
        """
        if member is not None:
            assert not children, \
                'Cannot supply both a member and children'

        self._import_replacer_children = children
        self._member = member
        self._module_path = module_path

        # Indirecting through __class__ so that children can
        # override _import (especially our instrumented version)
        cls = object.__getattribute__(self, '__class__')
        ScopeReplacer.__init__(self, scope=scope, name=name,
                               factory=cls._import)

    def _import(self, scope, name):
        children = object.__getattribute__(self, '_import_replacer_children')
        member = object.__getattribute__(self, '_member')
        module_path = object.__getattribute__(self, '_module_path')
        module_python_path = '.'.join(module_path)
        if member is not None:
            module = __import__(module_python_path, scope, scope, [member])
            return getattr(module, member)
        else:
            module = __import__(module_python_path, scope, scope, [])
            for path in module_path[1:]:
                module = getattr(module, path)

        # Prepare the children to be imported
        for child_name, child_path, grandchildren in children:
            # Using self.__class__, so that children get children classes
            # instantiated. (This helps with instrumented tests)
            cls = object.__getattribute__(self, '__class__')
            cls(module.__dict__, name=child_name,
                module_path=child_path, member=None,
                children=grandchildren)
        return module
