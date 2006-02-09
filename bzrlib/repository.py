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

from cStringIO import StringIO

from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.errors import InvalidRevisionId
from bzrlib.lockable_files import LockableFiles
from bzrlib.osutils import safe_unicode
from bzrlib.revision import NULL_REVISION
from bzrlib.store import copy_all
from bzrlib.store.weave import WeaveStore
from bzrlib.store.text import TextStore
from bzrlib.tree import RevisionTree
from bzrlib.testament import Testament
from bzrlib.tree import EmptyTree
import bzrlib.xml5



class Repository(object):
    """Repository holding history for one or more branches.

    The repository holds and retrieves historical information including
    revisions and file history.  It's normally accessed only by the Branch,
    which views a particular line of development through that history.

    The Repository builds on top of Stores and a Transport, which respectively 
    describe the disk data format and the way of accessing the (possibly 
    remote) disk.
    """

    def __init__(self, transport, branch_format):
        # circular dependencies:
        from bzrlib.branch import (BzrBranchFormat4,
                                   BzrBranchFormat5,
                                   BzrBranchFormat6,
                                   BzrBranchFormat7_escape,
                                   )
        object.__init__(self)
        self.control_files = LockableFiles(transport.clone(bzrlib.BZRDIR), 'README')

        dir_mode = self.control_files._dir_mode
        file_mode = self.control_files._file_mode

        def get_weave(name, prefixed=False, escaped=False):
            if name:
                name = bzrlib.BZRDIR + '/' + safe_unicode(name)
            else:
                name = bzrlib.BZRDIR
            relpath = self.control_files._escape(name)
            weave_transport = transport.clone(relpath)
            ws = WeaveStore(weave_transport, prefixed=prefixed,
                            dir_mode=dir_mode,
                            file_mode=file_mode, escaped=escaped)
            if self.control_files._transport.should_cache():
                ws.enable_cache = True
            return ws


        def get_store(name, compressed=True, prefixed=False, escaped=False):
            # FIXME: This approach of assuming stores are all entirely compressed
            # or entirely uncompressed is tidy, but breaks upgrade from 
            # some existing branches where there's a mixture; we probably 
            # still want the option to look for both.
            if name:
                name = bzrlib.BZRDIR + '/' + safe_unicode(name)
            else:
                name = bzrlib.BZRDIR
            relpath = self.control_files._escape(name)
            store = TextStore(transport.clone(relpath),
                              prefixed=prefixed, compressed=compressed,
                              dir_mode=dir_mode,
                              file_mode=file_mode, escaped=escaped)
            #if self._transport.should_cache():
            #    cache_path = os.path.join(self.cache_root, name)
            #    os.mkdir(cache_path)
            #    store = bzrlib.store.CachedStore(store, cache_path)
            return store


        if isinstance(branch_format, BzrBranchFormat4):
            self.inventory_store = get_store('inventory-store')
            self.text_store = get_store('text-store')
            self.revision_store = get_store('revision-store')
        elif isinstance(branch_format, BzrBranchFormat5):
            self.control_weaves = get_weave('')
            self.weave_store = get_weave('weaves')
            self.revision_store = get_store('revision-store', compressed=False)
        elif isinstance(branch_format, BzrBranchFormat6):
            self.control_weaves = get_weave('')
            self.weave_store = get_weave('weaves', prefixed=True)
            self.revision_store = get_store('revision-store', compressed=False,
                                            prefixed=True)
        elif isinstance(branch_format, BzrBranchFormat7_escape):
            self.control_weaves = get_weave('', escaped=True)
            self.weave_store = get_weave('weaves', prefixed=True, escaped=True)
            self.revision_store = get_store('revision-store', compressed=False,
                                            prefixed=True, escaped=True)
        self.revision_store.register_suffix('sig')

    def lock_write(self):
        self.control_files.lock_write()

    def lock_read(self):
        self.control_files.lock_read()

    def unlock(self):
        self.control_files.unlock()

    @needs_read_lock
    def copy(self, destination):
        destination.lock_write()
        try:
            destination.control_weaves.copy_multi(self.control_weaves, 
                ['inventory'])
            copy_all(self.weave_store, destination.weave_store)
            copy_all(self.revision_store, destination.revision_store)
        finally:
            destination.unlock()

    def has_revision(self, revision_id):
        """True if this branch has a copy of the revision.

        This does not necessarily imply the revision is merge
        or on the mainline."""
        return (revision_id is None
                or self.revision_store.has_id(revision_id))

    @needs_read_lock
    def get_revision_xml_file(self, revision_id):
        """Return XML file object for revision object."""
        if not revision_id or not isinstance(revision_id, basestring):
            raise InvalidRevisionId(revision_id=revision_id, branch=self)
        try:
            return self.revision_store.get(revision_id)
        except (IndexError, KeyError):
            raise bzrlib.errors.NoSuchRevision(self, revision_id)

    @needs_read_lock
    def get_revision_xml(self, revision_id):
        return self.get_revision_xml_file(revision_id).read()

    @needs_read_lock
    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        xml_file = self.get_revision_xml_file(revision_id)

        try:
            r = bzrlib.xml5.serializer_v5.read_revision(xml_file)
        except SyntaxError, e:
            raise bzrlib.errors.BzrError('failed to unpack revision_xml',
                                         [revision_id,
                                          str(e)])
            
        assert r.revision_id == revision_id
        return r

    @needs_read_lock
    def get_revision_sha1(self, revision_id):
        """Hash the stored value of a revision, and return it."""
        # In the future, revision entries will be signed. At that
        # point, it is probably best *not* to include the signature
        # in the revision hash. Because that lets you re-sign
        # the revision, (add signatures/remove signatures) and still
        # have all hash pointers stay consistent.
        # But for now, just hash the contents.
        return bzrlib.osutils.sha_file(self.get_revision_xml_file(revision_id))

    @needs_write_lock
    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        self.revision_store.add(StringIO(gpg_strategy.sign(plaintext)), 
                                revision_id, "sig")

    @needs_read_lock
    def get_inventory_weave(self):
        return self.control_weaves.get_weave('inventory',
            self.get_transaction())

    @needs_read_lock
    def get_inventory(self, revision_id):
        """Get Inventory object by hash."""
        xml = self.get_inventory_xml(revision_id)
        return bzrlib.xml5.serializer_v5.read_inventory_from_string(xml)

    @needs_read_lock
    def get_inventory_xml(self, revision_id):
        """Get inventory XML as a file object."""
        try:
            assert isinstance(revision_id, basestring), type(revision_id)
            iw = self.get_inventory_weave()
            return iw.get_text(iw.lookup(revision_id))
        except IndexError:
            raise bzrlib.errors.HistoryMissing(self, 'inventory', revision_id)

    @needs_read_lock
    def get_inventory_sha1(self, revision_id):
        """Return the sha1 hash of the inventory entry
        """
        return self.get_revision(revision_id).inventory_sha1

    @needs_read_lock
    def get_revision_inventory(self, revision_id):
        """Return inventory of a past revision."""
        # TODO: Unify this with get_inventory()
        # bzr 0.0.6 and later imposes the constraint that the inventory_id
        # must be the same as its revision, so this is trivial.
        if revision_id is None:
            # This does not make sense: if there is no revision,
            # then it is the current tree inventory surely ?!
            # and thus get_root_id() is something that looks at the last
            # commit on the branch, and the get_root_id is an inventory check.
            raise NotImplementedError
            # return Inventory(self.get_root_id())
        else:
            return self.get_inventory(revision_id)

    @needs_read_lock
    def revision_tree(self, revision_id):
        """Return Tree for a revision on this branch.

        `revision_id` may be None for the null revision, in which case
        an `EmptyTree` is returned."""
        # TODO: refactor this to use an existing revision object
        # so we don't need to read it in twice.
        if revision_id is None or revision_id == NULL_REVISION:
            return EmptyTree()
        else:
            inv = self.get_revision_inventory(revision_id)
            return RevisionTree(self, inv, revision_id)

    @needs_read_lock
    def get_ancestry(self, revision_id):
        """Return a list of revision-ids integrated by a revision.
        
        This is topologically sorted.
        """
        if revision_id is None:
            return [None]
        w = self.get_inventory_weave()
        return [None] + map(w.idx_to_name,
                            w.inclusions([w.lookup(revision_id)]))

    @needs_read_lock
    def print_file(self, file, revision_id):
        """Print `file` to stdout.
        
        FIXME RBC 20060125 as John Meinel points out this is a bad api
        - it writes to stdout, it assumes that that is valid etc. Fix
        by creating a new more flexible convenience function.
        """
        tree = self.revision_tree(revision_id)
        # use inventory as it was in that revision
        file_id = tree.inventory.path2id(file)
        if not file_id:
            raise BzrError("%r is not present in revision %s" % (file, revno))
            try:
                revno = self.revision_id_to_revno(revision_id)
            except errors.NoSuchRevision:
                # TODO: This should not be BzrError,
                # but NoSuchFile doesn't fit either
                raise BzrError('%r is not present in revision %s' 
                                % (file, revision_id))
            else:
                raise BzrError('%r is not present in revision %s'
                                % (file, revno))
        tree.print_file(file_id)

    def get_transaction(self):
        return self.control_files.get_transaction()

    @needs_write_lock
    def sign_revision(self, revision_id, gpg_strategy):
        plaintext = Testament.from_revision(self, revision_id).as_short_text()
        self.store_revision_signature(gpg_strategy, plaintext, revision_id)
