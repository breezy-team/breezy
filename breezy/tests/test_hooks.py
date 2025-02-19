# Copyright (C) 2007-2012, 2016 Canonical Ltd
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

"""Tests for the core Hooks logic."""

from .. import branch, errors, pyutils, tests
from .. import hooks as _mod_hooks
from ..hooks import (
    HookPoint,
    Hooks,
    UnknownHook,
    install_lazy_named_hook,
    known_hooks,
    known_hooks_key_to_object,
)


class TestErrors(tests.TestCase):
    def test_unknown_hook(self):
        error = UnknownHook("branch", "foo")
        self.assertEqualDiff(
            "The branch hook 'foo' is unknown in this version of breezy.", str(error)
        )
        error = UnknownHook("tree", "bar")
        self.assertEqualDiff(
            "The tree hook 'bar' is unknown in this version of breezy.", str(error)
        )


class TestHooks(tests.TestCase):
    def test_docs(self):
        """docs() should return something reasonable about the Hooks."""

        class MyHooks(Hooks):
            pass

        hooks = MyHooks("breezy.tests.test_hooks", "some_hooks")
        hooks.add_hook(
            "post_tip_change",
            "Invoked after the tip of a branch changes. Called with "
            "a ChangeBranchTipParams object.",
            (1, 4),
        )
        hooks.add_hook(
            "pre_tip_change",
            "Invoked before the tip of a branch changes. Called with "
            "a ChangeBranchTipParams object. Hooks should raise "
            "TipChangeRejected to signal that a tip change is not permitted.",
            (1, 6),
            None,
        )
        self.assertEqualDiff(
            "MyHooks\n"
            "-------\n"
            "\n"
            "post_tip_change\n"
            "~~~~~~~~~~~~~~~\n"
            "\n"
            "Introduced in: 1.4\n"
            "\n"
            "Invoked after the tip of a branch changes. Called with a\n"
            "ChangeBranchTipParams object.\n"
            "\n"
            "pre_tip_change\n"
            "~~~~~~~~~~~~~~\n"
            "\n"
            "Introduced in: 1.6\n"
            "\n"
            "Invoked before the tip of a branch changes. Called with a\n"
            "ChangeBranchTipParams object. Hooks should raise TipChangeRejected to\n"
            "signal that a tip change is not permitted.\n",
            hooks.docs(),
        )

    def test_install_named_hook_raises_unknown_hook(self):
        hooks = Hooks("breezy.tests.test_hooks", "some_hooks")
        self.assertRaises(UnknownHook, hooks.install_named_hook, "silly", None, "")

    def test_install_named_hook_appends_known_hook(self):
        hooks = Hooks("breezy.tests.test_hooks", "some_hooks")
        hooks["set_rh"] = []
        hooks.install_named_hook("set_rh", None, "demo")
        self.assertEqual(hooks["set_rh"], [None])

    def test_install_named_hook_and_retrieve_name(self):
        hooks = Hooks("breezy.tests.test_hooks", "somehooks")
        hooks["set_rh"] = []
        hooks.install_named_hook("set_rh", None, "demo")
        self.assertEqual("demo", hooks.get_hook_name(None))

    def test_uninstall_named_hook(self):
        hooks = Hooks("breezy.tests.test_hooks", "some_hooks")
        hooks.add_hook("set_rh", "Set revision history", (2, 0))
        hooks.install_named_hook("set_rh", None, "demo")
        self.assertEqual(1, len(hooks["set_rh"]))
        hooks.uninstall_named_hook("set_rh", "demo")
        self.assertEqual(0, len(hooks["set_rh"]))

    def test_uninstall_multiple_named_hooks(self):
        # Multiple callbacks with the same label all get removed
        hooks = Hooks("breezy.tests.test_hooks", "some_hooks")
        hooks.add_hook("set_rh", "Set revision history", (2, 0))
        hooks.install_named_hook("set_rh", 1, "demo")
        hooks.install_named_hook("set_rh", 2, "demo")
        hooks.install_named_hook("set_rh", 3, "othername")
        self.assertEqual(3, len(hooks["set_rh"]))
        hooks.uninstall_named_hook("set_rh", "demo")
        self.assertEqual(1, len(hooks["set_rh"]))

    def test_uninstall_named_hook_unknown_callable(self):
        hooks = Hooks("breezy.tests.test_hooks", "some_hooks")
        hooks.add_hook("set_rh", "Set revision hsitory", (2, 0))
        self.assertRaises(KeyError, hooks.uninstall_named_hook, "set_rh", "demo")

    def test_uninstall_named_hook_raises_unknown_hook(self):
        hooks = Hooks("breezy.tests.test_hooks", "some_hooks")
        self.assertRaises(UnknownHook, hooks.uninstall_named_hook, "silly", "")

    def test_uninstall_named_hook_old_style(self):
        hooks = Hooks("breezy.tests.test_hooks", "some_hooks")
        hooks["set_rh"] = []
        hooks.install_named_hook("set_rh", None, "demo")
        self.assertRaises(
            errors.UnsupportedOperation, hooks.uninstall_named_hook, "set_rh", "demo"
        )

    hooks = Hooks("breezy.tests.test_hooks", "TestHooks.hooks")

    def test_install_lazy_named_hook(self):
        # When the hook points are not yet registered the hook is
        # added to the _lazy_hooks dictionary in breezy.hooks.
        self.hooks.add_hook("set_rh", "doc", (0, 15))

        def set_rh():
            return None

        install_lazy_named_hook(
            "breezy.tests.test_hooks", "TestHooks.hooks", "set_rh", set_rh, "demo"
        )
        set_rh_lazy_hooks = _mod_hooks._lazy_hooks[
            ("breezy.tests.test_hooks", "TestHooks.hooks", "set_rh")
        ]
        self.assertEqual(1, len(set_rh_lazy_hooks))
        self.assertEqual(set_rh, set_rh_lazy_hooks[0][0].get_obj())
        self.assertEqual("demo", set_rh_lazy_hooks[0][1])
        self.assertEqual(list(TestHooks.hooks["set_rh"]), [set_rh])

    @classmethod
    def set_rh(cls):
        return None

    def test_install_named_hook_lazy(self):
        hooks = Hooks("breezy.tests.hooks", "some_hooks")
        hooks["set_rh"] = HookPoint("set_rh", "doc", (0, 15), None)
        hooks.install_named_hook_lazy(
            "set_rh", "breezy.tests.test_hooks", "TestHooks.set_rh", "demo"
        )
        self.assertEqual(list(hooks["set_rh"]), [TestHooks.set_rh])

    def test_install_named_hook_lazy_old(self):
        # An exception is raised if a lazy hook is raised for
        # an old style hook point.
        hooks = Hooks("breezy.tests.hooks", "some_hooks")
        hooks["set_rh"] = []
        self.assertRaises(
            errors.UnsupportedOperation,
            hooks.install_named_hook_lazy,
            "set_rh",
            "breezy.tests.test_hooks",
            "TestHooks.set_rh",
            "demo",
        )

    def test_valid_lazy_hooks(self):
        # Make sure that all the registered lazy hooks are referring to existing
        # hook points which allow lazy registration.
        for key, callbacks in _mod_hooks._lazy_hooks.items():
            (module_name, member_name, hook_name) = key
            obj = pyutils.get_named_object(module_name, member_name)
            self.assertEqual(obj._module, module_name)
            self.assertEqual(obj._member_name, member_name)
            self.assertTrue(hook_name in obj)
            self.assertIs(callbacks, obj[hook_name]._callbacks)


