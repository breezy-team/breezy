# Copyright (C) 2006, 2008-2012, 2016 Canonical Ltd
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

"""Tests for the Registry classes."""

import os
import sys

from breezy import branch, osutils, registry, tests


class TestRegistry(tests.TestCase):
    def register_stuff(self, a_registry):
        a_registry.register("one", 1)
        a_registry.register("two", 2)
        a_registry.register("four", 4)
        a_registry.register("five", 5)

    def test_registry(self):
        a_registry = registry.Registry()
        self.register_stuff(a_registry)

        self.assertIsNone(a_registry.default_key)

        # test get() (self.default_key is None)
        self.assertRaises(KeyError, a_registry.get)
        self.assertRaises(KeyError, a_registry.get, None)
        self.assertEqual(2, a_registry.get("two"))
        self.assertRaises(KeyError, a_registry.get, "three")

        # test _set_default_key
        a_registry.default_key = "five"
        self.assertEqual(a_registry.default_key, "five")
        self.assertEqual(5, a_registry.get())
        self.assertEqual(5, a_registry.get(None))
        # If they ask for a specific entry, they should get KeyError
        # not the default value. They can always pass None if they prefer
        self.assertRaises(KeyError, a_registry.get, "six")
        self.assertRaises(KeyError, a_registry._set_default_key, "six")

        # test keys()
        self.assertEqual(["five", "four", "one", "two"], a_registry.keys())

    def test_registry_funcs(self):
        a_registry = registry.Registry()
        self.register_stuff(a_registry)

        self.assertIn("one", a_registry)
        a_registry.remove("one")
        self.assertNotIn("one", a_registry)
        self.assertRaises(KeyError, a_registry.get, "one")

        a_registry.register("one", "one")

        self.assertEqual(["five", "four", "one", "two"], sorted(a_registry.keys()))
        self.assertEqual(
            [("five", 5), ("four", 4), ("one", "one"), ("two", 2)],
            sorted(a_registry.iteritems()),
        )

    def test_register_override(self):
        a_registry = registry.Registry()
        a_registry.register("one", "one")
        self.assertRaises(KeyError, a_registry.register, "one", "two")
        self.assertRaises(
            KeyError, a_registry.register, "one", "two", override_existing=False
        )

        a_registry.register("one", "two", override_existing=True)
        self.assertEqual("two", a_registry.get("one"))

        self.assertRaises(KeyError, a_registry.register_lazy, "one", "three", "four")

        a_registry.register_lazy("one", "module", "member", override_existing=True)

    def test_registry_help(self):
        a_registry = registry.Registry()
        a_registry.register("one", 1, help="help text for one")
        # We should not have to import the module to return the help
        # information
        a_registry.register_lazy(
            "two", "nonexistent_module", "member", help="help text for two"
        )

        # We should be able to handle a callable to get information
        help_calls = []

        def generic_help(reg, key):
            help_calls.append(key)
            return f"generic help for {key}"

        a_registry.register("three", 3, help=generic_help)
        a_registry.register_lazy(
            "four", "nonexistent_module", "member2", help=generic_help
        )
        a_registry.register("five", 5)

        def help_from_object(reg, key):
            obj = reg.get(key)
            return obj.help()

        class SimpleObj:
            def help(self):
                return "this is my help"

        a_registry.register("six", SimpleObj(), help=help_from_object)

        self.assertEqual("help text for one", a_registry.get_help("one"))
        self.assertEqual("help text for two", a_registry.get_help("two"))
        self.assertEqual("generic help for three", a_registry.get_help("three"))
        self.assertEqual(["three"], help_calls)
        self.assertEqual("generic help for four", a_registry.get_help("four"))
        self.assertEqual(["three", "four"], help_calls)
        self.assertEqual(None, a_registry.get_help("five"))
        self.assertEqual("this is my help", a_registry.get_help("six"))

        self.assertRaises(KeyError, a_registry.get_help, None)
        self.assertRaises(KeyError, a_registry.get_help, "seven")

        a_registry.default_key = "one"
        self.assertEqual("help text for one", a_registry.get_help(None))
        self.assertRaises(KeyError, a_registry.get_help, "seven")

        self.assertEqual(
            [
                ("five", None),
                ("four", "generic help for four"),
                ("one", "help text for one"),
                ("six", "this is my help"),
                ("three", "generic help for three"),
                ("two", "help text for two"),
            ],
            sorted((key, a_registry.get_help(key)) for key in a_registry.keys()),
        )

        # We don't know what order it was called in, but we should get
        # 2 more calls to three and four
        self.assertEqual(["four", "four", "three", "three"], sorted(help_calls))

    def test_registry_info(self):
        a_registry = registry.Registry()
        a_registry.register("one", 1, info="string info")
        # We should not have to import the module to return the info
        a_registry.register_lazy("two", "nonexistent_module", "member", info=2)

        # We should be able to handle a callable to get information
        a_registry.register("three", 3, info=["a", "list"])
        obj = object()
        a_registry.register_lazy("four", "nonexistent_module", "member2", info=obj)
        a_registry.register("five", 5)

        self.assertEqual("string info", a_registry.get_info("one"))
        self.assertEqual(2, a_registry.get_info("two"))
        self.assertEqual(["a", "list"], a_registry.get_info("three"))
        self.assertIs(obj, a_registry.get_info("four"))
        self.assertIs(None, a_registry.get_info("five"))

        self.assertRaises(KeyError, a_registry.get_info, None)
        self.assertRaises(KeyError, a_registry.get_info, "six")

        a_registry.default_key = "one"
        self.assertEqual("string info", a_registry.get_info(None))
        self.assertRaises(KeyError, a_registry.get_info, "six")

        self.assertEqual(
            [
                ("five", None),
                ("four", obj),
                ("one", "string info"),
                ("three", ["a", "list"]),
                ("two", 2),
            ],
            sorted((key, a_registry.get_info(key)) for key in a_registry.keys()),
        )

    def test_get_prefix(self):
        my_registry = registry.Registry()
        http_object = object()
        sftp_object = object()
        my_registry.register("http:", http_object)
        my_registry.register("sftp:", sftp_object)
        found_object, suffix = my_registry.get_prefix("http://foo/bar")
        self.assertEqual("//foo/bar", suffix)
        self.assertIs(http_object, found_object)
        self.assertIsNot(sftp_object, found_object)
        found_object, suffix = my_registry.get_prefix("sftp://baz/qux")
        self.assertEqual("//baz/qux", suffix)
        self.assertIs(sftp_object, found_object)

    def test_registry_alias(self):
        a_registry = registry.Registry()
        a_registry.register("one", 1, info="string info")
        a_registry.register_alias("two", "one")
        a_registry.register_alias("three", "one", info="own info")
        self.assertEqual(a_registry.get("one"), a_registry.get("two"))
        self.assertEqual(a_registry.get_help("one"), a_registry.get_help("two"))
        self.assertEqual(a_registry.get_info("one"), a_registry.get_info("two"))
        self.assertEqual("own info", a_registry.get_info("three"))
        self.assertEqual({"two": "one", "three": "one"}, a_registry.aliases())
        self.assertEqual(
            {"one": ["three", "two"]},
            {k: sorted(v) for (k, v) in a_registry.alias_map().items()},
        )

    def test_registry_alias_exists(self):
        a_registry = registry.Registry()
        a_registry.register("one", 1, info="string info")
        a_registry.register("two", 2)
        self.assertRaises(KeyError, a_registry.register_alias, "one", "one")

    def test_registry_alias_targetmissing(self):
        a_registry = registry.Registry()
        self.assertRaises(KeyError, a_registry.register_alias, "one", "two")


