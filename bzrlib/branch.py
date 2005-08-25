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


import sys
import os

import bzrlib
from bzrlib.trace import mutter, note
from bzrlib.osutils import isdir, quotefn, compact_date, rand_bytes, \
     splitpath, \
     sha_file, appendpath, file_kind

from bzrlib.errors import BzrError, InvalidRevisionNumber, InvalidRevisionId
import bzrlib.errors
from bzrlib.textui import show_status
from bzrlib.revision import Revision
from bzrlib.xml import unpack_xml
from bzrlib.delta import compare_trees
from bzrlib.tree import EmptyTree, RevisionTree
import bzrlib.ui


BZR_BRANCH_FORMAT = "Bazaar-NG branch, format 0.0.4\n"
## TODO: Maybe include checks for common corruption of newlines, etc?


# TODO: Some operations like log might retrieve the same revisions
# repeatedly to calculate deltas.  We could perhaps have a weakref
# cache in memory to make this faster.

# TODO: please move the revision-string syntax stuff out of the branch
# object; it's clutter


def find_branch(f, **args):
    if f and (f.startswith('http://') or f.startswith('https://')):
        import remotebranch 
        return remotebranch.RemoteBranch(f, **args)
    else:
        return Branch(f, **args)


def find_cached_branch(f, cache_root, **args):
    from remotebranch import RemoteBranch
    br = find_branch(f, **args)
    def cacheify(br, store_name):
        from meta_store import CachedStore
        cache_path = os.path.join(cache_root, store_name)
        os.mkdir(cache_path)
        new_store = CachedStore(getattr(br, store_name), cache_path)
        setattr(br, store_name, new_store)

    if isinstance(br, RemoteBranch):
        cacheify(br, 'inventory_store')
        cacheify(br, 'text_store')
        cacheify(br, 'revision_store')
    return br


def _relpath(base, path):
    """Return path relative to base, or raise exception.

    The path may be either an absolute path or a path relative to the
    current working directory.

    Lifted out of Branch.relpath for ease of testing.

    os.path.commonprefix (python2.4) has a bad bug that it works just
    on string prefixes, assuming that '/u' is a prefix of '/u2'.  This
    avoids that problem."""
    rp = os.path.abspath(path)

    s = []
    head = rp
    while len(head) >= len(base):
        if head == base:
            break
        head, tail = os.path.split(head)
        if tail:
            s.insert(0, tail)
    else:
        from errors import NotBranchError
        raise NotBranchError("path %r is not within branch %r" % (rp, base))

    return os.sep.join(s)
        

def find_branch_root(f=None):
    """Find the branch root enclosing f, or pwd.

    f may be a filename or a URL.

    It is not necessary that f exists.

    Basically we keep looking up until we find the control directory or
    run into the root.  If there isn't one, raises NotBranchError.
    """
    if f == None:
        f = os.getcwd()
    elif hasattr(os.path, 'realpath'):
        f = os.path.realpath(f)
    else:
        f = os.path.abspath(f)
    if not os.path.exists(f):
        raise BzrError('%r does not exist' % f)
        

    orig_f = f

    while True:
        if os.path.exists(os.path.join(f, bzrlib.BZRDIR)):
            return f
        head, tail = os.path.split(f)
        if head == f:
            # reached the root, whatever that may be
            raise bzrlib.errors.NotBranchError('%s is not in a branch' % orig_f)
        f = head



# XXX: move into bzrlib.errors; subclass BzrError    
class DivergedBranches(Exception):
    def __init__(self, branch1, branch2):
        self.branch1 = branch1
        self.branch2 = branch2
        Exception.__init__(self, "These branches have diverged.")


######################################################################
# branch objects

