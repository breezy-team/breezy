# Copyright (C) 2006-2012 Aaron Bentley
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
#

"""Tests of the 'brz import' command."""

import os

from ... import tests
from .. import features

LzmaFeature = features.ModuleAvailableFeature("lzma")


class TestImport(tests.TestCaseWithTransport):
    def test_import_upstream(self):
        self.run_bzr("init source")
        os.mkdir("source/src")
        with open("source/src/myfile", "wb") as f:
            f.write(b"hello?")
        os.chdir("source")
        self.run_bzr("add")
        self.run_bzr("commit -m hello")
        self.run_bzr("export ../source-0.1.tar.gz")
        self.run_bzr("export ../source-0.1.tar.bz2")
        self.run_bzr("export ../source-0.1")
        self.run_bzr("init ../import")
        os.chdir("../import")
        self.run_bzr("import ../source-0.1.tar.gz")
        self.assertPathExists("src/myfile")
        result = self.run_bzr("import ../source-0.1.tar.gz", retcode=3)[1]
        self.assertContainsRe(result, "Working tree has uncommitted changes")
        self.run_bzr("commit -m commit")
        self.run_bzr("import ../source-0.1.tar.gz")
        os.chdir("..")
        self.run_bzr("init import2")
        self.run_bzr("import source-0.1.tar.gz import2")
        self.assertPathExists("import2/src/myfile")
        self.run_bzr("import source-0.1.tar.gz import3")
        self.assertPathExists("import3/src/myfile")
        self.run_bzr("import source-0.1.tar.bz2 import4")
        self.assertPathExists("import4/src/myfile")
        self.run_bzr("import source-0.1 import5")
        self.assertPathExists("import5/src/myfile")

    def test_import_upstream_lzma(self):
        self.requireFeature(LzmaFeature)
        self.run_bzr("init source")
        os.mkdir("source/src")
        with open("source/src/myfile", "wb") as f:
            f.write(b"hello?")
        os.chdir("source")
        self.run_bzr("add")
        self.run_bzr("commit -m hello")
        self.run_bzr("export ../source-0.1.tar.lzma")
        self.run_bzr("export ../source-0.1.tar.xz")
        os.chdir("..")
        self.run_bzr("import source-0.1.tar.lzma import1")
        self.assertPathExists("import1/src/myfile")
        self.run_bzr("import source-0.1.tar.xz import2")
        self.assertPathExists("import2/src/myfile")