class TestRegistryIter(tests.TestCase):
    """Test registry iteration behaviors.

    There are dark corner cases here when the registered objects trigger
    addition in the iterated registry.
    """

    def setUp(self):
        super().setUp()

        # We create a registry with "official" objects and "hidden"
        # objects. The later represent the side effects that led to bug #277048
        # and #430510
        _registry = registry.Registry()

        def register_more():
            _registry.register("hidden", None)

        # Avoid closing over self by binding local variable
        self.registry = _registry
        self.registry.register("passive", None)
        self.registry.register("active", register_more)
        self.registry.register("passive-too", None)

        class InvasiveGetter(registry._ObjectGetter):
            def get_obj(inner_self):  # noqa: N805
                # Surprise ! Getting a registered object (think lazy loaded
                # module) register yet another object !
                _registry.register("more hidden", None)
                return inner_self._obj

        self.registry.register("hacky", None)
        # We peek under the covers because the alternative is to use lazy
        # registration and create a module that can reference our test registry
        # it's too much work for such a corner case -- vila 090916
        self.registry._dict["hacky"] = InvasiveGetter(None)

    def _iter_them(self, iter_func_name):
        iter_func = getattr(self.registry, iter_func_name, None)
        self.assertIsNot(None, iter_func)
        count = 0
        for name, func in iter_func():
            count += 1
            self.assertNotIn(name, ("hidden", "more hidden"))
            if func is not None:
                # Using an object register another one as a side effect
                func()
        self.assertEqual(4, count)

    def test_iteritems(self):
        # the dict is modified during the iteration
        self.assertRaises(RuntimeError, self._iter_them, "iteritems")

    def test_items(self):
        # we should be able to iterate even if one item modify the dict
        self._iter_them("items")


