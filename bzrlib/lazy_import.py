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
        :param module_path: The fully specified dotted path to the module.
            'bzrlib.foo.bar'
        :param member: The member inside the module to import, often this is
            None, indicating the module is being imported.
        :param children: Children entries to be imported later.
            This should be a list of children specifications.
            [('foo', 'bzrlib.foo', [('bar', 'bzrlib.foo.bar'),])]
        Examples:
            import foo => name='foo' module_path='foo',
                          member=None, children=[]
            import foo.bar => name='foo' module_path='foo', member=None,
                              children=[('bar', 'foo.bar', [])]
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
        ScopeReplacer.__init__(self, scope=scope, name=name,
                               factory=ImportReplacer._import)

    def _import(self, scope, name):
        children = object.__getattribute__(self, '_import_replacer_children')
        member = object.__getattribute__(self, '_member')
        module_path = object.__getattribute__(self, '_module_path')
        if member is not None:
            module = __import__(module_path, scope, scope, (member,))
            return getattr(module, member)
        else:
            module = __import__(module_path, scope, scope, None)

        # Prepare the children to be imported
        for child_name, child_path, grandchildren in children:
            ImportReplacer(module.__dict__, name=child_name,
                           module_path=child_path, member=None,
                           children=grandchildren)

    def _replace(self):
        """Actually replace self with other in the given scope"""
        factory = object.__getattribute__(self, '_factory')
        scope = object.__getattribute__(self, '_scope')
        name = object.__getattribute__(self, '_name')
        obj = factory()
        scope[name] = obj
        return obj


class _Importer(object):
    """Helper for importing modules, but waiting until they are used.

    This also helps to ensure that existing ScopeReplacer objects are
    re-used in the current scope.
    """

    __slots__ = ['scope', 'modname', 'fromlist', 'mod']

    def __init__(self, scope, modname, fromlist):
        """
        :param scope: calling context globals() where the import should be made
        :param modname: The name of the module
        :param fromlist: the fromlist portion of 'from foo import bar'
        """
        self.scope = scope
        self.modname = modname
        self.fromlist = fromlist
        self.mod = None

    def module(self):
        """Import a module if not imported yet, and return"""
        if self.mod is None:
            self.mod = __import__(self.modname, self.scope, self.scope,
                                  self.fromlist)
            if isinstance(self.mod, _replacer):
                del sys.modules[self.modname]
                self.mod = __import__(self.modname, self.scope, self.scope,
                                      self.fromlist)
            del self.modname, self.fromlist
        return self.mod

class _replacer(object):
    '''placeholder for a demand loaded module. demandload puts this in
    a target scope.  when an attribute of this object is looked up,
    this object is replaced in the target scope with the actual
    module.

    we use __getattribute__ to avoid namespace clashes between
    placeholder object and real module.'''

    def __init__(self, importer, target):
        self.importer = importer
        self.target = target
        # consider case where we do this:
        #   demandload(globals(), 'foo.bar foo.quux')
        # foo will already exist in target scope when we get to
        # foo.quux.  so we remember that we will need to demandload
        # quux into foo's scope when we really load it.
        self.later = []

    def module(self):
        return object.__getattribute__(self, 'importer').module()

    def __getattribute__(self, key):
        '''look up an attribute in a module and return it. replace the
        name of the module in the caller\'s dict with the actual
        module.'''

        module = object.__getattribute__(self, 'module')()
        target = object.__getattribute__(self, 'target')
        importer = object.__getattribute__(self, 'importer')
        later = object.__getattribute__(self, 'later')

        if later:
            demandload(module.__dict__, ' '.join(later))

        importer.scope[target] = module

        return getattr(module, key)

class _replacer_from(_replacer):
    '''placeholder for a demand loaded module.  used for "from foo
    import ..." emulation. semantics of this are different than
    regular import, so different implementation needed.'''

    def module(self):
        importer = object.__getattribute__(self, 'importer')
        target = object.__getattribute__(self, 'target')

        return getattr(importer.module(), target)

    def __call__(self, *args, **kwargs):
        target = object.__getattribute__(self, 'module')()
        return target(*args, **kwargs)

def demandload(scope, modules):
    '''import modules into scope when each is first used.

    scope should be the value of globals() in the module calling this
    function, or locals() in the calling function.

    modules is a string listing module names, separated by white
    space.  names are handled like this:

    foo            import foo
    foo bar        import foo, bar
    foo.bar        import foo.bar
    foo:bar        from foo import bar
    foo:bar,quux   from foo import bar, quux
    foo.bar:quux   from foo.bar import quux'''

    for mod in modules.split():
        col = mod.find(':')
        if col >= 0:
            fromlist = mod[col+1:].split(',')
            mod = mod[:col]
        else:
            fromlist = []
        importer = _importer(scope, mod, fromlist)
        if fromlist:
            for name in fromlist:
                scope[name] = _replacer_from(importer, name)
        else:
            dot = mod.find('.')
            if dot >= 0:
                basemod = mod[:dot]
                val = scope.get(basemod)
                # if base module has already been demandload()ed,
                # remember to load this submodule into its namespace
                # when needed.
                if isinstance(val, _replacer):
                    later = object.__getattribute__(val, 'later')
                    later.append(mod[dot+1:])
                    continue
            else:
                basemod = mod
            scope[basemod] = _replacer(importer, basemod)

def lazy_import(scope, module_name, member=None, import_as=None):
    """Lazily import a module into the correct scope.

    This is meant as a possible replacement for __import__.
    It will return a ScopeReplacer object, which will call the real
    '__import__' at the appropriate time.

    :param module_name: The dotted module name
    :param member: Optional, if supplied return the sub member instead of
        the base module.
    :param import_as: Use this as the local object name instead of the
        default name.
    """
    if import_as is None:
        if member is None:
            module_pieces = module_name.split('.')
            final_name = module_pieces[0]
            def factory():
                return __import__(module_name, scope, locals(), [])
        else:
            final_name = member
    else:
        raise NotImplemented('import_as is not yet implemented')