class TestHook(tests.TestCase):
    def test___init__(self):
        doc = (
            "Invoked after changing the tip of a branch object. Called with"
            "a breezy.branch.PostChangeBranchTipParams object"
        )
        hook = HookPoint("post_tip_change", doc, (0, 15), None)
        self.assertEqual(doc, hook.__doc__)
        self.assertEqual("post_tip_change", hook.name)
        self.assertEqual((0, 15), hook.introduced)
        self.assertEqual(None, hook.deprecated)
        self.assertEqual([], list(hook))

    def test_docs(self):
        doc = (
            "Invoked after changing the tip of a branch object. Called with"
            " a breezy.branch.PostChangeBranchTipParams object"
        )
        hook = HookPoint("post_tip_change", doc, (0, 15), None)
        self.assertEqual(
            "post_tip_change\n"
            "~~~~~~~~~~~~~~~\n"
            "\n"
            "Introduced in: 0.15\n"
            "\n"
            "Invoked after changing the tip of a branch object. Called with a\n"
            "breezy.branch.PostChangeBranchTipParams object\n",
            hook.docs(),
        )

    def test_hook(self):
        hook = HookPoint("foo", "no docs", None, None)

        def callback():
            pass

        hook.hook(callback, "my callback")
        self.assertEqual([callback], list(hook))

    @classmethod
    def lazy_callback(cls):
        pass

    def test_lazy_hook(self):
        hook = HookPoint("foo", "no docs", None, None)
        hook.hook_lazy(
            "breezy.tests.test_hooks", "TestHook.lazy_callback", "my callback"
        )
        self.assertEqual([TestHook.lazy_callback], list(hook))

    def test_uninstall(self):
        hook = HookPoint("foo", "no docs", None, None)
        hook.hook_lazy(
            "breezy.tests.test_hooks", "TestHook.lazy_callback", "my callback"
        )
        self.assertEqual([TestHook.lazy_callback], list(hook))
        hook.uninstall("my callback")
        self.assertEqual([], list(hook))

    def test_uninstall_unknown(self):
        hook = HookPoint("foo", "no docs", None, None)
        self.assertRaises(KeyError, hook.uninstall, "my callback")

    def test___repr(self):
        # The repr should list all the callbacks, with names.
        hook = HookPoint("foo", "no docs", None, None)

        def callback():
            pass

        hook.hook(callback, "my callback")
        callback_repr = repr(callback)
        self.assertEqual(
            "<HookPoint(foo), callbacks=[%s(my callback)]>" % callback_repr, repr(hook)
        )


class TestHookRegistry(tests.TestCase):
    def test_items_are_reasonable_keys(self):
        # All the items in the known_hooks registry need to map from
        # (module_name, member_name) tuples to the callable used to get an
        # empty Hooks for that attribute. This is used to support the test
        # suite which needs to generate empty hooks (and HookPoints) to ensure
        # isolation and prevent tests failing spuriously.
        for key, factory in known_hooks.items():
            self.assertTrue(
                callable(factory),
                "The factory({!r}) for {!r} is not callable".format(factory, key),
            )
            obj = known_hooks_key_to_object(key)
            self.assertIsInstance(obj, Hooks)
            new_hooks = factory()
            self.assertIsInstance(obj, Hooks)
            self.assertEqual(type(obj), type(new_hooks))
            self.assertEqual("No hook name", new_hooks.get_hook_name(None))

    def test_known_hooks_key_to_object(self):
        self.assertIs(
            branch.Branch.hooks,
            known_hooks_key_to_object(("breezy.branch", "Branch.hooks")),
        )

    def test_known_hooks_key_to_parent_and_attribute(self):
        self.assertEqual(
            (branch.Branch, "hooks"),
            known_hooks.key_to_parent_and_attribute(("breezy.branch", "Branch.hooks")),
        )
        self.assertEqual(
            (branch, "Branch"),
            known_hooks.key_to_parent_and_attribute(("breezy.branch", "Branch")),
        )
