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

To get a WorkingTree, call bzrdir.open_workingtree() or
WorkingTree.open(dir).
"""

MERGE_MODIFIED_HEADER_1 = "BZR merge-modified list format 1"

# FIXME: I don't know if writing out the cache from the destructor is really a
# good idea, because destructors are considered poor taste in Python, and it's
# not predictable when it will be written out.

# TODO: Give the workingtree sole responsibility for the working inventory;
# remove the variable and references to it from the branch.  This may require
# updating the commit code so as to update the inventory within the working
# copy, and making sure there's only one WorkingTree for any directory on disk.
# At the momenthey may alias the inventory and have old copies of it in memory.

from copy import deepcopy
from cStringIO import StringIO
import errno
import fnmatch
import os
import re
import stat
 

from bzrlib.atomicfile import AtomicFile
from bzrlib.branch import (Branch,
                           quotefn)
import bzrlib.bzrdir as bzrdir
from bzrlib.decorators import needs_read_lock, needs_write_lock
import bzrlib.errors as errors
from bzrlib.errors import (BzrCheckError,
                           BzrError,
                           DivergedBranches,
                           WeaveRevisionNotPresent,
                           NotBranchError,
                           NoSuchFile,
                           NotVersionedError,
                           MergeModifiedFormatError)
from bzrlib.inventory import InventoryEntry, Inventory
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.merge import merge_inner, transform_tree
from bzrlib.osutils import (
                            abspath,
                            appendpath,
                            compact_date,
                            file_kind,
                            isdir,
                            getcwd,
                            pathjoin,
                            pumpfile,
                            safe_unicode,
                            splitpath,
                            rand_bytes,
                            normpath,
                            realpath,
                            relpath,
                            rename,
                            supports_executable,
                            )
from bzrlib.progress import DummyProgress
from bzrlib.revision import NULL_REVISION
from bzrlib.rio import RioReader, RioWriter, Stanza
from bzrlib.symbol_versioning import *
from bzrlib.textui import show_status
import bzrlib.tree
from bzrlib.trace import mutter
from bzrlib.transform import build_tree
from bzrlib.transport import get_transport
from bzrlib.transport.local import LocalTransport
import bzrlib.ui
import bzrlib.xml5

_non_word_re = None
def _get_non_word_re():
    """Get the compiled regular expression for non-unicode words."""
    global _non_word_re
    if _non_word_re is None:

        # TODO: jam 20060106 Currently the BZR codebase can't really handle
        #           unicode ids. There are a lot of code paths which don't
        #           expect them. And we need to do more serious testing
        #           before we enable unicode in ids.
        #_non_word_re = re.compile(r'[^\w.]', re.UNICODE)
        _non_word_re = re.compile(r'[^\w.]')
    return _non_word_re


def gen_file_id(name):
    """Return new file id.

    This should probably generate proper UUIDs, but for the moment we
    cope with just randomness because running uuidgen every time is
    slow.
    """
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
    non_word = _get_non_word_re()
    name = non_word.sub('', name)

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

    def __init__(self, basedir='.',
                 branch=DEPRECATED_PARAMETER,
                 _inventory=None,
                 _control_files=None,
                 _internal=False,
                 _format=None,
                 _bzrdir=None):
        """Construct a WorkingTree for basedir.

        If the branch is not supplied, it is opened automatically.
        If the branch is supplied, it must be the branch for this basedir.
        (branch.base is not cross checked, because for remote branches that
        would be meaningless).
        """
        self._format = _format
        self.bzrdir = _bzrdir
        if not _internal:
            # not created via open etc.
            warn("WorkingTree() is deprecated as of bzr version 0.8. "
                 "Please use bzrdir.open_workingtree or WorkingTree.open().",
                 DeprecationWarning,
                 stacklevel=2)
            wt = WorkingTree.open(basedir)
            self.branch = wt.branch
            self.basedir = wt.basedir
            self._control_files = wt._control_files
            self._hashcache = wt._hashcache
            self._set_inventory(wt._inventory)
            self._format = wt._format
            self.bzrdir = wt.bzrdir
        from bzrlib.hashcache import HashCache
        from bzrlib.trace import note, mutter
        assert isinstance(basedir, basestring), \
            "base directory %r is not a string" % basedir
        basedir = safe_unicode(basedir)
        mutter("opening working tree %r", basedir)
        if deprecated_passed(branch):
            if not _internal:
                warn("WorkingTree(..., branch=XXX) is deprecated as of bzr 0.8."
                     " Please use bzrdir.open_workingtree() or WorkingTree.open().",
                     DeprecationWarning,
                     stacklevel=2
                     )
            self.branch = branch
        else:
            self.branch = self.bzrdir.open_branch()
        assert isinstance(self.branch, Branch), \
            "branch %r is not a Branch" % self.branch
        self.basedir = realpath(basedir)
        # if branch is at our basedir and is a format 6 or less
        if isinstance(self._format, WorkingTreeFormat2):
            # share control object
            self._control_files = self.branch.control_files
        elif _control_files is not None:
            assert False, "not done yet"
#            self._control_files = _control_files
        else:
            # only ready for format 3
            assert isinstance(self._format, WorkingTreeFormat3)
            self._control_files = LockableFiles(
                self.bzrdir.get_workingtree_transport(None),
                'lock', TransportLock)

        # update the whole cache up front and write to disk if anything changed;
        # in the future we might want to do this more selectively
        # two possible ways offer themselves : in self._unlock, write the cache
        # if needed, or, when the cache sees a change, append it to the hash
        # cache file, and have the parser take the most recent entry for a
        # given path only.
        cache_filename = self.bzrdir.get_workingtree_transport(None).abspath('stat-cache')
        hc = self._hashcache = HashCache(basedir, cache_filename, self._control_files._file_mode)
        hc.read()
        # is this scan needed ? it makes things kinda slow.
        hc.scan()

        if hc.needs_write:
            mutter("write hc")
            hc.write()

        if _inventory is None:
            self._set_inventory(self.read_working_inventory())
        else:
            self._set_inventory(_inventory)

    def _set_inventory(self, inv):
        self._inventory = inv
        self.path2id = self._inventory.path2id

    def is_control_filename(self, filename):
        """True if filename is the name of a control file in this tree.
        
        This is true IF and ONLY IF the filename is part of the meta data
        that bzr controls in this tree. I.E. a random .bzr directory placed
        on disk will not be a control file for this tree.
        """
        try:
            self.bzrdir.transport.relpath(self.abspath(filename))
            return True
        except errors.PathNotChild:
            return False

    @staticmethod
    def open(path=None, _unsupported=False):
        """Open an existing working tree at path.

        """
        if path is None:
            path = os.path.getcwdu()
        control = bzrdir.BzrDir.open(path, _unsupported)
        return control.open_workingtree(_unsupported)
        
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
            path = os.getcwdu()
        control, relpath = bzrdir.BzrDir.open_containing(path)
        return control.open_workingtree(), relpath

    @staticmethod
    def open_downlevel(path=None):
        """Open an unsupported working tree.

        Only intended for advanced situations like upgrading part of a bzrdir.
        """
        return WorkingTree.open(path, _unsupported=True)

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
    
    def basis_tree(self):
        """Return RevisionTree for the current last revision."""
        revision_id = self.last_revision()
        if revision_id is not None:
            try:
                xml = self.read_basis_inventory(revision_id)
                inv = bzrlib.xml5.serializer_v5.read_inventory_from_string(xml)
                return bzrlib.tree.RevisionTree(self.branch.repository, inv,
                                                revision_id)
            except NoSuchFile:
                pass
        return self.branch.repository.revision_tree(revision_id)

    @staticmethod
    @deprecated_method(zero_eight)
    def create(branch, directory):
        """Create a workingtree for branch at directory.

        If existing_directory already exists it must have a .bzr directory.
        If it does not exist, it will be created.

        This returns a new WorkingTree object for the new checkout.

        TODO FIXME RBC 20060124 when we have checkout formats in place this
        should accept an optional revisionid to checkout [and reject this if
        checking out into the same dir as a pre-checkout-aware branch format.]

        XXX: When BzrDir is present, these should be created through that 
        interface instead.
        """
        warn('delete WorkingTree.create', stacklevel=3)
        transport = get_transport(directory)
        if branch.bzrdir.root_transport.base == transport.base:
            # same dir 
            return branch.bzrdir.create_workingtree()
        # different directory, 
        # create a branch reference
        # and now a working tree.
        raise NotImplementedError
 
    @staticmethod
    @deprecated_method(zero_eight)
    def create_standalone(directory):
        """Create a checkout and a branch and a repo at directory.

        Directory must exist and be empty.

        please use BzrDir.create_standalone_workingtree
        """
        return bzrdir.BzrDir.create_standalone_workingtree(directory)

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

    @needs_read_lock
    def clone(self, to_bzrdir, revision_id=None, basis=None):
        """Duplicate this working tree into to_bzr, including all state.
        
        Specifically modified files are kept as modified, but
        ignored and unknown files are discarded.

        If you want to make a new line of development, see bzrdir.sprout()

        revision
            If not None, the cloned tree will have its last revision set to 
            revision, and and difference between the source trees last revision
            and this one merged in.

        basis
            If not None, a closer copy of a tree which may have some files in
            common, and which file content should be preferentially copied from.
        """
        # assumes the target bzr dir format is compatible.
        result = self._format.initialize(to_bzrdir)
        self.copy_content_into(result, revision_id)
        return result

    @needs_read_lock
    def copy_content_into(self, tree, revision_id=None):
        """Copy the current content and user files of this tree into tree."""
        if revision_id is None:
            transform_tree(tree, self)
        else:
            # TODO now merge from tree.last_revision to revision
            transform_tree(tree, self)
            tree.set_last_revision(revision_id)

    @needs_write_lock
    def commit(self, message=None, revprops=None, *args, **kwargs):
        # avoid circular imports
        from bzrlib.commit import Commit
        if revprops is None:
            revprops = {}
        if not 'branch-nick' in revprops:
            revprops['branch-nick'] = self.branch.nick
        # args for wt.commit start at message from the Commit.commit method,
        # but with branch a kwarg now, passing in args as is results in the
        #message being used for the branch
        args = (DEPRECATED_PARAMETER, message, ) + args
        Commit().commit(working_tree=self, revprops=revprops, *args, **kwargs)
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
        if not supports_executable():
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
            if self.is_control_filename(f):
                raise BzrError("cannot add control file %s" % quotefn(f))

            fp = splitpath(f)

            if len(fp) == 0:
                raise BzrError("cannot add top-level %r" % f)

            fullpath = normpath(self.abspath(f))

            try:
                kind = file_kind(fullpath)
            except OSError, e:
                if e.errno == errno.ENOENT:
                    raise NoSuchFile(fullpath)
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
            merges_file = self._control_files.get_utf8('pending-merges')
        except OSError, e:
            if e.errno != errno.ENOENT:
                raise
            return []
        p = []
        for l in merges_file.readlines():
            p.append(l.rstrip('\n'))
        return p

    @needs_write_lock
    def set_pending_merges(self, rev_list):
        self._control_files.put_utf8('pending-merges', '\n'.join(rev_list))

    @needs_write_lock
    def set_merge_modified(self, modified_hashes):
        my_file = StringIO()
        my_file.write(MERGE_MODIFIED_HEADER_1 + '\n')
        writer = RioWriter(my_file)
        for file_id, hash in modified_hashes.iteritems():
            s = Stanza(file_id=file_id, hash=hash)
            writer.write_stanza(s)
        my_file.seek(0)
        self._control_files.put('merge-hashes', my_file)

    @needs_read_lock
    def merge_modified(self):
        try:
            hashfile = self._control_files.get('merge-hashes')
        except NoSuchFile:
            return {}
        merge_hashes = {}
        try:
            if hashfile.next() != MERGE_MODIFIED_HEADER_1 + '\n':
                raise MergeModifiedFormatError()
        except StopIteration:
            raise MergeModifiedFormatError()
        for s in RioReader(hashfile):
            file_id = s.get("file_id")
            hash = s.get("hash")
            if hash == self.get_file_sha1(file_id):
                merge_hashes[file_id] = hash
        return merge_hashes

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

                # the bzrdir for this tree
                if self.bzrdir.transport.base.endswith(f + '/'):
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
        
        >>> from bzrlib.bzrdir import ScratchDir
        >>> d = ScratchDir(files=['foo', 'foo~'])
        >>> b = d.open_branch()
        >>> tree = d.open_workingtree()
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
    def pull(self, source, overwrite=False, stop_revision=None):
        source.lock_read()
        try:
            old_revision_history = self.branch.revision_history()
            basis_tree = self.basis_tree()
            count = self.branch.pull(source, overwrite, stop_revision)
            new_revision_history = self.branch.revision_history()
            if new_revision_history != old_revision_history:
                if len(old_revision_history):
                    other_revision = old_revision_history[-1]
                else:
                    other_revision = None
                repository = self.branch.repository
                pb = bzrlib.ui.ui_factory.nested_progress_bar()
                try:
                    merge_inner(self.branch,
                                self.branch.basis_tree(),
                                basis_tree, 
                                this_tree=self, 
                                pb=pb)
                finally:
                    pb.finished()
                self.set_last_revision(self.branch.last_revision())
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
            l.extend([line.rstrip("\n\r").decode('utf-8') 
                      for line in f.readlines()])
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

        # FIXME: fnmatch also won't match unicode exact path filenames.
        #        it does seem to handle wildcard, as long as the non-wildcard
        #        characters are ascii.
        
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

    @needs_read_lock
    def last_revision(self):
        """Return the last revision id of this working tree.

        In early branch formats this was == the branch last_revision,
        but that cannot be relied upon - for working tree operations,
        always use tree.last_revision().
        """
        return self.branch.last_revision()

    def lock_read(self):
        """See Branch.lock_read, and WorkingTree.unlock."""
        self.branch.lock_read()
        try:
            return self._control_files.lock_read()
        except:
            self.branch.unlock()
            raise

    def lock_write(self):
        """See Branch.lock_write, and WorkingTree.unlock."""
        self.branch.lock_write()
        try:
            return self._control_files.lock_write()
        except:
            self.branch.unlock()
            raise

    def _basis_inventory_name(self, revision_id):
        return 'basis-inventory.%s' % revision_id

    @needs_write_lock
    def set_last_revision(self, new_revision, old_revision=None):
        """Change the last revision in the working tree."""
        self._remove_old_basis(old_revision)
        if self._change_last_revision(new_revision):
            self._cache_basis_inventory(new_revision)

    def _change_last_revision(self, new_revision):
        """Template method part of set_last_revision to perform the change."""
        if new_revision is None:
            self.branch.set_revision_history([])
            return False
        # current format is locked in with the branch
        revision_history = self.branch.revision_history()
        try:
            position = revision_history.index(new_revision)
        except ValueError:
            raise errors.NoSuchRevision(self.branch, new_revision)
        self.branch.set_revision_history(revision_history[:position + 1])
        return True

    def _cache_basis_inventory(self, new_revision):
        """Cache new_revision as the basis inventory."""
        try:
            xml = self.branch.repository.get_inventory_xml(new_revision)
            path = self._basis_inventory_name(new_revision)
            self._control_files.put_utf8(path, xml)
        except WeaveRevisionNotPresent:
            pass

    def _remove_old_basis(self, old_revision):
        """Remove the old basis inventory 'old_revision'."""
        if old_revision is not None:
            try:
                path = self._basis_inventory_name(old_revision)
                path = self._control_files._escape(path)
                self._control_files._transport.delete(path)
            except NoSuchFile:
                pass

    def read_basis_inventory(self, revision_id):
        """Read the cached basis inventory."""
        path = self._basis_inventory_name(revision_id)
        return self._control_files.get_utf8(path).read()
        
    @needs_read_lock
    def read_working_inventory(self):
        """Read the working inventory."""
        # ElementTree does its own conversion from UTF-8, so open in
        # binary.
        result = bzrlib.xml5.serializer_v5.read_inventory(
            self._control_files.get('inventory'))
        self._set_inventory(result)
        return result

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
    def revert(self, filenames, old_tree=None, backups=True, 
               pb=DummyProgress()):
        from transform import revert
        if old_tree is None:
            old_tree = self.basis_tree()
        revert(self, old_tree, filenames, backups, pb)
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
            if entry.parent_id == orig_root_id:
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
        # FIXME: We want to write out the hashcache only when the last lock on
        # this working copy is released.  Peeking at the lock count is a bit
        # of a nasty hack; probably it's better to have a transaction object,
        # which can do some finalization when it's either successfully or
        # unsuccessfully completed.  (Denys's original patch did that.)
        # RBC 20060206 hookinhg into transaction will couple lock and transaction
        # wrongly. Hookinh into unllock on the control files object is fine though.
        
        # TODO: split this per format so there is no ugly if block
        if self._hashcache.needs_write and (
            # dedicated lock files
            self._control_files._lock_count==1 or 
            # shared lock files
            (self._control_files is self.branch.control_files and 
             self._control_files._lock_count==3)):
            self._hashcache.write()
        # reverse order of locking.
        result = self._control_files.unlock()
        try:
            self.branch.unlock()
        finally:
            return result

    @needs_write_lock
    def update(self):
        """Update a working tree along its branch.

        This will update the branch if its bound too, which means we have multiple trees involved:
        The new basis tree of the master.
        The old basis tree of the branch.
        The old basis tree of the working tree.
        The current working tree state.
        pathologically all three may be different, and non ancestors of each other.
        Conceptually we want to:
        Preserve the wt.basis->wt.state changes
        Transform the wt.basis to the new master basis.
        Apply a merge of the old branch basis to get any 'local' changes from it into the tree.
        Restore the wt.basis->wt.state changes.

        There isn't a single operation at the moment to do that, so we:
        Merge current state -> basis tree of the master w.r.t. the old tree basis.
        Do a 'normal' merge of the old branch basis if it is relevant.
        """
        old_tip = self.branch.update()
        if old_tip is not None:
            self.add_pending_merge(old_tip)
        self.branch.lock_read()
        try:
            result = 0
            if self.last_revision() != self.branch.last_revision():
                # merge tree state up to new branch tip.
                basis = self.basis_tree()
                to_tree = self.branch.basis_tree()
                result += merge_inner(self.branch,
                                      to_tree,
                                      basis,
                                      this_tree=self)
                self.set_last_revision(self.branch.last_revision())
            if old_tip and old_tip != self.last_revision():
                # our last revision was not the prior branch last reivison
                # and we have converted that last revision to a pending merge.
                # base is somewhere between the branch tip now
                # and the now pending merge
                from bzrlib.revision import common_ancestor
                try:
                    base_rev_id = common_ancestor(self.branch.last_revision(),
                                                  old_tip,
                                                  self.branch.repository)
                except errors.NoCommonAncestor:
                    base_rev_id = None
                base_tree = self.branch.repository.revision_tree(base_rev_id)
                other_tree = self.branch.repository.revision_tree(old_tip)
                result += merge_inner(self.branch,
                                      other_tree,
                                      base_tree,
                                      this_tree=self)
            return result
        finally:
            self.branch.unlock()

    @needs_write_lock
    def _write_inventory(self, inv):
        """Write inventory as the current inventory."""
        sio = StringIO()
        bzrlib.xml5.serializer_v5.write_inventory(inv, sio)
        sio.seek(0)
        self._control_files.put('inventory', sio)
        self._set_inventory(inv)
        mutter('wrote working inventory')


class WorkingTree3(WorkingTree):
    """This is the Format 3 working tree.

    This differs from the base WorkingTree by:
     - having its own file lock
     - having its own last-revision property.
    """

    @needs_read_lock
    def last_revision(self):
        """See WorkingTree.last_revision."""
        try:
            return self._control_files.get_utf8('last-revision').read()
        except NoSuchFile:
            return None

    def _change_last_revision(self, revision_id):
        """See WorkingTree._change_last_revision."""
        if revision_id is None or revision_id == NULL_REVISION:
            try:
                self._control_files._transport.delete('last-revision')
            except errors.NoSuchFile:
                pass
            return False
        else:
            try:
                self.branch.revision_history().index(revision_id)
            except ValueError:
                raise errors.NoSuchRevision(self.branch, revision_id)
            self._control_files.put_utf8('last-revision', revision_id)
            return True


CONFLICT_SUFFIXES = ('.THIS', '.BASE', '.OTHER')
def get_conflicted_stem(path):
    for suffix in CONFLICT_SUFFIXES:
        if path.endswith(suffix):
            return path[:-len(suffix)]

@deprecated_function(zero_eight)
def is_control_file(filename):
    """See WorkingTree.is_control_filename(filename)."""
    ## FIXME: better check
    filename = normpath(filename)
    while filename != '':
        head, tail = os.path.split(filename)
        ## mutter('check %r for control file' % ((head, tail),))
        if tail == '.bzr':
            return True
        if filename == head:
            break
        filename = head
    return False


class WorkingTreeFormat(object):
    """An encapsulation of the initialization and open routines for a format.

    Formats provide three things:
     * An initialization routine,
     * a format string,
     * an open routine.

    Formats are placed in an dict by their format string for reference 
    during workingtree opening. Its not required that these be instances, they
    can be classes themselves with class methods - it simply depends on 
    whether state is needed for a given format or not.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the 
    object will be created every time regardless.
    """

    _default_format = None
    """The default format used for new trees."""

    _formats = {}
    """The known formats."""

    @classmethod
    def find_format(klass, a_bzrdir):
        """Return the format for the working tree object in a_bzrdir."""
        try:
            transport = a_bzrdir.get_workingtree_transport(None)
            format_string = transport.get("format").read()
            return klass._formats[format_string]
        except NoSuchFile:
            raise errors.NoWorkingTree(base=transport.base)
        except KeyError:
            raise errors.UnknownFormatError(format_string)

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format

    def get_format_string(self):
        """Return the ASCII format string that identifies this format."""
        raise NotImplementedError(self.get_format_string)

    def is_supported(self):
        """Is this format supported?

        Supported formats can be initialized and opened.
        Unsupported formats may not support initialization or committing or 
        some other features depending on the reason for not being supported.
        """
        return True

    @classmethod
    def register_format(klass, format):
        klass._formats[format.get_format_string()] = format

    @classmethod
    def set_default_format(klass, format):
        klass._default_format = format

    @classmethod
    def unregister_format(klass, format):
        assert klass._formats[format.get_format_string()] is format
        del klass._formats[format.get_format_string()]



class WorkingTreeFormat2(WorkingTreeFormat):
    """The second working tree format. 

    This format modified the hash cache from the format 1 hash cache.
    """

    def initialize(self, a_bzrdir, revision_id=None):
        """See WorkingTreeFormat.initialize()."""
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        branch = a_bzrdir.open_branch()
        if revision_id is not None:
            branch.lock_write()
            try:
                revision_history = branch.revision_history()
                try:
                    position = revision_history.index(revision_id)
                except ValueError:
                    raise errors.NoSuchRevision(branch, revision_id)
                branch.set_revision_history(revision_history[:position + 1])
            finally:
                branch.unlock()
        revision = branch.last_revision()
        inv = Inventory() 
        wt = WorkingTree(a_bzrdir.root_transport.base,
                         branch,
                         inv,
                         _internal=True,
                         _format=self,
                         _bzrdir=a_bzrdir)
        wt._write_inventory(inv)
        wt.set_root_id(inv.root.file_id)
        wt.set_last_revision(revision)
        wt.set_pending_merges([])
        build_tree(wt.basis_tree(), wt)
        return wt

    def __init__(self):
        super(WorkingTreeFormat2, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat6()

    def open(self, a_bzrdir, _found=False):
        """Return the WorkingTree object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already been done.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        return WorkingTree(a_bzrdir.root_transport.base,
                           _internal=True,
                           _format=self,
                           _bzrdir=a_bzrdir)


