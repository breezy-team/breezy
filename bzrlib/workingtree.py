# Copyright (C) 2005 Canonical Ltd

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

"""WorkingTree object and friends.

A WorkingTree represents the editable working copy of a branch.
Operations which represent the WorkingTree are also done here, 
such as renaming or adding files.  The WorkingTree has an inventory 
which is updated by these operations.  A commit produces a 
new revision based on the workingtree and its inventory.

At the moment every WorkingTree has its own branch.  Remote
WorkingTrees aren't supported.

To get a WorkingTree, call Branch.working_tree():
"""


# TODO: Don't allow WorkingTrees to be constructed for remote branches if 
# they don't work.

# FIXME: I don't know if writing out the cache from the destructor is really a
# good idea, because destructors are considered poor taste in Python, and it's
# not predictable when it will be written out.

# TODO: Give the workingtree sole responsibility for the working inventory;
# remove the variable and references to it from the branch.  This may require
# updating the commit code so as to update the inventory within the working
# copy, and making sure there's only one WorkingTree for any directory on disk.
# At the momenthey may alias the inventory and have old copies of it in memory.

import os
import stat
import fnmatch
 
from bzrlib.branch import Branch, needs_read_lock, needs_write_lock, quotefn
import bzrlib.tree
from bzrlib.osutils import appendpath, file_kind, isdir, splitpath, relpath
from bzrlib.errors import BzrCheckError, DivergedBranches, NotVersionedError
from bzrlib.trace import mutter


class TreeEntry(object):
    """An entry that implements the minium interface used by commands.

    This needs further inspection, it may be better to have 
    InventoryEntries without ids - though that seems wrong. For now,
    this is a parallel hierarchy to InventoryEntry, and needs to become
    one of several things: decorates to that hierarchy, children of, or
    parents of it.
    Another note is that these objects are currently only used when there is
    no InventoryEntry available - i.e. for unversioned objects.
    Perhaps they should be UnversionedEntry et al. ? - RBC 20051003
    """
 
    def __eq__(self, other):
        # yes, this us ugly, TODO: best practice __eq__ style.
        return (isinstance(other, TreeEntry)
                and other.__class__ == self.__class__)
 
    def kind_character(self):
        return "???"


class TreeDirectory(TreeEntry):
    """See TreeEntry. This is a directory in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeDirectory)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return "/"


class TreeFile(TreeEntry):
    """See TreeEntry. This is a regular file in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeFile)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return ''


