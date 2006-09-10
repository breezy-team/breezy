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

"""Test the lazy_import functionality."""

import os
import sys

from bzrlib import (
    lazy_import,
    osutils,
    )
from bzrlib.tests import TestCase, TestCaseInTempDir


class InstrumentedReplacer(lazy_import.ScopeReplacer):
    """Track what actions are done"""

    @staticmethod
    def use_actions(actions):
        InstrumentedReplacer.actions = actions

    def _replace(self):
        InstrumentedReplacer.actions.append('_replace')
        return lazy_import.ScopeReplacer._replace(self)

    def __getattribute__(self, attr):
        InstrumentedReplacer.actions.append(('__getattribute__', attr))
        return lazy_import.ScopeReplacer.__getattribute__(self, attr)

    def __call__(self, *args, **kwargs):
        InstrumentedReplacer.actions.append(('__call__', args, kwargs))
        return lazy_import.ScopeReplacer.__call__(self, *args, **kwargs)


class InstrumentedImportReplacer(lazy_import.ImportReplacer):

    @staticmethod
    def use_actions(actions):
        InstrumentedImportReplacer.actions = actions

    def _import(self, scope, name):
        InstrumentedImportReplacer.actions.append(('_import', name))
        return lazy_import.ImportReplacer._import(self, scope, name)

    def _replace(self):
        InstrumentedImportReplacer.actions.append('_replace')
        return lazy_import.ScopeReplacer._replace(self)

    def __getattribute__(self, attr):
        InstrumentedImportReplacer.actions.append(('__getattribute__', attr))
        return lazy_import.ScopeReplacer.__getattribute__(self, attr)

    def __call__(self, *args, **kwargs):
        InstrumentedImportReplacer.actions.append(('__call__', args, kwargs))
        return lazy_import.ScopeReplacer.__call__(self, *args, **kwargs)


class TestClass(object):
    """Just a simple test class instrumented for the test cases"""

    class_member = 'class_member'

    @staticmethod
    def use_actions(actions):
        TestClass.actions = actions

    def __init__(self):
        TestClass.actions.append('init')

    def foo(self, x):
        TestClass.actions.append(('foo', x))
        return 'foo'


class TestScopeReplacer(TestCase):
    """Test the ability of the replacer to put itself into the correct scope.

    In these tests we use the global scope, because we cannot replace
    variables in the local scope. This means that we need to be careful
    and not have the replacing objects use the same name, or we would
    get collisions.
    """

    def test_object(self):

        actions = []
        InstrumentedReplacer.use_actions(actions)
        TestClass.use_actions(actions)

        def factory(replacer, scope, name):
            actions.append('factory')
            return TestClass()

        try:
            test_obj1
        except NameError:
            # test_obj1 shouldn't exist yet
            pass
        else:
            self.fail('test_obj1 was not supposed to exist yet')

        InstrumentedReplacer(scope=globals(), name='test_obj1',
                             factory=factory)

        # We can't use isinstance() because that uses test_obj1.__class__
        # and that goes through __getattribute__ which would activate
        # the replacement
        self.assertEqual(InstrumentedReplacer,
                         object.__getattribute__(test_obj1, '__class__'))
        self.assertEqual('foo', test_obj1.foo(1))
        self.assertIsInstance(test_obj1, TestClass)
        self.assertEqual('foo', test_obj1.foo(2))
        self.assertEqual([('__getattribute__', 'foo'),
                          '_replace',
                          'factory',
                          'init',
                          ('foo', 1),
                          ('foo', 2),
                         ], actions)

    def test_class(self):
        actions = []
        InstrumentedReplacer.use_actions(actions)
        TestClass.use_actions(actions)

        def factory(replacer, scope, name):
            actions.append('factory')
            return TestClass

        try:
            test_class1
        except NameError:
            # test_class2 shouldn't exist yet
            pass
        else:
            self.fail('test_class1 was not supposed to exist yet')

        InstrumentedReplacer(scope=globals(), name='test_class1',
                             factory=factory)

        self.assertEqual('class_member', test_class1.class_member)
        self.assertEqual(test_class1, TestClass)
        self.assertEqual([('__getattribute__', 'class_member'),
                          '_replace',
                          'factory',
                         ], actions)

    def test_call_class(self):
        actions = []
        InstrumentedReplacer.use_actions(actions)
        TestClass.use_actions(actions)

        def factory(replacer, scope, name):
            actions.append('factory')
            return TestClass

        try:
            test_class2
        except NameError:
            # test_class2 shouldn't exist yet
            pass
        else:
            self.fail('test_class2 was not supposed to exist yet')

        InstrumentedReplacer(scope=globals(), name='test_class2',
                             factory=factory)

        self.failIf(test_class2 is TestClass)
        obj = test_class2()
        self.assertIs(test_class2, TestClass)
        self.assertIsInstance(obj, TestClass)
        self.assertEqual('class_member', obj.class_member)
        self.assertEqual([('__call__', (), {}),
                          '_replace',
                          'factory',
                          'init',
                         ], actions)

    def test_call_func(self):
        actions = []
        InstrumentedReplacer.use_actions(actions)

        def func(a, b, c=None):
            actions.append('func')
            return (a, b, c)

        def factory(replacer, scope, name):
            actions.append('factory')
            return func

        try:
            test_func1
        except NameError:
            # test_func1 shouldn't exist yet
            pass
        else:
            self.fail('test_func1 was not supposed to exist yet')
        InstrumentedReplacer(scope=globals(), name='test_func1',
                             factory=factory)

        self.failIf(test_func1 is func)
        val = test_func1(1, 2, c='3')
        self.assertIs(test_func1, func)

        self.assertEqual((1,2,'3'), val)
        self.assertEqual([('__call__', (1,2), {'c':'3'}),
                          '_replace',
                          'factory',
                          'func',
                         ], actions)


