#    __init__.py -- The plugin for bzr
#    Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk
#
#    This file is part of brz-debian.
#
#    brz-debian is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    brz-debian is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with brz-debian; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import posixpath
from typing import Optional

from debian.changelog import Changelog
from debmutate.changelog import new_changelog_entries, strip_changelog_message

from breezy.errors import BzrError
from breezy.tree import Tree

from . import tree_debian_tag_name


class UnreleasedChanges(BzrError):
    _fmt = "%(path)s says it's UNRELEASED."

    def __init__(self, path):
        BzrError.__init__(self)
        self.path = path


def changelog_changes(
    tree: Tree, basis_tree: Tree, cl_path: str = "debian/changelog"
) -> Optional[list[str]]:
    changes = []
    for change in tree.iter_changes(basis_tree, specific_files=[cl_path]):
        paths = change.path
        changed_content = change.changed_content
        versioned = change.versioned
        kind = change.kind
        # Content not changed
        if not changed_content:
            return None
        # Not versioned in new tree
        if not versioned[1]:
            return None
        # Not a file in one tree
        if kind[0] != "file" or kind[1] != "file":
            return None

        old_text = basis_tree.get_file_lines(paths[0])
        new_text = tree.get_file_lines(paths[1])
        changes.extend(new_changelog_entries(old_text, new_text))
    return changes


def changelog_commit_message(
    tree: Tree, basis_tree: Tree, path: str = "debian/changelog"
) -> Optional[str]:
    changes = changelog_changes(tree, basis_tree, path)
    if not changes:
        return None

    return "".join(strip_changelog_message(changes))


def debcommit(
    tree, committer=None, subpath="", paths=None, reporter=None, message=None
):
    """Create a git commit with message based on the new entries in changelog.

    Args:
      tree: Tree to commit in
      committer: Optional committer identity
      subpath: subpath to commit in
      paths: specifics paths to commit, if any
      reporter: CommitReporter to use
      message: Override commit message
    Returns:
      Created revision id
    """
    if message is None:
        message = changelog_commit_message(
            tree, tree.basis_tree(), path=posixpath.join(subpath, "debian/changelog")
        )
    if paths:
        specific_files = [posixpath.join(subpath, p) for p in paths]
    elif subpath:
        specific_files = [subpath]
    else:
        specific_files = None
    return tree.commit(
        committer=committer,
        message=message,
        specific_files=specific_files,
        reporter=reporter,
    )


def debcommit_release(tree, committer=None, subpath="", message=None, vendor=None):
    cl_path = posixpath.join(subpath, "debian/changelog")
    if message is None or vendor is None:
        cl = Changelog(tree.get_file(cl_path), max_blocks=1)
        if message is None:
            message = f"releasing package {cl[0].package} version {cl[0].version}"
        if vendor is None:
            from .util import suite_to_distribution

            vendor = suite_to_distribution(cl[0].distributions)
    tag_name = tree_debian_tag_name(tree, tree.branch, subpath=subpath, vendor=vendor)
    if tag_name is None:
        raise UnreleasedChanges(cl_path)
    revid = tree.commit(committer=committer, message=message)
    tree.branch.tags.set_tag(tag_name, revid)
    return tag_name
