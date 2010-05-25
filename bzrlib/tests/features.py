# Copyright (C) 2009, 2010 Canonical Ltd
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

from bzrlib import tests
from bzrlib.symbol_versioning import deprecated_in


apport = tests.ModuleAvailableFeature('apport')
paramiko = tests.ModuleAvailableFeature('paramiko')
pycurl = tests.ModuleAvailableFeature('pycurl')
pywintypes = tests.ModuleAvailableFeature('pywintypes')
subunit = tests.ModuleAvailableFeature('subunit')


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

