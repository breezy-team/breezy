# Copyright (C) 2006-2012 Aaron Bentley
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

"""Import upstream source into a branch."""

import errno
import os
import re
import stat
import tarfile
import zipfile
from io import BytesIO

from . import urlutils
from .bzr import generate_ids
from .controldir import ControlDir, is_control_filename
from .errors import BzrError, CommandError, NotBranchError
from .osutils import basename, file_iterator, file_kind, isdir, pathjoin, splitpath
from .trace import warning
from .transform import resolve_conflicts
from .transport import NoSuchFile, get_transport
from .workingtree import WorkingTree


# TODO(jelmer): Move this to transport.py ?
def open_from_url(location):
    location = urlutils.normalize_url(location)
    dirname, basename = urlutils.split(location)
    if location.endswith("/") and not basename.endswith("/"):
        basename += "/"
    return get_transport(dirname).get(basename)


class NotArchiveType(BzrError):
    _fmt = "%(path)s is not an archive."

    def __init__(self, path):
        BzrError.__init__(self)
        self.path = path


class ZipFileWrapper:
    def __init__(self, fileobj, mode):
        self.zipfile = zipfile.ZipFile(fileobj, mode)

    def getmembers(self):
        for info in self.zipfile.infolist():
            yield ZipInfoWrapper(self.zipfile, info)

    def extractfile(self, infowrapper):
        return BytesIO(self.zipfile.read(infowrapper.name))

    def add(self, filename):
        if isdir(filename):
            self.zipfile.writestr(filename + "/", "")
        else:
            self.zipfile.write(filename)

    def close(self):
        self.zipfile.close()


class ZipInfoWrapper:
    def __init__(self, zipfile, info):
        self.info = info
        self.type = None
        self.name = info.filename
        self.zipfile = zipfile
        self.mode = 0o666

    def isdir(self):
        # Really? Eeeew!
        return bool(self.name.endswith("/"))

    def isreg(self):
        # Really? Eeeew!
        return not self.isdir()


class DirWrapper:
    def __init__(self, fileobj, mode="r"):
        if mode != "r":
            raise AssertionError("only readonly supported")
        self.root = os.path.realpath(fileobj.read().decode("utf-8"))

    def __repr__(self):
        return "DirWrapper({!r})".format(self.root)

    def getmembers(self, subdir=None):
        if subdir is not None:
            mydir = pathjoin(self.root, subdir)
        else:
            mydir = self.root
        for child in os.listdir(mydir):
            if subdir is not None:
                child = pathjoin(subdir, child)
            fi = FileInfo(self.root, child)
            yield fi
            if fi.isdir():
                yield from self.getmembers(child)

    def extractfile(self, member):
        return open(member.fullpath, "rb")


class FileInfo:
    def __init__(self, root, filepath):
        self.fullpath = pathjoin(root, filepath)
        self.root = root
        if filepath != "":
            self.name = pathjoin(basename(root), filepath)
        else:
            print("root {!r}".format(root))
            self.name = basename(root)
        self.type = None
        stat = os.lstat(self.fullpath)
        self.mode = stat.st_mode
        if self.isdir():
            self.name += "/"

    def __repr__(self):
        return "FileInfo({!r})".format(self.name)

    def isreg(self):
        return stat.S_ISREG(self.mode)

    def isdir(self):
        return stat.S_ISDIR(self.mode)

    def issym(self):
        if stat.S_ISLNK(self.mode):
            self.linkname = os.readlink(self.fullpath)
            return True
        else:
            return False


def top_path(path):
    """Return the top directory given in a path."""
    components = splitpath(path)
    if len(components) > 0:
        return components[0]
    else:
        return ""


def common_directory(names):
    """Determine a single directory prefix from a list of names."""
    possible_prefix = None
    for name in names:
        name_top = top_path(name)
        if name_top == "":
            return None
        if possible_prefix is None:
            possible_prefix = name_top
        else:
            if name_top != possible_prefix:
                return None
    return possible_prefix


def do_directory(tt, trans_id, tree, relative_path, path):
    if isdir(path) and tree.is_versioned(relative_path):
        tt.cancel_deletion(trans_id)
    else:
        tt.create_directory(trans_id)


def add_implied_parents(implied_parents, path):
    """Update the set of implied parents from a path."""
    parent = os.path.dirname(path)
    if parent in implied_parents:
        return
    implied_parents.add(parent)
    add_implied_parents(implied_parents, parent)


def names_of_files(tar_file):
    for member in tar_file.getmembers():
        if member.type != "g":
            yield member.name


def should_ignore(relative_path):
    return is_control_filename(top_path(relative_path))


def import_tar(tree, tar_input):
    """Replace the contents of a working directory with tarfile contents.
    The tarfile may be a gzipped stream.  File ids will be updated.
    """
    tar_file = tarfile.open("lala", "r", tar_input)
    import_archive(tree, tar_file)


def import_zip(tree, zip_input):
    zip_file = ZipFileWrapper(zip_input, "r")
    import_archive(tree, zip_file)


