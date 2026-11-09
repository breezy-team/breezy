#    test_hooks.py -- Tests for builddeb hooks.
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import os

from ..config import DebBuildConfig
from ..hooks import HookFailedError, run_hook
from . import TestCaseInTempDir


class MockTree:
    def abspath(self, relpath):
        return os.path.abspath(relpath)


class HookTests(TestCaseInTempDir):
    default_conf = "default.conf"
    local_conf = "local.conf"

    def test_run_hook_allows_no_hook_defined(self):
        f = open(self.default_conf, "wb")
        f.close()
        config = DebBuildConfig([(self.default_conf, False)])
        run_hook(MockTree(), "pre-build", config)

    def test_run_hook_raises_when_hook_fails(self):
        with open(self.default_conf, "wb") as f:
            f.write(b"[HOOKS]\npre-build = false\n")
        config = DebBuildConfig([(self.default_conf, False)])
        self.assertRaises(HookFailedError, run_hook, MockTree(), "pre-build", config)

    def test_run_hook_when_hook_passes(self):
        with open(self.default_conf, "wb") as f:
            f.write(b"[HOOKS]\npre-build = true\n")
        config = DebBuildConfig([(self.default_conf, False)])
        run_hook(MockTree(), "pre-build", config)

    def test_run_hook_uses_cwd_by_default(self):
        with open(self.default_conf, "wb") as f:
            f.write(b"[HOOKS]\npre-build = touch a\n")
        config = DebBuildConfig([(self.default_conf, False)])
        run_hook(MockTree(), "pre-build", config)
        self.assertPathExists("a")

    def test_run_hook_uses_passed_wd(self):
        os.mkdir("dir")
        with open(self.default_conf, "wb") as f:
            f.write(b"[HOOKS]\npre-build = touch a\n")
        config = DebBuildConfig([(self.default_conf, False)])
        run_hook(MockTree(), "pre-build", config, wd="dir")
        self.assertPathExists("dir/a")

    def test_run_hook_uses_shell(self):
        with open(self.default_conf, "wb") as f:
            f.write(b"[HOOKS]\npost-build = touch a && touch b\n")
        config = DebBuildConfig([(self.default_conf, False)])
        run_hook(MockTree(), "post-build", config)
        self.assertPathExists("a")
        self.assertPathExists("b")

    def test_run_hook_uses_local_over_global(self):
        with open(self.default_conf, "wb") as f:
            f.write(b"[HOOKS]\npost-build = touch a\n")
        with open(self.local_conf, "wb") as f:
            f.write(b"[HOOKS]\npost-build = touch b\n")
        config = DebBuildConfig([(self.local_conf, False), (self.default_conf, False)])
        run_hook(MockTree(), "post-build", config)
        self.assertPathDoesNotExist("a")
        self.assertPathExists("b")