class TestRegistryWithDirs(tests.TestCaseInTempDir):
    """Registry tests that require temporary dirs."""

    def create_plugin_file(self, contents):
        """Create a file to be used as a plugin.

        This is created in a temporary directory, so that we
        are sure that it doesn't start in the plugin path.
        """
        os.mkdir("tmp")
        plugin_name = f"bzr_plugin_a_{osutils.rand_chars(4)}"
        with open("tmp/" + plugin_name + ".py", "wb") as f:
            f.write(contents)
        return plugin_name

    def create_simple_plugin(self):
        return self.create_plugin_file(
            b'object1 = "foo"\n'
            b"\n\n"
            b"def function(a,b,c):\n"
            b"    return a,b,c\n"
            b"\n\n"
            b"class MyClass(object):\n"
            b"    def __init__(self, a):\n"
            b"      self.a = a\n"
            b"\n\n"
        )

    def test_lazy_import_registry_foo(self):
        a_registry = registry.Registry()
        a_registry.register_lazy("foo", "breezy.branch", "Branch")
        a_registry.register_lazy("bar", "breezy.branch", "Branch.hooks")
        self.assertEqual(branch.Branch, a_registry.get("foo"))
        self.assertEqual(branch.Branch.hooks, a_registry.get("bar"))

    def test_lazy_import_registry(self):
        plugin_name = self.create_simple_plugin()
        a_registry = registry.Registry()
        a_registry.register_lazy("obj", plugin_name, "object1")
        a_registry.register_lazy("function", plugin_name, "function")
        a_registry.register_lazy("klass", plugin_name, "MyClass")
        a_registry.register_lazy("module", plugin_name, None)

        self.assertEqual(
            ["function", "klass", "module", "obj"], sorted(a_registry.keys())
        )
        # The plugin should not be loaded until we grab the first object
        self.assertNotIn(plugin_name, sys.modules)

        # By default the plugin won't be in the search path
        self.assertRaises(ImportError, a_registry.get, "obj")

        plugin_path = self.test_dir + "/tmp"  # noqa: S108
        sys.path.append(plugin_path)
        try:
            obj = a_registry.get("obj")
            self.assertEqual("foo", obj)
            self.assertIn(plugin_name, sys.modules)

            # Now grab another object
            func = a_registry.get("function")
            self.assertEqual(plugin_name, func.__module__)
            self.assertEqual("function", func.__name__)
            self.assertEqual((1, [], "3"), func(1, [], "3"))

            # And finally a class
            klass = a_registry.get("klass")
            self.assertEqual(plugin_name, klass.__module__)
            self.assertEqual("MyClass", klass.__name__)

            inst = klass(1)
            self.assertIsInstance(inst, klass)
            self.assertEqual(1, inst.a)

            module = a_registry.get("module")
            self.assertIs(obj, module.object1)
            self.assertIs(func, module.function)
            self.assertIs(klass, module.MyClass)
        finally:
            sys.path.remove(plugin_path)

    def test_lazy_import_get_module(self):
        a_registry = registry.Registry()
        a_registry.register_lazy("obj", "breezy.tests.test_registry", "object1")
        self.assertEqual("breezy.tests.test_registry", a_registry._get_module("obj"))

    def test_normal_get_module(self):
        class AThing:
            """Something."""

        a_registry = registry.Registry()
        a_registry.register("obj", AThing())
        self.assertEqual("breezy.tests.test_registry", a_registry._get_module("obj"))
