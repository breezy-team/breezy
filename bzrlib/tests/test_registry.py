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

    def test_registry_with_first_is_default(self):
        a_registry = registry.Registry(True)
        self.register_stuff(a_registry)

        self.failUnless(a_registry.default_key == 'one')

        # test get() (self.default_key == 'one')
        self.assertEqual(1, a_registry.get())
        self.assertEqual(1, a_registry.get(None))
        self.assertEqual(2, a_registry.get('two'))
        self.assertRaises(KeyError, a_registry.get, 'three')

        # test _set_default_key
        a_registry.default_key = 'five'
        self.failUnless(a_registry.default_key == 'five')
        self.assertEqual(5, a_registry.get())
        self.assertEqual(5, a_registry.get(None))
        self.assertRaises(KeyError, a_registry.get, 'six')
        self.assertRaises(KeyError, a_registry._set_default_key, 'six')

    def test_registry_like_dict(self):
        a_registry = registry.Registry()
        self.register_stuff(a_registry)

        self.failUnless('one' in a_registry)
        del a_registry['one']
        self.failIf('one' in a_registry)
        self.assertRaises(KeyError, a_registry.get, 'one')

        a_registry['one'] = 'one'
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