class TreeLink(TreeEntry):
    """See TreeEntry. This is a symlink in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeLink)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return ''


class WorkingTree(bzrlib.tree.Tree):
    """Working copy tree.

    The inventory is held in the `Branch` working-inventory, and the
    files are in a directory on disk.

    It is possible for a `WorkingTree` to have a filename which is
    not listed in the Inventory and vice versa.
    """

    def __init__(self, basedir, branch=None):
        """Construct a WorkingTree for basedir.

        If the branch is not supplied, it is opened automatically.
        If the branch is supplied, it must be the branch for this basedir.
        (branch.base is not cross checked, because for remote branches that
        would be meaningless).
        """
        from bzrlib.hashcache import HashCache
        from bzrlib.trace import note, mutter
        assert isinstance(basedir, basestring), \
            "base directory %r is not a string" % basedir
        if branch is None:
            branch = Branch.open(basedir)
        assert isinstance(branch, Branch), \
            "branch %r is not a Branch" % branch
        self._inventory = branch.inventory
        self.path2id = self._inventory.path2id
        self.branch = branch
        self.basedir = basedir

        # update the whole cache up front and write to disk if anything changed;
        # in the future we might want to do this more selectively
        hc = self._hashcache = HashCache(basedir)
        hc.read()
        hc.scan()

        if hc.needs_write:
            mutter("write hc")
            hc.write()
            
            
    def __del__(self):
        if self._hashcache.needs_write:
            self._hashcache.write()


    def __iter__(self):
        """Iterate through file_ids for this tree.

        file_ids are in a WorkingTree if they are in the working inventory
        and the working file exists.
        """
        inv = self._inventory
        for path, ie in inv.iter_entries():
            if bzrlib.osutils.lexists(self.abspath(path)):
                yield ie.file_id


    def __repr__(self):
        return "<%s of %s>" % (self.__class__.__name__,
                               getattr(self, 'basedir', None))



    def abspath(self, filename):
        return os.path.join(self.basedir, filename)

    def relpath(self, abspath):
        """Return the local path portion from a given absolute path."""
        return relpath(self.basedir, abspath)

    def has_filename(self, filename):
        return bzrlib.osutils.lexists(self.abspath(filename))

    def get_file(self, file_id):
        return self.get_file_byname(self.id2path(file_id))

    def get_file_byname(self, filename):
        return file(self.abspath(filename), 'rb')

    def _get_store_filename(self, file_id):
        ## XXX: badly named; this isn't in the store at all
        return self.abspath(self.id2path(file_id))


    def id2abspath(self, file_id):
        return self.abspath(self.id2path(file_id))

                
    def has_id(self, file_id):
        # files that have been deleted are excluded
        inv = self._inventory
        if not inv.has_id(file_id):
            return False
        path = inv.id2path(file_id)
        return bzrlib.osutils.lexists(self.abspath(path))

    def has_or_had_id(self, file_id):
        if file_id == self.inventory.root.file_id:
            return True
        return self.inventory.has_id(file_id)

    __contains__ = has_id
    

    def get_file_size(self, file_id):
        return os.path.getsize(self.id2abspath(file_id))

    def get_file_sha1(self, file_id):
        path = self._inventory.id2path(file_id)
        return self._hashcache.get_sha1(path)


    def is_executable(self, file_id):
        if os.name == "nt":
            return self._inventory[file_id].executable
        else:
            path = self._inventory.id2path(file_id)
            mode = os.lstat(self.abspath(path)).st_mode
            return bool(stat.S_ISREG(mode) and stat.S_IEXEC&mode)

    def get_symlink_target(self, file_id):
        return os.readlink(self.id2abspath(file_id))

    def file_class(self, filename):
        if self.path2id(filename):
            return 'V'
        elif self.is_ignored(filename):
            return 'I'
        else:
            return '?'


    def list_files(self):
        """Recursively list all files as (path, class, kind, id).

        Lists, but does not descend into unversioned directories.

        This does not include files that have been deleted in this
        tree.

        Skips the control directory.
        """
        inv = self._inventory

        def descend(from_dir_relpath, from_dir_id, dp):
            ls = os.listdir(dp)
            ls.sort()
            for f in ls:
                ## TODO: If we find a subdirectory with its own .bzr
                ## directory, then that is a separate tree and we
                ## should exclude it.
                if bzrlib.BZRDIR == f:
                    continue

                # path within tree
                fp = appendpath(from_dir_relpath, f)

                # absolute path
                fap = appendpath(dp, f)
                
                f_ie = inv.get_child(from_dir_id, f)
                if f_ie:
                    c = 'V'
                elif self.is_ignored(fp):
                    c = 'I'
                else:
                    c = '?'

                fk = file_kind(fap)

                if f_ie:
                    if f_ie.kind != fk:
                        raise BzrCheckError("file %r entered as kind %r id %r, "
                                            "now of kind %r"
                                            % (fap, f_ie.kind, f_ie.file_id, fk))

                # make a last minute entry
                if f_ie:
                    entry = f_ie
                else:
                    if fk == 'directory':
                        entry = TreeDirectory()
                    elif fk == 'file':
                        entry = TreeFile()
                    elif fk == 'symlink':
                        entry = TreeLink()
                    else:
                        entry = TreeEntry()
                
                yield fp, c, fk, (f_ie and f_ie.file_id), entry

                if fk != 'directory':
                    continue

                if c != 'V':
                    # don't descend unversioned directories
                    continue
                
                for ff in descend(fp, f_ie.file_id, fap):
                    yield ff

        for f in descend('', inv.root.file_id, self.basedir):
            yield f
            


    def unknowns(self):
        for subp in self.extras():
            if not self.is_ignored(subp):
                yield subp

    def iter_conflicts(self):
        conflicted = set()
        for path in (s[0] for s in self.list_files()):
            stem = get_conflicted_stem(path)
            if stem is None:
                continue
            if stem not in conflicted:
                conflicted.add(stem)
                yield stem

    @needs_write_lock
    def pull(self, source, remember=False, clobber=False):
        from bzrlib.merge import merge_inner
        source.lock_read()
        try:
            old_revision_history = self.branch.revision_history()
            try:
                self.branch.update_revisions(source)
            except DivergedBranches:
                if not clobber:
                    raise
                self.branch.set_revision_history(source.revision_history())
            new_revision_history = self.branch.revision_history()
            if new_revision_history != old_revision_history:
                if len(old_revision_history):
                    other_revision = old_revision_history[-1]
                else:
                    other_revision = None
                merge_inner(self.branch,
                            self.branch.basis_tree(), 
                            self.branch.revision_tree(other_revision))
            if self.branch.get_parent() is None or remember:
                self.branch.set_parent(source.base)
        finally:
            source.unlock()

    def extras(self):
        """Yield all unknown files in this WorkingTree.

        If there are any unknown directories then only the directory is
        returned, not all its children.  But if there are unknown files
        under a versioned subdirectory, they are returned.

        Currently returned depth-first, sorted by name within directories.
        """
        ## TODO: Work from given directory downwards
        for path, dir_entry in self.inventory.directories():
            mutter("search for unknowns in %r" % path)
            dirabs = self.abspath(path)
            if not isdir(dirabs):
                # e.g. directory deleted
                continue

            fl = []
            for subf in os.listdir(dirabs):
                if (subf != '.bzr'
                    and (subf not in dir_entry.children)):
                    fl.append(subf)
            
            fl.sort()
            for subf in fl:
                subp = appendpath(path, subf)
                yield subp


    def ignored_files(self):
        """Yield list of PATH, IGNORE_PATTERN"""
        for subp in self.extras():
            pat = self.is_ignored(subp)
            if pat != None:
                yield subp, pat


    def get_ignore_list(self):
        """Return list of ignore patterns.

        Cached in the Tree object after the first call.
        """
        if hasattr(self, '_ignorelist'):
            return self._ignorelist

        l = bzrlib.DEFAULT_IGNORE[:]
        if self.has_filename(bzrlib.IGNORE_FILENAME):
            f = self.get_file_byname(bzrlib.IGNORE_FILENAME)
            l.extend([line.rstrip("\n\r") for line in f.readlines()])
        self._ignorelist = l
        return l


    def is_ignored(self, filename):
        r"""Check whether the filename matches an ignore pattern.

        Patterns containing '/' or '\' need to match the whole path;
        others match against only the last component.

        If the file is ignored, returns the pattern which caused it to
        be ignored, otherwise None.  So this can simply be used as a
        boolean if desired."""

        # TODO: Use '**' to match directories, and other extended
        # globbing stuff from cvs/rsync.

        # XXX: fnmatch is actually not quite what we want: it's only
        # approximately the same as real Unix fnmatch, and doesn't
        # treat dotfiles correctly and allows * to match /.
        # Eventually it should be replaced with something more
        # accurate.
        
        for pat in self.get_ignore_list():
            if '/' in pat or '\\' in pat:
                
                # as a special case, you can put ./ at the start of a
                # pattern; this is good to match in the top-level
                # only;
                
                if (pat[:2] == './') or (pat[:2] == '.\\'):
                    newpat = pat[2:]
                else:
                    newpat = pat
                if fnmatch.fnmatchcase(filename, newpat):
                    return pat
            else:
                if fnmatch.fnmatchcase(splitpath(filename)[-1], pat):
                    return pat
        else:
            return None

    def kind(self, file_id):
        return file_kind(self.id2abspath(file_id))

    def lock_read(self):
        """See Branch.lock_read, and WorkingTree.unlock."""
        return self.branch.lock_read()

    def lock_write(self):
        """See Branch.lock_write, and WorkingTree.unlock."""
        return self.branch.lock_write()

    @needs_write_lock
    def remove(self, files, verbose=False):
        """Remove nominated files from the working inventory..

        This does not remove their text.  This does not run on XXX on what? RBC

        TODO: Refuse to remove modified files unless --force is given?

        TODO: Do something useful with directories.

        TODO: Should this remove the text or not?  Tough call; not
        removing may be useful and the user can just use use rm, and
        is the opposite of add.  Removing it is consistent with most
        other tools.  Maybe an option.
        """
        ## TODO: Normalize names
        ## TODO: Remove nested loops; better scalability
        if isinstance(files, basestring):
            files = [files]

        inv = self.inventory

        # do this before any modifications
        for f in files:
            fid = inv.path2id(f)
            if not fid:
                # TODO: Perhaps make this just a warning, and continue?
                # This tends to happen when 
                raise NotVersionedError(path=f)
            mutter("remove inventory entry %s {%s}" % (quotefn(f), fid))
            if verbose:
                # having remove it, it must be either ignored or unknown
                if self.is_ignored(f):
                    new_status = 'I'
                else:
                    new_status = '?'
                show_status(new_status, inv[fid].kind, quotefn(f))
            del inv[fid]

        self.branch._write_inventory(inv)

    def unlock(self):
        """See Branch.unlock.
        
        WorkingTree locking just uses the Branch locking facilities.
        This is current because all working trees have an embedded branch
        within them. IF in the future, we were to make branch data shareable
        between multiple working trees, i.e. via shared storage, then we 
        would probably want to lock both the local tree, and the branch.
        """
        return self.branch.unlock()


CONFLICT_SUFFIXES = ('.THIS', '.BASE', '.OTHER')
def get_conflicted_stem(path):
    for suffix in CONFLICT_SUFFIXES:
        if path.endswith(suffix):
            return path[:-len(suffix)]
