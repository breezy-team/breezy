# Copyright (C) 2005, 2006 Canonical
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib import errors
from bzrlib.inventory import InventoryEntry
from bzrlib.trace import mutter
from bzrlib.symbol_versioning import deprecated_function, zero_nine


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
        """output this delta in status-like form to to_file."""
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

        extra_modified = []

        if self.renamed:
            print >>to_file, 'renamed:'
            for (oldpath, newpath, fid, kind,
                 text_modified, meta_modified) in self.renamed:
                if text_modified or meta_modified:
                    extra_modified.append((newpath, fid, kind,
                                           text_modified, meta_modified))
                if meta_modified:
                    newpath += '*'
                if show_ids:
                    print >>to_file, '  %s => %s %s' % (oldpath, newpath, fid)
                else:
                    print >>to_file, '  %s => %s' % (oldpath, newpath)
                    
        if self.modified or extra_modified:
            print >>to_file, 'modified:'
            show_list(self.modified)
            show_list(extra_modified)
            
        if show_unchanged and self.unchanged:
            print >>to_file, 'unchanged:'
            show_list(self.unchanged)


@deprecated_function(zero_nine)
def compare_trees(old_tree, new_tree, want_unchanged=False,
                  specific_files=None, extra_trees=None,
                  require_versioned=False):
    """compare_trees was deprecated in 0.10. Please see Tree.changes_from."""
    return new_tree.changes_from(old_tree,
        want_unchanged=want_unchanged,
        specific_files=specific_files,
        extra_trees=extra_trees,
        require_versioned=require_versioned)


def _compare_trees(old_tree, new_tree, want_unchanged, specific_file_ids):

    delta = TreeDelta()
    # mutter('start compare_trees')

    root_id = new_tree.inventory.root.file_id
    for (file_id, path, content_change, versioned, parent_id, name, kind,
         executable) in new_tree.iter_changes(old_tree, want_unchanged, 
                                              specific_file_ids):
        if file_id == root_id:
            continue
        assert kind[0] == kind[1] or None in kind
        # the only 'kind change' permitted is creation/deletion
        fully_present = tuple((versioned[x] and kind[x] is not None) for
                              x in range(2))
        if fully_present[0] != fully_present[1]:
            if fully_present[1] is True:
                delta.added.append((path, file_id, kind[1]))
            else:
                assert fully_present[0] is True
                old_path = old_tree.id2path(file_id)
                delta.removed.append((old_path, file_id, kind[0]))
        elif fully_present[0] is False:
            continue
        elif name[0] != name[1] or parent_id[0] != parent_id[1]:
            # If the name changes, or the parent_id changes, we have a rename
            # (if we move a parent, that doesn't count as a rename for the
            # file)
            old_path = old_tree.id2path(file_id)
            delta.renamed.append((old_path,
                                  path,
                                  file_id, 
                                  kind[1],
                                  content_change, 
                                  (executable[0] != executable[1])))
        elif content_change is True or executable[0] != executable[1]:
            delta.modified.append((path, file_id, kind[1],
                                   content_change, 
                                   (executable[0] != executable[1])))
        else:
            delta.unchanged.append((path, file_id, kind[1]))

    delta.removed.sort()
    delta.added.sort()
    delta.renamed.sort()
    # TODO: jam 20060529 These lists shouldn't need to be sorted
    #       since we added them in alphabetical order.
    delta.modified.sort()
    delta.unchanged.sort()

    return delta
