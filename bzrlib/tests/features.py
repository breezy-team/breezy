# Copyright (C) 2009, 2010, 2011 Canonical Ltd
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

"""A collection of commonly used 'Features' which bzrlib uses to skip tests."""

import os
import stat
import sys

from bzrlib import (
    osutils,
    tests,
    )


class _NotRunningAsRoot(tests.Feature):

    def _probe(self):
        try:
            uid = os.getuid()
        except AttributeError:
            # If there is no uid, chances are there is no root either
            return True
        return uid != 0

    def feature_name(self):
        return 'Not running as root'


not_running_as_root = _NotRunningAsRoot()

apport = tests.ModuleAvailableFeature('apport')
lzma = tests.ModuleAvailableFeature('lzma')
meliae = tests.ModuleAvailableFeature('meliae')
paramiko = tests.ModuleAvailableFeature('paramiko')
pycurl = tests.ModuleAvailableFeature('pycurl')
pywintypes = tests.ModuleAvailableFeature('pywintypes')
sphinx = tests.ModuleAvailableFeature('sphinx')
subunit = tests.ModuleAvailableFeature('subunit')
testtools = tests.ModuleAvailableFeature('testtools')


class _BackslashDirSeparatorFeature(tests.Feature):

    def _probe(self):
        try:
            os.lstat(os.getcwd() + '\\')
        except OSError:
            return False
        else:
            return True

    def feature_name(self):
        return "Filesystem treats '\\' as a directory separator."

backslashdir_feature = _BackslashDirSeparatorFeature()


class _PosixPermissionsFeature(tests.Feature):

    def _probe(self):
        def has_perms():
            # create temporary file and check if specified perms are maintained.
            import tempfile

            write_perms = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
            f = tempfile.mkstemp(prefix='bzr_perms_chk_')
            fd, name = f
            os.close(fd)
            os.chmod(name, write_perms)

            read_perms = os.stat(name).st_mode & 0777
            os.unlink(name)
            return (write_perms == read_perms)

        return (os.name == 'posix') and has_perms()

    def feature_name(self):
        return 'POSIX permissions support'


posix_permissions_feature = _PosixPermissionsFeature()


class _ChownFeature(tests.Feature):
    """os.chown is supported"""

    def _probe(self):
        return os.name == 'posix' and hasattr(os, 'chown')

chown_feature = _ChownFeature()


class ExecutableFeature(tests.Feature):
    """Feature testing whether an executable of a given name is on the PATH."""

    def __init__(self, name):
        super(ExecutableFeature, self).__init__()
        self.name = name
        self._path = None

    @property
    def path(self):
        # This is a property, so accessing path ensures _probe was called
        self.available()
        return self._path

    def _probe(self):
        self._path = osutils.find_executable_on_path(self.name)
        return self._path is not None

    def feature_name(self):
        return '%s executable' % self.name


bash_feature = ExecutableFeature('bash')
sed_feature = ExecutableFeature('sed')
diff_feature = ExecutableFeature('diff')


class Win32Feature(tests.Feature):
    """Feature testing whether we're running selftest on Windows
    or Windows-like platform.
    """

    def _probe(self):
        return sys.platform == 'win32'

    def feature_name(self):
        return "win32 platform"

win32_feature = Win32Feature()