class Branch(object):
    """Branch holding a history of revisions.

    base
        Base directory of the branch.

    _lock_mode
        None, or 'r' or 'w'

    _lock_count
        If _lock_mode is true, a positive count of the number of times the
        lock has been taken.

    _lock
        Lock object from bzrlib.lock.
    """
    base = None
    _lock_mode = None
    _lock_count = None
    _lock = None
    
    # Map some sort of prefix into a namespace
    # stuff like "revno:10", "revid:", etc.
    # This should match a prefix with a function which accepts
    REVISION_NAMESPACES = {}

    def __init__(self, base, init=False, find_root=True):
        """Create new branch object at a particular location.

        base -- Base directory for the branch.
        
        init -- If True, create new control files in a previously
             unversioned directory.  If False, the branch must already
             be versioned.

        find_root -- If true and init is false, find the root of the
             existing branch containing base.

        In the test suite, creation of new trees is tested using the
        `ScratchBranch` class.
        """
        from bzrlib.store import ImmutableStore
        if init:
            self.base = os.path.realpath(base)
            self._make_control()
        elif find_root:
            self.base = find_branch_root(base)
        else:
            self.base = os.path.realpath(base)
            if not isdir(self.controlfilename('.')):
                from errors import NotBranchError
                raise NotBranchError("not a bzr branch: %s" % quotefn(base),
                                     ['use "bzr init" to initialize a new working tree',
                                      'current bzr can only operate from top-of-tree'])
        self._check_format()

        self.text_store = ImmutableStore(self.controlfilename('text-store'))
        self.revision_store = ImmutableStore(self.controlfilename('revision-store'))
        self.inventory_store = ImmutableStore(self.controlfilename('inventory-store'))


    def __str__(self):
        return '%s(%r)' % (self.__class__.__name__, self.base)


    __repr__ = __str__


    def __del__(self):
        if self._lock_mode or self._lock:
            from warnings import warn
            warn("branch %r was not explicitly unlocked" % self)
            self._lock.unlock()



    def lock_write(self):
        if self._lock_mode:
            if self._lock_mode != 'w':
                from errors import LockError
                raise LockError("can't upgrade to a write lock from %r" %
                                self._lock_mode)
            self._lock_count += 1
        else:
            from bzrlib.lock import WriteLock

            self._lock = WriteLock(self.controlfilename('branch-lock'))
            self._lock_mode = 'w'
            self._lock_count = 1



    def lock_read(self):
        if self._lock_mode:
            assert self._lock_mode in ('r', 'w'), \
                   "invalid lock mode %r" % self._lock_mode
            self._lock_count += 1
        else:
            from bzrlib.lock import ReadLock

            self._lock = ReadLock(self.controlfilename('branch-lock'))
            self._lock_mode = 'r'
            self._lock_count = 1
                        

            
    def unlock(self):
        if not self._lock_mode:
            from errors import LockError
            raise LockError('branch %r is not locked' % (self))

        if self._lock_count > 1:
            self._lock_count -= 1
        else:
            self._lock.unlock()
            self._lock = None
            self._lock_mode = self._lock_count = None


    def abspath(self, name):
        """Return absolute filename for something in the branch"""
        return os.path.join(self.base, name)


    def relpath(self, path):
        """Return path relative to this branch of something inside it.

        Raises an error if path is not in this branch."""
        return _relpath(self.base, path)


    def controlfilename(self, file_or_path):
        """Return location relative to branch."""
        if isinstance(file_or_path, basestring):
            file_or_path = [file_or_path]
        return os.path.join(self.base, bzrlib.BZRDIR, *file_or_path)


    def controlfile(self, file_or_path, mode='r'):
        """Open a control file for this branch.

        There are two classes of file in the control directory: text
        and binary.  binary files are untranslated byte streams.  Text
        control files are stored with Unix newlines and in UTF-8, even
        if the platform or locale defaults are different.

        Controlfiles should almost never be opened in write mode but
        rather should be atomically copied and replaced using atomicfile.
        """

        fn = self.controlfilename(file_or_path)

        if mode == 'rb' or mode == 'wb':
            return file(fn, mode)
        elif mode == 'r' or mode == 'w':
            # open in binary mode anyhow so there's no newline translation;
            # codecs uses line buffering by default; don't want that.
            import codecs
            return codecs.open(fn, mode + 'b', 'utf-8',
                               buffering=60000)
        else:
            raise BzrError("invalid controlfile mode %r" % mode)



    def _make_control(self):
        from bzrlib.inventory import Inventory
        from bzrlib.xml import pack_xml
        
        os.mkdir(self.controlfilename([]))
        self.controlfile('README', 'w').write(
            "This is a Bazaar-NG control directory.\n"
            "Do not change any files in this directory.\n")
        self.controlfile('branch-format', 'w').write(BZR_BRANCH_FORMAT)
        for d in ('text-store', 'inventory-store', 'revision-store'):
            os.mkdir(self.controlfilename(d))
        for f in ('revision-history', 'merged-patches',
                  'pending-merged-patches', 'branch-name',
                  'branch-lock',
                  'pending-merges'):
            self.controlfile(f, 'w').write('')
        mutter('created control directory in ' + self.base)

        # if we want per-tree root ids then this is the place to set
        # them; they're not needed for now and so ommitted for
        # simplicity.
        pack_xml(Inventory(), self.controlfile('inventory','w'))


    def _check_format(self):
        """Check this branch format is supported.

        The current tool only supports the current unstable format.

        In the future, we might need different in-memory Branch
        classes to support downlevel branches.  But not yet.
        """
        # This ignores newlines so that we can open branches created
        # on Windows from Linux and so on.  I think it might be better
        # to always make all internal files in unix format.
        fmt = self.controlfile('branch-format', 'r').read()
        fmt.replace('\r\n', '')
        if fmt != BZR_BRANCH_FORMAT:
            raise BzrError('sorry, branch format %r not supported' % fmt,
                           ['use a different bzr version',
                            'or remove the .bzr directory and "bzr init" again'])

    def get_root_id(self):
        """Return the id of this branches root"""
        inv = self.read_working_inventory()
        return inv.root.file_id

    def set_root_id(self, file_id):
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

    def read_working_inventory(self):
        """Read the working inventory."""
        from bzrlib.inventory import Inventory
        from bzrlib.xml import unpack_xml
        from time import time
        before = time()
        self.lock_read()
        try:
            # ElementTree does its own conversion from UTF-8, so open in
            # binary.
            inv = unpack_xml(Inventory,
                             self.controlfile('inventory', 'rb'))
            mutter("loaded inventory of %d items in %f"
                   % (len(inv), time() - before))
            return inv
        finally:
            self.unlock()
            

    def _write_inventory(self, inv):
        """Update the working inventory.

        That is to say, the inventory describing changes underway, that
        will be committed to the next revision.
        """
        from bzrlib.atomicfile import AtomicFile
        from bzrlib.xml import pack_xml
        
        self.lock_write()
        try:
            f = AtomicFile(self.controlfilename('inventory'), 'wb')
            try:
                pack_xml(inv, f)
                f.commit()
            finally:
                f.close()
        finally:
            self.unlock()
        
        mutter('wrote working inventory')
            

    inventory = property(read_working_inventory, _write_inventory, None,
                         """Inventory for the working copy.""")


    def add(self, files, verbose=False, ids=None):
        """Make files versioned.

        Note that the command line normally calls smart_add instead.

        This puts the files in the Added state, so that they will be
        recorded by the next commit.

        files
            List of paths to add, relative to the base of the tree.

        ids
            If set, use these instead of automatically generated ids.
            Must be the same length as the list of files, but may
            contain None for ids that are to be autogenerated.

        TODO: Perhaps have an option to add the ids even if the files do
              not (yet) exist.

        TODO: Perhaps return the ids of the files?  But then again it
              is easy to retrieve them if they're needed.

        TODO: Adding a directory should optionally recurse down and
              add all non-ignored children.  Perhaps do that in a
              higher-level method.
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

        self.lock_write()
        try:
            inv = self.read_working_inventory()
            for f,file_id in zip(files, ids):
                if is_control_file(f):
                    raise BzrError("cannot add control file %s" % quotefn(f))

                fp = splitpath(f)

                if len(fp) == 0:
                    raise BzrError("cannot add top-level %r" % f)

                fullpath = os.path.normpath(self.abspath(f))

                try:
                    kind = file_kind(fullpath)
                except OSError:
                    # maybe something better?
                    raise BzrError('cannot add: not a regular file or directory: %s' % quotefn(f))

                if kind != 'file' and kind != 'directory':
                    raise BzrError('cannot add: not a regular file or directory: %s' % quotefn(f))

                if file_id is None:
                    file_id = gen_file_id(f)
                inv.add_path(f, kind=kind, file_id=file_id)

                if verbose:
                    print 'added', quotefn(f)

                mutter("add file %s file_id:{%s} kind=%r" % (f, file_id, kind))

            self._write_inventory(inv)
        finally:
            self.unlock()
            

    def print_file(self, file, revno):
        """Print `file` to stdout."""
        self.lock_read()
        try:
            tree = self.revision_tree(self.lookup_revision(revno))
            # use inventory as it was in that revision
            file_id = tree.inventory.path2id(file)
            if not file_id:
                raise BzrError("%r is not present in revision %s" % (file, revno))
            tree.print_file(file_id)
        finally:
            self.unlock()


    def remove(self, files, verbose=False):
        """Mark nominated files for removal from the inventory.

        This does not remove their text.  This does not run on 

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

        self.lock_write()

        try:
            tree = self.working_tree()
            inv = tree.inventory

            # do this before any modifications
            for f in files:
                fid = inv.path2id(f)
                if not fid:
                    raise BzrError("cannot remove unversioned file %s" % quotefn(f))
                mutter("remove inventory entry %s {%s}" % (quotefn(f), fid))
                if verbose:
                    # having remove it, it must be either ignored or unknown
                    if tree.is_ignored(f):
                        new_status = 'I'
                    else:
                        new_status = '?'
                    show_status(new_status, inv[fid].kind, quotefn(f))
                del inv[fid]

            self._write_inventory(inv)
        finally:
            self.unlock()


    # FIXME: this doesn't need to be a branch method
    def set_inventory(self, new_inventory_list):
        from bzrlib.inventory import Inventory, InventoryEntry
        inv = Inventory(self.get_root_id())
        for path, file_id, parent, kind in new_inventory_list:
            name = os.path.basename(path)
            if name == "":
                continue
            inv.add(InventoryEntry(file_id, name, kind, parent))
        self._write_inventory(inv)


    def unknowns(self):
        """Return all unknown files.

        These are files in the working directory that are not versioned or
        control files or ignored.
        
        >>> b = ScratchBranch(files=['foo', 'foo~'])
        >>> list(b.unknowns())
        ['foo']
        >>> b.add('foo')
        >>> list(b.unknowns())
        []
        >>> b.remove('foo')
        >>> list(b.unknowns())
        ['foo']
        """
        return self.working_tree().unknowns()


    def append_revision(self, *revision_ids):
        from bzrlib.atomicfile import AtomicFile

        for revision_id in revision_ids:
            mutter("add {%s} to revision-history" % revision_id)

        rev_history = self.revision_history()
        rev_history.extend(revision_ids)

        f = AtomicFile(self.controlfilename('revision-history'))
        try:
            for rev_id in rev_history:
                print >>f, rev_id
            f.commit()
        finally:
            f.close()


    def get_revision_xml(self, revision_id):
        """Return XML file object for revision object."""
        if not revision_id or not isinstance(revision_id, basestring):
            raise InvalidRevisionId(revision_id)

        self.lock_read()
        try:
            try:
                return self.revision_store[revision_id]
            except IndexError:
                raise bzrlib.errors.NoSuchRevision(self, revision_id)
        finally:
            self.unlock()


    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        xml_file = self.get_revision_xml(revision_id)

        try:
            r = unpack_xml(Revision, xml_file)
        except SyntaxError, e:
            raise bzrlib.errors.BzrError('failed to unpack revision_xml',
                                         [revision_id,
                                          str(e)])
            
        assert r.revision_id == revision_id
        return r


    def get_revision_delta(self, revno):
        """Return the delta for one revision.

        The delta is relative to its mainline predecessor, or the
        empty tree for revision 1.
        """
        assert isinstance(revno, int)
        rh = self.revision_history()
        if not (1 <= revno <= len(rh)):
            raise InvalidRevisionNumber(revno)

        # revno is 1-based; list is 0-based

        new_tree = self.revision_tree(rh[revno-1])
        if revno == 1:
            old_tree = EmptyTree()
        else:
            old_tree = self.revision_tree(rh[revno-2])

        return compare_trees(old_tree, new_tree)

        

    def get_revision_sha1(self, revision_id):
        """Hash the stored value of a revision, and return it."""
        # In the future, revision entries will be signed. At that
        # point, it is probably best *not* to include the signature
        # in the revision hash. Because that lets you re-sign
        # the revision, (add signatures/remove signatures) and still
        # have all hash pointers stay consistent.
        # But for now, just hash the contents.
        return bzrlib.osutils.sha_file(self.get_revision_xml(revision_id))


    def get_inventory(self, inventory_id):
        """Get Inventory object by hash.

        TODO: Perhaps for this and similar methods, take a revision
               parameter which can be either an integer revno or a
               string hash."""
        from bzrlib.inventory import Inventory
        from bzrlib.xml import unpack_xml

        return unpack_xml(Inventory, self.get_inventory_xml(inventory_id))


    def get_inventory_xml(self, inventory_id):
        """Get inventory XML as a file object."""
        return self.inventory_store[inventory_id]
            

    def get_inventory_sha1(self, inventory_id):
        """Return the sha1 hash of the inventory entry
        """
        return sha_file(self.get_inventory_xml(inventory_id))


    def get_revision_inventory(self, revision_id):
        """Return inventory of a past revision."""
        # bzr 0.0.6 imposes the constraint that the inventory_id
        # must be the same as its revision, so this is trivial.
        if revision_id == None:
            from bzrlib.inventory import Inventory
            return Inventory(self.get_root_id())
        else:
            return self.get_inventory(revision_id)


    def revision_history(self):
        """Return sequence of revision hashes on to this branch.

        >>> ScratchBranch().revision_history()
        []
        """
        self.lock_read()
        try:
            return [l.rstrip('\r\n') for l in
                    self.controlfile('revision-history', 'r').readlines()]
        finally:
            self.unlock()


    def common_ancestor(self, other, self_revno=None, other_revno=None):
        """
        >>> import commit
        >>> sb = ScratchBranch(files=['foo', 'foo~'])
        >>> sb.common_ancestor(sb) == (None, None)
        True
        >>> commit.commit(sb, "Committing first revision", verbose=False)
        >>> sb.common_ancestor(sb)[0]
        1
        >>> clone = sb.clone()
        >>> commit.commit(sb, "Committing second revision", verbose=False)
        >>> sb.common_ancestor(sb)[0]
        2
        >>> sb.common_ancestor(clone)[0]
        1
        >>> commit.commit(clone, "Committing divergent second revision", 
        ...               verbose=False)
        >>> sb.common_ancestor(clone)[0]
        1
        >>> sb.common_ancestor(clone) == clone.common_ancestor(sb)
        True
        >>> sb.common_ancestor(sb) != clone.common_ancestor(clone)
        True
        >>> clone2 = sb.clone()
        >>> sb.common_ancestor(clone2)[0]
        2
        >>> sb.common_ancestor(clone2, self_revno=1)[0]
        1
        >>> sb.common_ancestor(clone2, other_revno=1)[0]
        1
        """
        my_history = self.revision_history()
        other_history = other.revision_history()
        if self_revno is None:
            self_revno = len(my_history)
        if other_revno is None:
            other_revno = len(other_history)
        indices = range(min((self_revno, other_revno)))
        indices.reverse()
        for r in indices:
            if my_history[r] == other_history[r]:
                return r+1, my_history[r]
        return None, None


    def revno(self):
        """Return current revision number for this branch.

        That is equivalent to the number of revisions committed to
        this branch.
        """
        return len(self.revision_history())


    def last_patch(self):
        """Return last patch hash, or None if no history.
        """
        ph = self.revision_history()
        if ph:
            return ph[-1]
        else:
            return None


    def missing_revisions(self, other, stop_revision=None, diverged_ok=False):
        """
        If self and other have not diverged, return a list of the revisions
        present in other, but missing from self.

        >>> from bzrlib.commit import commit
        >>> bzrlib.trace.silent = True
        >>> br1 = ScratchBranch()
        >>> br2 = ScratchBranch()
        >>> br1.missing_revisions(br2)
        []
        >>> commit(br2, "lala!", rev_id="REVISION-ID-1")
        >>> br1.missing_revisions(br2)
        [u'REVISION-ID-1']
        >>> br2.missing_revisions(br1)
        []
        >>> commit(br1, "lala!", rev_id="REVISION-ID-1")
        >>> br1.missing_revisions(br2)
        []
        >>> commit(br2, "lala!", rev_id="REVISION-ID-2A")
        >>> br1.missing_revisions(br2)
        [u'REVISION-ID-2A']
        >>> commit(br1, "lala!", rev_id="REVISION-ID-2B")
        >>> br1.missing_revisions(br2)
        Traceback (most recent call last):
        DivergedBranches: These branches have diverged.
        """
        self_history = self.revision_history()
        self_len = len(self_history)
        other_history = other.revision_history()
        other_len = len(other_history)
        common_index = min(self_len, other_len) -1
        if common_index >= 0 and \
            self_history[common_index] != other_history[common_index]:
            raise DivergedBranches(self, other)

        if stop_revision is None:
            stop_revision = other_len
        elif stop_revision > other_len:
            raise bzrlib.errors.NoSuchRevision(self, stop_revision)
        
        return other_history[self_len:stop_revision]


    def update_revisions(self, other, stop_revision=None):
        """Pull in all new revisions from other branch.
        
        >>> from bzrlib.commit import commit
        >>> bzrlib.trace.silent = True
        >>> br1 = ScratchBranch(files=['foo', 'bar'])
        >>> br1.add('foo')
        >>> br1.add('bar')
        >>> commit(br1, "lala!", rev_id="REVISION-ID-1", verbose=False)
        >>> br2 = ScratchBranch()
        >>> br2.update_revisions(br1)
        Added 2 texts.
        Added 1 inventories.
        Added 1 revisions.
        >>> br2.revision_history()
        [u'REVISION-ID-1']
        >>> br2.update_revisions(br1)
        Added 0 texts.
        Added 0 inventories.
        Added 0 revisions.
        >>> br1.text_store.total_size() == br2.text_store.total_size()
        True
        """
        progress = bzrlib.ui.ui_factory.progress_bar()
        progress.update('comparing histories')
        revision_ids = self.missing_revisions(other, stop_revision)
        count = self.install_revisions(other, revision_ids, progress=progress)
        self.append_revision(*revision_ids)
        print "Added %d revisions." % count
                    

    def install_revisions(self, other, revision_ids, progress=None):
        if hasattr(other.revision_store, "prefetch"):
            other.revision_store.prefetch(revision_ids)
        if hasattr(other.inventory_store, "prefetch"):
            inventory_ids = [other.get_revision(r).inventory_id
                             for r in revision_ids]
            other.inventory_store.prefetch(inventory_ids)
                
        revisions = []
        needed_texts = set()
        i = 0
        for rev_id in revision_ids:
            i += 1
            if progress:
                progress.update('fetching revision', i, len(revision_ids))
            rev = other.get_revision(rev_id)
            revisions.append(rev)
            inv = other.get_inventory(str(rev.inventory_id))
            for key, entry in inv.iter_entries():
                if entry.text_id is None:
                    continue
                if entry.text_id not in self.text_store:
                    needed_texts.add(entry.text_id)

        if progress:
            progress.clear()
                    
        count = self.text_store.copy_multi(other.text_store, needed_texts)
        print "Added %d texts." % count 
        inventory_ids = [ f.inventory_id for f in revisions ]
        count = self.inventory_store.copy_multi(other.inventory_store, 
                                                inventory_ids)
        print "Added %d inventories." % count 
        revision_ids = [ f.revision_id for f in revisions]
        count = self.revision_store.copy_multi(other.revision_store, 
                                               revision_ids)
        return count
       
    def commit(self, *args, **kw):
        from bzrlib.commit import commit
        commit(self, *args, **kw)
        

    def lookup_revision(self, revision):
        """Return the revision identifier for a given revision information."""
        revno, info = self.get_revision_info(revision)
        return info


    def revision_id_to_revno(self, revision_id):
        """Given a revision id, return its revno"""
        history = self.revision_history()
        try:
            return history.index(revision_id) + 1
        except ValueError:
            raise bzrlib.errors.NoSuchRevision(self, revision_id)


    def get_revision_info(self, revision):
        """Return (revno, revision id) for revision identifier.

        revision can be an integer, in which case it is assumed to be revno (though
            this will translate negative values into positive ones)
        revision can also be a string, in which case it is parsed for something like
            'date:' or 'revid:' etc.
        """
        if revision is None:
            return 0, None
        revno = None
        try:# Convert to int if possible
            revision = int(revision)
        except ValueError:
            pass
        revs = self.revision_history()
        if isinstance(revision, int):
            if revision == 0:
                return 0, None
            # Mabye we should do this first, but we don't need it if revision == 0
            if revision < 0:
                revno = len(revs) + revision + 1
            else:
                revno = revision
        elif isinstance(revision, basestring):
            for prefix, func in Branch.REVISION_NAMESPACES.iteritems():
                if revision.startswith(prefix):
                    revno = func(self, revs, revision)
                    break
            else:
                raise BzrError('No namespace registered for string: %r' % revision)

        if revno is None or revno <= 0 or revno > len(revs):
            raise BzrError("no such revision %s" % revision)
        return revno, revs[revno-1]

    def _namespace_revno(self, revs, revision):
        """Lookup a revision by revision number"""
        assert revision.startswith('revno:')
        try:
            return int(revision[6:])
        except ValueError:
            return None
    REVISION_NAMESPACES['revno:'] = _namespace_revno

    def _namespace_revid(self, revs, revision):
        assert revision.startswith('revid:')
        try:
            return revs.index(revision[6:]) + 1
        except ValueError:
            return None
    REVISION_NAMESPACES['revid:'] = _namespace_revid

    def _namespace_last(self, revs, revision):
        assert revision.startswith('last:')
        try:
            offset = int(revision[5:])
        except ValueError:
            return None
        else:
            if offset <= 0:
                raise BzrError('You must supply a positive value for --revision last:XXX')
            return len(revs) - offset + 1
    REVISION_NAMESPACES['last:'] = _namespace_last

    def _namespace_tag(self, revs, revision):
        assert revision.startswith('tag:')
        raise BzrError('tag: namespace registered, but not implemented.')
    REVISION_NAMESPACES['tag:'] = _namespace_tag

    def _namespace_date(self, revs, revision):
        assert revision.startswith('date:')
        import datetime
        # Spec for date revisions:
        #   date:value
        #   value can be 'yesterday', 'today', 'tomorrow' or a YYYY-MM-DD string.
        #   it can also start with a '+/-/='. '+' says match the first
        #   entry after the given date. '-' is match the first entry before the date
        #   '=' is match the first entry after, but still on the given date.
        #
        #   +2005-05-12 says find the first matching entry after May 12th, 2005 at 0:00
        #   -2005-05-12 says find the first matching entry before May 12th, 2005 at 0:00
        #   =2005-05-12 says find the first match after May 12th, 2005 at 0:00 but before
        #       May 13th, 2005 at 0:00
        #
        #   So the proper way of saying 'give me all entries for today' is:
        #       -r {date:+today}:{date:-tomorrow}
        #   The default is '=' when not supplied
        val = revision[5:]
        match_style = '='
        if val[:1] in ('+', '-', '='):
            match_style = val[:1]
            val = val[1:]

        today = datetime.datetime.today().replace(hour=0,minute=0,second=0,microsecond=0)
        if val.lower() == 'yesterday':
            dt = today - datetime.timedelta(days=1)
        elif val.lower() == 'today':
            dt = today
        elif val.lower() == 'tomorrow':
            dt = today + datetime.timedelta(days=1)
        else:
            import re
            # This should be done outside the function to avoid recompiling it.
            _date_re = re.compile(
                    r'(?P<date>(?P<year>\d\d\d\d)-(?P<month>\d\d)-(?P<day>\d\d))?'
                    r'(,|T)?\s*'
                    r'(?P<time>(?P<hour>\d\d):(?P<minute>\d\d)(:(?P<second>\d\d))?)?'
                )
            m = _date_re.match(val)
            if not m or (not m.group('date') and not m.group('time')):
                raise BzrError('Invalid revision date %r' % revision)

            if m.group('date'):
                year, month, day = int(m.group('year')), int(m.group('month')), int(m.group('day'))
            else:
                year, month, day = today.year, today.month, today.day
            if m.group('time'):
                hour = int(m.group('hour'))
                minute = int(m.group('minute'))
                if m.group('second'):
                    second = int(m.group('second'))
                else:
                    second = 0
            else:
                hour, minute, second = 0,0,0

            dt = datetime.datetime(year=year, month=month, day=day,
                    hour=hour, minute=minute, second=second)
        first = dt
        last = None
        reversed = False
        if match_style == '-':
            reversed = True
        elif match_style == '=':
            last = dt + datetime.timedelta(days=1)

        if reversed:
            for i in range(len(revs)-1, -1, -1):
                r = self.get_revision(revs[i])
                # TODO: Handle timezone.
                dt = datetime.datetime.fromtimestamp(r.timestamp)
                if first >= dt and (last is None or dt >= last):
                    return i+1
        else:
            for i in range(len(revs)):
                r = self.get_revision(revs[i])
                # TODO: Handle timezone.
                dt = datetime.datetime.fromtimestamp(r.timestamp)
                if first <= dt and (last is None or dt <= last):
                    return i+1
    REVISION_NAMESPACES['date:'] = _namespace_date

    def revision_tree(self, revision_id):
        """Return Tree for a revision on this branch.

        `revision_id` may be None for the null revision, in which case
        an `EmptyTree` is returned."""
        # TODO: refactor this to use an existing revision object
        # so we don't need to read it in twice.
        if revision_id == None:
            return EmptyTree()
        else:
            inv = self.get_revision_inventory(revision_id)
            return RevisionTree(self.text_store, inv)


    def working_tree(self):
        """Return a `Tree` for the working copy."""
        from workingtree import WorkingTree
        return WorkingTree(self.base, self.read_working_inventory())


    def basis_tree(self):
        """Return `Tree` object for last revision.

        If there are no revisions yet, return an `EmptyTree`.
        """
        r = self.last_patch()
        if r == None:
            return EmptyTree()
        else:
            return RevisionTree(self.text_store, self.get_revision_inventory(r))



    def rename_one(self, from_rel, to_rel):
        """Rename one file.

        This can change the directory or the filename or both.
        """
        self.lock_write()
        try:
            tree = self.working_tree()
            inv = tree.inventory
            if not tree.has_filename(from_rel):
                raise BzrError("can't rename: old working file %r does not exist" % from_rel)
            if tree.has_filename(to_rel):
                raise BzrError("can't rename: new working file %r already exists" % to_rel)

            file_id = inv.path2id(from_rel)
            if file_id == None:
                raise BzrError("can't rename: old name %r is not versioned" % from_rel)

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

            print "%s => %s" % (from_rel, to_rel)

            from_abs = self.abspath(from_rel)
            to_abs = self.abspath(to_rel)
            try:
                os.rename(from_abs, to_abs)
            except OSError, e:
                raise BzrError("failed to rename %r to %r: %s"
                        % (from_abs, to_abs, e[1]),
                        ["rename rolled back"])

            self._write_inventory(inv)
        finally:
            self.unlock()


    def move(self, from_paths, to_name):
        """Rename files.

        to_name must exist as a versioned directory.

        If to_name exists and is a directory, the files are moved into
        it, keeping their old names.  If it is a directory, 

        Note that to_name is only the last component of the new name;
        this doesn't change the directory.
        """
        self.lock_write()
        try:
            ## TODO: Option to move IDs only
            assert not isinstance(from_paths, basestring)
            tree = self.working_tree()
            inv = tree.inventory
            to_abs = self.abspath(to_name)
            if not isdir(to_abs):
                raise BzrError("destination %r is not a directory" % to_abs)
            if not tree.has_filename(to_name):
                raise BzrError("destination %r not in working directory" % to_abs)
            to_dir_id = inv.path2id(to_name)
            if to_dir_id == None and to_name != '':
                raise BzrError("destination %r is not a versioned directory" % to_name)
            to_dir_ie = inv[to_dir_id]
            if to_dir_ie.kind not in ('directory', 'root_directory'):
                raise BzrError("destination %r is not a directory" % to_abs)

            to_idpath = inv.get_idpath(to_dir_id)

            for f in from_paths:
                if not tree.has_filename(f):
                    raise BzrError("%r does not exist in working tree" % f)
                f_id = inv.path2id(f)
                if f_id == None:
                    raise BzrError("%r is not versioned" % f)
                name_tail = splitpath(f)[-1]
                dest_path = appendpath(to_name, name_tail)
                if tree.has_filename(dest_path):
                    raise BzrError("destination %r already exists" % dest_path)
                if f_id in to_idpath:
                    raise BzrError("can't move %r to a subdirectory of itself" % f)

            # OK, so there's a race here, it's possible that someone will
            # create a file in this interval and then the rename might be
            # left half-done.  But we should have caught most problems.

            for f in from_paths:
                name_tail = splitpath(f)[-1]
                dest_path = appendpath(to_name, name_tail)
                print "%s => %s" % (f, dest_path)
                inv.rename(inv.path2id(f), to_dir_id, name_tail)
                try:
                    os.rename(self.abspath(f), self.abspath(dest_path))
                except OSError, e:
                    raise BzrError("failed to rename %r to %r: %s" % (f, dest_path, e[1]),
                            ["rename rolled back"])

            self._write_inventory(inv)
        finally:
            self.unlock()


    def revert(self, filenames, old_tree=None, backups=True):
        """Restore selected files to the versions from a previous tree.

        backups
            If true (default) backups are made of files before
            they're renamed.
        """
        from bzrlib.errors import NotVersionedError, BzrError
        from bzrlib.atomicfile import AtomicFile
        from bzrlib.osutils import backup_file
        
        inv = self.read_working_inventory()
        if old_tree is None:
            old_tree = self.basis_tree()
        old_inv = old_tree.inventory

        nids = []
        for fn in filenames:
            file_id = inv.path2id(fn)
            if not file_id:
                raise NotVersionedError("not a versioned file", fn)
            if not old_inv.has_id(file_id):
                raise BzrError("file not present in old tree", fn, file_id)
            nids.append((fn, file_id))
            
        # TODO: Rename back if it was previously at a different location

        # TODO: If given a directory, restore the entire contents from
        # the previous version.

        # TODO: Make a backup to a temporary file.

        # TODO: If the file previously didn't exist, delete it?
        for fn, file_id in nids:
            backup_file(fn)
            
            f = AtomicFile(fn, 'wb')
            try:
                f.write(old_tree.get_file(file_id).read())
                f.commit()
            finally:
                f.close()


    def pending_merges(self):
        """Return a list of pending merges.

        These are revisions that have been merged into the working
        directory but not yet committed.
        """
        cfn = self.controlfilename('pending-merges')
        if not os.path.exists(cfn):
            return []
        p = []
        for l in self.controlfile('pending-merges', 'r').readlines():
            p.append(l.rstrip('\n'))
        return p


    def add_pending_merge(self, revision_id):
        from bzrlib.revision import validate_revision_id

        validate_revision_id(revision_id)

        p = self.pending_merges()
        if revision_id in p:
            return
        p.append(revision_id)
        self.set_pending_merges(p)


    def set_pending_merges(self, rev_list):
        from bzrlib.atomicfile import AtomicFile
        self.lock_write()
        try:
            f = AtomicFile(self.controlfilename('pending-merges'))
            try:
                for l in rev_list:
                    print >>f, l
                f.commit()
            finally:
                f.close()
        finally:
            self.unlock()



