# Copyright (C) 2005-2011 Canonical Ltd
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

"""Export trees to tarballs, non-controlled directories, zipfiles, etc.
"""

from __future__ import absolute_import

import os
import sys
import time
import warnings

from .. import (
    archive,
    errors,
    pyutils,
    trace,
    )

def get_export_generator(tree, dest=None, format=None, root=None, subdir=None,
                         per_file_timestamps=False, fileobj=None):
    """Returns a generator that exports the given tree.

    The generator is expected to yield None while exporting the tree while the
    actual export is written to ``fileobj``.

    :param tree: A Tree (such as RevisionTree) to export

    :param dest: The destination where the files, etc should be put

    :param format: The format (dir, zip, etc), if None, it will check the
        extension on dest, looking for a match

    :param root: The root location inside the format.  It is common practise to
        have zipfiles and tarballs extract into a subdirectory, rather than
        into the current working directory.  If root is None, the default root
        will be selected as the destination without its extension.

    :param subdir: A starting directory within the tree. None means to export
        the entire tree, and anything else should specify the relative path to
        a directory to start exporting from.

    :param per_file_timestamps: Whether to use the timestamp stored in the tree
        rather than now(). This will do a revision lookup for every file so
        will be significantly slower.

    :param fileobj: Optional file object to use
    """
    global _exporters

    if format is None and dest is not None:
        format = archive.format_registry.get_format_from_filename(dest)

    if format is None:
        # Default to 'dir'
        format = 'dir'

    # Most of the exporters will just have to call
    # this function anyway, so why not do it for them
    if root is None:
        root = get_root_name(dest)

    if not per_file_timestamps:
        force_mtime = time.time()
    else:
        force_mtime = None

    trace.mutter('export version %r', tree)

    if format == 'dir':
        with tree.lock_read():
            from breezy.export.dir_exporter import dir_exporter_generator
            for unused in dir_exporter_generator(tree, dest, root, subdir,
                    force_mtime):
                yield
        return

    with tree.lock_read():
        chunks = archive.create_archive(format, tree, dest, root, subdir,
                                        force_mtime)
        if dest == '-':
            for chunk in chunks:
                 sys.stdout.write(chunk)
                 yield
        elif fileobj is not None:
            for chunk in chunks:
                fileobj.write(chunk)
                yield
        else:
            with open(dest, 'wb') as f:
                for chunk in chunks:
                    f.writelines(chunk)
                    yield


def export(tree, dest, format=None, root=None, subdir=None,
           per_file_timestamps=False, fileobj=None):
    """Export the given Tree to the specific destination.

    :param tree: A Tree (such as RevisionTree) to export
    :param dest: The destination where the files,etc should be put
    :param format: The format (dir, zip, etc), if None, it will check the
                   extension on dest, looking for a match
    :param root: The root location inside the format.
                 It is common practise to have zipfiles and tarballs
                 extract into a subdirectory, rather than into the
                 current working directory.
                 If root is None, the default root will be
                 selected as the destination without its
                 extension.
    :param subdir: A starting directory within the tree. None means to export
        the entire tree, and anything else should specify the relative path to
        a directory to start exporting from.
    :param per_file_timestamps: Whether to use the timestamp stored in the
        tree rather than now(). This will do a revision lookup
        for every file so will be significantly slower.
    :param fileobj: Optional file object to use
    """
    for _ in get_export_generator(tree, dest, format, root, subdir,
                                  per_file_timestamps, fileobj):
        pass


def guess_format(filename):
    format = archive.format_registry.get_format_from_filename(filename)
    if format is None:
        format = 'dir'
    return format


def get_root_name(dest):
    """Get just the root name for an export.

    """
    global _exporter_extensions
    if dest == '-':
        # Exporting to -/foo doesn't make sense so use relative paths.
        return ''
    dest = os.path.basename(dest)
    for ext in archive.format_registry.extensions:
        if dest.endswith(ext):
            return dest[:-len(ext)]
    return dest


def _export_iter_entries(tree, subdir, skip_special=True):
    """Iter the entries for tree suitable for exporting.

    :param tree: A tree object.
    :param subdir: None or the path of an entry to start exporting from.
    :param skip_special: Whether to skip .bzr files.
    :return: iterator over tuples with final path, tree path and inventory
        entry for each entry to export
    """
    if subdir == '':
        subdir = None
    if subdir is not None:
        subdir = subdir.rstrip('/')
    entries = tree.iter_entries_by_dir()
    for path, entry in entries:
        if path == '':
            continue

        # The .bzr* namespace is reserved for "magic" files like
        # .bzrignore and .bzrrules - do not export these
        if skip_special and path.startswith(".bzr"):
            continue
        if path == subdir:
            if entry.kind == 'directory':
                continue
            final_path = entry.name
        elif subdir is not None:
            if path.startswith(subdir + '/'):
                final_path = path[len(subdir) + 1:]
            else:
                continue
        else:
            final_path = path
        if not tree.has_filename(path):
            continue

        yield final_path, path, entry
