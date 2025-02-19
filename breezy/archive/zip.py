# Copyright (C) 2005, 2006, 2008, 2009, 2010 Canonical Ltd
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

"""Export a Tree to a zip file."""

import stat
import tempfile
import time
import zipfile
from contextlib import closing

from .. import osutils
from ..export import _export_iter_entries
from ..trace import mutter

# Windows expects this bit to be set in the 'external_attr' section,
# or it won't consider the entry a directory.
ZIP_DIRECTORY_BIT = 1 << 4
FILE_PERMISSIONS = 0o644 << 16
DIR_PERMISSIONS = 0o755 << 16

_FILE_ATTR = stat.S_IFREG | FILE_PERMISSIONS
_DIR_ATTR = stat.S_IFDIR | ZIP_DIRECTORY_BIT | DIR_PERMISSIONS


def zip_archive_generator(
    tree, dest, root, subdir=None, force_mtime=None, recurse_nested=False
):
    """Export this tree to a new zip file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be overwritten".
    """
    compression = zipfile.ZIP_DEFLATED
    with tempfile.SpooledTemporaryFile() as buf:
        with closing(zipfile.ZipFile(buf, "w", compression)) as zipf, tree.lock_read():
            for dp, tp, ie in _export_iter_entries(
                tree, subdir, recurse_nested=recurse_nested
            ):
                mutter("  export {%s} kind %s to %s", tp, ie.kind, dest)

                # zipfile.ZipFile switches all paths to forward
                # slashes anyway, so just stick with that.
                if force_mtime is not None:
                    mtime = force_mtime
                else:
                    mtime = tree.get_file_mtime(tp)
                date_time = time.localtime(mtime)[:6]
                filename = osutils.pathjoin(root, dp)
                if ie.kind == "file":
                    zinfo = zipfile.ZipInfo(filename=filename, date_time=date_time)
                    zinfo.compress_type = compression
                    zinfo.external_attr = _FILE_ATTR
                    content = tree.get_file_text(tp)
                    zipf.writestr(zinfo, content)
                elif ie.kind in ("directory", "tree-reference"):
                    # Directories must contain a trailing slash, to indicate
                    # to the zip routine that they are really directories and
                    # not just empty files.
                    zinfo = zipfile.ZipInfo(
                        filename=filename + "/", date_time=date_time
                    )
                    zinfo.compress_type = compression
                    zinfo.external_attr = _DIR_ATTR
                    zipf.writestr(zinfo, "")
                elif ie.kind == "symlink":
                    zinfo = zipfile.ZipInfo(
                        filename=(filename + ".lnk"), date_time=date_time
                    )
                    zinfo.compress_type = compression
                    zinfo.external_attr = _FILE_ATTR
                    zipf.writestr(zinfo, tree.get_symlink_target(tp))
        # Urgh, headers are written last since they include e.g. file size.
        # So we have to buffer it all :(
        buf.seek(0)
        yield from osutils.file_iterator(buf)
