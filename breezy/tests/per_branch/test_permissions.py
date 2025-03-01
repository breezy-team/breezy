# Copyright (C) 2006-2010 Canonical Ltd
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


"""Tests for bzr setting permissions.

Files in the branch control directory (.bzr or .bzr/branch) should inherit
the .bzr directory permissions.
So if the directory is group writable, the files and subdirs should be as well.
"""

# TODO: jam 20051215 Currently the default behavior for 'bzr branch' is just
#                    defined by the local umask. This isn't terrible, is it
#                    the truly desired behavior?

import os
import stat
import sys

from breezy import tests
from breezy.bzr.branch import BzrBranch
from breezy.bzr.remote import RemoteBranchFormat
from breezy.controldir import ControlDir
from breezy.tests.test_permissions import check_mode_r


class _NullPermsStat:
    """A class that proxy's a stat result and strips permissions."""

    def __init__(self, orig_stat):
        self._orig_stat = orig_stat
        # We strip all permission bits from st_mode
        self.st_mode = orig_stat.st_mode & ~0o7777

    def __getattr__(self, name):
        return getattr(self._orig_stat, name)


class TestPermissions(tests.TestCaseWithTransport):
    def test_new_branch(self):
        if isinstance(self.branch_format, RemoteBranchFormat):
            # Remote branch format have no permission logic in them; there's
            # nothing to test here.
            raise tests.TestNotApplicable("Remote branches have no permission logic")
        if sys.platform == "win32":
            raise tests.TestNotApplicable("chmod has no effect on win32")
        os.mkdir("a")
        mode = stat.S_IMODE(os.stat("a").st_mode)
        t = self.make_branch_and_tree(".")
        # also, these are BzrBranch format specific things..
        if not isinstance(t.branch, BzrBranch):
            raise tests.TestNotApplicable("Only applicable to bzr branches")
        b = t.branch
        self.assertEqualMode(mode, b.controldir._get_dir_mode())
        self.assertEqualMode(mode & ~0o7111, b.controldir._get_file_mode())
        self.assertEqualMode(mode, b.control_files._dir_mode)
        self.assertEqualMode(mode & ~0o7111, b.control_files._file_mode)

        os.mkdir("d")
        os.chmod("d", 0o700)
        b = self.make_branch("d")
        self.assertEqualMode(0o700, b.controldir._get_dir_mode())
        self.assertEqualMode(0o600, b.controldir._get_file_mode())
        self.assertEqualMode(0o700, b.control_files._dir_mode)
        self.assertEqualMode(0o600, b.control_files._file_mode)
        check_mode_r(self, "d/.bzr", 0o0600, 0o0700)

    def test_new_branch_group_sticky_bit(self):
        if isinstance(self.branch_format, RemoteBranchFormat):
            # Remote branch format have no permission logic in them; there's
            # nothing to test here.
            raise tests.TestNotApplicable("Remote branches have no permission logic")
        if sys.platform == "win32":
            raise tests.TestNotApplicable("chmod has no effect on win32")
        elif sys.platform == "darwin" or "freebsd" in sys.platform:
            # FreeBSD-based platforms create temp dirs with the 'wheel' group,
            # which users are not likely to be in, and this prevents us
            # from setting the sgid bit
            os.chown(self.test_dir, os.getuid(), os.getgid())
        t = self.make_branch_and_tree(".")
        b = t.branch
        # also, these are BzrBranch format specific things..
        if not isinstance(b, BzrBranch):
            raise tests.TestNotApplicable("Only applicable to bzr branches")
        os.mkdir("b")
        os.chmod("b", 0o2777)
        b = self.make_branch("b")
        self.assertEqualMode(0o2777, b.controldir._get_dir_mode())
        self.assertEqualMode(0o0666, b.controldir._get_file_mode())
        self.assertEqualMode(0o2777, b.control_files._dir_mode)
        self.assertEqualMode(0o0666, b.control_files._file_mode)
        check_mode_r(self, "b/.bzr", 0o0666, 0o2777)

        os.mkdir("c")
        os.chmod("c", 0o2750)
        b = self.make_branch("c")
        self.assertEqualMode(0o2750, b.controldir._get_dir_mode())
        self.assertEqualMode(0o0640, b.controldir._get_file_mode())
        self.assertEqualMode(0o2750, b.control_files._dir_mode)
        self.assertEqualMode(0o0640, b.control_files._file_mode)
        check_mode_r(self, "c/.bzr", 0o0640, 0o2750)

    def test_mode_0(self):
        """Test when a transport returns null permissions for .bzr."""
        if isinstance(self.branch_format, RemoteBranchFormat):
            # Remote branch format have no permission logic in them; there's
            # nothing to test here.
            raise tests.TestNotApplicable("Remote branches have no permission logic")
        self.make_branch_and_tree(".")
        bzrdir = ControlDir.open(".")
        # Monkey patch the transport
        _orig_stat = bzrdir.transport.stat

        def null_perms_stat(*args, **kwargs):
            result = _orig_stat(*args, **kwargs)
            return _NullPermsStat(result)

        bzrdir.transport.stat = null_perms_stat
        self.assertIs(None, bzrdir._get_dir_mode())
        self.assertIs(None, bzrdir._get_file_mode())
