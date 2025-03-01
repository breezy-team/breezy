# Copyright (C) 2006-2011 Canonical Ltd
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

"""Test the lazy_import functionality."""

import os
import re
import sys

from .. import lazy_import, osutils
from . import TestCase, TestCaseInTempDir


class InstrumentedReplacer(lazy_import.ScopeReplacer):
    """Track what actions are done."""

    @staticmethod
    def use_actions(actions):
        InstrumentedReplacer.actions = actions

    def __getattribute__(self, attr):
        InstrumentedReplacer.actions.append(("__getattribute__", attr))
        return lazy_import.ScopeReplacer.__getattribute__(self, attr)

    def __call__(self, *args, **kwargs):
        InstrumentedReplacer.actions.append(("__call__", args, kwargs))
        return lazy_import.ScopeReplacer.__call__(self, *args, **kwargs)


class InstrumentedImportReplacer(lazy_import.ImportReplacer):
    @staticmethod
    def use_actions(actions):
        InstrumentedImportReplacer.actions = actions

    def _import(self, scope, name):
        InstrumentedImportReplacer.actions.append(("_import", name))
        return lazy_import.ImportReplacer._import(self, scope, name)

    def __getattribute__(self, attr):
        InstrumentedImportReplacer.actions.append(("__getattribute__", attr))
        return lazy_import.ScopeReplacer.__getattribute__(self, attr)

    def __call__(self, *args, **kwargs):
        InstrumentedImportReplacer.actions.append(("__call__", args, kwargs))
        return lazy_import.ScopeReplacer.__call__(self, *args, **kwargs)


class TestClass:
    """Just a simple test class instrumented for the test cases."""

    class_member = "class_member"

    @staticmethod
    def use_actions(actions):
        TestClass.actions = actions

    def __init__(self):
        TestClass.actions.append("init")

    def foo(self, x):
        TestClass.actions.append(("foo", x))
        return "foo"


