# Copyright (C) 2019 Breezy Developers
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


from breezy.tests import TestCaseWithTransport


class TestPatch(TestCaseWithTransport):
    def test_patch(self):
        self.run_bzr("init")
        with open("myfile", "w") as f:
            f.write("hello")
        self.run_bzr("add")
        self.run_bzr("commit -m hello")
        with open("myfile", "w") as f:
            f.write("goodbye")
        with open("mypatch", "w") as f:
            f.write(self.run_bzr("diff --color=never -p1", retcode=1)[0])
        self.run_bzr("revert")
        self.assertFileEqual("hello", "myfile")
        self.run_bzr("patch -p1 --silent mypatch")
        self.assertFileEqual("goodbye", "myfile")

    def test_patch_invalid_strip(self):
        self.run_bzr_error(
            args="patch --strip=a",
            error_regexes=["brz: ERROR: invalid value for option -p/--strip: a"],
        )
