# -*- coding: UTF-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.inventory import InventoryEntry
from bzrlib.trace import mutter

class TreeDelta(object):
    """Describes changes from one tree to another.

    Contains four lists:

    added
        (path, id, kind)
    removed
        (path, id, kind)
    renamed
        (oldpath, newpath, id, kind, text_modified, meta_modified)
    modified
        (path, id, kind, text_modified, meta_modified)
    unchanged
        (path, id, kind)

    Each id is listed only once.

    Files that are both modified and renamed are listed only in
    renamed, with the text_modified flag true. The text_modified
    applies either to the the content of the file or the target of the
    symbolic link, depending of the kind of file.

    Files are only considered renamed if their name has changed or
    their parent directory has changed.  Renaming a directory
    does not count as renaming all its contents.

    The lists are normally sorted when the delta is created.
    """
    def __init__(self):
        self.added = []
        self.removed = []
        self.renamed = []
        self.modified = []
        self.unchanged = []

    def __eq__(self, other):
        if not isinstance(other, TreeDelta):
            return False
        return self.added == other.added \
               and self.removed == other.removed \
               and self.renamed == other.renamed \
               and self.modified == other.modified \
               and self.unchanged == other.unchanged

    def __ne__(self, other):
        return not (self == other)

    def __repr__(self):
        return "TreeDelta(added=%r, removed=%r, renamed=%r, modified=%r," \
            " unchanged=%r)" % (self.added, self.removed, self.renamed,
            self.modified, self.unchanged)

    def has_changed(self):
        return bool(self.modified
                    or self.added
                    or self.removed
                    or self.renamed)

    def touches_file_id(self, file_id):
        """Return True if file_id is modified by this delta."""
        for l in self.added, self.removed, self.modified:
            for v in l:
                if v[1] == file_id:
                    return True
        for v in self.renamed:
            if v[2] == file_id:
                return True
        return False
            

    def show(self, to_file, show_ids=False, show_unchanged=False):
        def show_list(files):
            for item in files:
                path, fid, kind = item[:3]

                if kind == 'directory':
                    path += '/'
                elif kind == 'symlink':
                    path += '@'

                if len(item) == 5 and item[4]:
                    path += '*'

                if show_ids:
                    print >>to_file, '  %-30s %s' % (path, fid)
                else:
                    print >>to_file, ' ', path
            
        if self.removed:
            print >>to_file, 'removed:'
            show_list(self.removed)
                
        if self.added:
            print >>to_file, 'added:'
            show_list(self.added)

        if self.renamed:
            print >>to_file, 'renamed:'
            for (oldpath, newpath, fid, kind,
                 text_modified, meta_modified) in self.renamed:
                if meta_modified:
                    newpath += '*'
                if show_ids:
                    print >>to_file, '  %s => %s %s' % (oldpath, newpath, fid)
                else:
                    print >>to_file, '  %s => %s' % (oldpath, newpath)
                    
        if self.modified:
            print >>to_file, 'modified:'
            show_list(self.modified)
            
        if show_unchanged and self.unchanged:
            print >>to_file, 'unchanged:'
            show_list(self.unchanged)



def compare_trees(old_tree, new_tree, want_unchanged=False, specific_files=None):
    """Describe changes from one tree to another.

    Returns a TreeDelta with details of added, modified, renamed, and
    deleted entries.

    The root entry is specifically exempt.

    This only considers versioned files.

    want_unchanged
        If true, also list files unchanged from one version to
        the next.

    specific_files
        If true, only check for changes to specified names or
        files within them.
    """

    from osutils import is_inside_any
    
    old_inv = old_tree.inventory
    new_inv = new_tree.inventory
    delta = TreeDelta()
    mutter('start compare_trees')

    # TODO: match for specific files can be rather smarter by finding
    # the IDs of those files up front and then considering only that.

    for file_id in old_tree:
        if file_id in new_tree:
            old_ie = old_inv[file_id]
            new_ie = new_inv[file_id]

            kind = old_ie.kind
            assert kind == new_ie.kind
            
            assert kind in InventoryEntry.known_kinds, \
                   'invalid file kind %r' % kind

            if kind == 'root_directory':
                continue
            
            if specific_files:
                if (not is_inside_any(specific_files, old_inv.id2path(file_id)) 
                    and not is_inside_any(specific_files, new_inv.id2path(file_id))):
                    continue

            # temporary hack until all entries are populated before clients 
            # get them
            old_path = old_inv.id2path(file_id)
            new_path = new_inv.id2path(file_id)
            old_ie._read_tree_state(old_path, old_tree)
            new_ie._read_tree_state(new_path, new_tree)
            text_modified, meta_modified = new_ie.detect_changes(old_ie)

            # TODO: Can possibly avoid calculating path strings if the
            # two files are unchanged and their names and parents are
            # the same and the parents are unchanged all the way up.
            # May not be worthwhile.
            
            if (old_ie.name != new_ie.name
                or old_ie.parent_id != new_ie.parent_id):
                delta.renamed.append((old_path,
                                      new_path,
                                      file_id, kind,
                                      text_modified, meta_modified))
            elif text_modified or meta_modified:
                delta.modified.append((new_path, file_id, kind,
                                       text_modified, meta_modified))
            elif want_unchanged:
                delta.unchanged.append((new_path, file_id, kind))
        else:
            kind = old_inv.get_file_kind(file_id)
            if kind == 'root_directory':
                continue
            old_path = old_inv.id2path(file_id)
            if specific_files:
                if not is_inside_any(specific_files, old_path):
                    continue
            delta.removed.append((old_path, file_id, kind))

    mutter('start looking for new files')
    for file_id in new_inv:
        if file_id in old_inv:
            continue
        kind = new_inv.get_file_kind(file_id)
        if kind == 'root_directory':
            continue
        new_path = new_inv.id2path(file_id)
        if specific_files:
            if not is_inside_any(specific_files, new_path):
                continue
        delta.added.append((new_path, file_id, kind))
            
    delta.removed.sort()
    delta.added.sort()
    delta.renamed.sort()
    delta.modified.sort()
    delta.unchanged.sort()

    return delta