class TestScopeReplacer(TestCase):
    """Test the ability of the replacer to put itself into the correct scope.

    In these tests we use the global scope, because we cannot replace
    variables in the local scope. This means that we need to be careful
    and not have the replacing objects use the same name, or we would
    get collisions.
    """

    def setUp(self):
        super().setUp()
        # These tests assume we will not be proxying, so make sure proxying is
        # disabled.
        orig_proxy = lazy_import.ScopeReplacer._should_proxy

        def restore():
            lazy_import.ScopeReplacer._should_proxy = orig_proxy

        lazy_import.ScopeReplacer._should_proxy = False

    def test_object(self):
        """ScopeReplacer can create an instance in local scope.

        An object should appear in globals() by constructing a ScopeReplacer,
        and it will be replaced with the real object upon the first request.
        """
        actions = []
        InstrumentedReplacer.use_actions(actions)
        TestClass.use_actions(actions)

        def factory(replacer, scope, name):
            actions.append("factory")
            return TestClass()

        try:
            test_obj1
        except NameError:
            # test_obj1 shouldn't exist yet
            pass
        else:
            self.fail("test_obj1 was not supposed to exist yet")

        InstrumentedReplacer(scope=globals(), name="test_obj1", factory=factory)

        # We can't use isinstance() because that uses test_obj1.__class__
        # and that goes through __getattribute__ which would activate
        # the replacement
        self.assertEqual(
            InstrumentedReplacer, object.__getattribute__(test_obj1, "__class__")
        )
        self.assertEqual("foo", test_obj1.foo(1))
        self.assertIsInstance(test_obj1, TestClass)
        self.assertEqual("foo", test_obj1.foo(2))
        self.assertEqual(
            [
                ("__getattribute__", "foo"),
                "factory",
                "init",
                ("foo", 1),
                ("foo", 2),
            ],
            actions,
        )

    def test_setattr_replaces(self):
        """ScopeReplacer can create an instance in local scope.

        An object should appear in globals() by constructing a ScopeReplacer,
        and it will be replaced with the real object upon the first request.
        """
        actions = []
        TestClass.use_actions(actions)

        def factory(replacer, scope, name):
            return TestClass()

        try:
            test_obj6
        except NameError:
            # test_obj6 shouldn't exist yet
            pass
        else:
            self.fail("test_obj6 was not supposed to exist yet")

        lazy_import.ScopeReplacer(scope=globals(), name="test_obj6", factory=factory)

        # We can't use isinstance() because that uses test_obj6.__class__
        # and that goes through __getattribute__ which would activate
        # the replacement
        self.assertEqual(
            lazy_import.ScopeReplacer, object.__getattribute__(test_obj6, "__class__")
        )
        test_obj6.bar = "test"
        self.assertNotEqual(
            lazy_import.ScopeReplacer, object.__getattribute__(test_obj6, "__class__")
        )
        self.assertEqual("test", test_obj6.bar)

    def test_replace_side_effects(self):
        """Creating a new object should only create one entry in globals.

        And only that entry even after replacement.
        """
        try:
            test_scope1
        except NameError:
            # test_scope1 shouldn't exist yet
            pass
        else:
            self.fail("test_scope1 was not supposed to exist yet")

        # ignore the logged actions
        TestClass.use_actions([])

        def factory(replacer, scope, name):
            return TestClass()

        orig_globals = set(globals().keys())

        lazy_import.ScopeReplacer(scope=globals(), name="test_scope1", factory=factory)

        new_globals = set(globals().keys())

        self.assertEqual(
            lazy_import.ScopeReplacer, object.__getattribute__(test_scope1, "__class__")
        )
        self.assertEqual("foo", test_scope1.foo(1))
        self.assertIsInstance(test_scope1, TestClass)

        final_globals = set(globals().keys())

        self.assertEqual({"test_scope1"}, new_globals - orig_globals)
        self.assertEqual(set(), orig_globals - new_globals)
        self.assertEqual(set(), final_globals - new_globals)
        self.assertEqual(set(), new_globals - final_globals)

    def test_class(self):
        actions = []
        InstrumentedReplacer.use_actions(actions)
        TestClass.use_actions(actions)

        def factory(replacer, scope, name):
            actions.append("factory")
            return TestClass

        try:
            test_class1
        except NameError:
            # test_class2 shouldn't exist yet
            pass
        else:
            self.fail("test_class1 was not supposed to exist yet")

        InstrumentedReplacer(scope=globals(), name="test_class1", factory=factory)

        self.assertEqual("class_member", test_class1.class_member)
        self.assertEqual(test_class1, TestClass)
        self.assertEqual(
            [
                ("__getattribute__", "class_member"),
                "factory",
            ],
            actions,
        )

    def test_call_class(self):
        actions = []
        InstrumentedReplacer.use_actions(actions)
        TestClass.use_actions(actions)

        def factory(replacer, scope, name):
            actions.append("factory")
            return TestClass

        try:
            test_class2
        except NameError:
            # test_class2 shouldn't exist yet
            pass
        else:
            self.fail("test_class2 was not supposed to exist yet")

        InstrumentedReplacer(scope=globals(), name="test_class2", factory=factory)

        self.assertFalse(test_class2 is TestClass)
        obj = test_class2()
        self.assertIs(test_class2, TestClass)
        self.assertIsInstance(obj, TestClass)
        self.assertEqual("class_member", obj.class_member)
        self.assertEqual(
            [
                ("__call__", (), {}),
                "factory",
                "init",
            ],
            actions,
        )

    def test_call_func(self):
        actions = []
        InstrumentedReplacer.use_actions(actions)

        def func(a, b, c=None):
            actions.append("func")
            return (a, b, c)

        def factory(replacer, scope, name):
            actions.append("factory")
            return func

        try:
            test_func1
        except NameError:
            # test_func1 shouldn't exist yet
            pass
        else:
            self.fail("test_func1 was not supposed to exist yet")
        InstrumentedReplacer(scope=globals(), name="test_func1", factory=factory)

        self.assertFalse(test_func1 is func)
        val = test_func1(1, 2, c="3")
        self.assertIs(test_func1, func)

        self.assertEqual((1, 2, "3"), val)
        self.assertEqual(
            [
                ("__call__", (1, 2), {"c": "3"}),
                "factory",
                "func",
            ],
            actions,
        )

    def test_other_variable(self):
        """Test when a ScopeReplacer is assigned to another variable.

        This test could be updated if we find a way to trap '=' rather
        than just giving a belated exception.
        ScopeReplacer only knows about the variable it was created as,
        so until the object is replaced, it is illegal to pass it to
        another variable. (Though discovering this may take a while)
        """
        actions = []
        InstrumentedReplacer.use_actions(actions)
        TestClass.use_actions(actions)

        def factory(replacer, scope, name):
            actions.append("factory")
            return TestClass()

        try:
            test_obj2
        except NameError:
            # test_obj2 shouldn't exist yet
            pass
        else:
            self.fail("test_obj2 was not supposed to exist yet")

        InstrumentedReplacer(scope=globals(), name="test_obj2", factory=factory)

        self.assertEqual(
            InstrumentedReplacer, object.__getattribute__(test_obj2, "__class__")
        )
        # This is technically not allowed, but we don't have a way to
        # test it until later.
        test_obj3 = test_obj2
        self.assertEqual(
            InstrumentedReplacer, object.__getattribute__(test_obj2, "__class__")
        )
        self.assertEqual(
            InstrumentedReplacer, object.__getattribute__(test_obj3, "__class__")
        )

        # The first use of the alternate variable causes test_obj2 to
        # be replaced.
        self.assertEqual("foo", test_obj3.foo(1))
        # test_obj2 has been replaced, but the ScopeReplacer has no
        # idea of test_obj3
        self.assertEqual(TestClass, object.__getattribute__(test_obj2, "__class__"))
        self.assertEqual(
            InstrumentedReplacer, object.__getattribute__(test_obj3, "__class__")
        )
        # We should be able to access test_obj2 attributes normally
        self.assertEqual("foo", test_obj2.foo(2))
        self.assertEqual("foo", test_obj2.foo(3))

        # However, the next access on test_obj3 should raise an error
        # because only now are we able to detect the problem.
        self.assertRaises(
            lazy_import.IllegalUseOfScopeReplacer, getattr, test_obj3, "foo"
        )

        self.assertEqual(
            [
                ("__getattribute__", "foo"),
                "factory",
                "init",
                ("foo", 1),
                ("foo", 2),
                ("foo", 3),
                ("__getattribute__", "foo"),
            ],
            actions,
        )

    def test_enable_proxying(self):
        """Test that we can allow ScopeReplacer to proxy."""
        actions = []
        InstrumentedReplacer.use_actions(actions)
        TestClass.use_actions(actions)

        def factory(replacer, scope, name):
            actions.append("factory")
            return TestClass()

        try:
            test_obj4
        except NameError:
            # test_obj4 shouldn't exist yet
            pass
        else:
            self.fail("test_obj4 was not supposed to exist yet")

        lazy_import.ScopeReplacer._should_proxy = True
        InstrumentedReplacer(scope=globals(), name="test_obj4", factory=factory)

        self.assertEqual(
            InstrumentedReplacer, object.__getattribute__(test_obj4, "__class__")
        )
        test_obj5 = test_obj4
        self.assertEqual(
            InstrumentedReplacer, object.__getattribute__(test_obj4, "__class__")
        )
        self.assertEqual(
            InstrumentedReplacer, object.__getattribute__(test_obj5, "__class__")
        )

        # The first use of the alternate variable causes test_obj2 to
        # be replaced.
        self.assertEqual("foo", test_obj4.foo(1))
        self.assertEqual(TestClass, object.__getattribute__(test_obj4, "__class__"))
        self.assertEqual(
            InstrumentedReplacer, object.__getattribute__(test_obj5, "__class__")
        )
        # We should be able to access test_obj4 attributes normally
        self.assertEqual("foo", test_obj4.foo(2))
        # because we enabled proxying, test_obj5 can access its members as well
        self.assertEqual("foo", test_obj5.foo(3))
        self.assertEqual("foo", test_obj5.foo(4))

        # However, it cannot be replaced by the ScopeReplacer
        self.assertEqual(
            InstrumentedReplacer, object.__getattribute__(test_obj5, "__class__")
        )

        self.assertEqual(
            [
                ("__getattribute__", "foo"),
                "factory",
                "init",
                ("foo", 1),
                ("foo", 2),
                ("__getattribute__", "foo"),
                ("foo", 3),
                ("__getattribute__", "foo"),
                ("foo", 4),
            ],
            actions,
        )

    def test_replacing_from_own_scope_fails(self):
        """If a ScopeReplacer tries to replace itself a nice error is given."""
        actions = []
        InstrumentedReplacer.use_actions(actions)
        TestClass.use_actions(actions)

        def factory(replacer, scope, name):
            actions.append("factory")
            # return the name in given scope, which is currently the replacer
            return scope[name]

        try:
            test_obj7
        except NameError:
            # test_obj7 shouldn't exist yet
            pass
        else:
            self.fail("test_obj7 was not supposed to exist yet")

        InstrumentedReplacer(scope=globals(), name="test_obj7", factory=factory)

        self.assertEqual(
            InstrumentedReplacer, object.__getattribute__(test_obj7, "__class__")
        )
        e = self.assertRaises(lazy_import.IllegalUseOfScopeReplacer, test_obj7)
        self.assertIn("replace itself", e.msg)
        self.assertEqual([("__call__", (), {}), "factory"], actions)


