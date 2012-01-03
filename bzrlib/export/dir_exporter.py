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

"""Export a bzrlib.tree.Tree to a new or empty directory."""

from __future__ import absolute_import

import errno
import os

from bzrlib import errors, osutils
from bzrlib.export import _export_iter_entries


def dir_exporter_generator(tree, dest, root, subdir=None,
                           force_mtime=None, fileobj=None):
    """Return a generator that exports this tree to a new directory.

    `dest` should either not exist or should be empty. If it does not exist it
    will be created holding the contents of this tree.

    :param fileobj: Is not used in this exporter

    :note: If the export fails, the destination directory will be
           left in an incompletely exported state: export is not transactional.
    """
    try:
        os.mkdir(dest)
    except OSError, e:
        if e.errno == errno.EEXIST:
            # check if directory empty
            if os.listdir(dest) != []:
                raise errors.BzrError(
                    "Can't export tree to non-empty directory.")
        else:
            raise
    # Iterate everything, building up the files we will want to export, and
    # creating the directories and symlinks that we need.
    # This tracks (file_id, (destination_path, executable))
    # This matches the api that tree.iter_files_bytes() wants
    # Note in the case of revision trees, this does trigger a double inventory
    # lookup, hopefully it isn't too expensive.
    to_fetch = []
    for dp, tp, ie in _export_iter_entries(tree, subdir):
        fullpath = osutils.pathjoin(dest, dp)
        if ie.kind == "file":
            to_fetch.append((ie.file_id, (dp, tp, ie.file_id)))
        elif ie.kind == "directory":
            os.mkdir(fullpath)
        elif ie.kind == "symlink":
            try:
                symlink_target = tree.get_symlink_target(ie.file_id, tp)
                os.symlink(symlink_target, fullpath)
            except OSError, e:
                raise errors.BzrError(
                    "Failed to create symlink %r -> %r, error: %s"
                    % (fullpath, symlink_target, e))
        else:
            raise errors.BzrError("don't know how to export {%s} of kind %r" %
               (ie.file_id, ie.kind))

        yield
    # The data returned here can be in any order, but we've already created all
    # the directories
    flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY | getattr(os, 'O_BINARY', 0)
    for (relpath, treepath, file_id), chunks in tree.iter_files_bytes(to_fetch):
        fullpath = osutils.pathjoin(dest, relpath)
        # We set the mode and let the umask sort out the file info
        mode = 0666
        if tree.is_executable(file_id, treepath):
            mode = 0777
        out = os.fdopen(os.open(fullpath, flags, mode), 'wb')
        try:
            out.writelines(chunks)
        finally:
            out.close()
        if force_mtime is not None:
            mtime = force_mtime
        else:
            mtime = tree.get_file_mtime(file_id, treepath)
        os.utime(fullpath, (mtime, mtime))

        yield
