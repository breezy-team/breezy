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


def changelog_changes(tree, basis_tree, cl_path='debian/changelog'):
    changes = []
    for change in tree.iter_changes(
            basis_tree, specific_files=[cl_path]):
        # Content not changed
        if not change[2]:
            return None
        # Not versioned in new tree
        if not change[3][1]:
            return None
        # Not a file in one tree
        if change[6][0] != 'file' or change[6][1] != 'file':
            return None
        old_text = basis_tree.get_file_lines(change[1][0])
        new_text = tree.get_file_lines(change[1][1])
        import difflib
        sequencematcher = difflib.SequenceMatcher
        for group in sequencematcher(
                None, old_text, new_text).get_grouped_opcodes(0):
            j1, j2 = group[0][3], group[-1][4]
            for line in new_text[j1:j2]:
                if line.startswith(b"  "):
                    # Debian Policy Manual states that debian/changelog must be
                    # UTF-8
                    changes.append(line.decode('utf-8'))
    return changes


def changelog_commit_message(tree, basis_tree, path='debian/changelog'):
    changes = changelog_changes(tree, basis_tree, path)
    if not changes:
        return None

    from .util import strip_changelog_message
    return ''.join(strip_changelog_message(changes))