class ImportReplacerHelper(TestCaseInTempDir):
    """Test the ability to have a lazily imported module or object."""

    def setUp(self):
        super().setUp()
        self.create_modules()
        base_path = self.test_dir + "/base"

        self.actions = []
        InstrumentedImportReplacer.use_actions(self.actions)

        sys.path.append(base_path)
        self.addCleanup(sys.path.remove, base_path)

        def instrumented_import(mod, scope1, scope2, fromlist, level):
            self.actions.append(("import", mod, fromlist, level))
            return __import__(mod, scope1, scope2, fromlist, level=level)

        self.addCleanup(setattr, lazy_import, "_builtin_import", __import__)
        lazy_import._builtin_import = instrumented_import

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
        root_name = "root_" + rand_suffix
        mod_name = "mod_" + rand_suffix
        sub_name = "sub_" + rand_suffix
        submoda_name = "submoda_" + rand_suffix
        submodb_name = "submodb_" + rand_suffix

        os.mkdir("base")
        root_path = osutils.pathjoin("base", root_name)
        os.mkdir(root_path)
        osutils.pathjoin(root_path, "__init__.py")
        with open(osutils.pathjoin(root_path, "__init__.py"), "w") as f:
            f.write("var1 = 1\ndef func1(a):\n  return a\n")
        mod_path = osutils.pathjoin(root_path, mod_name + ".py")
        with open(mod_path, "w") as f:
            f.write("var2 = 2\ndef func2(a):\n  return a\n")

        sub_path = osutils.pathjoin(root_path, sub_name)
        os.mkdir(sub_path)
        with open(osutils.pathjoin(sub_path, "__init__.py"), "w") as f:
            f.write("var3 = 3\ndef func3(a):\n  return a\n")
        submoda_path = osutils.pathjoin(sub_path, submoda_name + ".py")
        with open(submoda_path, "w") as f:
            f.write("var4 = 4\ndef func4(a):\n  return a\n")
        submodb_path = osutils.pathjoin(sub_path, submodb_name + ".py")
        with open(submodb_path, "w") as f:
            f.write("var5 = 5\ndef func5(a):\n  return a\n")
        self.root_name = root_name
        self.mod_name = mod_name
        self.sub_name = sub_name
        self.submoda_name = submoda_name
        self.submodb_name = submodb_name


