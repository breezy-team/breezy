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


import sys, os, os.path, random, time, sha, sets, types, re, shutil, tempfile
import traceback, socket, fnmatch, difflib, time
from binascii import hexlify

import bzrlib
from inventory import Inventory
from trace import mutter, note
from tree import Tree, EmptyTree, RevisionTree
from inventory import InventoryEntry, Inventory
from osutils import isdir, quotefn, isfile, uuid, sha_file, username, \
     format_date, compact_date, pumpfile, user_email, rand_bytes, splitpath, \
     joinpath, sha_string, file_kind, local_time_offset, appendpath
from store import ImmutableStore
from revision import Revision
from errors import bailout, BzrError
from textui import show_status

BZR_BRANCH_FORMAT = "Bazaar-NG branch, format 0.0.4\n"
## TODO: Maybe include checks for common corruption of newlines, etc?



def find_branch(f, **args):
    if f and (f.startswith('http://') or f.startswith('https://')):
        import remotebranch 
        return remotebranch.RemoteBranch(f, **args)
    else:
        return Branch(f, **args)
        

def find_branch_root(f=None):
    """Find the branch root enclosing f, or pwd.

    f may be a filename or a URL.

    It is not necessary that f exists.

    Basically we keep looking up until we find the control directory or
    run into the root."""
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
            raise BzrError('%r is not in a branch' % orig_f)
        f = head
    


######################################################################
# branch objects