class ScratchBranch(Branch):
    """Special test class: a branch that cleans up after itself.

    >>> b = ScratchBranch()
    >>> isdir(b.base)
    True
    >>> bd = b.base
    >>> b.destroy()
    >>> isdir(bd)
    False
    """
    def __init__(self, files=[], dirs=[], base=None):
        """Make a test branch.

        This creates a temporary directory and runs init-tree in it.

        If any files are listed, they are created in the working copy.
        """
        from tempfile import mkdtemp
        init = False
        if base is None:
            base = mkdtemp()
            init = True
        Branch.__init__(self, base, init=init)
        for d in dirs:
            os.mkdir(self.abspath(d))
            
        for f in files:
            file(os.path.join(self.base, f), 'w').write('content of %s' % f)


    def clone(self):
        """
        >>> orig = ScratchBranch(files=["file1", "file2"])
        >>> clone = orig.clone()
        >>> os.path.samefile(orig.base, clone.base)
        False
        >>> os.path.isfile(os.path.join(clone.base, "file1"))
        True
        """
        from shutil import copytree
        from tempfile import mkdtemp
        base = mkdtemp()
        os.rmdir(base)
        copytree(self.base, base, symlinks=True)
        return ScratchBranch(base=base)
        
    def __del__(self):
        self.destroy()

    def destroy(self):
        """Destroy the test branch, removing the scratch directory."""
        from shutil import rmtree
        try:
            if self.base:
                mutter("delete ScratchBranch %s" % self.base)
                rmtree(self.base)
        except OSError, e:
            # Work around for shutil.rmtree failing on Windows when
            # readonly files are encountered
            mutter("hit exception in destroying ScratchBranch: %s" % e)
            for root, dirs, files in os.walk(self.base, topdown=False):
                for name in files:
                    os.chmod(os.path.join(root, name), 0700)
            rmtree(self.base)
        self.base = None

    

######################################################################
# predicates


def is_control_file(filename):
    ## FIXME: better check
    filename = os.path.normpath(filename)
    while filename != '':
        head, tail = os.path.split(filename)
        ## mutter('check %r for control file' % ((head, tail), ))
        if tail == bzrlib.BZRDIR:
            return True
        if filename == head:
            break
        filename = head
    return False



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

