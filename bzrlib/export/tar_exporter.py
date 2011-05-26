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

"""Export a Tree to a non-versioned directory.
"""

import os
import StringIO
import sys
import tarfile

from bzrlib import (
    errors,
    osutils,
    )
from bzrlib.export import _export_iter_entries
from bzrlib.filters import (
    ContentFilterContext,
    filtered_output_bytes,
    )


def export_tarball(tree, ball, root, subdir=None, filtered=False,
                   force_mtime=None):
    """Export tree contents to a tarball.

    :param tree: Tree to export
    :param ball: Tarball to export to
    :param filtered: Whether to apply filters
    :param subdir: Sub directory to export
    :param force_mtime: Option mtime to force, instead of using
        tree timestamps.
    """
    for dp, ie in _export_iter_entries(tree, subdir):
        filename = osutils.pathjoin(root, dp).encode('utf8')
        item = tarfile.TarInfo(filename)
        if force_mtime is not None:
            item.mtime = force_mtime
        else:
            item.mtime = tree.get_file_mtime(ie.file_id, dp)
        if ie.kind == "file":
            item.type = tarfile.REGTYPE
            if tree.is_executable(ie.file_id):
                item.mode = 0755
            else:
                item.mode = 0644
            if filtered:
                chunks = tree.get_file_lines(ie.file_id)
                filters = tree._content_filter_stack(dp)
                context = ContentFilterContext(dp, tree, ie)
                contents = filtered_output_bytes(chunks, filters, context)
                content = ''.join(contents)
                item.size = len(content)
                fileobj = StringIO.StringIO(content)
            else:
                item.size = tree.get_file_size(ie.file_id)
                fileobj = tree.get_file(ie.file_id)
        elif ie.kind == "directory":
            item.type = tarfile.DIRTYPE
            item.name += '/'
            item.size = 0
            item.mode = 0755
            fileobj = None
        elif ie.kind == "symlink":
            item.type = tarfile.SYMTYPE
            item.size = 0
            item.mode = 0755
            item.linkname = tree.get_symlink_target(ie.file_id)
            fileobj = None
        else:
            raise errors.BzrError("don't know how to export {%s} of kind %r" %
                           (ie.file_id, ie.kind))
        ball.addfile(item, fileobj)


def tgz_exporter(tree, dest, root, subdir, filtered=False, force_mtime=None):
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
    if dest == '-':
        basename = None
        stream = sys.stdout
        is_stdout = True
    else:
        stream = open(dest, 'wb')
        # gzip file is used with an explicit fileobj so that
        # the basename can be stored in the gzip file rather than
        # dest. (bug 102234)
        basename = os.path.basename(dest)
    try:
        zipstream = gzip.GzipFile(basename, 'w', fileobj=stream, mtime=root_mtime)
    except TypeError:
        # Python < 2.7 doesn't support the mtime argument
        zipstream = gzip.GzipFile(basename, 'w', fileobj=stream)
    ball = tarfile.open(None, 'w|', fileobj=zipstream)
    export_tarball(tree, ball, root, subdir, filtered=filtered,
                   force_mtime=force_mtime)
    ball.close()
    zipstream.close()
    if not is_stdout:
        stream.close()


def tbz_exporter(tree, dest, root, subdir, filtered=False, force_mtime=None):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    if dest == '-':
        ball = tarfile.open(None, 'w|bz2', sys.stdout)
    else:
        # tarfile.open goes on to do 'os.getcwd() + dest' for opening
        # the tar file. With dest being unicode, this throws UnicodeDecodeError
        # unless we encode dest before passing it on. This works around
        # upstream python bug http://bugs.python.org/issue8396
        # (fixed in Python 2.6.5 and 2.7b1)
        ball = tarfile.open(dest.encode(osutils._fs_enc), 'w:bz2')
    export_tarball(tree, ball, root, subdir, filtered=filtered,
                   force_mtime=force_mtime)
    ball.close()


def plain_tar_exporter(tree, dest, root, subdir, compression=None,
                       filtered=False, force_mtime=None):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    if dest == '-':
        stream = sys.stdout
    else:
        stream = open(dest, 'wb')
    ball = tarfile.open(None, 'w|', stream)
    export_tarball(tree, ball, root, subdir, filtered=filtered,
                   force_mtime=force_mtime)
    ball.close()


def tar_xz_exporter(tree, dest, root, subdir, filtered=False,
                    force_mtime=None):
    return tar_lzma_exporter(tree, dest, root, subdir, filtered=filtered,
        force_mtime=force_mtime, compression_format="xz")


def tar_lzma_exporter(tree, dest, root, subdir, filtered=False, force_mtime=None, compression_format="alone"):
    """Export this tree to a new .tar.lzma file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    if dest == '-':
        raise errors.BzrError("Writing to stdout not supported for .tar.lzma")

    try:
        import lzma
    except ImportError, e:
        raise errors.DependencyNotPresent('lzma', e)

    stream = lzma.LZMAFile(dest.encode(osutils._fs_enc), 'w',
            options={"format": compression_format})
    ball = tarfile.open(None, 'w:', fileobj=stream)
    export_tarball(tree, ball, root, subdir, filtered=filtered,
                   force_mtime=force_mtime)
    ball.close()

