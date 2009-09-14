# Copyright (C) 2007, 2009 Canonical Ltd
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

from bzrlib import branch, errors
from bzrlib.hooks import (
    HookPoint,
    Hooks,
    known_hooks,
    known_hooks_key_to_object,
    known_hooks_key_to_parent_and_attribute,
    )
from bzrlib.errors import (
    UnknownHook,
    )

from bzrlib.tests import TestCase


class TestHooks(TestCase):

    def test_create_hook_first(self):
        hooks = Hooks()
        doc = ("Invoked after changing the tip of a branch object. Called with"
            "a bzrlib.branch.PostChangeBranchTipParams object")
        hook = HookPoint("post_tip_change", doc, (0, 15), None)
        hooks.create_hook(hook)
        self.assertEqual(hook, hooks['post_tip_change'])

    def test_create_hook_name_collision_errors(self):
        hooks = Hooks()
        doc = ("Invoked after changing the tip of a branch object. Called with"
            "a bzrlib.branch.PostChangeBranchTipParams object")
        hook = HookPoint("post_tip_change", doc, (0, 15), None)
        hook2 = HookPoint("post_tip_change", None, None, None)
        hooks.create_hook(hook)
        self.assertRaises(errors.DuplicateKey, hooks.create_hook, hook2)
        self.assertEqual(hook, hooks['post_tip_change'])

    def test_docs(self):
        """docs() should return something reasonable about the Hooks."""
        class MyHooks(Hooks):
            pass
        hooks = MyHooks()
        hooks['legacy'] = []
        hook1 = HookPoint('post_tip_change',
            "Invoked after the tip of a branch changes. Called with "
            "a ChangeBranchTipParams object.", (1, 4), None)
        hook2 = HookPoint('pre_tip_change',
            "Invoked before the tip of a branch changes. Called with "
            "a ChangeBranchTipParams object. Hooks should raise "
            "TipChangeRejected to signal that a tip change is not permitted.",
            (1, 6), None)
        hooks.create_hook(hook1)
        hooks.create_hook(hook2)
        self.assertEqualDiff(
            "MyHooks\n"
            "-------\n"
            "\n"
            "legacy\n"
            "~~~~~~\n"
            "\n"
            "An old-style hook. For documentation see the __init__ method of 'MyHooks'\n"
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
            "signal that a tip change is not permitted.\n", hooks.docs())

    def test_install_named_hook_raises_unknown_hook(self):
        hooks = Hooks()
        self.assertRaises(UnknownHook, hooks.install_named_hook, 'silly',
                          None, "")

    def test_install_named_hook_appends_known_hook(self):
        hooks = Hooks()
        hooks['set_rh'] = []
        hooks.install_named_hook('set_rh', None, "demo")
        self.assertEqual(hooks['set_rh'], [None])

    def test_install_named_hook_and_retrieve_name(self):
        hooks = Hooks()
        hooks['set_rh'] = []
        hooks.install_named_hook('set_rh', None, "demo")
        self.assertEqual("demo", hooks.get_hook_name(None))


class TestHook(TestCase):

    def test___init__(self):
        doc = ("Invoked after changing the tip of a branch object. Called with"
            "a bzrlib.branch.PostChangeBranchTipParams object")
        hook = HookPoint("post_tip_change", doc, (0, 15), None)
        self.assertEqual(doc, hook.__doc__)
        self.assertEqual("post_tip_change", hook.name)
        self.assertEqual((0, 15), hook.introduced)
        self.assertEqual(None, hook.deprecated)
        self.assertEqual([], list(hook))

    def test_docs(self):
        doc = ("Invoked after changing the tip of a branch object. Called with"
            " a bzrlib.branch.PostChangeBranchTipParams object")
        hook = HookPoint("post_tip_change", doc, (0, 15), None)
        self.assertEqual("post_tip_change\n"
            "~~~~~~~~~~~~~~~\n"
            "\n"
            "Introduced in: 0.15\n"
            "\n"
            "Invoked after changing the tip of a branch object. Called with a\n"
            "bzrlib.branch.PostChangeBranchTipParams object\n", hook.docs())

    def test_hook(self):
        hook = HookPoint("foo", "no docs", None, None)
        def callback():
            pass
        hook.hook(callback, "my callback")
        self.assertEqual([callback], list(hook))

    def test___repr(self):
        # The repr should list all the callbacks, with names.
        hook = HookPoint("foo", "no docs", None, None)
        def callback():
            pass
        hook.hook(callback, "my callback")
        callback_repr = repr(callback)
        self.assertEqual(
            '<HookPoint(foo), callbacks=[%s(my callback)]>' %
            callback_repr, repr(hook))


class TestHookRegistry(TestCase):

    def test_items_are_reasonable_keys(self):
        # All the items in the known_hooks registry need to map from
        # (module_name, member_name) tuples to the callable used to get an
        # empty Hooks for that attribute. This is used to support the test
        # suite which needs to generate empty hooks (and HookPoints) to ensure
        # isolation and prevent tests failing spuriously.
        for key, factory in known_hooks.items():
            self.assertTrue(callable(factory),
                "The factory(%r) for %r is not callable" % (factory, key))
            obj = known_hooks_key_to_object(key)
            self.assertIsInstance(obj, Hooks)
            new_hooks = factory()
            self.assertIsInstance(obj, Hooks)
            self.assertEqual(type(obj), type(new_hooks))

    def test_known_hooks_key_to_object(self):
        self.assertIs(branch.Branch.hooks,
            known_hooks_key_to_object(('bzrlib.branch', 'Branch.hooks')))

    def test_known_hooks_key_to_parent_and_attribute(self):
        self.assertEqual((branch.Branch, 'hooks'),
            known_hooks_key_to_parent_and_attribute(
            ('bzrlib.branch', 'Branch.hooks')))
        self.assertEqual((branch, 'Branch'),
            known_hooks_key_to_parent_and_attribute(
            ('bzrlib.branch', 'Branch')))