class TestImportReplacer(TestCaseInTempDir):
    """Test the ability to have a lazily imported module or object"""

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        self.create_modules()
        base_path = self.test_dir + '/base'

        self.actions = []
        InstrumentedImportReplacer.use_actions(self.actions)

        original_import = __import__
        def instrumented_import(mod, scope1, scope2, fromlist):
            self.actions.append(('import', mod, fromlist))
            return original_import(mod, scope1, scope2, fromlist)

        def cleanup():
            if base_path in sys.path:
                sys.path.remove(base_path)
            __builtins__['__import__'] = original_import
        self.addCleanup(cleanup)
        sys.path.append(base_path)
        __builtins__['__import__'] = instrumented_import

    def create_modules(self):
        """Create some random modules to be imported.

        Each entry has a random suffix, and the full names are saved

        These are setup as follows:
         base/ <= used to ensure not in default search path
            root-XXX/
                __init__.py <= This will contain var1, func1
                mod-XXX.py <= This will contain var2, func2
                sub-XXX/
                    __init__.py <= Contains var3, func3
                    submod-XXX.py <= contains var4, func4
        """
        rand_suffix = osutils.rand_chars(4)
        root_name = 'root_' + rand_suffix
        mod_name = 'mod_' + rand_suffix
        sub_name = 'sub_' + rand_suffix
        submod_name = 'submod_' + rand_suffix
        os.mkdir('base')
        root_path = osutils.pathjoin('base', root_name)
        os.mkdir(root_path)
        root_init = osutils.pathjoin(root_path, '__init__.py')
        f = open(osutils.pathjoin(root_path, '__init__.py'), 'wb')
        try:
            f.write('var1 = 1\ndef func1(a):\n  return a\n')
        finally:
            f.close()
        mod_path = osutils.pathjoin(root_path, mod_name + '.py')
        f = open(mod_path, 'wb')
        try:
            f.write('var2 = 2\ndef func2(a):\n  return a\n')
        finally:
            f.close()

        sub_path = osutils.pathjoin(root_path, sub_name)
        os.mkdir(sub_path)
        f = open(osutils.pathjoin(sub_path, '__init__.py'), 'wb')
        try:
            f.write('var3 = 3\ndef func3(a):\n  return a\n')
        finally:
            f.close()
        submod_path = osutils.pathjoin(sub_path, submod_name + '.py')
        f = open(submod_path, 'wb')
        try:
            f.write('var4 = 4\ndef func4(a):\n  return a\n')
        finally:
            f.close()
        self.root_name = root_name
        self.mod_name = mod_name
        self.sub_name = sub_name
        self.submod_name = submod_name

    def test_basic_import(self):
        sub_mod_path = '.'.join([self.root_name, self.sub_name,
                                  self.submod_name])
        root = __import__(sub_mod_path, globals(), locals(), [])
        self.assertEqual(1, root.var1)
        self.assertEqual(3, getattr(root, self.sub_name).var3)
        self.assertEqual(4, getattr(getattr(root, self.sub_name),
                                    self.submod_name).var4)

        mod_path = '.'.join([self.root_name, self.mod_name])
        root = __import__(mod_path, globals(), locals(), [])
        self.assertEqual(2, getattr(root, self.mod_name).var2)

        self.assertEqual([('import', sub_mod_path, []),
                          ('import', mod_path, []),
                         ], self.actions)

    def test_import_root(self):
        try:
            root1
        except NameError:
            # root1 shouldn't exist yet
            pass
        else:
            self.fail('root1 was not supposed to exist yet')

        # This should replicate 'import root-xxyyzz as root1'
        InstrumentedImportReplacer(scope=globals(), name='root1',
                                   module_path=self.root_name,
                                   member=None,
                                   children=[])

        self.assertEqual(InstrumentedImportReplacer,
                         object.__getattribute__(root1, '__class__'))
        self.assertEqual(1, root1.var1)
        self.assertEqual('x', root1.func1('x'))

        self.assertEqual([('__getattribute__', 'var1'),
                          '_replace',
                          ('_import', 'root1'),
                          ('import', self.root_name, []),
                         ], self.actions)
