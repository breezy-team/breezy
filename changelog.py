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

from typing import List, Optional

from breezy.tree import Tree
from debmutate.changelog import new_changelog_entries


def changelog_changes(
        tree: Tree, basis_tree: Tree,
        cl_path: str = 'debian/changelog') -> List[str]:
    changes = []
    for change in tree.iter_changes(
            basis_tree, specific_files=[cl_path]):
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
        if kind[0] != 'file' or kind[1] != 'file':
            return None

        old_text = basis_tree.get_file_lines(paths[0])
        new_text = tree.get_file_lines(paths[1])
        changes.extend(new_changelog_entries(old_text, new_text))
    return changes


def changelog_commit_message(
        tree: Tree, basis_tree: Tree,
        path: str = 'debian/changelog') -> Optional[str]:
    changes = changelog_changes(tree, basis_tree, path)
    if not changes:
        return None

    from .util import strip_changelog_message
    return ''.join(strip_changelog_message(changes))
