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

"""Export a Tree to a non-versioned directory."""

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

def prepare_tarball_item(tree, root, final_path, entry, filtered=False,
                         force_mtime=None):
    """Prepare a tarball item for exporting
        
    :param tree: Tree to export

    :param final_path: Final path to place item

    :param entry: Entry to export

    :param filtered: Whether to apply filters

    :param force_mtime: Option mtime to force, instead of using tree timestamps.
    
    Returns a (tarinfo, fileobj) tuple
    """
    filename = osutils.pathjoin(root, final_path).encode('utf8')
    item = tarfile.TarInfo(filename)
    if force_mtime is not None:
        item.mtime = force_mtime
    else:
        item.mtime = tree.get_file_mtime(entry.file_id, final_path)
    if entry.kind == "file":
        item.type = tarfile.REGTYPE
        if tree.is_executable(entry.file_id):
            item.mode = 0755
        else:
            item.mode = 0644
        if filtered:
            chunks = tree.get_file_lines(entry.file_id)
            filters = tree._content_filter_stack(final_path)
            context = ContentFilterContext(final_path, tree, entry)
            contents = filtered_output_bytes(chunks, filters, context)
            content = ''.join(contents)
            item.size = len(content)
            fileobj = StringIO.StringIO(content)
        else:
            item.size = tree.get_file_size(entry.file_id)
            fileobj = tree.get_file(entry.file_id)
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
        item.linkname = tree.get_symlink_target(entry.file_id)
        fileobj = None
    else:
        raise errors.BzrError("don't know how to export {%s} of kind %r"
                              % (entry.file_id, entry.kind))
    return (item, fileobj)

def export_tarball_generator(tree, ball, root, subdir=None, filtered=False,
                   force_mtime=None):
    """Export tree contents to a tarball. This is a generator.

    :param tree: Tree to export

    :param ball: Tarball to export to

    :param filtered: Whether to apply filters

    :param subdir: Sub directory to export

    :param force_mtime: Option mtime to force, instead of using tree
        timestamps.
    """
    for final_path, entry in _export_iter_entries(tree, subdir):

        (item, fileobj) = prepare_tarball_item(tree, root, final_path,
                                               entry, filtered, force_mtime)
        ball.addfile(item, fileobj)

        yield


def export_tarball(tree, ball, root, subdir=None, filtered=False,
                   force_mtime=None):

    for _ in export_tarball_generator(tree, ball, root, subdir, filtered,
                                      force_mtime):
        pass

def tgz_exporter_generator(tree, dest, root, subdir, filtered=False,
                           force_mtime=None, fileobj=None):
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
    if fileobj is not None:
        stream = fileobj
    elif dest == '-':
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
        zipstream = gzip.GzipFile(basename, 'w', fileobj=stream,
                                  mtime=root_mtime)
    except TypeError:
        # Python < 2.7 doesn't support the mtime argument
        zipstream = gzip.GzipFile(basename, 'w', fileobj=stream)
    ball = tarfile.open(None, 'w|', fileobj=zipstream)

    for _ in export_tarball_generator(tree, ball, root, subdir, filtered,
                                      force_mtime):

        yield
    # Closing ball may trigger writes to zipstream
    ball.close()
    # Closing zipstream may trigger writes to stream
    zipstream.close()
    if not is_stdout:
        # Now we can safely close the stream
        stream.close()



def tgz_exporter(tree, dest, root, subdir, filtered=False, force_mtime=None,
                 fileobj=None):

    for _ in tgz_exporter_generator(tree, dest, root, subdir, filtered,
                                    force_mtime, fileobj):
        pass


def tbz_exporter_generator(tree, dest, root, subdir, filtered=False,
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
        # tarfile.open goes on to do 'os.getcwd() + dest' for opening
        # the tar file. With dest being unicode, this throws UnicodeDecodeError
        # unless we encode dest before passing it on. This works around
        # upstream python bug http://bugs.python.org/issue8396
        # (fixed in Python 2.6.5 and 2.7b1)
        ball = tarfile.open(dest.encode(osutils._fs_enc), 'w:bz2')

    for _ in export_tarball_generator(tree, ball, root, subdir, filtered,
                                      force_mtime):
        yield

    ball.close()


def tbz_exporter(tree, dest, root, subdir, filtered=False, force_mtime=None,
                 fileobj=None):

    for _ in tbz_exporter_generator(tree, dest, root, subdir, filtered,
                                    force_mtime, fileobj):
        pass


def plain_tar_exporter_generator(tree, dest, root, subdir, compression=None,
                                 filtered=False, force_mtime=None,
                                 fileobj=None):
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

    for _ in export_tarball_generator(tree, ball, root, subdir, filtered,
                                      force_mtime):

        yield

    ball.close()

def plain_tar_exporter(tree, dest, root, subdir, compression=None,
                       filtered=False, force_mtime=None, fileobj=None):

    for _ in plain_tar_exporter_generator(
        tree, dest, root, subdir, compression, filtered, force_mtime, fileobj):
        pass


def tar_xz_exporter_generator(tree, dest, root, subdir, filtered=False,
                              force_mtime=None, fileobj=None):

    return tar_lzma_exporter_generator(tree, dest, root, subdir, filtered,
                                       force_mtime, fileobj, "xz")


def tar_xz_exporter(tree, dest, root, subdir, filtered=False, force_mtime=None,
                     fileobj=None):
    for _ in tar_xz_exporter_generator(tree, dest, root, subdir, filtered,
                                       force_mtime, fileobj):
        pass


def tar_lzma_exporter_generator(tree, dest, root, subdir, filtered=False,
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

    for _ in export_tarball_generator(
        tree, ball, root, subdir, filtered=filtered, force_mtime=force_mtime):
        yield

    ball.close()


def tar_lzma_exporter(tree, dest, root, subdir, filtered=False,
                      force_mtime=None, fileobj=None,
                      compression_format="alone"):
    for _ in tar_lzma_exporter_generator(tree, dest, root, subdir, filtered,
                                         force_mtime, fileobj,
                                         compression_format):
        pass
