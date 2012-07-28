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
import time
import warnings

from bzrlib import (
    errors,
    pyutils,
    trace,
    )

# Maps format name => export function
_exporters = {}
# Maps filename extensions => export format name
_exporter_extensions = {}


def register_exporter(format, extensions, func, override=False):
    """Register an exporter.

    :param format: This is the name of the format, such as 'tgz' or 'zip'
    :param extensions: Extensions which should be used in the case that a
                       format was not explicitly specified.
    :type extensions: List
    :param func: The function. It will be called with (tree, dest, root)
    :param override: Whether to override an object which already exists.
                     Frequently plugins will want to provide functionality
                     until it shows up in mainline, so the default is False.
    """
    global _exporters, _exporter_extensions

    if (format not in _exporters) or override:
        _exporters[format] = func

    for ext in extensions:
        if (ext not in _exporter_extensions) or override:
            _exporter_extensions[ext] = format


def register_lazy_exporter(scheme, extensions, module, funcname):
    """Register lazy-loaded exporter function.

    When requesting a specific type of export, load the respective path.
    """
    def _loader(tree, dest, root, subdir, force_mtime, fileobj):
        func = pyutils.get_named_object(module, funcname)
        return func(tree, dest, root, subdir, force_mtime=force_mtime,
            fileobj=fileobj)

    register_exporter(scheme, extensions, _loader)


def get_export_generator(tree, dest=None, format=None, root=None, subdir=None,
                         filtered=False, per_file_timestamps=False,
                         fileobj=None):
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

    :param filtered: If True, content filtering is applied to the exported
        files.  Deprecated in favour of passing a ContentFilterTree
        as the source.

    :param per_file_timestamps: Whether to use the timestamp stored in the tree
        rather than now(). This will do a revision lookup for every file so
        will be significantly slower.

    :param fileobj: Optional file object to use
    """
    global _exporters, _exporter_extensions

    if format is None and dest is not None:
        for ext in _exporter_extensions:
            if dest.endswith(ext):
                format = _exporter_extensions[ext]
                break

    # Most of the exporters will just have to call
    # this function anyway, so why not do it for them
    if root is None:
        root = get_root_name(dest)

    if format not in _exporters:
        raise errors.NoSuchExportFormat(format)

    if not per_file_timestamps:
        force_mtime = time.time()
    else:
        force_mtime = None

    trace.mutter('export version %r', tree)

    if filtered:
        from bzrlib.filter_tree import ContentFilterTree
        warnings.warn(
            "passing filtered=True to export is deprecated in bzr 2.4",
            stacklevel=2)
        tree = ContentFilterTree(tree, tree._content_filter_stack)
        # We don't want things re-filtered by the specific exporter.
        filtered = False

    tree.lock_read()
    try:
        for _ in _exporters[format](
            tree, dest, root, subdir,
            force_mtime=force_mtime, fileobj=fileobj):
            yield
    finally:
        tree.unlock()


def export(tree, dest, format=None, root=None, subdir=None, filtered=False,
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
    :param filtered: If True, content filtering is applied to the
        files exported.  Deprecated in favor of passing an ContentFilterTree.
    :param per_file_timestamps: Whether to use the timestamp stored in the
        tree rather than now(). This will do a revision lookup
        for every file so will be significantly slower.
    :param fileobj: Optional file object to use
    """
    for _ in get_export_generator(tree, dest, format, root, subdir, filtered,
                                  per_file_timestamps, fileobj):
        pass


def get_root_name(dest):
    """Get just the root name for an export.

    """
    global _exporter_extensions
    if dest == '-':
        # Exporting to -/foo doesn't make sense so use relative paths.
        return ''
    dest = os.path.basename(dest)
    for ext in _exporter_extensions:
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
    entries.next()  # skip root
    for path, entry in entries:
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


register_lazy_exporter(None, [], 'bzrlib.export.dir_exporter',
                       'dir_exporter_generator')
register_lazy_exporter('dir', [], 'bzrlib.export.dir_exporter',
                       'dir_exporter_generator')
register_lazy_exporter('tar', ['.tar'], 'bzrlib.export.tar_exporter',
                       'plain_tar_exporter_generator')
register_lazy_exporter('tgz', ['.tar.gz', '.tgz'],
                       'bzrlib.export.tar_exporter',
                       'tgz_exporter_generator')
register_lazy_exporter('tbz2', ['.tar.bz2', '.tbz2'],
                       'bzrlib.export.tar_exporter', 'tbz_exporter_generator')
register_lazy_exporter('tlzma', ['.tar.lzma'], 'bzrlib.export.tar_exporter',
                       'tar_lzma_exporter_generator')
register_lazy_exporter('txz', ['.tar.xz'], 'bzrlib.export.tar_exporter',
                       'tar_xz_exporter_generator')
register_lazy_exporter('zip', ['.zip'], 'bzrlib.export.zip_exporter',
                       'zip_exporter_generator')
