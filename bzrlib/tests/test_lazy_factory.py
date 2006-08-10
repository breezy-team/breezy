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

"""Tests for the LazyFactory class"""

import os
import sys

from bzrlib import (
    errors,
    lazy_factory,
    osutils,
    )
from bzrlib.tests import TestCaseInTempDir


class TestLazyFactory(TestCaseInTempDir):

    def create_plugin_file(self, contents):
        plugin_name = 'bzr_plugin_a_%s' % (osutils.rand_chars(4),)
        open(plugin_name+'.py', 'wb').write(contents)
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

    def test_lazy_factory(self):
        plugin_name = self.create_simple_plugin()
        factory = lazy_factory.LazyFactory()
        factory.register('obj', plugin_name, 'object1')
        factory.register('function', plugin_name, 'function')
        factory.register('klass', plugin_name, 'MyClass')
        factory.register('module', plugin_name, None)

        self.assertEqual(['function', 'klass', 'module', 'obj'],
                         sorted(factory.keys()))
        # The plugin should not be loaded until we grab the first object
        self.failIf(plugin_name in sys.modules)

        # By default the plugin won't be in the search path
        self.assertRaises(ImportError, factory.get, 'obj')

        cwd = os.getcwd()
        sys.path.append(cwd)
        try:
            obj = factory.get('obj')
            self.assertEqual('foo', obj)
            self.failUnless(plugin_name in sys.modules)

            # Now grab another object
            func = factory.get('function')
            self.assertEqual(plugin_name, func.__module__)
            self.assertEqual('function', func.__name__)
            self.assertEqual((1, [], '3'), func(1, [], '3'))

            # And finally a class
            klass = factory.get('klass')
            self.assertEqual(plugin_name, klass.__module__)
            self.assertEqual('MyClass', klass.__name__)

            inst = klass(1)
            self.assertIsInstance(inst, klass)
            self.assertEqual(1, inst.a)

            module = factory.get('module')
            self.assertIs(obj, module.object1)
            self.assertIs(func, module.function)
            self.assertIs(klass, module.MyClass)
        finally:
            sys.path.remove(cwd)
