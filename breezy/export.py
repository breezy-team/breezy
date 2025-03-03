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

"""Export trees to tarballs, non-controlled directories, zipfiles, etc."""

import errno
import os
import sys
import time

from . import archive, errors, osutils, trace


def export(
    tree,
    dest,
    format=None,
    root=None,
    subdir=None,
    per_file_timestamps=False,
    fileobj=None,
    recurse_nested=False,
):
    """Export the given Tree to the specific destination.

    Args:
      tree: A Tree (such as RevisionTree) to export
      dest: The destination where the files,etc should be put
      format: The format (dir, zip, etc), if None, it will check the
              extension on dest, looking for a match
      root: The root location inside the format.
            It is common practise to have zipfiles and tarballs
            extract into a subdirectory, rather than into the
            current working directory.
            If root is None, the default root will be
            selected as the destination without its
            extension.
      subdir: A starting directory within the tree. None means to export the
              entire tree, and anything else should specify the relative path
              to a directory to start exporting from.
      per_file_timestamps: Whether to use the timestamp stored in the tree
          rather than now(). This will do a revision lookup for every file so will
          be significantly slower.
      fileobj: Optional file object to use
    """
    if format is None and dest is not None:
        format = guess_format(dest)

    # Most of the exporters will just have to call
    # this function anyway, so why not do it for them
    if root is None:
        root = get_root_name(dest)

    if not per_file_timestamps:
        force_mtime = time.time()
        if getattr(tree, "_repository", None):
            try:
                force_mtime = tree._repository.get_revision(
                    tree.get_revision_id()
                ).timestamp
            except errors.NoSuchRevision:
                pass
            except errors.UnsupportedOperation:
                pass
    else:
        force_mtime = None

    trace.mutter("export version %r", tree)

    if format == "dir":
        # TODO(jelmer): If the tree is remote (e.g. HPSS, Git Remote),
        # then we should stream a tar file and unpack that on the fly.
        with tree.lock_read():
            for _unused in dir_exporter_generator(
                tree, dest, root, subdir, force_mtime, recurse_nested=recurse_nested
            ):
                pass
        return

    with tree.lock_read():
        chunks = tree.archive(
            format,
            dest,
            root=root,
            subdir=subdir,
            force_mtime=force_mtime,
            recurse_nested=recurse_nested,
        )
        if dest == "-":
            for chunk in chunks:
                getattr(sys.stdout, "buffer", sys.stdout).write(chunk)
        elif fileobj is not None:
            for chunk in chunks:
                fileobj.write(chunk)
        else:
            with open(dest, "wb") as f:
                for chunk in chunks:
                    f.write(chunk)


def guess_format(filename, default="dir"):
    """Guess the export format based on a file name.

    :param filename: Filename to guess from
    :param default: Default format to fall back to
    :return: format name
    """
    format = archive.format_registry.get_format_from_filename(filename)
    if format is None:
        format = default
    return format


def get_root_name(dest):
    """Get just the root name for an export."""
    global _exporter_extensions
    if dest == "-":
        # Exporting to -/foo doesn't make sense so use relative paths.
        return ""
    dest = os.path.basename(dest)
    for ext in archive.format_registry.extensions:
        if dest.endswith(ext):
            return dest[: -len(ext)]
    return dest


def _export_iter_entries(tree, subdir, skip_special=True, recurse_nested=False):
    """Iter the entries for tree suitable for exporting.

    :param tree: A tree object.
    :param subdir: None or the path of an entry to start exporting from.
    :param skip_special: Whether to skip .bzr files.
    :return: iterator over tuples with final path, tree path and inventory
        entry for each entry to export
    """
    if subdir == "":
        subdir = None
    if subdir is not None:
        subdir = subdir.rstrip("/")
    entries = tree.iter_entries_by_dir(recurse_nested=recurse_nested)
    for path, entry in entries:
        if path == "":
            continue

        if skip_special and tree.is_special_path(path):
            continue
        if path == subdir:
            if entry.kind == "directory":
                continue
            final_path = entry.name
        elif subdir is not None:
            if path.startswith(subdir + "/"):
                final_path = path[len(subdir) + 1 :]
            else:
                continue
        else:
            final_path = path
        if not tree.has_filename(path):
            continue

        yield final_path, path, entry


def dir_exporter_generator(
    tree, dest, root, subdir=None, force_mtime=None, fileobj=None, recurse_nested=False
):
    """Return a generator that exports this tree to a new directory.

    `dest` should either not exist or should be empty. If it does not exist it
    will be created holding the contents of this tree.

    :note: If the export fails, the destination directory will be
           left in an incompletely exported state: export is not transactional.
    """
    try:
        os.mkdir(dest)
    except OSError as e:
        if e.errno == errno.EEXIST:
            # check if directory empty
            if os.listdir(dest) != []:
                raise errors.BzrError("Can't export tree to non-empty directory.")
        else:
            raise
    # Iterate everything, building up the files we will want to export, and
    # creating the directories and symlinks that we need.
    # This tracks (None, (destination_path, executable))
    # This matches the api that tree.iter_files_bytes() wants
    # Note in the case of revision trees, this does trigger a double inventory
    # lookup, hopefully it isn't too expensive.
    to_fetch = []
    for dp, tp, ie in _export_iter_entries(tree, subdir, recurse_nested=recurse_nested):
        fullpath = osutils.pathjoin(dest, dp)
        if ie.kind == "file":
            to_fetch.append((tp, (dp, tp, None)))
        elif ie.kind in ("directory", "tree-reference"):
            os.mkdir(fullpath)
        elif ie.kind == "symlink":
            try:
                symlink_target = tree.get_symlink_target(tp)
                os.symlink(symlink_target, fullpath)
            except OSError as e:
                raise errors.BzrError(
                    "Failed to create symlink {!r} -> {!r}, error: {}".format(
                        fullpath, symlink_target, e
                    )
                )
        else:
            raise errors.BzrError(
                "don't know how to export {{{}}} of kind {!r}".format(tp, ie.kind)
            )

        yield
    # The data returned here can be in any order, but we've already created all
    # the directories
    flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    for (relpath, treepath, _unused_none), chunks in tree.iter_files_bytes(to_fetch):
        fullpath = osutils.pathjoin(dest, relpath)
        # We set the mode and let the umask sort out the file info
        mode = 0o666
        if tree.is_executable(treepath):
            mode = 0o777
        with os.fdopen(os.open(fullpath, flags, mode), "wb") as out:
            out.writelines(chunks)
        if force_mtime is not None:
            mtime = force_mtime
        else:
            mtime = tree.get_file_mtime(treepath)
        os.utime(fullpath, (mtime, mtime))

        yield
