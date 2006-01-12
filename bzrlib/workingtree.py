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

from copy import deepcopy
import os
import stat
import fnmatch
 
from bzrlib.branch import (Branch,
                           is_control_file,
                           needs_read_lock,
                           needs_write_lock,
                           quotefn)
from bzrlib.errors import (BzrCheckError,
                           BzrError,
                           DivergedBranches,
                           WeaveRevisionNotPresent,
                           NotBranchError,
                           NoSuchFile,
                           NotVersionedError)
from bzrlib.inventory import InventoryEntry
from bzrlib.osutils import (appendpath,
                            compact_date,
                            file_kind,
                            isdir,
                            getcwd,
                            pathjoin,
                            pumpfile,
                            splitpath,
                            rand_bytes,
                            abspath,
                            normpath,
                            realpath,
                            relpath,
                            rename)
from bzrlib.textui import show_status
import bzrlib.tree
from bzrlib.trace import mutter
import bzrlib.xml5


def gen_file_id(name):
    """Return new file id.

    This should probably generate proper UUIDs, but for the moment we
    cope with just randomness because running uuidgen every time is
    slow."""
    import re
    from binascii import hexlify
    from time import time

    # get last component
    idx = name.rfind('/')
    if idx != -1:
        name = name[idx+1 : ]
    idx = name.rfind('\\')
    if idx != -1:
        name = name[idx+1 : ]

    # make it not a hidden file
    name = name.lstrip('.')

    # remove any wierd characters; we don't escape them but rather
    # just pull them out
    name = re.sub(r'[^\w.]', '', name)

    s = hexlify(rand_bytes(8))
    return '-'.join((name, compact_date(time()), s))


