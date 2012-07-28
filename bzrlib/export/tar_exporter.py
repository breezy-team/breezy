# Copyright (C) 2005, 2006, 2008-2011 Canonical Ltd
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

"""Export a tree to a tarball."""

from __future__ import absolute_import

import os
import StringIO
import sys
import tarfile

from bzrlib import (
    errors,
    osutils,
    )
from bzrlib.export import _export_iter_entries


def prepare_tarball_item(tree, root, final_path, tree_path, entry, force_mtime=None):
    """Prepare a tarball item for exporting

    :param tree: Tree to export
    :param final_path: Final path to place item
    :param tree_path: Path for the entry in the tree
    :param entry: Entry to export
    :param force_mtime: Option mtime to force, instead of using tree
        timestamps.

    Returns a (tarinfo, fileobj) tuple
    """
    filename = osutils.pathjoin(root, final_path).encode('utf8')
    item = tarfile.TarInfo(filename)
    if force_mtime is not None:
        item.mtime = force_mtime
    else:
        item.mtime = tree.get_file_mtime(entry.file_id, tree_path)
    if entry.kind == "file":
        item.type = tarfile.REGTYPE
        if tree.is_executable(entry.file_id, tree_path):
            item.mode = 0755
        else:
            item.mode = 0644
        # This brings the whole file into memory, but that's almost needed for
        # the tarfile contract, which wants the size of the file up front.  We
        # want to make sure it doesn't change, and we need to read it in one
        # go for content filtering.
        content = tree.get_file_text(entry.file_id, tree_path)
        item.size = len(content)
        fileobj = StringIO.StringIO(content)
    elif entry.kind == "directory":
        item.type = tarfile.DIRTYPE
        item.name += '/'
        item.size = 0
        item.mode = 0755
        fileobj = None
    elif entry.kind == "symlink":
        item.type = tarfile.SYMTYPE
        item.size = 0
        item.mode = 0755
        item.linkname = tree.get_symlink_target(entry.file_id, tree_path)
        fileobj = None
    else:
        raise errors.BzrError("don't know how to export {%s} of kind %r"
                              % (entry.file_id, entry.kind))
    return (item, fileobj)


def export_tarball_generator(tree, ball, root, subdir=None, force_mtime=None):
    """Export tree contents to a tarball.

    :returns: A generator that will repeatedly produce None as each file is
        emitted.  The entire generator must be consumed to complete writing
        the file.

    :param tree: Tree to export

    :param ball: Tarball to export to; it will be closed when writing is
        complete.

    :param subdir: Sub directory to export

    :param force_mtime: Option mtime to force, instead of using tree
        timestamps.
    """
    try:
        for final_path, tree_path, entry in _export_iter_entries(tree, subdir):
            (item, fileobj) = prepare_tarball_item(
                tree, root, final_path, tree_path, entry, force_mtime)
            ball.addfile(item, fileobj)
            yield
    finally:
        ball.close()


def tgz_exporter_generator(tree, dest, root, subdir, force_mtime=None,
    fileobj=None):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    import gzip
    if force_mtime is not None:
        root_mtime = force_mtime
    elif (getattr(tree, "repository", None) and
          getattr(tree, "get_revision_id", None)):
        # If this is a revision tree, use the revisions' timestamp
        rev = tree.repository.get_revision(tree.get_revision_id())
        root_mtime = rev.timestamp
    elif tree.get_root_id() is not None:
        root_mtime = tree.get_file_mtime(tree.get_root_id())
    else:
        root_mtime = None

    is_stdout = False
    basename = None
    if fileobj is not None:
        stream = fileobj
    elif dest == '-':
        stream = sys.stdout
        is_stdout = True
    else:
        stream = open(dest, 'wb')
        # gzip file is used with an explicit fileobj so that
        # the basename can be stored in the gzip file rather than
        # dest. (bug 102234)
        basename = os.path.basename(dest)
    try:
        zipstream = gzip.GzipFile(basename, 'w', fileobj=stream,
                                  mtime=root_mtime)
    except TypeError:
        # Python < 2.7 doesn't support the mtime argument
        zipstream = gzip.GzipFile(basename, 'w', fileobj=stream)
    ball = tarfile.open(None, 'w|', fileobj=zipstream)
    for _ in export_tarball_generator(
        tree, ball, root, subdir, force_mtime):
        yield
    # Closing zipstream may trigger writes to stream
    zipstream.close()
    if not is_stdout:
        # Now we can safely close the stream
        stream.close()


def tbz_exporter_generator(tree, dest, root, subdir,
                           force_mtime=None, fileobj=None):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    if fileobj is not None:
        ball = tarfile.open(None, 'w|bz2', fileobj)
    elif dest == '-':
        ball = tarfile.open(None, 'w|bz2', sys.stdout)
    else:
        # tarfile.open goes on to do 'os.getcwd() + dest' for opening the
        # tar file. With dest being unicode, this throws UnicodeDecodeError
        # unless we encode dest before passing it on. This works around
        # upstream python bug http://bugs.python.org/issue8396 (fixed in
        # Python 2.6.5 and 2.7b1)
        ball = tarfile.open(dest.encode(osutils._fs_enc), 'w:bz2')
    return export_tarball_generator(
        tree, ball, root, subdir, force_mtime)


def plain_tar_exporter_generator(tree, dest, root, subdir, compression=None,
    force_mtime=None, fileobj=None):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    if fileobj is not None:
        stream = fileobj
    elif dest == '-':
        stream = sys.stdout
    else:
        stream = open(dest, 'wb')
    ball = tarfile.open(None, 'w|', stream)
    return export_tarball_generator(
        tree, ball, root, subdir, force_mtime)


def tar_xz_exporter_generator(tree, dest, root, subdir,
                              force_mtime=None, fileobj=None):
    return tar_lzma_exporter_generator(tree, dest, root, subdir,
                                       force_mtime, fileobj, "xz")


def tar_lzma_exporter_generator(tree, dest, root, subdir,
                      force_mtime=None, fileobj=None,
                                compression_format="alone"):
    """Export this tree to a new .tar.lzma file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    if dest == '-':
        raise errors.BzrError("Writing to stdout not supported for .tar.lzma")

    if fileobj is not None:
        raise errors.BzrError(
            "Writing to fileobject not supported for .tar.lzma")
    try:
        import lzma
    except ImportError, e:
        raise errors.DependencyNotPresent('lzma', e)

    stream = lzma.LZMAFile(dest.encode(osutils._fs_enc), 'w',
        options={"format": compression_format})
    ball = tarfile.open(None, 'w:', fileobj=stream)
    return export_tarball_generator(
        tree, ball, root, subdir, force_mtime=force_mtime)