class Branch(object):
    """Branch holding a history of revisions.

    base
        Base directory of the branch.
    """
    _lockmode = None
    
    def __init__(self, base, init=False, find_root=True, lock_mode='w'):
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
        if init:
            self.base = os.path.realpath(base)
            self._make_control()
        elif find_root:
            self.base = find_branch_root(base)
        else:
            self.base = os.path.realpath(base)
            if not isdir(self.controlfilename('.')):
                bailout("not a bzr branch: %s" % quotefn(base),
                        ['use "bzr init" to initialize a new working tree',
                         'current bzr can only operate from top-of-tree'])
        self._check_format()
        self.lock(lock_mode)

        self.text_store = ImmutableStore(self.controlfilename('text-store'))
        self.revision_store = ImmutableStore(self.controlfilename('revision-store'))
        self.inventory_store = ImmutableStore(self.controlfilename('inventory-store'))


    def __str__(self):
        return '%s(%r)' % (self.__class__.__name__, self.base)


    __repr__ = __str__



    def lock(self, mode='w'):
        """Lock the on-disk branch, excluding other processes."""
        try:
            import fcntl, errno

            if mode == 'w':
                lm = fcntl.LOCK_EX
                om = os.O_WRONLY | os.O_CREAT
            elif mode == 'r':
                lm = fcntl.LOCK_SH
                om = os.O_RDONLY
            else:
                raise BzrError("invalid locking mode %r" % mode)

            try:
                lockfile = os.open(self.controlfilename('branch-lock'), om)
            except OSError, e:
                if e.errno == errno.ENOENT:
                    # might not exist on branches from <0.0.4
                    self.controlfile('branch-lock', 'w').close()
                    lockfile = os.open(self.controlfilename('branch-lock'), om)
                else:
                    raise e
            
            fcntl.lockf(lockfile, lm)
            def unlock():
                fcntl.lockf(lockfile, fcntl.LOCK_UN)
                os.close(lockfile)
                self._lockmode = None
            self.unlock = unlock
            self._lockmode = mode
        except ImportError:
            warning("please write a locking method for platform %r" % sys.platform)
            def unlock():
                self._lockmode = None
            self.unlock = unlock
            self._lockmode = mode


    def _need_readlock(self):
        if self._lockmode not in ['r', 'w']:
            raise BzrError('need read lock on branch, only have %r' % self._lockmode)

    def _need_writelock(self):
        if self._lockmode not in ['w']:
            raise BzrError('need write lock on branch, only have %r' % self._lockmode)


    def abspath(self, name):
        """Return absolute filename for something in the branch"""
        return os.path.join(self.base, name)


    def relpath(self, path):
        """Return path relative to this branch of something inside it.

        Raises an error if path is not in this branch."""
        rp = os.path.realpath(path)
        # FIXME: windows
        if not rp.startswith(self.base):
            bailout("path %r is not within branch %r" % (rp, self.base))
        rp = rp[len(self.base):]
        rp = rp.lstrip(os.sep)
        return rp


    def controlfilename(self, file_or_path):
        """Return location relative to branch."""
        if isinstance(file_or_path, types.StringTypes):
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
        os.mkdir(self.controlfilename([]))
        self.controlfile('README', 'w').write(
            "This is a Bazaar-NG control directory.\n"
            "Do not change any files in this directory.")
        self.controlfile('branch-format', 'w').write(BZR_BRANCH_FORMAT)
        for d in ('text-store', 'inventory-store', 'revision-store'):
            os.mkdir(self.controlfilename(d))
        for f in ('revision-history', 'merged-patches',
                  'pending-merged-patches', 'branch-name',
                  'branch-lock'):
            self.controlfile(f, 'w').write('')
        mutter('created control directory in ' + self.base)
        Inventory().write_xml(self.controlfile('inventory','w'))


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
            bailout('sorry, branch format %r not supported' % fmt,
                    ['use a different bzr version',
                     'or remove the .bzr directory and "bzr init" again'])


    def read_working_inventory(self):
        """Read the working inventory."""
        self._need_readlock()
        before = time.time()
        # ElementTree does its own conversion from UTF-8, so open in
        # binary.
        inv = Inventory.read_xml(self.controlfile('inventory', 'rb'))
        mutter("loaded inventory of %d items in %f"
               % (len(inv), time.time() - before))
        return inv


    def _write_inventory(self, inv):
        """Update the working inventory.

        That is to say, the inventory describing changes underway, that
        will be committed to the next revision.
        """
        self._need_writelock()
        ## TODO: factor out to atomicfile?  is rename safe on windows?
        ## TODO: Maybe some kind of clean/dirty marker on inventory?
        tmpfname = self.controlfilename('inventory.tmp')
        tmpf = file(tmpfname, 'wb')
        inv.write_xml(tmpf)
        tmpf.close()
        inv_fname = self.controlfilename('inventory')
        if sys.platform == 'win32':
            os.remove(inv_fname)
        os.rename(tmpfname, inv_fname)
        mutter('wrote working inventory')


    inventory = property(read_working_inventory, _write_inventory, None,
                         """Inventory for the working copy.""")


    def add(self, files, verbose=False, ids=None):
        """Make files versioned.

        Note that the command line normally calls smart_add instead.

        This puts the files in the Added state, so that they will be
        recorded by the next commit.

        TODO: Perhaps have an option to add the ids even if the files do
               not (yet) exist.

        TODO: Perhaps return the ids of the files?  But then again it
               is easy to retrieve them if they're needed.

        TODO: Option to specify file id.

        TODO: Adding a directory should optionally recurse down and
               add all non-ignored children.  Perhaps do that in a
               higher-level method.
        """
        self._need_writelock()

        # TODO: Re-adding a file that is removed in the working copy
        # should probably put it back with the previous ID.
        if isinstance(files, types.StringTypes):
            assert(ids is None or isinstance(ids, types.StringTypes))
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
                bailout("cannot add control file %s" % quotefn(f))

            fp = splitpath(f)

            if len(fp) == 0:
                bailout("cannot add top-level %r" % f)
                
            fullpath = os.path.normpath(self.abspath(f))

            try:
                kind = file_kind(fullpath)
            except OSError:
                # maybe something better?
                bailout('cannot add: not a regular file or directory: %s' % quotefn(f))
            
            if kind != 'file' and kind != 'directory':
                bailout('cannot add: not a regular file or directory: %s' % quotefn(f))

            if file_id is None:
                file_id = gen_file_id(f)
            inv.add_path(f, kind=kind, file_id=file_id)

            if verbose:
                show_status('A', kind, quotefn(f))
                
            mutter("add file %s file_id:{%s} kind=%r" % (f, file_id, kind))
            
        self._write_inventory(inv)


    def print_file(self, file, revno):
        """Print `file` to stdout."""
        self._need_readlock()
        tree = self.revision_tree(self.lookup_revision(revno))
        # use inventory as it was in that revision
        file_id = tree.inventory.path2id(file)
        if not file_id:
            bailout("%r is not present in revision %d" % (file, revno))
        tree.print_file(file_id)
        

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
        self._need_writelock()

        if isinstance(files, types.StringTypes):
            files = [files]
        
        tree = self.working_tree()
        inv = tree.inventory

        # do this before any modifications
        for f in files:
            fid = inv.path2id(f)
            if not fid:
                bailout("cannot remove unversioned file %s" % quotefn(f))
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

    def set_inventory(self, new_inventory_list):
        inv = Inventory()
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


    def append_revision(self, revision_id):
        mutter("add {%s} to revision-history" % revision_id)
        rev_history = self.revision_history()

        tmprhname = self.controlfilename('revision-history.tmp')
        rhname = self.controlfilename('revision-history')
        
        f = file(tmprhname, 'wt')
        rev_history.append(revision_id)
        f.write('\n'.join(rev_history))
        f.write('\n')
        f.close()

        if sys.platform == 'win32':
            os.remove(rhname)
        os.rename(tmprhname, rhname)
        


    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        self._need_readlock()
        r = Revision.read_xml(self.revision_store[revision_id])
        assert r.revision_id == revision_id
        return r


    def get_inventory(self, inventory_id):
        """Get Inventory object by hash.

        TODO: Perhaps for this and similar methods, take a revision
               parameter which can be either an integer revno or a
               string hash."""
        self._need_readlock()
        i = Inventory.read_xml(self.inventory_store[inventory_id])
        return i


    def get_revision_inventory(self, revision_id):
        """Return inventory of a past revision."""
        self._need_readlock()
        if revision_id == None:
            return Inventory()
        else:
            return self.get_inventory(self.get_revision(revision_id).inventory_id)


    def revision_history(self):
        """Return sequence of revision hashes on to this branch.

        >>> ScratchBranch().revision_history()
        []
        """
        self._need_readlock()
        return [l.rstrip('\r\n') for l in self.controlfile('revision-history', 'r').readlines()]


    def enum_history(self, direction):
        """Return (revno, revision_id) for history of branch.

        direction
            'forward' is from earliest to latest
            'reverse' is from latest to earliest
        """
        rh = self.revision_history()
        if direction == 'forward':
            i = 1
            for rid in rh:
                yield i, rid
                i += 1
        elif direction == 'reverse':
            i = len(rh)
            while i > 0:
                yield i, rh[i-1]
                i -= 1
        else:
            raise ValueError('invalid history direction', direction)


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


    def commit(self, *args, **kw):
        """Deprecated"""
        from bzrlib.commit import commit
        commit(self, *args, **kw)
        

    def lookup_revision(self, revno):
        """Return revision hash for revision number."""
        if revno == 0:
            return None

        try:
            # list is 0-based; revisions are 1-based
            return self.revision_history()[revno-1]
        except IndexError:
            raise BzrError("no such revision %s" % revno)


    def revision_tree(self, revision_id):
        """Return Tree for a revision on this branch.

        `revision_id` may be None for the null revision, in which case
        an `EmptyTree` is returned."""
        # TODO: refactor this to use an existing revision object
        # so we don't need to read it in twice.
        self._need_readlock()
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
        self._need_writelock()
        tree = self.working_tree()
        inv = tree.inventory
        if not tree.has_filename(from_rel):
            bailout("can't rename: old working file %r does not exist" % from_rel)
        if tree.has_filename(to_rel):
            bailout("can't rename: new working file %r already exists" % to_rel)
            
        file_id = inv.path2id(from_rel)
        if file_id == None:
            bailout("can't rename: old name %r is not versioned" % from_rel)

        if inv.path2id(to_rel):
            bailout("can't rename: new name %r is already versioned" % to_rel)

        to_dir, to_tail = os.path.split(to_rel)
        to_dir_id = inv.path2id(to_dir)
        if to_dir_id == None and to_dir != '':
            bailout("can't determine destination directory id for %r" % to_dir)

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
            bailout("failed to rename %r to %r: %s"
                    % (from_abs, to_abs, e[1]),
                    ["rename rolled back"])

        self._write_inventory(inv)
            


    def move(self, from_paths, to_name):
        """Rename files.

        to_name must exist as a versioned directory.

        If to_name exists and is a directory, the files are moved into
        it, keeping their old names.  If it is a directory, 

        Note that to_name is only the last component of the new name;
        this doesn't change the directory.
        """
        self._need_writelock()
        ## TODO: Option to move IDs only
        assert not isinstance(from_paths, basestring)
        tree = self.working_tree()
        inv = tree.inventory
        to_abs = self.abspath(to_name)
        if not isdir(to_abs):
            bailout("destination %r is not a directory" % to_abs)
        if not tree.has_filename(to_name):
            bailout("destination %r not in working directory" % to_abs)
        to_dir_id = inv.path2id(to_name)
        if to_dir_id == None and to_name != '':
            bailout("destination %r is not a versioned directory" % to_name)
        to_dir_ie = inv[to_dir_id]
        if to_dir_ie.kind not in ('directory', 'root_directory'):
            bailout("destination %r is not a directory" % to_abs)

        to_idpath = inv.get_idpath(to_dir_id)

        for f in from_paths:
            if not tree.has_filename(f):
                bailout("%r does not exist in working tree" % f)
            f_id = inv.path2id(f)
            if f_id == None:
                bailout("%r is not versioned" % f)
            name_tail = splitpath(f)[-1]
            dest_path = appendpath(to_name, name_tail)
            if tree.has_filename(dest_path):
                bailout("destination %r already exists" % dest_path)
            if f_id in to_idpath:
                bailout("can't move %r to a subdirectory of itself" % f)

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
                bailout("failed to rename %r to %r: %s" % (f, dest_path, e[1]),
                        ["rename rolled back"])

        self._write_inventory(inv)




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
    def __init__(self, files=[], dirs=[]):
        """Make a test branch.

        This creates a temporary directory and runs init-tree in it.

        If any files are listed, they are created in the working copy.
        """
        Branch.__init__(self, tempfile.mkdtemp(), init=True)
        for d in dirs:
            os.mkdir(self.abspath(d))
            
        for f in files:
            file(os.path.join(self.base, f), 'w').write('content of %s' % f)


    def __del__(self):
        self.destroy()

    def destroy(self):
        """Destroy the test branch, removing the scratch directory."""
        try:
            mutter("delete ScratchBranch %s" % self.base)
            shutil.rmtree(self.base)
        except OSError, e:
            # Work around for shutil.rmtree failing on Windows when
            # readonly files are encountered
            mutter("hit exception in destroying ScratchBranch: %s" % e)
            for root, dirs, files in os.walk(self.base, topdown=False):
                for name in files:
                    os.chmod(os.path.join(root, name), 0700)
            shutil.rmtree(self.base)
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
    return '-'.join((name, compact_date(time.time()), s))