def import_dir(tree, dir_input):
    dir_file = DirWrapper(dir_input)
    import_archive(tree, dir_file)


def import_archive(tree, archive_file):
    with tree.transform() as tt:
        import_archive_to_transform(tree, archive_file, tt)
        tt.apply()


def import_archive_to_transform(tree, archive_file, tt):
    prefix = common_directory(names_of_files(archive_file))
    removed = set()
    for path, entry in tree.iter_entries_by_dir():
        if entry.parent_id is None:
            continue
        trans_id = tt.trans_id_tree_path(path)
        tt.delete_contents(trans_id)
        removed.add(path)

    added = set()
    implied_parents = set()
    seen = set()
    for member in archive_file.getmembers():
        if member.type == "g":
            # type 'g' is a header
            continue
        # Inverse functionality in bzr uses utf-8.  We could also
        # interpret relative to fs encoding, which would match native
        # behaviour better.
        relative_path = member.name
        if not isinstance(relative_path, str):
            relative_path = relative_path.decode("utf-8")
        if prefix is not None:
            relative_path = relative_path[len(prefix) + 1 :]
            relative_path = relative_path.rstrip("/")
        if relative_path == "":
            continue
        if should_ignore(relative_path):
            continue
        add_implied_parents(implied_parents, relative_path)
        trans_id = tt.trans_id_tree_path(relative_path)
        added.add(relative_path.rstrip("/"))
        path = tree.abspath(relative_path)
        if member.name in seen:
            if tt.final_kind(trans_id) == "file":
                tt.set_executability(None, trans_id)
            tt.cancel_creation(trans_id)
        seen.add(member.name)
        if member.isreg():
            tt.create_file(file_iterator(archive_file.extractfile(member)), trans_id)
            executable = (member.mode & 0o111) != 0
            tt.set_executability(executable, trans_id)
        elif member.isdir():
            do_directory(tt, trans_id, tree, relative_path, path)
        elif member.issym():
            tt.create_symlink(member.linkname, trans_id)
        else:
            continue
        if not tt.final_is_versioned(trans_id):
            name = basename(member.name.rstrip("/"))
            file_id = generate_ids.gen_file_id(name)
            tt.version_file(trans_id, file_id=file_id)

    for relative_path in implied_parents.difference(added):
        if relative_path == "":
            continue
        trans_id = tt.trans_id_tree_path(relative_path)
        path = tree.abspath(relative_path)
        do_directory(tt, trans_id, tree, relative_path, path)
        if tt.tree_file_id(trans_id) is None:
            tt.version_file(trans_id, file_id=trans_id)
        added.add(relative_path)

    for path in removed.difference(added):
        tt.unversion_file(tt.trans_id_tree_path(path))

    for conflict in tt.cook_conflicts(resolve_conflicts(tt)):
        warning(conflict)


def do_import(source, tree_directory=None):
    """Implementation of import command.  Intended for UI only."""
    if tree_directory is not None:
        try:
            tree = WorkingTree.open(tree_directory)
        except NotBranchError:
            if not os.path.exists(tree_directory):
                os.mkdir(tree_directory)
            branch = ControlDir.create_branch_convenience(tree_directory)
            tree = branch.controldir.open_workingtree()
    else:
        tree = WorkingTree.open_containing(".")[0]
    with tree.lock_write():
        if tree.changes_from(tree.basis_tree()).has_changed():
            raise CommandError("Working tree has uncommitted changes.")

        try:
            archive, external_compressor = get_archive_type(source)
        except NotArchiveType:
            if file_kind(source) == "directory":
                s = BytesIO(source.encode("utf-8"))
                s.seek(0)
                import_dir(tree, s)
            else:
                raise CommandError("Unhandled import source")
        else:
            if archive == "zip":
                import_zip(tree, open_from_url(source))
            elif archive == "tar":
                try:
                    tar_input = open_from_url(source)
                    if external_compressor == "bz2":
                        import bz2

                        tar_input = BytesIO(bz2.decompress(tar_input.read()))
                    elif external_compressor == "lzma":
                        import lzma

                        tar_input = BytesIO(lzma.decompress(tar_input.read()))
                except OSError as e:
                    if e.errno == errno.ENOENT:
                        raise NoSuchFile(source)
                try:
                    import_tar(tree, tar_input)
                finally:
                    tar_input.close()


def get_archive_type(path):
    """Return the type of archive and compressor indicated by path name.

    Only external compressors are returned, so zip files are only
    ('zip', None).  .tgz is treated as ('tar', 'gz') and '.tar.xz' is treated
    as ('tar', 'lzma').
    """
    matches = re.match(r".*\.(zip|tgz|tar(.(gz|bz2|lzma|xz))?)$", path)
    if not matches:
        raise NotArchiveType(path)
    external_compressor = None
    if matches.group(3) is not None:
        archive = "tar"
        external_compressor = matches.group(3)
        if external_compressor == "xz":
            external_compressor = "lzma"
    elif matches.group(1) == "tgz":
        return "tar", "gz"
    else:
        archive = matches.group(1)
    return archive, external_compressor