class TestImportReplacerHelper(ImportReplacerHelper):
    def test_basic_import(self):
        """Test that a real import of these modules works."""
        sub_mod_path = ".".join([self.root_name, self.sub_name, self.submoda_name])
        root = lazy_import._builtin_import(sub_mod_path, {}, {}, [], 0)
        self.assertEqual(1, root.var1)
        self.assertEqual(3, getattr(root, self.sub_name).var3)
        self.assertEqual(
            4, getattr(getattr(root, self.sub_name), self.submoda_name).var4
        )

        mod_path = ".".join([self.root_name, self.mod_name])
        root = lazy_import._builtin_import(mod_path, {}, {}, [], 0)
        self.assertEqual(2, getattr(root, self.mod_name).var2)

        self.assertEqual(
            [
                ("import", sub_mod_path, [], 0),
                ("import", mod_path, [], 0),
            ],
            self.actions,
        )


class TestImportReplacer(ImportReplacerHelper):
    def test_import_root(self):
        """Test 'import root-XXX as root1'."""
        try:
            root1
        except NameError:
            # root1 shouldn't exist yet
            pass
        else:
            self.fail("root1 was not supposed to exist yet")

        # This should replicate 'import root-xxyyzz as root1'
        InstrumentedImportReplacer(
            scope=globals(),
            name="root1",
            module_path=[self.root_name],
            member=None,
            children={},
        )

        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(root1, "__class__")
        )
        self.assertEqual(1, root1.var1)
        self.assertEqual("x", root1.func1("x"))

        self.assertEqual(
            [
                ("__getattribute__", "var1"),
                ("_import", "root1"),
                ("import", self.root_name, [], 0),
            ],
            self.actions,
        )

    def test_import_mod(self):
        """Test 'import root-XXX.mod-XXX as mod2'."""
        try:
            mod1
        except NameError:
            # mod1 shouldn't exist yet
            pass
        else:
            self.fail("mod1 was not supposed to exist yet")

        mod_path = self.root_name + "." + self.mod_name
        InstrumentedImportReplacer(
            scope=globals(),
            name="mod1",
            module_path=[self.root_name, self.mod_name],
            member=None,
            children={},
        )

        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(mod1, "__class__")
        )
        self.assertEqual(2, mod1.var2)
        self.assertEqual("y", mod1.func2("y"))

        self.assertEqual(
            [
                ("__getattribute__", "var2"),
                ("_import", "mod1"),
                ("import", mod_path, [], 0),
            ],
            self.actions,
        )

    def test_import_mod_from_root(self):
        """Test 'from root-XXX import mod-XXX as mod2'."""
        try:
            mod2
        except NameError:
            # mod2 shouldn't exist yet
            pass
        else:
            self.fail("mod2 was not supposed to exist yet")

        InstrumentedImportReplacer(
            scope=globals(),
            name="mod2",
            module_path=[self.root_name],
            member=self.mod_name,
            children={},
        )

        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(mod2, "__class__")
        )
        self.assertEqual(2, mod2.var2)
        self.assertEqual("y", mod2.func2("y"))

        self.assertEqual(
            [
                ("__getattribute__", "var2"),
                ("_import", "mod2"),
                ("import", self.root_name, [self.mod_name], 0),
            ],
            self.actions,
        )

    def test_import_root_and_mod(self):
        """Test 'import root-XXX.mod-XXX' remapping both to root3.mod3."""
        try:
            root3
        except NameError:
            # root3 shouldn't exist yet
            pass
        else:
            self.fail("root3 was not supposed to exist yet")

        InstrumentedImportReplacer(
            scope=globals(),
            name="root3",
            module_path=[self.root_name],
            member=None,
            children={"mod3": ([self.root_name, self.mod_name], None, {})},
        )

        # So 'root3' should be a lazy import
        # and once it is imported, mod3 should also be lazy until
        # actually accessed.
        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(root3, "__class__")
        )
        self.assertEqual(1, root3.var1)

        # There is a mod3 member, but it is also lazy
        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(root3.mod3, "__class__")
        )
        self.assertEqual(2, root3.mod3.var2)

        mod_path = self.root_name + "." + self.mod_name
        self.assertEqual(
            [
                ("__getattribute__", "var1"),
                ("_import", "root3"),
                ("import", self.root_name, [], 0),
                ("__getattribute__", "var2"),
                ("_import", "mod3"),
                ("import", mod_path, [], 0),
            ],
            self.actions,
        )

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
            self.fail("root4 was not supposed to exist yet")

        InstrumentedImportReplacer(
            scope=globals(),
            name="root4",
            module_path=[self.root_name],
            member=None,
            children={},
        )

        # So 'root4' should be a lazy import
        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(root4, "__class__")
        )

        # Lets add a new child to be imported on demand
        # This syntax of using object.__getattribute__ is the correct method
        # for accessing the _import_replacer_children member
        children = object.__getattribute__(root4, "_import_replacer_children")
        children["mod4"] = ([self.root_name, self.mod_name], None, {})

        # Accessing root4.mod4 should import root, but mod should stay lazy
        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(root4.mod4, "__class__")
        )
        self.assertEqual(2, root4.mod4.var2)

        mod_path = self.root_name + "." + self.mod_name
        self.assertEqual(
            [
                ("__getattribute__", "mod4"),
                ("_import", "root4"),
                ("import", self.root_name, [], 0),
                ("__getattribute__", "var2"),
                ("_import", "mod4"),
                ("import", mod_path, [], 0),
            ],
            self.actions,
        )

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
            # root5 shouldn't exist yet
            pass
        else:
            self.fail("root5 was not supposed to exist yet")

        InstrumentedImportReplacer(
            scope=globals(),
            name="root5",
            module_path=[self.root_name],
            member=None,
            children={
                "mod5": ([self.root_name, self.mod_name], None, {}),
                "sub5": (
                    [self.root_name, self.sub_name],
                    None,
                    {
                        "submoda5": (
                            [self.root_name, self.sub_name, self.submoda_name],
                            None,
                            {},
                        ),
                        "submodb5": (
                            [self.root_name, self.sub_name, self.submodb_name],
                            None,
                            {},
                        ),
                    },
                ),
            },
        )

        # So 'root5' should be a lazy import
        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(root5, "__class__")
        )

        # Accessing root5.mod5 should import root, but mod should stay lazy
        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(root5.mod5, "__class__")
        )
        # root5.sub5 should still be lazy, but not re-import root5
        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(root5.sub5, "__class__")
        )

        # Accessing root5.sub5.submoda5 should import sub5, but not either
        # of the sub objects (they should be available as lazy objects
        self.assertEqual(
            InstrumentedImportReplacer,
            object.__getattribute__(root5.sub5.submoda5, "__class__"),
        )
        self.assertEqual(
            InstrumentedImportReplacer,
            object.__getattribute__(root5.sub5.submodb5, "__class__"),
        )

        # This should import mod5
        self.assertEqual(2, root5.mod5.var2)
        # These should import submoda5 and submodb5
        self.assertEqual(4, root5.sub5.submoda5.var4)
        self.assertEqual(5, root5.sub5.submodb5.var5)

        mod_path = self.root_name + "." + self.mod_name
        sub_path = self.root_name + "." + self.sub_name
        submoda_path = sub_path + "." + self.submoda_name
        submodb_path = sub_path + "." + self.submodb_name

        self.assertEqual(
            [
                ("__getattribute__", "mod5"),
                ("_import", "root5"),
                ("import", self.root_name, [], 0),
                ("__getattribute__", "submoda5"),
                ("_import", "sub5"),
                ("import", sub_path, [], 0),
                ("__getattribute__", "var2"),
                ("_import", "mod5"),
                ("import", mod_path, [], 0),
                ("__getattribute__", "var4"),
                ("_import", "submoda5"),
                ("import", submoda_path, [], 0),
                ("__getattribute__", "var5"),
                ("_import", "submodb5"),
                ("import", submodb_path, [], 0),
            ],
            self.actions,
        )


