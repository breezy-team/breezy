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

import sys, os, os.path, random, time, sha, sets, types, re, shutil, tempfile
import traceback, socket, fnmatch, difflib, time
from binascii import hexlify

import bzrlib
from inventory import Inventory
from trace import mutter, note
from tree import Tree, EmptyTree, RevisionTree, WorkingTree
from inventory import InventoryEntry, Inventory
from osutils import isdir, quotefn, isfile, uuid, sha_file, username, chomp, \
     format_date, compact_date, pumpfile, user_email, rand_bytes, splitpath, \
     joinpath, sha_string, file_kind, local_time_offset
from store import ImmutableStore
from revision import Revision
from errors import bailout
from textui import show_status
from diff import diff_trees

BZR_BRANCH_FORMAT = "Bazaar-NG branch, format 0.0.4\n"
## TODO: Maybe include checks for common corruption of newlines, etc?





######################################################################
# branch objects

class Branch:
    """Branch holding a history of revisions.

    :todo: Perhaps use different stores for different classes of object,
           so that we can keep track of how much space each one uses,
           or garbage-collect them.

    :todo: Add a RemoteBranch subclass.  For the basic case of read-only
           HTTP access this should be very easy by, 
           just redirecting controlfile access into HTTP requests.
           We would need a RemoteStore working similarly.

    :todo: Keep the on-disk branch locked while the object exists.

    :todo: mkdir() method.
    """
    def __init__(self, base, init=False):
        """Create new branch object at a particular location.

        :param base: Base directory for the branch.

        :param init: If True, create new control files in a previously
             unversioned directory.  If False, the branch must already
             be versioned.

        In the test suite, creation of new trees is tested using the
        `ScratchBranch` class.
        """
        self.base = os.path.realpath(base)
        if init:
            self._make_control()
        else:
            if not isdir(self.controlfilename('.')):
                bailout("not a bzr branch: %s" % quotefn(base),
                        ['use "bzr init" to initialize a new working tree',
                         'current bzr can only operate from top-of-tree'])
            self._check_format()

        self.text_store = ImmutableStore(self.controlfilename('text-store'))
        self.revision_store = ImmutableStore(self.controlfilename('revision-store'))
        self.inventory_store = ImmutableStore(self.controlfilename('inventory-store'))


    def __str__(self):
        return '%s(%r)' % (self.__class__.__name__, self.base)


    __repr__ = __str__


    def _rel(self, name):
        """Return filename relative to branch top"""
        return os.path.join(self.base, name)
        

    def controlfilename(self, file_or_path):
        """Return location relative to branch."""
        if isinstance(file_or_path, types.StringTypes):
            file_or_path = [file_or_path]
        return os.path.join(self.base, bzrlib.BZRDIR, *file_or_path)


    def controlfile(self, file_or_path, mode='r'):
        """Open a control file for this branch"""
        return file(self.controlfilename(file_or_path), mode)


    def _make_control(self):
        os.mkdir(self.controlfilename([]))
        self.controlfile('README', 'w').write(
            "This is a Bazaar-NG control directory.\n"
            "Do not change any files in this directory.")
        self.controlfile('branch-format', 'w').write(BZR_BRANCH_FORMAT)
        for d in ('text-store', 'inventory-store', 'revision-store'):
            os.mkdir(self.controlfilename(d))
        for f in ('revision-history', 'merged-patches',
                  'pending-merged-patches', 'branch-name'):
            self.controlfile(f, 'w').write('')
        mutter('created control directory in ' + self.base)
        Inventory().write_xml(self.controlfile('inventory','w'))


    def _check_format(self):
        """Check this branch format is supported.

        The current tool only supports the current unstable format.

        In the future, we might need different in-memory Branch
        classes to support downlevel branches.  But not yet.
        """        
        # read in binary mode to detect newline wierdness.
        fmt = self.controlfile('branch-format', 'rb').read()
        if fmt != BZR_BRANCH_FORMAT:
            bailout('sorry, branch format %r not supported' % fmt,
                    ['use a different bzr version',
                     'or remove the .bzr directory and "bzr init" again'])


    def read_working_inventory(self):
        """Read the working inventory."""
        before = time.time()
        inv = Inventory.read_xml(self.controlfile('inventory', 'r'))
        mutter("loaded inventory of %d items in %f"
               % (len(inv), time.time() - before))
        return inv


    def _write_inventory(self, inv):
        """Update the working inventory.

        That is to say, the inventory describing changes underway, that
        will be committed to the next revision.
        """
        inv.write_xml(self.controlfile('inventory', 'w'))
        mutter('wrote inventory to %s' % quotefn(self.controlfilename('inventory')))


    inventory = property(read_working_inventory, _write_inventory, None,
                         """Inventory for the working copy.""")


    def add(self, files, verbose=False):
        """Make files versioned.

        This puts the files in the Added state, so that they will be
        recorded by the next commit.

        :todo: Perhaps have an option to add the ids even if the files do
               not (yet) exist.

        :todo: Perhaps return the ids of the files?  But then again it
               is easy to retrieve them if they're needed.

        :todo: Option to specify file id.

        :todo: Adding a directory should optionally recurse down and
               add all non-ignored children.  Perhaps do that in a
               higher-level method.

        >>> b = ScratchBranch(files=['foo'])
        >>> 'foo' in b.unknowns()
        True
        >>> b.show_status()
        ?       foo
        >>> b.add('foo')
        >>> 'foo' in b.unknowns()
        False
        >>> bool(b.inventory.path2id('foo'))
        True
        >>> b.show_status()
        A       foo

        >>> b.add('foo')
        Traceback (most recent call last):
        ...
        BzrError: ('foo is already versioned', [])

        >>> b.add(['nothere'])
        Traceback (most recent call last):
        BzrError: ('cannot add: not a regular file or directory: nothere', [])
        """

        # TODO: Re-adding a file that is removed in the working copy
        # should probably put it back with the previous ID.
        if isinstance(files, types.StringTypes):
            files = [files]
        
        inv = self.read_working_inventory()
        for f in files:
            if is_control_file(f):
                bailout("cannot add control file %s" % quotefn(f))

            fp = splitpath(f)

            if len(fp) == 0:
                bailout("cannot add top-level %r" % f)
                
            fullpath = os.path.normpath(self._rel(f))

            if isfile(fullpath):
                kind = 'file'
            elif isdir(fullpath):
                kind = 'directory'
            else:
                bailout('cannot add: not a regular file or directory: %s' % quotefn(f))

            if len(fp) > 1:
                parent_name = joinpath(fp[:-1])
                mutter("lookup parent %r" % parent_name)
                parent_id = inv.path2id(parent_name)
                if parent_id == None:
                    bailout("cannot add: parent %r is not versioned"
                            % joinpath(fp[:-1]))
            else:
                parent_id = None

            file_id = _gen_file_id(fp[-1])
            inv.add(InventoryEntry(file_id, fp[-1], kind=kind, parent_id=parent_id))
            if verbose:
                show_status('A', kind, quotefn(f))
                
            mutter("add file %s file_id:{%s} kind=%r parent_id={%s}"
                   % (f, file_id, kind, parent_id))
        self._write_inventory(inv)



    def remove(self, files, verbose=False):
        """Mark nominated files for removal from the inventory.

        This does not remove their text.  This does not run on 

        :todo: Refuse to remove modified files unless --force is given?

        >>> b = ScratchBranch(files=['foo'])
        >>> b.add('foo')
        >>> b.inventory.has_filename('foo')
        True
        >>> b.remove('foo')
        >>> b.working_tree().has_filename('foo')
        True
        >>> b.inventory.has_filename('foo')
        False
        
        >>> b = ScratchBranch(files=['foo'])
        >>> b.add('foo')
        >>> b.commit('one')
        >>> b.remove('foo')
        >>> b.commit('two')
        >>> b.inventory.has_filename('foo') 
        False
        >>> b.basis_tree().has_filename('foo') 
        False
        >>> b.working_tree().has_filename('foo') 
        True

        :todo: Do something useful with directories.

        :todo: Should this remove the text or not?  Tough call; not
        removing may be useful and the user can just use use rm, and
        is the opposite of add.  Removing it is consistent with most
        other tools.  Maybe an option.
        """
        ## TODO: Normalize names
        ## TODO: Remove nested loops; better scalability

        if isinstance(files, types.StringTypes):
            files = [files]
        
        inv = self.read_working_inventory()

        # do this before any modifications
        for f in files:
            fid = inv.path2id(f)
            if not fid:
                bailout("cannot remove unversioned file %s" % quotefn(f))
            mutter("remove inventory entry %s {%s}" % (quotefn(f), fid))
            if verbose:
                show_status('D', inv[fid].kind, quotefn(f))
            del inv[fid]

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


    def commit(self, message, timestamp=None, timezone=None,
               committer=None,
               verbose=False):
        """Commit working copy as a new revision.
        
        The basic approach is to add all the file texts into the
        store, then the inventory, then make a new revision pointing
        to that inventory and store that.
        
        This is not quite safe if the working copy changes during the
        commit; for the moment that is simply not allowed.  A better
        approach is to make a temporary copy of the files before
        computing their hashes, and then add those hashes in turn to
        the inventory.  This should mean at least that there are no
        broken hash pointers.  There is no way we can get a snapshot
        of the whole directory at an instant.  This would also have to
        be robust against files disappearing, moving, etc.  So the
        whole thing is a bit hard.

        :param timestamp: if not None, seconds-since-epoch for a
             postdated/predated commit.
        """

        ## TODO: Show branch names

        # TODO: Don't commit if there are no changes, unless forced?

        # First walk over the working inventory; and both update that
        # and also build a new revision inventory.  The revision
        # inventory needs to hold the text-id, sha1 and size of the
        # actual file versions committed in the revision.  (These are
        # not present in the working inventory.)  We also need to
        # detect missing/deleted files, and remove them from the
        # working inventory.

        work_inv = self.read_working_inventory()
        inv = Inventory()
        basis = self.basis_tree()
        basis_inv = basis.inventory
        missing_ids = []
        for path, entry in work_inv.iter_entries():
            ## TODO: Cope with files that have gone missing.

            ## TODO: Check that the file kind has not changed from the previous
            ## revision of this file (if any).

            entry = entry.copy()

            p = self._rel(path)
            file_id = entry.file_id
            mutter('commit prep file %s, id %r ' % (p, file_id))

            if not os.path.exists(p):
                mutter("    file is missing, removing from inventory")
                if verbose:
                    show_status('D', entry.kind, quotefn(path))
                missing_ids.append(file_id)
                continue

            # TODO: Handle files that have been deleted

            # TODO: Maybe a special case for empty files?  Seems a
            # waste to store them many times.

            inv.add(entry)

            if basis_inv.has_id(file_id):
                old_kind = basis_inv[file_id].kind
                if old_kind != entry.kind:
                    bailout("entry %r changed kind from %r to %r"
                            % (file_id, old_kind, entry.kind))

            if entry.kind == 'directory':
                if not isdir(p):
                    bailout("%s is entered as directory but not a directory" % quotefn(p))
            elif entry.kind == 'file':
                if not isfile(p):
                    bailout("%s is entered as file but is not a file" % quotefn(p))

                content = file(p, 'rb').read()

                entry.text_sha1 = sha_string(content)
                entry.text_size = len(content)

                old_ie = basis_inv.has_id(file_id) and basis_inv[file_id]
                if (old_ie
                    and (old_ie.text_size == entry.text_size)
                    and (old_ie.text_sha1 == entry.text_sha1)):
                    ## assert content == basis.get_file(file_id).read()
                    entry.text_id = basis_inv[file_id].text_id
                    mutter('    unchanged from previous text_id {%s}' %
                           entry.text_id)
                    
                else:
                    entry.text_id = _gen_file_id(entry.name)
                    self.text_store.add(content, entry.text_id)
                    mutter('    stored with text_id {%s}' % entry.text_id)
                    if verbose:
                        if not old_ie:
                            state = 'A'
                        elif (old_ie.name == entry.name
                              and old_ie.parent_id == entry.parent_id):
                            state = 'R'
                        else:
                            state = 'M'

                        show_status(state, entry.kind, quotefn(path))

        for file_id in missing_ids:
            # have to do this later so we don't mess up the iterator.
            # since parents may be removed before their children we
            # have to test.

            # FIXME: There's probably a better way to do this; perhaps
            # the workingtree should know how to filter itself.
            if work_inv.has_id(file_id):
                del work_inv[file_id]


        inv_id = rev_id = _gen_revision_id(time.time())
        
        inv_tmp = tempfile.TemporaryFile()
        inv.write_xml(inv_tmp)
        inv_tmp.seek(0)
        self.inventory_store.add(inv_tmp, inv_id)
        mutter('new inventory_id is {%s}' % inv_id)

        self._write_inventory(work_inv)

        if timestamp == None:
            timestamp = time.time()

        if committer == None:
            committer = username()

        if timezone == None:
            timezone = local_time_offset()

        mutter("building commit log message")
        rev = Revision(timestamp=timestamp,
                       timezone=timezone,
                       committer=committer,
                       precursor = self.last_patch(),
                       message = message,
                       inventory_id=inv_id,
                       revision_id=rev_id)

        rev_tmp = tempfile.TemporaryFile()
        rev.write_xml(rev_tmp)
        rev_tmp.seek(0)
        self.revision_store.add(rev_tmp, rev_id)
        mutter("new revision_id is {%s}" % rev_id)
        
        ## XXX: Everything up to here can simply be orphaned if we abort
        ## the commit; it will leave junk files behind but that doesn't
        ## matter.

        ## TODO: Read back the just-generated changeset, and make sure it
        ## applies and recreates the right state.

        ## TODO: Also calculate and store the inventory SHA1
        mutter("committing patch r%d" % (self.revno() + 1))

        mutter("append to revision-history")
        self.controlfile('revision-history', 'at').write(rev_id + '\n')

        mutter("done!")


    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        r = Revision.read_xml(self.revision_store[revision_id])
        assert r.revision_id == revision_id
        return r


    def get_inventory(self, inventory_id):
        """Get Inventory object by hash.

        :todo: Perhaps for this and similar methods, take a revision
               parameter which can be either an integer revno or a
               string hash."""
        i = Inventory.read_xml(self.inventory_store[inventory_id])
        return i


    def get_revision_inventory(self, revision_id):
        """Return inventory of a past revision."""
        if revision_id == None:
            return Inventory()
        else:
            return self.get_inventory(self.get_revision(revision_id).inventory_id)


    def revision_history(self):
        """Return sequence of revision hashes on to this branch.

        >>> ScratchBranch().revision_history()
        []
        """
        return [chomp(l) for l in self.controlfile('revision-history').readlines()]


    def revno(self):
        """Return current revision number for this branch.

        That is equivalent to the number of revisions committed to
        this branch.

        >>> b = ScratchBranch()
        >>> b.revno()
        0
        >>> b.commit('no foo')
        >>> b.revno()
        1
        """
        return len(self.revision_history())


    def last_patch(self):
        """Return last patch hash, or None if no history.

        >>> ScratchBranch().last_patch() == None
        True
        """
        ph = self.revision_history()
        if ph:
            return ph[-1]


    def lookup_revision(self, revno):
        """Return revision hash for revision number."""
        if revno == 0:
            return None

        try:
            # list is 0-based; revisions are 1-based
            return self.revision_history()[revno-1]
        except IndexError:
            bailout("no such revision %s" % revno)


    def revision_tree(self, revision_id):
        """Return Tree for a revision on this branch.

        `revision_id` may be None for the null revision, in which case
        an `EmptyTree` is returned."""

        if revision_id == None:
            return EmptyTree()
        else:
            inv = self.get_revision_inventory(revision_id)
            return RevisionTree(self.text_store, inv)


    def working_tree(self):
        """Return a `Tree` for the working copy."""
        return WorkingTree(self.base, self.read_working_inventory())


    def basis_tree(self):
        """Return `Tree` object for last revision.

        If there are no revisions yet, return an `EmptyTree`.

        >>> b = ScratchBranch(files=['foo'])
        >>> b.basis_tree().has_filename('foo')
        False
        >>> b.working_tree().has_filename('foo')
        True
        >>> b.add('foo')
        >>> b.commit('add foo')
        >>> b.basis_tree().has_filename('foo')
        True
        """
        r = self.last_patch()
        if r == None:
            return EmptyTree()
        else:
            return RevisionTree(self.text_store, self.get_revision_inventory(r))



    def write_log(self, show_timezone='original'):
        """Write out human-readable log of commits to this branch

        :param utc: If true, show dates in universal time, not local time."""
        ## TODO: Option to choose either original, utc or local timezone
        revno = 1
        precursor = None
        for p in self.revision_history():
            print '-' * 40
            print 'revno:', revno
            ## TODO: Show hash if --id is given.
            ##print 'revision-hash:', p
            rev = self.get_revision(p)
            print 'committer:', rev.committer
            print 'timestamp: %s' % (format_date(rev.timestamp, rev.timezone or 0,
                                                 show_timezone))

            ## opportunistic consistency check, same as check_patch_chaining
            if rev.precursor != precursor:
                bailout("mismatched precursor!")

            print 'message:'
            if not rev.message:
                print '  (no message)'
            else:
                for l in rev.message.split('\n'):
                    print '  ' + l

            revno += 1
            precursor = p



    def show_status(branch, show_all=False):
        """Display single-line status for non-ignored working files.

        The list is show sorted in order by file name.

        >>> b = ScratchBranch(files=['foo', 'foo~'])
        >>> b.show_status()
        ?       foo
        >>> b.add('foo')
        >>> b.show_status()
        A       foo
        >>> b.commit("add foo")
        >>> b.show_status()

        :todo: Get state for single files.

        :todo: Perhaps show a slash at the end of directory names.        

        """

        # We have to build everything into a list first so that it can
        # sorted by name, incorporating all the different sources.

        # FIXME: Rather than getting things in random order and then sorting,
        # just step through in order.

        # Interesting case: the old ID for a file has been removed,
        # but a new file has been created under that name.

        old = branch.basis_tree()
        old_inv = old.inventory
        new = branch.working_tree()
        new_inv = new.inventory

        for fs, fid, oldname, newname, kind in diff_trees(old, new):
            if fs == 'R':
                show_status(fs, kind,
                            oldname + ' => ' + newname)
            elif fs == 'A' or fs == 'M':
                show_status(fs, kind, newname)
            elif fs == 'D':
                show_status(fs, kind, oldname)
            elif fs == '.':
                if show_all:
                    show_status(fs, kind, newname)
            elif fs == 'I':
                if show_all:
                    show_status(fs, kind, newname)
            elif fs == '?':
                show_status(fs, kind, newname)
            else:
                bailout("wierd file state %r" % ((fs, fid),))
                


class ScratchBranch(Branch):
    """Special test class: a branch that cleans up after itself.

    >>> b = ScratchBranch()
    >>> isdir(b.base)
    True
    >>> bd = b.base
    >>> del b
    >>> isdir(bd)
    False
    """
    def __init__(self, files = []):
        """Make a test branch.

        This creates a temporary directory and runs init-tree in it.

        If any files are listed, they are created in the working copy.
        """
        Branch.__init__(self, tempfile.mkdtemp(), init=True)
        for f in files:
            file(os.path.join(self.base, f), 'w').write('content of %s' % f)


    def __del__(self):
        """Destroy the test branch, removing the scratch directory."""
        shutil.rmtree(self.base)

    

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
        filename = head
    return False



def _gen_revision_id(when):
    """Return new revision-id."""
    s = '%s-%s-' % (user_email(), compact_date(when))
    s += hexlify(rand_bytes(8))
    return s


def _gen_file_id(name):
    """Return new file id.

    This should probably generate proper UUIDs, but for the moment we
    cope with just randomness because running uuidgen every time is
    slow."""
    assert '/' not in name
    while name[0] == '.':
        name = name[1:]
    s = hexlify(rand_bytes(8))
    return '-'.join((name, compact_date(time.time()), s))


