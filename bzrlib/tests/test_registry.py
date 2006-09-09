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

"""Tests for the Registry classes"""

import os
import sys

from bzrlib import (
    errors,
    registry,
    osutils,
    )
from bzrlib.tests import TestCase, TestCaseInTempDir


class TestRegistry(TestCase):

    def register_stuff(self, a_registry):
        a_registry.register('one', 1)
        a_registry.register('two', 2)
        a_registry.register('four', 4)
        a_registry.register('five', 5)

    def test_registry(self):
        a_registry = registry.Registry()
        self.register_stuff(a_registry)

        self.failUnless(a_registry.default_key is None)

        # test get() (self.default_key == None)
        self.assertRaises(KeyError, a_registry.get)
        self.assertRaises(KeyError, a_registry.get, None)
        self.assertEqual(2, a_registry.get('two'))
        self.assertRaises(KeyError, a_registry.get, 'three')

        # test _set_default_key
        a_registry.default_key = 'five'
        self.failUnless(a_registry.default_key == 'five')
        self.assertEqual(5, a_registry.get())
        self.assertEqual(5, a_registry.get(None))
        # If they ask for a specific entry, they should get KeyError
        # not the default value. They can always pass None if they prefer
        self.assertRaises(KeyError, a_registry.get, 'six')
        self.assertRaises(KeyError, a_registry._set_default_key, 'six')

        # test keys()
        self.assertEqual(['five', 'four', 'one', 'two'], a_registry.keys())

    def test_registry_like_dict(self):
        a_registry = registry.Registry()
        self.register_stuff(a_registry)

        self.failUnless('one' in a_registry)
        del a_registry['one']
        self.failIf('one' in a_registry)
        self.assertRaises(KeyError, a_registry.get, 'one')

        # We intentionally don't implement __setitem__, because
        # register() is a much richer function, that doesn't translate
        # well into foo[x] = y
        def set_one():
            a_registry['one'] = 'one'
        self.assertRaises(AttributeError, set_one)

        a_registry.register('one', 'one')
        self.assertEqual('one', a_registry['one'])
        self.assertEqual(4, len(a_registry))

        self.assertEqual(['five', 'four', 'one', 'two'],
                         sorted(a_registry.iterkeys()))
        self.assertEqual([('five', 5), ('four', 4),
                          ('one', 'one'), ('two', 2)],
                         sorted(a_registry.iteritems()))
        self.assertEqual([2, 4, 5, 'one'],
                         sorted(a_registry.itervalues()))

        self.assertEqual(['five', 'four', 'one', 'two'],
                         sorted(a_registry.keys()))
        self.assertEqual([('five', 5), ('four', 4),
                          ('one', 'one'), ('two', 2)],
                         sorted(a_registry.items()))
        self.assertEqual([2, 4, 5, 'one'],
                         sorted(a_registry.values()))

    def test_register_override(self):
        a_registry = registry.Registry()
        a_registry.register('one', 'one')
        self.assertRaises(KeyError, a_registry.register, 'one', 'two')
        self.assertRaises(KeyError, a_registry.register, 'one', 'two',
                                    override_existing=False)

        a_registry.register('one', 'two', override_existing=True)
        self.assertEqual('two', a_registry.get('one'))

        self.assertRaises(KeyError, a_registry.register_lazy,
                          'one', 'three', 'four')

        a_registry.register_lazy('one', 'module', 'member',
                                 override_existing=True)

    def test_registry_help(self):
        a_registry = registry.Registry()
        a_registry.register('one', 1, help='help text for one')
        # We should not have to import the module to return the help
        # information
        a_registry.register_lazy('two', 'nonexistent_module', 'member',
                                 help='help text for two')

        # We should be able to handle a callable to get information
        help_calls = []
        def generic_help(reg, key):
            help_calls.append(key)
            return 'generic help for %s' % (key,)
        a_registry.register('three', 3, help=generic_help)
        a_registry.register_lazy('four', 'nonexistent_module', 'member2',
                                 help=generic_help)
        a_registry.register('five', 5)

        self.assertEqual('help text for one', a_registry.get_help('one'))
        self.assertEqual('help text for two', a_registry.get_help('two'))
        self.assertEqual('generic help for three',
                         a_registry.get_help('three'))
        self.assertEqual(['three'], help_calls)
        self.assertEqual('generic help for four',
                         a_registry.get_help('four'))
        self.assertEqual(['three', 'four'], help_calls)
        self.assertEqual(None, a_registry.get_help('five'))

        self.assertRaises(KeyError, a_registry.get_help, None)
        self.assertRaises(KeyError, a_registry.get_help, 'six')

        a_registry.default_key = 'one'
        self.assertEqual('help text for one', a_registry.get_help(None))
        self.assertRaises(KeyError, a_registry.get_help, 'six')

        self.assertEqual([('five', None),
                          ('four', 'generic help for four'),
                          ('one', 'help text for one'),
                          ('three', 'generic help for three'),
                          ('two', 'help text for two'),
                         ], sorted(a_registry.iterhelp()))
        # We don't know what order it was called in, but we should get
        # 2 more calls to three and four
        self.assertEqual(['four', 'four', 'three', 'three'],
                         sorted(help_calls))

    def test_registry_info(self):
        a_registry = registry.Registry()
        a_registry.register('one', 1, info='string info')
        # We should not have to import the module to return the info
        a_registry.register_lazy('two', 'nonexistent_module', 'member',
                                 info=2)

        # We should be able to handle a callable to get information
        a_registry.register('three', 3, info=['a', 'list'])
        obj = object()
        a_registry.register_lazy('four', 'nonexistent_module', 'member2',
                                 info=obj)
        a_registry.register('five', 5)

        self.assertEqual('string info', a_registry.get_info('one'))
        self.assertEqual(2, a_registry.get_info('two'))
        self.assertEqual(['a', 'list'], a_registry.get_info('three'))
        self.assertIs(obj, a_registry.get_info('four'))
        self.assertIs(None, a_registry.get_info('five'))

        self.assertRaises(KeyError, a_registry.get_info, None)
        self.assertRaises(KeyError, a_registry.get_info, 'six')

        a_registry.default_key = 'one'
        self.assertEqual('string info', a_registry.get_info(None))
        self.assertRaises(KeyError, a_registry.get_info, 'six')

        self.assertEqual([('five', None),
                          ('four', obj),
                          ('one', 'string info'),
                          ('three', ['a', 'list']),
                          ('two', 2),
                         ], sorted(a_registry.iterinfo()))