class TestConvertImportToMap(TestCase):
    """Directly test the conversion from import strings to maps."""

    def check(self, expected, import_strings):
        proc = lazy_import.ImportProcessor()
        for import_str in import_strings:
            proc._convert_import_str(import_str)
        self.assertEqual(
            expected,
            proc.imports,
            "Import of {!r} was not converted correctly"
            " {} != {}".format(import_strings, expected, proc.imports),
        )

    def test_import_one(self):
        self.check(
            {
                "one": (["one"], None, {}),
            },
            ["import one"],
        )

    def test_import_one_two(self):
        one_two_map = {
            "one": (
                ["one"],
                None,
                {
                    "two": (["one", "two"], None, {}),
                },
            ),
        }
        self.check(one_two_map, ["import one.two"])
        self.check(one_two_map, ["import one, one.two"])
        self.check(one_two_map, ["import one", "import one.two"])
        self.check(one_two_map, ["import one.two", "import one"])

    def test_import_one_two_three(self):
        one_two_three_map = {
            "one": (
                ["one"],
                None,
                {
                    "two": (
                        ["one", "two"],
                        None,
                        {
                            "three": (["one", "two", "three"], None, {}),
                        },
                    ),
                },
            ),
        }
        self.check(one_two_three_map, ["import one.two.three"])
        self.check(one_two_three_map, ["import one, one.two.three"])
        self.check(one_two_three_map, ["import one", "import one.two.three"])
        self.check(one_two_three_map, ["import one.two.three", "import one"])

    def test_import_one_as_x(self):
        self.check(
            {
                "x": (["one"], None, {}),
            },
            ["import one as x"],
        )

    def test_import_one_two_as_x(self):
        self.check(
            {
                "x": (["one", "two"], None, {}),
            },
            ["import one.two as x"],
        )

    def test_import_mixed(self):
        mixed = {
            "x": (["one", "two"], None, {}),
            "one": (
                ["one"],
                None,
                {
                    "two": (["one", "two"], None, {}),
                },
            ),
        }
        self.check(mixed, ["import one.two as x, one.two"])
        self.check(mixed, ["import one.two as x", "import one.two"])
        self.check(mixed, ["import one.two", "import one.two as x"])

    def test_import_with_as(self):
        self.check({"fast": (["fast"], None, {})}, ["import fast"])


