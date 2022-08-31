# Copyright (C) 2018 Breezy Developers
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

"""Export trees to tarballs, zipfiles, etc.
"""

import os
import time
import warnings

from .. import (
    errors,
    pyutils,
    registry,
    trace,
    )


class ArchiveFormatInfo(object):

    def __init__(self, extensions):
        self.extensions = extensions


class ArchiveFormatRegistry(registry.Registry):
    """Registry of archive formats."""

    def __init__(self):
        self._extension_map = {}
        super(ArchiveFormatRegistry, self).__init__()

    @property
    def extensions(self):
        return self._extension_map.keys()

    def register(self, key, factory, extensions, help=None):
        """Register an archive format.
        """
        registry.Registry.register(self, key, factory, help,
                                   ArchiveFormatInfo(extensions))
        self._register_extensions(key, extensions)

    def register_lazy(self, key, module_name, member_name, extensions,
                      help=None):
        registry.Registry.register_lazy(self, key, module_name, member_name,
                                        help, ArchiveFormatInfo(extensions))
        self._register_extensions(key, extensions)

    def _register_extensions(self, name, extensions):
        for ext in extensions:
            self._extension_map[ext] = name

    def get_format_from_filename(self, filename):
        """Determine the archive format from an extension.

        :param filename: Filename to guess from
        :return: A format name, or None
        """
        for ext, format in self._extension_map.items():
            if filename.endswith(ext):
                return format
        else:
            return None


def create_archive(format, tree, name, root=None, subdir=None,
                   force_mtime=None, recurse_nested=False):
    try:
        archive_fn = format_registry.get(format)
    except KeyError:
        raise errors.NoSuchExportFormat(format)
    return archive_fn(tree, name, root=root, subdir=subdir,
                      force_mtime=force_mtime,
                      recurse_nested=recurse_nested)


format_registry = ArchiveFormatRegistry()
format_registry.register_lazy('tar', 'breezy.archive.tar',
                              'plain_tar_generator', ['.tar'], )
format_registry.register_lazy('tgz', 'breezy.archive.tar',
                              'tgz_generator', ['.tar.gz', '.tgz'])
format_registry.register_lazy('tbz2', 'breezy.archive.tar',
                              'tbz_generator', ['.tar.bz2', '.tbz2'])
format_registry.register_lazy('tlzma', 'breezy.archive.tar',
                              'tar_lzma_generator', ['.tar.lzma'])
format_registry.register_lazy('txz', 'breezy.archive.tar',
                              'tar_xz_generator', ['.tar.xz'])
format_registry.register_lazy('zip', 'breezy.archive.zip',
                              'zip_archive_generator', ['.zip'])
