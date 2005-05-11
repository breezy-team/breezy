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
from errors import BzrError


def diff_trees(old_tree, new_tree):
    """Compute diff between two trees.

    They may be in different branches and may be working or historical
    trees.

    This only compares the versioned files, paying no attention to
    files which are ignored or unknown.  Those can only be present in
    working trees and can be reported on separately.

    Yields a sequence of (state, id, old_name, new_name, kind).
    Each filename and each id is listed only once.
    """
    ## TODO: Allow specifying a list of files to compare, rather than
    ## doing the whole tree?  (Not urgent.)

    ## TODO: Allow diffing any two inventories, not just the
    ## current one against one.  We mgiht need to specify two
    ## stores to look for the files if diffing two branches.  That
    ## might imply this shouldn't be primarily a Branch method.

    sha_match_cnt = modified_cnt = 0

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

        if old_item:
            # can't handle the old tree being a WorkingTree
            assert old_class == 'V'

        if new_item and (new_class != 'V'):
            yield new_class, None, None, new_name, new_kind
            new_item = next(new_it)
        elif (not new_item) or (old_item and (old_name < new_name)):
            if new_tree.has_id(old_id):
                # will be mentioned as renamed under new name
                pass
            else:
                yield 'D', old_id, old_name, None, old_kind
            old_item = next(old_it)
        elif (not old_item) or (new_item and (new_name < old_name)):
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
            elif old_tree.get_file_sha1(old_id) == new_tree.get_file_sha1(old_id):
                sha_match_cnt += 1
                yield '.', new_id, old_name, new_name, new_kind
            else:
                modified_cnt += 1
                yield 'M', new_id, old_name, new_name, new_kind

            new_item = next(new_it)
            old_item = next(old_it)


    mutter("diff finished: %d SHA matches, %d modified"
           % (sha_match_cnt, modified_cnt))



def show_diff(b, revision, file_list):
    import difflib, sys, types
    
    if revision == None:
        old_tree = b.basis_tree()
    else:
        old_tree = b.revision_tree(b.lookup_revision(revision))
        
    new_tree = b.working_tree()

    # TODO: Options to control putting on a prefix or suffix, perhaps as a format string
    old_label = ''
    new_label = ''

    DEVNULL = '/dev/null'
    # Windows users, don't panic about this filename -- it is a
    # special signal to GNU patch that the file should be created or
    # deleted respectively.

    # TODO: Generation of pseudo-diffs for added/deleted files could
    # be usefully made into a much faster special case.

    # TODO: Better to return them in sorted order I think.

    if file_list:
        file_list = [b.relpath(f) for f in file_list]

    # FIXME: If given a file list, compare only those files rather
    # than comparing everything and then throwing stuff away.
    
    for file_state, fid, old_name, new_name, kind in diff_trees(old_tree, new_tree):

        if file_list and (new_name not in file_list):
            continue
        
        # Don't show this by default; maybe do it if an option is passed
        # idlabel = '      {%s}' % fid
        idlabel = ''

        def diffit(oldlines, newlines, **kw):
            
            # FIXME: difflib is wrong if there is no trailing newline.
            # The syntax used by patch seems to be "\ No newline at
            # end of file" following the last diff line from that
            # file.  This is not trivial to insert into the
            # unified_diff output and it might be better to just fix
            # or replace that function.

            # In the meantime we at least make sure the patch isn't
            # mangled.
            

            # Special workaround for Python2.3, where difflib fails if
            # both sequences are empty.
            if not oldlines and not newlines:
                return

            nonl = False

            if oldlines and (oldlines[-1][-1] != '\n'):
                oldlines[-1] += '\n'
                nonl = True
            if newlines and (newlines[-1][-1] != '\n'):
                newlines[-1] += '\n'
                nonl = True

            ud = difflib.unified_diff(oldlines, newlines, **kw)

            # work-around for difflib being too smart for its own good
            # if /dev/null is "1,0", patch won't recognize it as /dev/null
            if not oldlines:
                ud = list(ud)
                ud[2] = ud[2].replace('-1,0', '-0,0')
            elif not newlines:
                ud = list(ud)
                ud[2] = ud[2].replace('+1,0', '+0,0')
            
            sys.stdout.writelines(ud)
            if nonl:
                print "\\ No newline at end of file"
            sys.stdout.write('\n')
        
        if file_state in ['.', '?', 'I']:
            continue
        elif file_state == 'A':
            print '*** added %s %r' % (kind, new_name)
            if kind == 'file':
                diffit([],
                       new_tree.get_file(fid).readlines(),
                       fromfile=DEVNULL,
                       tofile=new_label + new_name + idlabel)
        elif file_state == 'D':
            assert isinstance(old_name, types.StringTypes)
            print '*** deleted %s %r' % (kind, old_name)
            if kind == 'file':
                diffit(old_tree.get_file(fid).readlines(), [],
                       fromfile=old_label + old_name + idlabel,
                       tofile=DEVNULL)
        elif file_state in ['M', 'R']:
            if file_state == 'M':
                assert kind == 'file'
                assert old_name == new_name
                print '*** modified %s %r' % (kind, new_name)
            elif file_state == 'R':
                print '*** renamed %s %r => %r' % (kind, old_name, new_name)

            if kind == 'file':
                diffit(old_tree.get_file(fid).readlines(),
                       new_tree.get_file(fid).readlines(),
                       fromfile=old_label + old_name + idlabel,
                       tofile=new_label + new_name)
        else:
            raise BzrError("can't represent state %s {%s}" % (file_state, fid))