class TestFromToMap(TestCase):
    """Directly test the conversion of 'from foo import bar' syntax."""

    def check_result(self, expected, from_strings):
        proc = lazy_import.ImportProcessor()
        for from_str in from_strings:
            proc._convert_from_str(from_str)
        self.assertEqual(
            expected,
            proc.imports,
            "Import of {!r} was not converted correctly"
            " {} != {}".format(from_strings, expected, proc.imports),
        )

    def test_from_one_import_two(self):
        self.check_result({"two": (["one"], "two", {})}, ["from one import two"])

    def test_from_one_import_two_as_three(self):
        self.check_result(
            {"three": (["one"], "two", {})}, ["from one import two as three"]
        )

    def test_from_one_import_two_three(self):
        two_three_map = {
            "two": (["one"], "two", {}),
            "three": (["one"], "three", {}),
        }
        self.check_result(two_three_map, ["from one import two, three"])
        self.check_result(
            two_three_map, ["from one import two", "from one import three"]
        )

    def test_from_one_two_import_three(self):
        self.check_result(
            {"three": (["one", "two"], "three", {})}, ["from one.two import three"]
        )


class TestCanonicalize(TestCase):
    """Test that we can canonicalize import texts."""

    def check(self, expected, text):
        proc = lazy_import.ImportProcessor()
        parsed = proc._canonicalize_import_text(text)
        self.assertEqual(
            expected,
            parsed,
            "Incorrect parsing of text:\n{}\n{}\n!=\n{}".format(text, expected, parsed),
        )

    def test_import_one(self):
        self.check(["import one"], "import one")
        self.check(["import one"], "\nimport one\n\n")

    def test_import_one_two(self):
        self.check(["import one, two"], "import one, two")
        self.check(["import one, two"], "\nimport one, two\n\n")

    def test_import_one_as_two_as(self):
        self.check(["import one as x, two as y"], "import one as x, two as y")
        self.check(["import one as x, two as y"], "\nimport one as x, two as y\n")

    def test_from_one_import_two(self):
        self.check(["from one import two"], "from one import two")
        self.check(["from one import two"], "\nfrom one import two\n\n")
        self.check(["from one import two"], "\nfrom one import (two)\n")
        self.check(["from one import  two "], "\nfrom one import (\n\ttwo\n)\n")

    def test_multiple(self):
        self.check(
            ["import one", "import two, three", "from one import four"],
            "import one\nimport two, three\nfrom one import four",
        )
        self.check(
            ["import one", "import two, three", "from one import four"],
            "import one\nimport (two, three)\nfrom one import four",
        )
        self.check(
            ["import one", "import two, three", "from one import four"],
            "import one\nimport two, three\nfrom one import four",
        )
        self.check(
            ["import one", "import two, three", "from one import  four, "],
            "import one\nimport two, three\nfrom one import (\n    four,\n    )\n",
        )

    def test_missing_trailing(self):
        proc = lazy_import.ImportProcessor()
        self.assertRaises(
            lazy_import.InvalidImportLine,
            proc._canonicalize_import_text,
            "from foo import (\n  bar\n",
        )


