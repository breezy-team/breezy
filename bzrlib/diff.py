#! /usr/bin/env python
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

from sets import Set

from trace import mutter






def diff_trees(old_tree, new_tree):
    """Compute diff between two trees.

    They may be in different branches and may be working or historical
    trees.

    Yields a sequence of (state, id, old_name, new_name, kind).
    Each filename and each id is listed only once.
    """

    ## TODO: Compare files before diffing; only mention those that have changed

    ## TODO: Set nice names in the headers, maybe include diffstat

    ## TODO: Perhaps make this a generator rather than using
    ## a callback object?

    ## TODO: Allow specifying a list of files to compare, rather than
    ## doing the whole tree?  (Not urgent.)

    ## TODO: Allow diffing any two inventories, not just the
    ## current one against one.  We mgiht need to specify two
    ## stores to look for the files if diffing two branches.  That
    ## might imply this shouldn't be primarily a Branch method.

    ## XXX: This doesn't report on unknown files; that can be done
    ## from a separate method.

    old_it = old_tree.list_files()
    new_it = new_tree.list_files()

    def next(it):
        try:
            return it.next()
        except StopIteration:
            return None

    old_item = next(old_it)
    new_item = next(new_it)

    # We step through the two sorted iterators in parallel, trying to
    # keep them lined up.

    while (old_item != None) or (new_item != None):
        # OK, we still have some remaining on both, but they may be
        # out of step.        
        if old_item != None:
            old_name, old_class, old_kind, old_id = old_item
        else:
            old_name = None
            
        if new_item != None:
            new_name, new_class, new_kind, new_id = new_item
        else:
            new_name = None

        mutter("   diff pairwise %r" % (old_item,))
        mutter("                 %r" % (new_item,))

        if old_item:
            # can't handle the old tree being a WorkingTree
            assert old_class == 'V'

        if new_item and (new_class != 'V'):
            yield new_class, None, None, new_name, new_kind
            new_item = next(new_it)
        elif (not new_item) or (old_item and (old_name < new_name)):
            mutter("     extra entry in old-tree sequence")
            if new_tree.has_id(old_id):
                # will be mentioned as renamed under new name
                pass
            else:
                yield 'D', old_id, old_name, None, old_kind
            old_item = next(old_it)
        elif (not old_item) or (new_item and (new_name < old_name)):
            mutter("     extra entry in new-tree sequence")
            if old_tree.has_id(new_id):
                yield 'R', new_id, old_tree.id2path(new_id), new_name, new_kind
            else:
                yield 'A', new_id, None, new_name, new_kind
            new_item = next(new_it)
        elif old_id != new_id:
            assert old_name == new_name
            # both trees have a file of this name, but it is not the
            # same file.  in other words, the old filename has been
            # overwritten by either a newly-added or a renamed file.
            # (should we return something about the overwritten file?)
            if old_tree.has_id(new_id):
                # renaming, overlying a deleted file
                yield 'R', new_id, old_tree.id2path(new_id), new_name, new_kind
            else:
                yield 'A', new_id, None, new_name, new_kind

            new_item = next(new_it)
            old_item = next(old_it)
        else:
            assert old_id == new_id
            assert old_id != None
            assert old_name == new_name
            assert old_kind == new_kind

            if old_kind == 'directory':
                yield '.', new_id, old_name, new_name, new_kind
            elif old_tree.get_file_size(old_id) != new_tree.get_file_size(old_id):
                mutter("    file size has changed, must be different")
                yield 'M', new_id, old_name, new_name, new_kind
            elif old_tree.get_file_sha1(old_id) == new_tree.get_file_sha1(old_id):
                mutter("      SHA1 indicates they're identical")
                ## assert compare_files(old_tree.get_file(i), new_tree.get_file(i))
                yield '.', new_id, old_name, new_name, new_kind
            else:
                mutter("      quick compare shows different")
                yield 'M', new_id, old_name, new_name, new_kind

            new_item = next(new_it)
            old_item = next(old_it)