class WorkingTreeFormat3(WorkingTreeFormat):
    """The second working tree format updated to record a format marker.

    This format modified the hash cache from the format 1 hash cache.
    """

    def get_format_string(self):
        """See WorkingTreeFormat.get_format_string()."""
        return "Bazaar-NG Working Tree format 3"

    def initialize(self, a_bzrdir, revision_id=None):
        """See WorkingTreeFormat.initialize().
        
        revision_id allows creating a working tree at a differnet
        revision than the branch is at.
        """
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        transport = a_bzrdir.get_workingtree_transport(self)
        control_files = LockableFiles(transport, 'lock', TransportLock)
        control_files.put_utf8('format', self.get_format_string())
        branch = a_bzrdir.open_branch()
        if revision_id is None:
            revision_id = branch.last_revision()
        inv = Inventory() 
        wt = WorkingTree3(a_bzrdir.root_transport.base,
                         branch,
                         inv,
                         _internal=True,
                         _format=self,
                         _bzrdir=a_bzrdir)
        wt._write_inventory(inv)
        wt.set_root_id(inv.root.file_id)
        wt.set_last_revision(revision_id)
        wt.set_pending_merges([])
        build_tree(wt.basis_tree(), wt)
        return wt

    def __init__(self):
        super(WorkingTreeFormat3, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirMetaFormat1()

    def open(self, a_bzrdir, _found=False):
        """Return the WorkingTree object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already been done.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        return WorkingTree3(a_bzrdir.root_transport.base,
                           _internal=True,
                           _format=self,
                           _bzrdir=a_bzrdir)

    def __str__(self):
        return self.get_format_string()


# formats which have no format string are not discoverable
# and not independently creatable, so are not registered.
__default_format = WorkingTreeFormat3()
WorkingTreeFormat.register_format(__default_format)
WorkingTreeFormat.set_default_format(__default_format)
_legacy_formats = [WorkingTreeFormat2(),
                   ]


class WorkingTreeTestProviderAdapter(object):
    """A tool to generate a suite testing multiple workingtree formats at once.

    This is done by copying the test once for each transport and injecting
    the transport_server, transport_readonly_server, and workingtree_format
    classes into each copy. Each copy is also given a new id() to make it
    easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._formats = formats
    
    def adapt(self, test):
        from bzrlib.tests import TestSuite
        result = TestSuite()
        for workingtree_format, bzrdir_format in self._formats:
            new_test = deepcopy(test)
            new_test.transport_server = self._transport_server
            new_test.transport_readonly_server = self._transport_readonly_server
            new_test.bzrdir_format = bzrdir_format
            new_test.workingtree_format = workingtree_format
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), workingtree_format.__class__.__name__)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result