class TestImportProcessor(TestCase):
    """Test that ImportProcessor can turn import texts into lazy imports."""

    def check(self, expected, text):
        proc = lazy_import.ImportProcessor()
        proc._build_map(text)
        self.assertEqual(
            expected,
            proc.imports,
            "Incorrect processing of:\n{}\n{}\n!=\n{}".format(text, expected, proc.imports),
        )

    def test_import_one(self):
        exp = {"one": (["one"], None, {})}
        self.check(exp, "import one")
        self.check(exp, "\nimport one\n")

    def test_import_one_two(self):
        exp = {
            "one": (
                ["one"],
                None,
                {
                    "two": (["one", "two"], None, {}),
                },
            ),
        }
        self.check(exp, "import one.two")
        self.check(exp, "import one, one.two")
        self.check(exp, "import one\nimport one.two")

    def test_import_as(self):
        exp = {"two": (["one"], None, {})}
        self.check(exp, "import one as two")

    def test_import_many(self):
        exp = {
            "one": (
                ["one"],
                None,
                {
                    "two": (
                        ["one", "two"],
                        None,
                        {
                            "three": (["one", "two", "three"], None, {}),
                        },
                    ),
                    "four": (["one", "four"], None, {}),
                },
            ),
            "five": (["one", "five"], None, {}),
        }
        self.check(exp, "import one.two.three, one.four, one.five as five")
        self.check(
            exp,
            "import one.five as five\n"
            "import one\n"
            "import one.two.three\n"
            "import one.four\n",
        )

    def test_from_one_import_two(self):
        exp = {"two": (["one"], "two", {})}
        self.check(exp, "from one import two\n")
        self.check(exp, "from one import (\n    two,\n    )\n")

    def test_from_one_import_two_two(self):
        exp = {"two": (["one"], "two", {})}
        self.check(exp, "from one import two\n")
        self.check(exp, "from one import (two)\n")
        self.check(exp, "from one import (two,)\n")
        self.check(exp, "from one import two as two\n")
        self.check(exp, "from one import (\n    two,\n    )\n")

    def test_from_many(self):
        exp = {
            "two": (["one"], "two", {}),
            "three": (["one", "two"], "three", {}),
            "five": (["one", "two"], "four", {}),
        }
        self.check(
            exp, "from one import two\nfrom one.two import three, four as five\n"
        )
        self.check(
            exp,
            "from one import two\n"
            "from one.two import (\n"
            "    three,\n"
            "    four as five,\n"
            "    )\n",
        )

    def test_mixed(self):
        exp = {
            "two": (["one"], "two", {}),
            "three": (["one", "two"], "three", {}),
            "five": (["one", "two"], "four", {}),
            "one": (
                ["one"],
                None,
                {
                    "two": (["one", "two"], None, {}),
                },
            ),
        }
        self.check(
            exp,
            "from one import two\n"
            "from one.two import three, four as five\n"
            "import one.two",
        )
        self.check(
            exp,
            "from one import two\n"
            "from one.two import (\n"
            "    three,\n"
            "    four as five,\n"
            "    )\n"
            "import one\n"
            "import one.two\n",
        )

    def test_incorrect_line(self):
        proc = lazy_import.ImportProcessor()
        self.assertRaises(lazy_import.InvalidImportLine, proc._build_map, "foo bar baz")
        self.assertRaises(lazy_import.InvalidImportLine, proc._build_map, "improt foo")
        self.assertRaises(lazy_import.InvalidImportLine, proc._build_map, "importfoo")
        self.assertRaises(lazy_import.InvalidImportLine, proc._build_map, "fromimport")

    def test_name_collision(self):
        proc = lazy_import.ImportProcessor()
        proc._build_map("import foo")

        # All of these would try to create an object with the
        # same name as an existing object.
        self.assertRaises(
            lazy_import.ImportNameCollision, proc._build_map, "import bar as foo"
        )
        self.assertRaises(
            lazy_import.ImportNameCollision,
            proc._build_map,
            "from foo import bar as foo",
        )
        self.assertRaises(
            lazy_import.ImportNameCollision, proc._build_map, "from bar import foo"
        )

    def test_relative_imports(self):
        proc = lazy_import.ImportProcessor()
        self.assertRaises(ImportError, proc._build_map, "import .bar as foo")
        self.assertRaises(ImportError, proc._build_map, "from .foo import bar as foo")
        self.assertRaises(ImportError, proc._build_map, "from .bar import foo")