class TreeDelta:
    """Describes changes from one tree to another.

    Contains four lists:

    added
        (path, id)
    removed
        (path, id)
    renamed
        (oldpath, newpath, id, text_modified)
    modified
        (path, id)

    Each id is listed only once.

    Files that are both modified and renamed are listed only in
    renamed, with the text_modified flag true.
    """
    def __init__(self):
        self.added = []
        self.removed = []
        self.renamed = []
        self.modified = []

    def show(self, to_file, show_ids):
        if self.removed:
            print >>to_file, 'removed files:'
            for path, fid in self.removed:
                if show_ids:
                    print >>to_file, '  %-30s %s' % (path, fid)
                else:
                    print >>to_file, ' ', path
        if self.added:
            print >>to_file, 'added files:'
            for path, fid in self.added:
                if show_ids:
                    print >>to_file, '  %-30s %s' % (path, fid)
                else:
                    print >>to_file, '  ' + path
        if self.renamed:
            print >>to_file, 'renamed files:'
            for oldpath, newpath, fid, text_modified in self.renamed:
                if show_ids:
                    print >>to_file, '  %s => %s %s' % (oldpath, newpath, fid)
                else:
                    print >>to_file, '  %s => %s' % (oldpath, newpath)
        if self.modified:
            print >>to_file, 'modified files:'
            for path, fid in self.modified:
                if show_ids:
                    print >>to_file, '  %-30s %s' % (path, fid)
                else:
                    print >>to_file, '  ' + path

        

def compare_inventories(old_inv, new_inv):
    """Return a TreeDelta object describing changes between inventories.

    This only describes changes in the shape of the tree, not the
    actual texts.

    This is an alternative to diff_trees() and should probably
    eventually replace it.
    """
    old_ids = old_inv.id_set()
    new_ids = new_inv.id_set()
    delta = TreeDelta()

    delta.removed = [(old_inv.id2path(fid), fid) for fid in (old_ids - new_ids)]
    delta.removed.sort()

    delta.added = [(new_inv.id2path(fid), fid) for fid in (new_ids - old_ids)]
    delta.added.sort()

    for fid in old_ids & new_ids:
        old_ie = old_inv[fid]
        new_ie = new_inv[fid]
        old_path = old_inv.id2path(fid)
        new_path = new_inv.id2path(fid)

        text_modified = (old_ie.text_sha1 != new_ie.text_sha1)

        if old_path != new_path:
            delta.renamed.append((old_path, new_path, fid, text_modified))
        elif text_modified:
            delta.modified.append((new_path, fid))

    delta.modified.sort()
    delta.renamed.sort()    

    return delta




def compare_trees(old_tree, new_tree):
    old_inv = old_tree.inventory
    new_inv = new_tree.inventory
    delta = TreeDelta()
    for file_id in old_inv:
        if file_id in new_inv:
            old_path = old_inv.id2path(file_id)
            new_path = new_inv.id2path(file_id)

            kind = old_inv.get_file_kind(file_id)
            assert kind in ('file', 'directory', 'symlink', 'root_directory'), \
                   'invalid file kind %r' % kind
            if kind == 'file':
                old_sha1 = old_tree.get_file_sha1(file_id)
                new_sha1 = new_tree.get_file_sha1(file_id)
                text_modified = (old_sha1 != new_sha1)
            else:
                ## mutter("no text to check for %r %r" % (file_id, kind))
                text_modified = False
            
            if old_path != new_path:
                delta.renamed.append((old_path, new_path, file_id, text_modified))
            elif text_modified:
                delta.modified.append((new_path, file_id))
        else:
            delta.removed.append((old_inv.id2path(file_id), file_id))
    for file_id in new_inv:
        if file_id in old_inv:
            continue
        delta.added.append((new_inv.id2path(file_id), file_id))
            
    delta.removed.sort()
    delta.added.sort()
    delta.renamed.sort()
    delta.modified.sort()

    return delta
