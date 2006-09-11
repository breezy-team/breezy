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
                    submoda-XXX.py <= contains var4, func4
                    submodb-XXX.py <= containse var5, func5
        """
        rand_suffix = osutils.rand_chars(4)
        root_name = 'root_' + rand_suffix
        mod_name = 'mod_' + rand_suffix
        sub_name = 'sub_' + rand_suffix
        submoda_name = 'submoda_' + rand_suffix
        submodb_name = 'submodb_' + rand_suffix

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
        submoda_path = osutils.pathjoin(sub_path, submoda_name + '.py')
        f = open(submoda_path, 'wb')
        try:
            f.write('var4 = 4\ndef func4(a):\n  return a\n')
        finally:
            f.close()
        submodb_path = osutils.pathjoin(sub_path, submodb_name + '.py')
        f = open(submodb_path, 'wb')
        try:
            f.write('var5 = 5\ndef func5(a):\n  return a\n')
        finally:
            f.close()
        self.root_name = root_name
        self.mod_name = mod_name
        self.sub_name = sub_name
        self.submoda_name = submoda_name
        self.submodb_name = submodb_name

    def test_basic_import(self):
        """Test that a real import of these modules works"""
        sub_mod_path = '.'.join([self.root_name, self.sub_name,
                                  self.submoda_name])
        root = __import__(sub_mod_path, globals(), locals(), [])
        self.assertEqual(1, root.var1)
        self.assertEqual(3, getattr(root, self.sub_name).var3)
        self.assertEqual(4, getattr(getattr(root, self.sub_name),
                                    self.submoda_name).var4)

        mod_path = '.'.join([self.root_name, self.mod_name])
        root = __import__(mod_path, globals(), locals(), [])
        self.assertEqual(2, getattr(root, self.mod_name).var2)

        self.assertEqual([('import', sub_mod_path, []),
                          ('import', mod_path, []),
                         ], self.actions)

    def test_import_root(self):
        """Test 'import root-XXX as root1'"""
        try:
            root1
        except NameError:
            # root1 shouldn't exist yet
            pass
        else:
            self.fail('root1 was not supposed to exist yet')

        # This should replicate 'import root-xxyyzz as root1'
        InstrumentedImportReplacer(scope=globals(), name='root1',
                                   module_path=[self.root_name],
                                   member=None, children=[])

        self.assertEqual(InstrumentedImportReplacer,
                         object.__getattribute__(root1, '__class__'))
        self.assertEqual(1, root1.var1)
        self.assertEqual('x', root1.func1('x'))

        self.assertEqual([('__getattribute__', 'var1'),
                          '_replace',
                          ('_import', 'root1'),
                          ('import', self.root_name, []),
                         ], self.actions)

    def test_import_mod(self):
        """Test 'import root-XXX.mod-XXX as mod2'"""
        try:
            mod1
        except NameError:
            # mod1 shouldn't exist yet
            pass
        else:
            self.fail('mod1 was not supposed to exist yet')

        mod_path = self.root_name + '.' + self.mod_name
        InstrumentedImportReplacer(scope=globals(), name='mod1',
                                   module_path=[self.root_name, self.mod_name],
                                   member=None, children=[])

        self.assertEqual(InstrumentedImportReplacer,
                         object.__getattribute__(mod1, '__class__'))
        self.assertEqual(2, mod1.var2)
        self.assertEqual('y', mod1.func2('y'))

        self.assertEqual([('__getattribute__', 'var2'),
                          '_replace',
                          ('_import', 'mod1'),
                          ('import', mod_path, []),
                         ], self.actions)

    def test_import_mod_from_root(self):
        """Test 'from root-XXX import mod-XXX as mod2'"""
        try:
            mod2
        except NameError:
            # mod2 shouldn't exist yet
            pass
        else:
            self.fail('mod2 was not supposed to exist yet')

        InstrumentedImportReplacer(scope=globals(), name='mod2',
                                   module_path=[self.root_name],
                                   member=self.mod_name, children=[])

        self.assertEqual(InstrumentedImportReplacer,
                         object.__getattribute__(mod2, '__class__'))
        self.assertEqual(2, mod2.var2)
        self.assertEqual('y', mod2.func2('y'))

        self.assertEqual([('__getattribute__', 'var2'),
                          '_replace',
                          ('_import', 'mod2'),
                          ('import', self.root_name, [self.mod_name]),
                         ], self.actions)

    def test_import_root_and_mod(self):
        """Test 'import root-XXX.mod-XXX' remapping both to root3.mod3"""
        try:
            root3
        except NameError:
            # root3 shouldn't exist yet
            pass
        else:
            self.fail('root3 was not supposed to exist yet')

        InstrumentedImportReplacer(scope=globals(),
            name='root3', module_path=[self.root_name], member=None,
            children=[('mod3', [self.root_name, self.mod_name], [])])

        # So 'root3' should be a lazy import
        # and once it is imported, mod3 should also be lazy until
        # actually accessed.
        self.assertEqual(InstrumentedImportReplacer,
                         object.__getattribute__(root3, '__class__'))
        self.assertEqual(1, root3.var1)

        # There is a mod3 member, but it is also lazy
        self.assertEqual(InstrumentedImportReplacer,
                         object.__getattribute__(root3.mod3, '__class__'))
        self.assertEqual(2, root3.mod3.var2)

        mod_path = self.root_name + '.' + self.mod_name
        self.assertEqual([('__getattribute__', 'var1'),
                          '_replace',
                          ('_import', 'root3'),
                          ('import', self.root_name, []),
                          ('__getattribute__', 'var2'),
                          '_replace',
                          ('_import', 'mod3'),
                          ('import', mod_path, []),
                         ], self.actions)

    def test_import_root_and_root_mod(self):
        """Test that 'import root, root.mod' can be done.

        The second import should re-use the first one, and just add
        children to be imported.
        """
        try:
            root4
        except NameError:
            # root4 shouldn't exist yet
            pass
        else:
            self.fail('root4 was not supposed to exist yet')

        InstrumentedImportReplacer(scope=globals(),
            name='root4', module_path=[self.root_name], member=None,
            children=[])

        # So 'root4' should be a lazy import
        self.assertEqual(InstrumentedImportReplacer,
                         object.__getattribute__(root4, '__class__'))

        # Lets add a new child to be imported on demand
        # This syntax of using object.__getattribute__ is the correct method
        # for accessing the _import_replacer_children member
        children = object.__getattribute__(root4, '_import_replacer_children')
        children.append(('mod4', [self.root_name, self.mod_name], []))

        # Accessing root4.mod4 should import root, but mod should stay lazy
        self.assertEqual(InstrumentedImportReplacer,
                         object.__getattribute__(root4.mod4, '__class__'))
        self.assertEqual(2, root4.mod4.var2)

        mod_path = self.root_name + '.' + self.mod_name
        self.assertEqual([('__getattribute__', 'mod4'),
                          '_replace',
                          ('_import', 'root4'),
                          ('import', self.root_name, []),
                          ('__getattribute__', 'var2'),
                          '_replace',
                          ('_import', 'mod4'),
                          ('import', mod_path, []),
                         ], self.actions)

    def test_import_root_sub_submod(self):
        """Test import root.mod, root.sub.submoda, root.sub.submodb
        root should be a lazy import, with multiple children, who also
        have children to be imported.
        And when root is imported, the children should be lazy, and
        reuse the intermediate lazy object.
        """
        try:
            root5
        except NameError:
            # root4 shouldn't exist yet
            pass
        else:
            self.fail('root5 was not supposed to exist yet')

        InstrumentedImportReplacer(scope=globals(),
            name='root5', module_path=[self.root_name], member=None,
            children=[('mod5', [self.root_name, self.mod_name], []),
                      ('sub5', [self.root_name, self.sub_name],
                            [('submoda5', [self.root_name, self.sub_name,
                                         self.submoda_name], []),
                             ('submodb5', [self.root_name, self.sub_name,
                                          self.submodb_name], [])
                            ]),
                     ])

        # So 'root5' should be a lazy import
        self.assertEqual(InstrumentedImportReplacer,
                         object.__getattribute__(root5, '__class__'))

        # Accessing root5.mod5 should import root, but mod should stay lazy
        self.assertEqual(InstrumentedImportReplacer,
                         object.__getattribute__(root5.mod5, '__class__'))
        # root5.sub5 should still be lazy, but not re-import root5
        self.assertEqual(InstrumentedImportReplacer,
                         object.__getattribute__(root5.sub5, '__class__'))
        # Accessing root5.sub5.submoda5 should import sub5, but not either
        # of the sub objects (they should be available as lazy objects
        self.assertEqual(InstrumentedImportReplacer,
                     object.__getattribute__(root5.sub5.submoda5, '__class__'))
        self.assertEqual(InstrumentedImportReplacer,
                     object.__getattribute__(root5.sub5.submodb5, '__class__'))

        # This should import mod5
        self.assertEqual(2, root5.mod5.var2)
        # These should import submoda5 and submodb5
        self.assertEqual(4, root5.sub5.submoda5.var4)
        self.assertEqual(5, root5.sub5.submodb5.var5)

        mod_path = self.root_name + '.' + self.mod_name
        sub_path = self.root_name + '.' + self.sub_name
        submoda_path = sub_path + '.' + self.submoda_name
        submodb_path = sub_path + '.' + self.submodb_name

        self.assertEqual([('__getattribute__', 'mod5'),
                          '_replace',
                          ('_import', 'root5'),
                          ('import', self.root_name, []),
                          ('__getattribute__', 'submoda5'),
                          '_replace',
                          ('_import', 'sub5'),
                          ('import', sub_path, []),
                          ('__getattribute__', 'var2'),
                          '_replace',
                          ('_import', 'mod5'),
                          ('import', mod_path, []),
                          ('__getattribute__', 'var4'),
                          '_replace',
                          ('_import', 'submoda5'),
                          ('import', submoda_path, []),
                          ('__getattribute__', 'var5'),
                          '_replace',
                          ('_import', 'submodb5'),
                          ('import', submodb_path, []),
                         ], self.actions)
