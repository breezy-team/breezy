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


from bzrlib import (
    lazy_import,
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


class TestClass(object):
    """Just a simple test class instrumented for the test cases"""

    actions = []

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

