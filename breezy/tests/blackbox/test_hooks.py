# Copyright (C) 2008, 2009, 2011, 2012, 2016 Canonical Ltd
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

"""Tests for commands related to hooks."""

from breezy.branch import Branch
from breezy.tests import TestCaseWithTransport


def _foo_hook():
    pass


class TestHooks(TestCaseWithTransport):
    def _check_hooks_output(self, command_output, hooks):
        for hook_type in Branch.hooks:
            s = "\n  ".join(hooks.get(hook_type, ["<no hooks installed>"]))
            self.assertTrue("{}:\n    {}".format(hook_type, s) in command_output)

    def test_hooks_with_no_hooks(self):
        self.make_branch(".")
        out, err = self.run_bzr("hooks")
        self.assertEqual(err, "")
        for _hook_type in Branch.hooks:
            self._check_hooks_output(out, {})

    def test_hooks_with_unnamed_hook(self):
        self.make_branch(".")

        def foo():
            return

        Branch.hooks.install_named_hook("post_push", foo, None)
        out, err = self.run_bzr("hooks")
        self._check_hooks_output(out, {"post_push": ["No hook name"]})

    def test_hooks_with_named_hook(self):
        self.make_branch(".")

        def foo():
            return

        name = "Foo Bar Hook"
        Branch.hooks.install_named_hook("post_push", foo, name)
        out, err = self.run_bzr("hooks")
        self._check_hooks_output(out, {"post_push": [name]})

    def test_hooks_no_branch(self):
        self.run_bzr("hooks")

    def test_hooks_lazy_with_unnamed_hook(self):
        self.make_branch(".")

        def foo():
            return

        Branch.hooks.install_named_hook_lazy(
            "post_push", "breezy.tests.blackbox.test_hooks", "_foo_hook", None
        )
        out, err = self.run_bzr("hooks")
        self._check_hooks_output(out, {"post_push": ["No hook name"]})

    def test_hooks_lazy_with_named_hook(self):
        self.make_branch(".")

        def foo():
            return

        Branch.hooks.install_named_hook_lazy(
            "post_push",
            "breezy.tests.blackbox.test_hooks",
            "_foo_hook",
            "hook has a name",
        )
        out, err = self.run_bzr("hooks")
        self._check_hooks_output(out, {"post_push": ["hook has a name"]})