class TestRegistryWithDirs(TestCaseInTempDir):
    """Registry tests that require temporary dirs"""

    def create_plugin_file(self, contents):
        """Create a file to be used as a plugin.

        This is created in a temporary directory, so that we
        are sure that it doesn't start in the plugin path.
        """
        os.mkdir('tmp')
        plugin_name = 'bzr_plugin_a_%s' % (osutils.rand_chars(4),)
        open('tmp/'+plugin_name+'.py', 'wb').write(contents)
        return plugin_name

    def create_simple_plugin(self):
        return self.create_plugin_file(
            'object1 = "foo"\n'
            '\n\n'
            'def function(a,b,c):\n'
            '    return a,b,c\n'
            '\n\n'
            'class MyClass(object):\n'
            '    def __init__(self, a):\n'
            '      self.a = a\n'
            '\n\n'
        )

    def test_lazy_import_registry(self):
        plugin_name = self.create_simple_plugin()
        a_registry = registry.Registry()
        a_registry.register_lazy('obj', plugin_name, 'object1')
        a_registry.register_lazy('function', plugin_name, 'function')
        a_registry.register_lazy('klass', plugin_name, 'MyClass')
        a_registry.register_lazy('module', plugin_name, None)

        self.assertEqual(['function', 'klass', 'module', 'obj'],
                         sorted(a_registry.keys()))
        # The plugin should not be loaded until we grab the first object
        self.failIf(plugin_name in sys.modules)

        # By default the plugin won't be in the search path
        self.assertRaises(ImportError, a_registry.get, 'obj')

        plugin_path = os.getcwd() + '/tmp'
        sys.path.append(plugin_path)
        try:
            obj = a_registry.get('obj')
            self.assertEqual('foo', obj)
            self.failUnless(plugin_name in sys.modules)

            # Now grab another object
            func = a_registry.get('function')
            self.assertEqual(plugin_name, func.__module__)
            self.assertEqual('function', func.__name__)
            self.assertEqual((1, [], '3'), func(1, [], '3'))

            # And finally a class
            klass = a_registry.get('klass')
            self.assertEqual(plugin_name, klass.__module__)
            self.assertEqual('MyClass', klass.__name__)

            inst = klass(1)
            self.assertIsInstance(inst, klass)
            self.assertEqual(1, inst.a)

            module = a_registry.get('module')
            self.assertIs(obj, module.object1)
            self.assertIs(func, module.function)
            self.assertIs(klass, module.MyClass)
        finally:
            sys.path.remove(plugin_path)