def gen_root_id():
    """Return a new tree-root file id."""
    return gen_file_id('TREE_ROOT')


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

    def __init__(self, basedir=u'.', branch=None):
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
        self.branch = branch
        self.basedir = realpath(basedir)

        # update the whole cache up front and write to disk if anything changed;
        # in the future we might want to do this more selectively
        # two possible ways offer themselves : in self._unlock, write the cache
        # if needed, or, when the cache sees a change, append it to the hash
        # cache file, and have the parser take the most recent entry for a
        # given path only.
        hc = self._hashcache = HashCache(basedir)
        hc.read()
        hc.scan()

        if hc.needs_write:
            mutter("write hc")
            hc.write()

        self._set_inventory(self.read_working_inventory())

    def _set_inventory(self, inv):
        self._inventory = inv
        self.path2id = self._inventory.path2id

    @staticmethod
    def open_containing(path=None):
        """Open an existing working tree which has its root about path.
        
        This probes for a working tree at path and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into /.  If there isn't one, raises NotBranchError.
        TODO: give this a new exception.
        If there is one, it is returned, along with the unused portion of path.
        """
        if path is None:
            path = getcwd()
        else:
            # sanity check.
            if path.find('://') != -1:
                raise NotBranchError(path=path)
        path = abspath(path)
        tail = u''
        while True:
            try:
                return WorkingTree(path), tail
            except NotBranchError:
                pass
            if tail:
                tail = pathjoin(os.path.basename(path), tail)
            else:
                tail = os.path.basename(path)
            lastpath = path
            path = os.path.dirname(path)
            if lastpath == path:
                # reached the root, whatever that may be
                raise NotBranchError(path=path)

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
        return pathjoin(self.basedir, filename)

    def relpath(self, abs):
        """Return the local path portion from a given absolute path."""
        return relpath(self.basedir, abs)

    def has_filename(self, filename):
        return bzrlib.osutils.lexists(self.abspath(filename))

    def get_file(self, file_id):
        return self.get_file_byname(self.id2path(file_id))

    def get_file_byname(self, filename):
        return file(self.abspath(filename), 'rb')

    def get_root_id(self):
        """Return the id of this trees root"""
        inv = self.read_working_inventory()
        return inv.root.file_id
        
    def _get_store_filename(self, file_id):
        ## XXX: badly named; this is not in the store at all
        return self.abspath(self.id2path(file_id))

    @needs_write_lock
    def commit(self, *args, **kw):
        from bzrlib.commit import Commit
        Commit().commit(self.branch, *args, **kw)
        self._set_inventory(self.read_working_inventory())

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

    @needs_read_lock
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

    @needs_write_lock
    def add(self, files, ids=None):
        """Make files versioned.

        Note that the command line normally calls smart_add instead,
        which can automatically recurse.

        This adds the files to the inventory, so that they will be
        recorded by the next commit.

        files
            List of paths to add, relative to the base of the tree.

        ids
            If set, use these instead of automatically generated ids.
            Must be the same length as the list of files, but may
            contain None for ids that are to be autogenerated.

        TODO: Perhaps have an option to add the ids even if the files do
              not (yet) exist.

        TODO: Perhaps callback with the ids and paths as they're added.
        """
        # TODO: Re-adding a file that is removed in the working copy
        # should probably put it back with the previous ID.
        if isinstance(files, basestring):
            assert(ids is None or isinstance(ids, basestring))
            files = [files]
            if ids is not None:
                ids = [ids]

        if ids is None:
            ids = [None] * len(files)
        else:
            assert(len(ids) == len(files))

        inv = self.read_working_inventory()
        for f,file_id in zip(files, ids):
            if is_control_file(f):
                raise BzrError("cannot add control file %s" % quotefn(f))

            fp = splitpath(f)

            if len(fp) == 0:
                raise BzrError("cannot add top-level %r" % f)

            fullpath = normpath(self.abspath(f))

            try:
                kind = file_kind(fullpath)
            except OSError:
                # maybe something better?
                raise BzrError('cannot add: not a regular file, symlink or directory: %s' % quotefn(f))

            if not InventoryEntry.versionable_kind(kind):
                raise BzrError('cannot add: not a versionable file ('
                               'i.e. regular file, symlink or directory): %s' % quotefn(f))

            if file_id is None:
                file_id = gen_file_id(f)
            inv.add_path(f, kind=kind, file_id=file_id)

            mutter("add file %s file_id:{%s} kind=%r" % (f, file_id, kind))
        self._write_inventory(inv)

    @needs_write_lock
    def add_pending_merge(self, *revision_ids):
        # TODO: Perhaps should check at this point that the
        # history of the revision is actually present?
        p = self.pending_merges()
        updated = False
        for rev_id in revision_ids:
            if rev_id in p:
                continue
            p.append(rev_id)
            updated = True
        if updated:
            self.set_pending_merges(p)

    @needs_read_lock
    def pending_merges(self):
        """Return a list of pending merges.

        These are revisions that have been merged into the working
        directory but not yet committed.
        """
        try:
            f = self.branch.control_files.controlfile('pending-merges', 'r')
        except NoSuchFile:
            return []
        p = []
        for l in f.readlines():
            p.append(l.rstrip('\n'))
        return p

    @needs_write_lock
    def set_pending_merges(self, rev_list):
        self.branch.control_files.put_utf8('pending-merges', '\n'.join(rev_list))

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

        for f in descend(u'', inv.root.file_id, self.basedir):
            yield f

    @needs_write_lock
    def move(self, from_paths, to_name):
        """Rename files.

        to_name must exist in the inventory.

        If to_name exists and is a directory, the files are moved into
        it, keeping their old names.  

        Note that to_name is only the last component of the new name;
        this doesn't change the directory.

        This returns a list of (from_path, to_path) pairs for each
        entry that is moved.
        """
        result = []
        ## TODO: Option to move IDs only
        assert not isinstance(from_paths, basestring)
        inv = self.inventory
        to_abs = self.abspath(to_name)
        if not isdir(to_abs):
            raise BzrError("destination %r is not a directory" % to_abs)
        if not self.has_filename(to_name):
            raise BzrError("destination %r not in working directory" % to_abs)
        to_dir_id = inv.path2id(to_name)
        if to_dir_id == None and to_name != '':
            raise BzrError("destination %r is not a versioned directory" % to_name)
        to_dir_ie = inv[to_dir_id]
        if to_dir_ie.kind not in ('directory', 'root_directory'):
            raise BzrError("destination %r is not a directory" % to_abs)

        to_idpath = inv.get_idpath(to_dir_id)

        for f in from_paths:
            if not self.has_filename(f):
                raise BzrError("%r does not exist in working tree" % f)
            f_id = inv.path2id(f)
            if f_id == None:
                raise BzrError("%r is not versioned" % f)
            name_tail = splitpath(f)[-1]
            dest_path = appendpath(to_name, name_tail)
            if self.has_filename(dest_path):
                raise BzrError("destination %r already exists" % dest_path)
            if f_id in to_idpath:
                raise BzrError("can't move %r to a subdirectory of itself" % f)

        # OK, so there's a race here, it's possible that someone will
        # create a file in this interval and then the rename might be
        # left half-done.  But we should have caught most problems.
        orig_inv = deepcopy(self.inventory)
        try:
            for f in from_paths:
                name_tail = splitpath(f)[-1]
                dest_path = appendpath(to_name, name_tail)
                result.append((f, dest_path))
                inv.rename(inv.path2id(f), to_dir_id, name_tail)
                try:
                    rename(self.abspath(f), self.abspath(dest_path))
                except OSError, e:
                    raise BzrError("failed to rename %r to %r: %s" %
                                   (f, dest_path, e[1]),
                            ["rename rolled back"])
        except:
            # restore the inventory on error
            self._set_inventory(orig_inv)
            raise
        self._write_inventory(inv)
        return result

    @needs_write_lock
    def rename_one(self, from_rel, to_rel):
        """Rename one file.

        This can change the directory or the filename or both.
        """
        inv = self.inventory
        if not self.has_filename(from_rel):
            raise BzrError("can't rename: old working file %r does not exist" % from_rel)
        if self.has_filename(to_rel):
            raise BzrError("can't rename: new working file %r already exists" % to_rel)

        file_id = inv.path2id(from_rel)
        if file_id == None:
            raise BzrError("can't rename: old name %r is not versioned" % from_rel)

        entry = inv[file_id]
        from_parent = entry.parent_id
        from_name = entry.name
        
        if inv.path2id(to_rel):
            raise BzrError("can't rename: new name %r is already versioned" % to_rel)

        to_dir, to_tail = os.path.split(to_rel)
        to_dir_id = inv.path2id(to_dir)
        if to_dir_id == None and to_dir != '':
            raise BzrError("can't determine destination directory id for %r" % to_dir)

        mutter("rename_one:")
        mutter("  file_id    {%s}" % file_id)
        mutter("  from_rel   %r" % from_rel)
        mutter("  to_rel     %r" % to_rel)
        mutter("  to_dir     %r" % to_dir)
        mutter("  to_dir_id  {%s}" % to_dir_id)

        inv.rename(file_id, to_dir_id, to_tail)

        from_abs = self.abspath(from_rel)
        to_abs = self.abspath(to_rel)
        try:
            rename(from_abs, to_abs)
        except OSError, e:
            inv.rename(file_id, from_parent, from_name)
            raise BzrError("failed to rename %r to %r: %s"
                    % (from_abs, to_abs, e[1]),
                    ["rename rolled back"])
        self._write_inventory(inv)

    @needs_read_lock
    def unknowns(self):
        """Return all unknown files.

        These are files in the working directory that are not versioned or
        control files or ignored.
        
        >>> from bzrlib.branch import ScratchBranch
        >>> b = ScratchBranch(files=['foo', 'foo~'])
        >>> tree = WorkingTree(b.base, b)
        >>> map(str, tree.unknowns())
        ['foo']
        >>> tree.add('foo')
        >>> list(b.unknowns())
        []
        >>> tree.remove('foo')
        >>> list(b.unknowns())
        [u'foo']
        """
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
    def pull(self, source, overwrite=False):
        from bzrlib.merge import merge_inner
        source.lock_read()
        try:
            old_revision_history = self.branch.revision_history()
            count = self.branch.pull(source, overwrite)
            new_revision_history = self.branch.revision_history()
            if new_revision_history != old_revision_history:
                if len(old_revision_history):
                    other_revision = old_revision_history[-1]
                else:
                    other_revision = None
                repository = self.branch.repository
                merge_inner(self.branch,
                            self.branch.basis_tree(), 
                            repository.revision_tree(other_revision))
            return count
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
            mutter("search for unknowns in %r", path)
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

    def _basis_inventory_name(self, revision_id):
        return 'basis-inventory.%s' % revision_id

    def set_last_revision(self, new_revision, old_revision=None):
        if old_revision is not None:
            try:
                path = self._basis_inventory_name(old_revision)
                path = self.branch.control_files._escape(path)
                self.branch.control_files._transport.delete(path)
            except NoSuchFile:
                pass
        try:
            xml = self.branch.repository.get_inventory_xml(new_revision)
            path = self._basis_inventory_name(new_revision)
            self.branch.control_files.put_utf8(path, xml)
        except WeaveRevisionNotPresent:
            pass

    def read_basis_inventory(self, revision_id):
        """Read the cached basis inventory."""
        path = self._basis_inventory_name(revision_id)
        return self.branch.control_files.controlfile(path, 'r').read()
        
    @needs_read_lock
    def read_working_inventory(self):
        """Read the working inventory."""
        # ElementTree does its own conversion from UTF-8, so open in
        # binary.
        f = self.branch.control_files.controlfile('inventory', 'rb')
        return bzrlib.xml5.serializer_v5.read_inventory(f)

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
            mutter("remove inventory entry %s {%s}", quotefn(f), fid)
            if verbose:
                # having remove it, it must be either ignored or unknown
                if self.is_ignored(f):
                    new_status = 'I'
                else:
                    new_status = '?'
                show_status(new_status, inv[fid].kind, quotefn(f))
            del inv[fid]

        self._write_inventory(inv)

    @needs_write_lock
    def revert(self, filenames, old_tree=None, backups=True):
        from bzrlib.merge import merge_inner
        if old_tree is None:
            old_tree = self.branch.basis_tree()
        merge_inner(self.branch, old_tree,
                    self, ignore_zero=True,
                    backup_files=backups, 
                    interesting_files=filenames)
        if not len(filenames):
            self.set_pending_merges([])

    @needs_write_lock
    def set_inventory(self, new_inventory_list):
        from bzrlib.inventory import (Inventory,
                                      InventoryDirectory,
                                      InventoryEntry,
                                      InventoryFile,
                                      InventoryLink)
        inv = Inventory(self.get_root_id())
        for path, file_id, parent, kind in new_inventory_list:
            name = os.path.basename(path)
            if name == "":
                continue
            # fixme, there should be a factory function inv,add_?? 
            if kind == 'directory':
                inv.add(InventoryDirectory(file_id, name, parent))
            elif kind == 'file':
                inv.add(InventoryFile(file_id, name, parent))
            elif kind == 'symlink':
                inv.add(InventoryLink(file_id, name, parent))
            else:
                raise BzrError("unknown kind %r" % kind)
        self._write_inventory(inv)

    @needs_write_lock
    def set_root_id(self, file_id):
        """Set the root id for this tree."""
        inv = self.read_working_inventory()
        orig_root_id = inv.root.file_id
        del inv._byid[inv.root.file_id]
        inv.root.file_id = file_id
        inv._byid[inv.root.file_id] = inv.root
        for fid in inv:
            entry = inv[fid]
            if entry.parent_id in (None, orig_root_id):
                entry.parent_id = inv.root.file_id
        self._write_inventory(inv)

    def unlock(self):
        """See Branch.unlock.
        
        WorkingTree locking just uses the Branch locking facilities.
        This is current because all working trees have an embedded branch
        within them. IF in the future, we were to make branch data shareable
        between multiple working trees, i.e. via shared storage, then we 
        would probably want to lock both the local tree, and the branch.
        """
        if self._hashcache.needs_write and self.branch._lock_count==1:
            self._hashcache.write()
        return self.branch.unlock()

    @needs_write_lock
    def _write_inventory(self, inv):
        """Write inventory as the current inventory."""
        from cStringIO import StringIO
        from bzrlib.atomicfile import AtomicFile
        sio = StringIO()
        bzrlib.xml5.serializer_v5.write_inventory(inv, sio)
        sio.seek(0)
        f = AtomicFile(self.branch.control_files.controlfilename('inventory'))
        try:
            pumpfile(sio, f)
            f.commit()
        finally:
            f.close()
        self._set_inventory(inv)
        mutter('wrote working inventory')
            

CONFLICT_SUFFIXES = ('.THIS', '.BASE', '.OTHER')
def get_conflicted_stem(path):
    for suffix in CONFLICT_SUFFIXES:
        if path.endswith(suffix):
            return path[:-len(suffix)]