class TestLazyImportProcessor(ImportReplacerHelper):
    def test_root(self):
        try:
            root6
        except NameError:
            pass  # root6 should not be defined yet
        else:
            self.fail("root6 was not supposed to exist yet")

        text = "import {} as root6".format(self.root_name)
        proc = lazy_import.ImportProcessor(InstrumentedImportReplacer)
        proc.lazy_import(scope=globals(), text=text)

        # So 'root6' should be a lazy import
        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(root6, "__class__")
        )

        self.assertEqual(1, root6.var1)
        self.assertEqual("x", root6.func1("x"))

        self.assertEqual(
            [
                ("__getattribute__", "var1"),
                ("_import", "root6"),
                ("import", self.root_name, [], 0),
            ],
            self.actions,
        )

    def test_import_deep(self):
        """Test import root.mod, root.sub.submoda, root.sub.submodb
        root should be a lazy import, with multiple children, who also
        have children to be imported.
        And when root is imported, the children should be lazy, and
        reuse the intermediate lazy object.
        """
        try:
            submoda7
        except NameError:
            pass  # submoda7 should not be defined yet
        else:
            self.fail("submoda7 was not supposed to exist yet")

        text = (
            """\
import {root_name}.{sub_name}.{submoda_name} as submoda7
""".format(**self.__dict__)
        )
        proc = lazy_import.ImportProcessor(InstrumentedImportReplacer)
        proc.lazy_import(scope=globals(), text=text)

        # So 'submoda7' should be a lazy import
        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(submoda7, "__class__")
        )

        # This should import submoda7
        self.assertEqual(4, submoda7.var4)

        sub_path = self.root_name + "." + self.sub_name
        submoda_path = sub_path + "." + self.submoda_name

        self.assertEqual(
            [
                ("__getattribute__", "var4"),
                ("_import", "submoda7"),
                ("import", submoda_path, [], 0),
            ],
            self.actions,
        )

    def test_lazy_import(self):
        """Smoke test that lazy_import() does the right thing."""
        try:
            root8
        except NameError:
            pass  # root8 should not be defined yet
        else:
            self.fail("root8 was not supposed to exist yet")
        lazy_import.lazy_import(
            globals(),
            "import {} as root8".format(self.root_name),
            lazy_import_class=InstrumentedImportReplacer,
        )

        self.assertEqual(
            InstrumentedImportReplacer, object.__getattribute__(root8, "__class__")
        )

        self.assertEqual(1, root8.var1)
        self.assertEqual(1, root8.var1)
        self.assertEqual(1, root8.func1(1))

        self.assertEqual(
            [
                ("__getattribute__", "var1"),
                ("_import", "root8"),
                ("import", self.root_name, [], 0),
            ],
            self.actions,
        )


class TestScopeReplacerReentrance(TestCase):
    """The ScopeReplacer should be reentrant.

    Invoking a replacer while an invocation was already on-going leads to a
    race to see which invocation will be the first to call _replace.
    The losing caller used to see an exception (bugs 396819 and 702914).

    These tests set up a tracer that stops at a suitable moment (upon
    entry of a specified method) and starts another call to the
    functionality in question (__call__, __getattribute__, __setattr_)
    in order to win the race, setting up the original caller to lose.
    """

    def tracer(self, frame, event, arg):
        if event != "call":
            return self.tracer
        # Grab the name of the file that contains the code being executed.
        code = frame.f_code
        filename = code.co_filename
        # Convert ".pyc" and ".pyo" file names to their ".py" equivalent.
        filename = re.sub(r"\.py[co]$", ".py", filename)
        function_name = code.co_name
        # If we're executing a line of code from the right module...
        if (
            filename.endswith("lazy_import.py")
            and function_name == self.method_to_trace
        ):
            # We don't need to trace any more.
            sys.settrace(None)
            # Run another racer.  This one will "win" the race.
            self.racer()
        return self.tracer

    def run_race(self, racer, method_to_trace="_resolve"):
        self.overrideAttr(lazy_import.ScopeReplacer, "_should_proxy", True)
        self.racer = racer
        self.method_to_trace = method_to_trace
        sys.settrace(self.tracer)
        self.racer()  # Should not raise any exception
        # Make sure the tracer actually found the code it was
        # looking for.  If not, maybe the code was refactored in
        # such a way that these tests aren't needed any more.
        self.assertEqual(None, sys.gettrace())

    def test_call(self):
        def factory(*args):
            return factory

        replacer = lazy_import.ScopeReplacer({}, factory, "name")
        self.run_race(replacer)

    def test_setattr(self):
        class Replaced:
            pass

        def factory(*args):
            return Replaced()

        replacer = lazy_import.ScopeReplacer({}, factory, "name")

        def racer():
            replacer.foo = 42

        self.run_race(racer)

    def test_getattribute(self):
        class Replaced:
            foo = "bar"

        def factory(*args):
            return Replaced()

        replacer = lazy_import.ScopeReplacer({}, factory, "name")

        def racer():
            replacer.foo

        self.run_race(racer)
