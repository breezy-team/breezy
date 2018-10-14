# This file is a modified copy of bzrtools' upstream_import.py, last changed in
# bzrtools 1.14.0.

"""Import upstream source into a branch"""

from __future__ import absolute_import

import errno
import os
from io import BytesIO
import tarfile

from ...upstream_import import (
    add_implied_parents,
    common_directory,
    do_directory,
    names_of_files,
    DirWrapper,
    ZipFileWrapper,
    )
from ... import generate_ids
from ... import urlutils
from ...controldir import ControlDir
from ...errors import NoSuchFile, BzrCommandError, NotBranchError
from ...osutils import file_iterator, basename, file_kind, splitpath, normpath
from ...sixish import StringIO
from ...trace import warning
from ...transform import TreeTransform, resolve_conflicts, cook_conflicts
from ...transport import get_transport
from ...workingtree import WorkingTree
from .errors import UnknownType


def open_from_url(location):
    location = urlutils.normalize_url(location)
    dirname, basename = urlutils.split(location)
    if location.endswith('/') and not basename.endswith('/'):
        basename += '/'
    return get_transport(dirname).get(basename)


files_to_ignore = set(
    ['.shelf', '.bzr', '.bzr.backup', '.bzrtags',
     '.bzr-builddeb'])


def should_ignore(relative_path):
    parts = splitpath(relative_path)
    if not parts:
        return False
    for part in parts:
        if part in files_to_ignore:
            return True
        if part.endswith(',v'):
            return True


def import_tar(tree, tar_input, file_ids_from=None, target_tree=None):
    """Replace the contents of a working directory with tarfile contents.
    The tarfile may be a gzipped stream.  File ids will be updated.
    """
    tar_file = tarfile.open('lala', 'r', tar_input)
    import_archive(tree, tar_file, file_ids_from=file_ids_from,
            target_tree=target_tree)

def import_zip(tree, zip_input, file_ids_from=None, target_tree=None):
    zip_file = ZipFileWrapper(zip_input, 'r')
    import_archive(tree, zip_file, file_ids_from=file_ids_from,
            target_tree=target_tree)

def import_dir(tree, dir, file_ids_from=None, target_tree=None):
    dir_input = BytesIO(dir.encode('utf-8'))
    dir_input.seek(0)
    dir_file = DirWrapper(dir_input)
    import_archive(tree, dir_file, file_ids_from=file_ids_from,
            target_tree=target_tree)

def import_archive(tree, archive_file, file_ids_from=None, target_tree=None):
    if file_ids_from is None:
        file_ids_from = []
    for other_tree in file_ids_from:
        other_tree.lock_read()
    try:
        return _import_archive(tree, archive_file, file_ids_from,
                target_tree=target_tree)
    finally:
        for other_tree in file_ids_from:
            other_tree.unlock()

def _get_paths_to_process(archive_file, prefix, implied_parents):
    to_process = set()
    for member in archive_file.getmembers():
        if member.type == 'g':
            # type 'g' is a header
            continue
        relative_path = member.name
        relative_path = normpath(relative_path)
        relative_path = relative_path.lstrip('/')
        if prefix is not None:
            relative_path = relative_path[len(prefix)+1:]
            relative_path = relative_path.rstrip('/')
        if relative_path == '' or relative_path == '.':
            continue
        if should_ignore(relative_path):
            continue
        add_implied_parents(implied_parents, relative_path)
        to_process.add((relative_path, member))
    return to_process


