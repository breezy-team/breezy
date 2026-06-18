#    test_builder.py -- Testsuite for builddeb builder.py
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
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

from ....tests import TestCaseInTempDir
from ..builder import (
    BuildFailedError,
    DebBuild,
    NoSourceDirError,
)


class TestDebBuild(TestCaseInTempDir):
    def test_prepare_makes_parents(self):
        builder = DebBuild(None, "target/sub/sub2", None)
        builder.prepare()
        self.assertPathExists("target/sub")
        self.assertPathDoesNotExist("target/sub/sub2")

    def test_prepare_purges_dir(self):
        self.build_tree(["target/", "target/sub/"])
        builder = DebBuild(None, "target/sub/", None)
        builder.prepare()
        self.assertPathExists("target")
        self.assertPathDoesNotExist("target/sub")

    def test_use_existing_preserves(self):
        self.build_tree(["target/", "target/sub/"])
        builder = DebBuild(None, "target/sub/", None, use_existing=True)
        builder.prepare()
        self.assertPathExists("target/sub")

    def test_use_existing_errors_if_not_present(self):
        self.build_tree(["target/"])
        builder = DebBuild(None, "target/sub/", None, use_existing=True)
        self.assertRaises(NoSourceDirError, builder.prepare)
        self.assertPathDoesNotExist("target/sub")

    def test_export(self):
        class MkdirDistiller:
            def distill(self, target):
                os.mkdir(target)

        builder = DebBuild(MkdirDistiller(), "target", None)
        builder.export()
        self.assertPathExists("target")

    def test_build(self):
        builder = DebBuild(None, "target", "touch built")
        self.build_tree(["target/"])
        builder.build()
        self.assertPathExists("target/built")

    def test_build_fails(self):
        builder = DebBuild(None, "target", "false")
        self.build_tree(["target/"])
        self.assertRaises(BuildFailedError, builder.build)

    def test_clean(self):
        builder = DebBuild(None, "target", None)
        self.build_tree(["target/", "target/foo"])
        builder.clean()
        self.assertPathDoesNotExist("target")
