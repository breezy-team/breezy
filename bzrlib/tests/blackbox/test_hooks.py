# Copyright (C) 2008 Canonical Ltd
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

"""Tests for commands related to hooks"""

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseWithTransport


class TestHooks(TestCaseWithTransport):

    def _check_hooks_output(self, command_output, hooks):
        for hook_type in Branch.hooks:
            s = "\n  ".join(hooks.get(hook_type, ["<no hooks installed>"]))
            self.assert_("%s:\n  %s" % (hook_type, s) in command_output)

    def test_hooks_with_no_hooks(self):
        self.make_branch('.')
        out, err = self.run_bzr('hooks')
        self.assertEqual(err, "")
        for hook_type in Branch.hooks:
            self._check_hooks_output(out, {})

    def test_hooks_with_unnamed_hook(self):
        self.make_branch('.')
        def foo(): return
        Branch.hooks.install_named_hook('set_rh', foo, None)
        out, err = self.run_bzr('hooks')
        self._check_hooks_output(out, {'set_rh': ["No hook name"]})

    def test_hooks_with_named_hook(self):
        self.make_branch('.')
        def foo(): return
        name = "Foo Bar Hook"
        Branch.hooks.install_named_hook('set_rh', foo, name)
        out, err = self.run_bzr('hooks')
        self._check_hooks_output(out, {'set_rh': [name]})

    def test_hooks_no_branch(self):
        self.run_bzr('hooks', retcode=3)