def _import_archive(tree, archive_file, file_ids_from, target_tree=None):
    prefix = common_directory(names_of_files(archive_file))
    tt = TreeTransform(tree)
    try:
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
        to_process = _get_paths_to_process(archive_file, prefix,
                implied_parents)
        renames = {}

        # First we find the renames
        other_trees = file_ids_from[:]
        if target_tree is not None:
            other_trees.insert(0, target_tree)
        for other_tree in other_trees:
            for relative_path, member in to_process:
                trans_id = tt.trans_id_tree_path(relative_path)
                existing_file_id = tt.tree_file_id(trans_id)
                target_id = other_tree.path2id(relative_path)
                if (target_id is not None
                    and target_id != existing_file_id
                    and target_id not in renames):
                    renames[target_id] = relative_path

        # The we do the work
        for relative_path, member in to_process:
            trans_id = tt.trans_id_tree_path(relative_path)
            added.add(relative_path.rstrip('/'))
            # To handle renames, we need to not use the preserved file id, rather
            # we need to lookup the file id in target_tree, if there is one. If
            # there isn't, we should use the one in the current tree, and failing
            # that we will allocate one. In this importer we want the
            # target_tree to be authoritative about id2path, which is why we
            # consult it first.
            existing_file_id = tt.tree_file_id(trans_id)
            # If we find an id that we know we are going to assign to
            # different path as it has been renamed in one of the
            # file_ids_from trees then we ignore the one in this tree.
            if existing_file_id in renames:
                if relative_path != renames[existing_file_id]:
                    existing_file_id = None
            found_file_id = None
            if target_tree is not None:
                found_file_id = target_tree.path2id(relative_path)
                if found_file_id in renames:
                    if renames[found_file_id] != relative_path:
                        found_file_id = None
            if found_file_id is None and existing_file_id is None:
                for other_tree in file_ids_from:
                    found_file_id = other_tree.path2id(relative_path)
                    if found_file_id is not None:
                        if found_file_id in renames:
                            if renames[found_file_id] != relative_path:
                                found_file_id = None
                                continue
                        break
            if (found_file_id is not None
                and found_file_id != existing_file_id):
                # Found a specific file id in one of the source trees
                tt.version_file(found_file_id, trans_id)
                if existing_file_id is not None:
                    # We need to remove the existing file so it can be
                    # replaced by the file (and file id) from the
                    # file_ids_from tree.
                    tt.delete_versioned(trans_id)
                trans_id = tt.trans_id_file_id(found_file_id)

            if not found_file_id and not existing_file_id:
                # No file_id in any of the source trees and no file id in the base
                # tree.
                name = basename(member.name.rstrip('/'))
                file_id = generate_ids.gen_file_id(name)
                tt.version_file(file_id, trans_id)
            path = tree.abspath(relative_path)
            if member.name in seen:
                if tt.final_kind(trans_id) == 'file':
                    tt.set_executability(None, trans_id)
                tt.cancel_creation(trans_id)
            seen.add(member.name)
            if member.isreg():
                tt.create_file(file_iterator(archive_file.extractfile(member)),
                               trans_id)
                executable = (member.mode & 0o111) != 0
                tt.set_executability(executable, trans_id)
            elif member.isdir():
                do_directory(tt, trans_id, tree, relative_path, path)
            elif member.issym():
                tt.create_symlink(member.linkname, trans_id)
            else:
                raise UnknownType(relative_path)

        for relative_path in implied_parents.difference(added):
            if relative_path == "":
                continue
            trans_id = tt.trans_id_tree_path(relative_path)
            path = tree.abspath(relative_path)
            do_directory(tt, trans_id, tree, relative_path, path)
            if tt.tree_file_id(trans_id) is None:
                found = False
                for other_tree in file_ids_from:
                    with other_tree.lock_read():
                        if other_tree.has_filename(relative_path):
                            file_id = other_tree.path2id(relative_path)
                            if file_id is not None:
                                tt.version_file(file_id, trans_id)
                                found = True
                                break
                if not found:
                    # Should this really use the trans_id as the
                    # file_id?
                    tt.version_file(trans_id, trans_id)
            added.add(relative_path)

        for path in removed.difference(added):
            tt.unversion_file(tt.trans_id_tree_path(path))

        for conflict in cook_conflicts(resolve_conflicts(tt), tt):
            warning('%s', conflict)
        tt.apply()
    finally:
        tt.finalize()


def do_import(source, tree_directory=None):
    """Implementation of import command.  Intended for UI only"""
    if tree_directory is not None:
        try:
            tree = WorkingTree.open(tree_directory)
        except NotBranchError:
            if not os.path.exists(tree_directory):
                os.mkdir(tree_directory)
            branch = ControlDir.create_branch_convenience(tree_directory)
            tree = branch.controldir.open_workingtree()
    else:
        tree = WorkingTree.open_containing('.')[0]
    with tree.lock_write():
        if tree.changes_from(tree.basis_tree()).has_changed():
            raise BzrCommandError("Working tree has uncommitted changes.")

        if (source.endswith('.tar') or source.endswith('.tar.gz') or
            source.endswith('.tar.bz2')) or source.endswith('.tgz'):
            try:
                tar_input = open_from_url(source)
                if source.endswith('.bz2'):
                    tar_input = BytesIO(tar_input.read().decode('bz2'))
            except IOError as e:
                if e.errno == errno.ENOENT:
                    raise NoSuchFile(source)
            try:
                import_tar(tree, tar_input)
            finally:
                tar_input.close()
        elif source.endswith('.zip'):
            import_zip(tree, open_from_url(source))
        elif file_kind(source) == 'directory':
            import_dir(tree, source)
        else:
            raise BzrCommandError('Unhandled import source')
