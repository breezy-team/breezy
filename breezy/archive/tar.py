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

import os
import tarfile
from contextlib import closing
from io import BytesIO

from .. import errors, osutils
from ..export import _export_iter_entries


def prepare_tarball_item(tree, root, final_path, tree_path, entry, force_mtime=None):
    """Prepare a tarball item for exporting.

    :param tree: Tree to export
    :param final_path: Final path to place item
    :param tree_path: Path for the entry in the tree
    :param entry: Entry to export
    :param force_mtime: Option mtime to force, instead of using tree
        timestamps.

    Returns a (tarinfo, fileobj) tuple
    """
    filename = osutils.pathjoin(root, final_path)
    item = tarfile.TarInfo(filename)
    if force_mtime is not None:
        item.mtime = force_mtime
    else:
        item.mtime = tree.get_file_mtime(tree_path)
    if entry.kind == "file":
        item.type = tarfile.REGTYPE
        if tree.is_executable(tree_path):
            item.mode = 0o755
        else:
            item.mode = 0o644
        # This brings the whole file into memory, but that's almost needed for
        # the tarfile contract, which wants the size of the file up front.  We
        # want to make sure it doesn't change, and we need to read it in one
        # go for content filtering.
        content = tree.get_file_text(tree_path)
        item.size = len(content)
        fileobj = BytesIO(content)
    elif entry.kind in ("directory", "tree-reference"):
        item.type = tarfile.DIRTYPE
        item.name += "/"
        item.size = 0
        item.mode = 0o755
        fileobj = None
    elif entry.kind == "symlink":
        item.type = tarfile.SYMTYPE
        item.size = 0
        item.mode = 0o755
        item.linkname = tree.get_symlink_target(tree_path)
        fileobj = None
    else:
        raise errors.BzrError(
            "don't know how to export {{{}}} of kind {!r}".format(final_path, entry.kind)
        )
    return (item, fileobj)


def tarball_generator(
    tree, root, subdir=None, force_mtime=None, format="", recurse_nested=False
):
    """Export tree contents to a tarball.

    Args:
      tree: Tree to export
      subdir: Sub directory to export
      force_mtime: Option mtime to force, instead of using tree
        timestamps.
    Returns: A generator that will produce file content chunks.
    """
    buf = BytesIO()
    with closing(tarfile.open(None, "w:{}".format(format), buf)) as ball, tree.lock_read():
        for final_path, tree_path, entry in _export_iter_entries(
            tree, subdir, recurse_nested=recurse_nested
        ):
            (item, fileobj) = prepare_tarball_item(
                tree, root, final_path, tree_path, entry, force_mtime
            )
            ball.addfile(item, fileobj)
            # Yield the data that was written so far, rinse, repeat.
            yield buf.getvalue()
            buf.truncate(0)
            buf.seek(0)
    yield buf.getvalue()


def tgz_generator(tree, dest, root, subdir, force_mtime=None, recurse_nested=False):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    with tree.lock_read():
        import gzip

        if force_mtime is not None:
            root_mtime = force_mtime
        elif getattr(tree, "repository", None) and getattr(
            tree, "get_revision_id", None
        ):
            # If this is a revision tree, use the revisions' timestamp
            rev = tree.repository.get_revision(tree.get_revision_id())
            root_mtime = rev.timestamp
        elif tree.is_versioned(""):
            root_mtime = tree.get_file_mtime("")
        else:
            root_mtime = None

        basename = None
        # gzip file is used with an explicit fileobj so that
        # the basename can be stored in the gzip file rather than
        # dest. (bug 102234)
        basename = os.path.basename(dest)
        buf = BytesIO()
        zipstream = gzip.GzipFile(basename, "w", fileobj=buf, mtime=root_mtime)
        for chunk in tarball_generator(
            tree, root, subdir, force_mtime, recurse_nested=recurse_nested
        ):
            zipstream.write(chunk)
            # Yield the data that was written so far, rinse, repeat.
            yield buf.getvalue()
            buf.truncate(0)
            buf.seek(0)
        # Closing zipstream may trigger writes to stream
        zipstream.close()
        yield buf.getvalue()


def tbz_generator(tree, dest, root, subdir, force_mtime=None, recurse_nested=False):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    return tarball_generator(
        tree, root, subdir, force_mtime, format="bz2", recurse_nested=recurse_nested
    )


def plain_tar_generator(
    tree, dest, root, subdir, force_mtime=None, recurse_nested=False
):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    return tarball_generator(
        tree, root, subdir, force_mtime, format="", recurse_nested=recurse_nested
    )


def tar_xz_generator(tree, dest, root, subdir, force_mtime=None, recurse_nested=False):
    return tar_lzma_generator(
        tree, dest, root, subdir, force_mtime, "xz", recurse_nested=recurse_nested
    )


def tar_lzma_generator(
    tree,
    dest,
    root,
    subdir,
    force_mtime=None,
    compression_format="alone",
    recurse_nested=False,
):
    """Export this tree to a new .tar.lzma file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    try:
        import lzma
    except ModuleNotFoundError as exc:
        raise errors.DependencyNotPresent("lzma", e) from exc

    compressor = lzma.LZMACompressor(
        format={
            "xz": lzma.FORMAT_XZ,
            "raw": lzma.FORMAT_RAW,
            "alone": lzma.FORMAT_ALONE,
        }[compression_format]
    )

    for chunk in tarball_generator(
        tree, root, subdir, force_mtime=force_mtime, recurse_nested=recurse_nested
    ):
        yield compressor.compress(chunk)

    yield compressor.flush()
