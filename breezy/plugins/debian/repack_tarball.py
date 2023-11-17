#    repack_tarball.py -- Repack files/dirs in to tarballs.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import bz2
import gzip
import hashlib
import os
import shutil
import tarfile
import time
import zipfile
from io import BytesIO

from ...errors import (
    BzrError,
    DependencyNotPresent,
)
from ...transport import FileExists, get_transport
from .util import open_file, open_file_via_transport


class UnsupportedRepackFormat(BzrError):
    _fmt = (
        'Either the file extension of "%(location)s" indicates that '
        "it is a format unsupported for repacking or it is a "
        "remote directory."
    )

    def __init__(self, location):
        BzrError.__init__(self, location=location)


class TgzRepacker:
    """Repacks something to be a .tar.gz."""

    def __init__(self, source_f):
        """Create a repacker that repacks what is in source_f.

        :param source_f: a file object to read the source from.
        """
        self.source_f = source_f

    def repack(self, target_f):
        """Repacks and writes the repacked tar.gz to target_f.

        target_f should be closed after calling this method.

        :param target_f: a file object to write the result to.
        """
        raise NotImplementedError(self.repack)


class CopyRepacker(TgzRepacker):
    """A Repacker that just copies."""

    def repack(self, target_f):
        shutil.copyfileobj(self.source_f, target_f)


class TarTgzRepacker(TgzRepacker):
    """A TgzRepacker that just gzips the input."""

    def repack(self, target_f):
        with gzip.GzipFile(mode="w", fileobj=target_f) as gz:
            shutil.copyfileobj(self.source_f, gz)


class Tbz2TgzRepacker(TgzRepacker):
    """A TgzRepacker that repacks from a .tar.bz2."""

    def repack(self, target_f):
        content = bz2.decompress(self.source_f.read())
        with gzip.GzipFile(mode="w", fileobj=target_f) as gz:
            gz.write(content)


class TarLzma2TgzRepacker(TgzRepacker):
    """A TgzRepacker that repacks from a .tar.lzma or .tar.xz."""

    def repack(self, target_f):
        try:
            import lzma
        except ImportError as e:
            raise DependencyNotPresent("lzma", e) from e
        content = lzma.decompress(self.source_f.read())
        with gzip.GzipFile(mode="w", fileobj=target_f) as gz:
            gz.write(content)


class ZipTgzRepacker(TgzRepacker):
    """A TgzRepacker that repacks from a .zip file."""

    def _repack_zip_to_tar(self, zip, tar):
        for info in zip.infolist():
            tarinfo = tarfile.TarInfo(info.filename)
            tarinfo.size = info.file_size
            tarinfo.mtime = time.mktime(info.date_time + (0, 1, -1))
            if info.filename.endswith("/"):
                tarinfo.mode = 0o755
                tarinfo.type = tarfile.DIRTYPE
            else:
                tarinfo.mode = 0o644
                tarinfo.type = tarfile.REGTYPE
            contents = BytesIO(zip.read(info.filename))
            tar.addfile(tarinfo, contents)

    def repack(self, target_f):
        with zipfile.ZipFile(self.source_f, "r") as zip, tarfile.open(
            mode="w:gz", fileobj=target_f
        ) as tar:
            self._repack_zip_to_tar(zip, tar)


def get_filetype(filename):
    types = {
        ".tar.gz": "gz",
        ".tgz": "gz",
        ".tar.bz2": "bz2",
        ".tar.xz": "xz",
        ".tar.lzma": "lzma",
        ".tbz2": "bz2",
        ".tar": "tar",
        ".zip": "zip",
    }
    for filetype, name in types.items():
        if filename.endswith(filetype):
            return name


def get_repacker_class(source_format, target_format):
    """Return the appropriate repacker based on the file extension."""
    if source_format == target_format:
        return CopyRepacker
    known_formatters = {
        ("bz2", "gz"): Tbz2TgzRepacker,
        ("lzma", "gz"): TarLzma2TgzRepacker,
        ("xz", "gz"): TarLzma2TgzRepacker,
        ("tar", "gz"): TarTgzRepacker,
        ("zip", "gz"): ZipTgzRepacker,
    }
    return known_formatters.get((source_format, target_format))


def _error_if_exists(target_transport, new_name, source_name):
    with open_file(source_name) as source_f:
        source_sha = hashlib.sha256(source_f.read()).hexdigest()
    with open_file_via_transport(new_name, target_transport) as target_f:
        target_sha = hashlib.sha256(target_f.read()).hexdigest()
    if source_sha != target_sha:
        raise FileExists(new_name)


def _repack_directory(target_transport, new_name, source_name):
    target_transport.ensure_base()
    with target_transport.open_write_stream(new_name) as target_f, tarfile.open(
        mode="w:gz", fileobj=target_f
    ) as tar:
        tar.add(source_name, os.path.basename(source_name))


def _repack_other(target_transport, new_name, source_name):
    source_filetype = get_filetype(source_name)
    target_filetype = get_filetype(new_name)
    repacker_cls = get_repacker_class(source_filetype, target_filetype)
    if repacker_cls is None:
        raise UnsupportedRepackFormat(source_name)
    target_transport.ensure_base()
    with target_transport.open_write_stream(new_name) as target_f, open_file(
        source_name
    ) as source_f:
        repacker = repacker_cls(source_f)
        repacker.repack(target_f)


def repack_tarball(source_name, new_name, target_dir=None):
    """Repack the file/dir named to a .tar.gz with the chosen name.

    This function takes a named file of either .tar.gz, .tar .tgz .tar.bz2
    or .zip type, or a directory, and creates the file named in the second
    argument in .tar.gz format.

    If target_dir is specified then that directory will be created if it
    doesn't exist, and the new_name will be interpreted relative to that
    directory.

    The source must exist, and the target cannot exist, unless it is identical
    to the source.

    :param source_name: the current name of the file/dir
    :type source_name: string
    :param new_name: the desired name of the tarball
    :type new_name: string
    :keyword target_dir: the directory to consider new_name relative to, and
                         will be created if non-existant.
    :type target_dir: string
    :return: None
    :throws NoSuchFile: if source_name doesn't exist.
    :throws FileExists: if the target filename (after considering target_dir)
                        exists, and is not identical to the source.
    :throws BzrCommandError: if the source isn't supported for repacking.
    """
    if target_dir is None:
        target_dir = "."
    extra, new_name = os.path.split(new_name)
    target_transport = get_transport(os.path.join(target_dir, extra))
    if target_transport.has(new_name):
        source_format = get_filetype(source_name)
        target_format = get_filetype(new_name)
        if source_format != target_format:
            raise FileExists(new_name)
        _error_if_exists(target_transport, new_name, source_name)
        return
    if os.path.isdir(source_name):
        _repack_directory(target_transport, new_name, source_name)
    else:
        _repack_other(target_transport, new_name, source_name)
