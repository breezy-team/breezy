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

from copy import deepcopy
from cStringIO import StringIO
from unittest import TestSuite
import xml.sax.saxutils


import bzrlib.bzrdir as bzrdir
from bzrlib.decorators import needs_read_lock, needs_write_lock
import bzrlib.errors as errors
from bzrlib.errors import InvalidRevisionId
from bzrlib.lockable_files import LockableFiles
from bzrlib.osutils import safe_unicode
from bzrlib.revision import NULL_REVISION
from bzrlib.store import copy_all
from bzrlib.store.weave import WeaveStore
from bzrlib.store.text import TextStore
from bzrlib.trace import mutter
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

    @needs_read_lock
    def all_revision_ids(self):
        """Returns a list of all the revision ids in the repository.

        It would be nice to have this topologically sorted, but its not yet.
        """
        possible_ids = self.get_inventory_weave().names()
        result = []
        for id in possible_ids:
            if self.has_revision(id):
               result.append(id)
        return result

    @staticmethod
    def create(a_bzrdir):
        """Construct the current default format repository in a_bzrdir."""
        return RepositoryFormat.get_default_format().initialize(a_bzrdir)

    def __init__(self, transport, branch_format, _format=None, a_bzrdir=None):
        object.__init__(self)
        if transport is not None:
            self.control_files = LockableFiles(transport.clone(bzrlib.BZRDIR), 'README')
        else: 
            # TODO: clone into repository if needed
            self.control_files = LockableFiles(a_bzrdir.transport, 'README')

        dir_mode = self.control_files._dir_mode
        file_mode = self.control_files._file_mode
        self._format = _format
        self.bzrdir = a_bzrdir

        def get_weave(name, prefixed=False):
            if name:
                name = safe_unicode(name)
            else:
                name = ''
            relpath = self.control_files._escape(name)
            weave_transport = self.control_files._transport.clone(relpath)
            ws = WeaveStore(weave_transport, prefixed=prefixed,
                            dir_mode=dir_mode,
                            file_mode=file_mode)
            if self.control_files._transport.should_cache():
                ws.enable_cache = True
            return ws


        def get_store(name, compressed=True, prefixed=False):
            # FIXME: This approach of assuming stores are all entirely compressed
            # or entirely uncompressed is tidy, but breaks upgrade from 
            # some existing branches where there's a mixture; we probably 
            # still want the option to look for both.
            if name:
                name = safe_unicode(name)
            else:
                name = ''
            relpath = self.control_files._escape(name)
            store = TextStore(self.control_files._transport.clone(relpath),
                              prefixed=prefixed, compressed=compressed,
                              dir_mode=dir_mode,
                              file_mode=file_mode)
            #if self._transport.should_cache():
            #    cache_path = os.path.join(self.cache_root, name)
            #    os.mkdir(cache_path)
            #    store = bzrlib.store.CachedStore(store, cache_path)
            return store

        if branch_format is not None:
            # circular dependencies:
            from bzrlib.branch import (BzrBranchFormat4,
                                       BzrBranchFormat5,
                                       BzrBranchFormat6,
                                       )
            if isinstance(branch_format, BzrBranchFormat4):
                self._format = RepositoryFormat4()
            elif isinstance(branch_format, BzrBranchFormat5):
                self._format = RepositoryFormat5()
            elif isinstance(branch_format, BzrBranchFormat6):
                self._format = RepositoryFormat6()
            

        if isinstance(self._format, RepositoryFormat4):
            self.inventory_store = get_store('inventory-store')
            self.text_store = get_store('text-store')
            self.revision_store = get_store('revision-store')
        elif isinstance(self._format, RepositoryFormat5):
            self.control_weaves = get_weave('')
            self.weave_store = get_weave('weaves')
            self.revision_store = get_store('revision-store', compressed=False)
        elif isinstance(self._format, RepositoryFormat6):
            self.control_weaves = get_weave('')
            self.weave_store = get_weave('weaves', prefixed=True)
            self.revision_store = get_store('revision-store', compressed=False,
                                            prefixed=True)
        self.revision_store.register_suffix('sig')

    def lock_write(self):
        self.control_files.lock_write()

    def lock_read(self):
        self.control_files.lock_read()

    @staticmethod
    def open(base):
        """Open the repository rooted at base.

        For instance, if the repository is at URL/.bzr/repository,
        Repository.open(URL) -> a Repository instance.
        """
        control = bzrdir.BzrDir.open(base)
        return control.open_repository()

    def push_stores(self, to, revision=NULL_REVISION):
        """FIXME: document and find a consistent name with other classes."""
        if (not isinstance(self._format, RepositoryFormat4) or
            self._format != to._format):
            from bzrlib.fetch import RepoFetcher
            mutter("Using fetch logic to push between %s(%s) and %s(%s)",
                   self, self._format, to, to._format)
            RepoFetcher(to_repository=to, from_repository=self,
                         last_revision=revision)
            return

        # format 4 to format 4 logic only.
        store_pairs = ((self.text_store,      to.text_store),
                       (self.inventory_store, to.inventory_store),
                       (self.revision_store,  to.revision_store))
        try:
            for from_store, to_store in store_pairs: 
                copy_all(from_store, to_store)
        except UnlistableStore:
            raise UnlistableBranch(from_store)

    def unlock(self):
        self.control_files.unlock()

    @needs_read_lock
    def clone(self, a_bzrdir):
        """Clone this repository into a_bzrdir using the current format.

        Currently no check is made that the format of this repository and
        the bzrdir format are compatible. FIXME RBC 20060201.
        """
        result = self._format.initialize(a_bzrdir)
        self.copy(result)
        return result

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

    def fileid_involved_between_revs(self, from_revid, to_revid):
        """Find file_id(s) which are involved in the changes between revisions.

        This determines the set of revisions which are involved, and then
        finds all file ids affected by those revisions.
        """
        # TODO: jam 20060119 This code assumes that w.inclusions will
        #       always be correct. But because of the presence of ghosts
        #       it is possible to be wrong.
        #       One specific example from Robert Collins:
        #       Two branches, with revisions ABC, and AD
        #       C is a ghost merge of D.
        #       Inclusions doesn't recognize D as an ancestor.
        #       If D is ever merged in the future, the weave
        #       won't be fixed, because AD never saw revision C
        #       to cause a conflict which would force a reweave.
        w = self.get_inventory_weave()
        from_set = set(w.inclusions([w.lookup(from_revid)]))
        to_set = set(w.inclusions([w.lookup(to_revid)]))
        included = to_set.difference(from_set)
        changed = map(w.idx_to_name, included)
        return self._fileid_involved_by_set(changed)

    def fileid_involved(self, last_revid=None):
        """Find all file_ids modified in the ancestry of last_revid.

        :param last_revid: If None, last_revision() will be used.
        """
        w = self.get_inventory_weave()
        if not last_revid:
            changed = set(w._names)
        else:
            included = w.inclusions([w.lookup(last_revid)])
            changed = map(w.idx_to_name, included)
        return self._fileid_involved_by_set(changed)

    def fileid_involved_by_set(self, changes):
        """Find all file_ids modified by the set of revisions passed in.

        :param changes: A set() of revision ids
        """
        # TODO: jam 20060119 This line does *nothing*, remove it.
        #       or better yet, change _fileid_involved_by_set so
        #       that it takes the inventory weave, rather than
        #       pulling it out by itself.
        return self._fileid_involved_by_set(changes)

    def _fileid_involved_by_set(self, changes):
        """Find the set of file-ids affected by the set of revisions.

        :param changes: A set() of revision ids.
        :return: A set() of file ids.
        
        This peaks at the Weave, interpreting each line, looking to
        see if it mentions one of the revisions. And if so, includes
        the file id mentioned.
        This expects both the Weave format, and the serialization
        to have a single line per file/directory, and to have
        fileid="" and revision="" on that line.
        """
        assert (isinstance(self._format, RepositoryFormat5) or
                isinstance(self._format, RepositoryFormat6)), \
            "fileid_involved only supported for branches which store inventory as xml"

        w = self.get_inventory_weave()
        file_ids = set()
        for line in w._weave:

            # it is ugly, but it is due to the weave structure
            if not isinstance(line, basestring): continue

            start = line.find('file_id="')+9
            if start < 9: continue
            end = line.find('"', start)
            assert end>= 0
            file_id = xml.sax.saxutils.unescape(line[start:end])

            # check if file_id is already present
            if file_id in file_ids: continue

            start = line.find('revision="')+10
            if start < 10: continue
            end = line.find('"', start)
            assert end>= 0
            revision_id = xml.sax.saxutils.unescape(line[start:end])

            if revision_id in changes:
                file_ids.add(file_id)
        return file_ids

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
        if not self.has_revision(revision_id):
            raise errors.NoSuchRevision(self, revision_id)
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


class RepositoryFormat(object):
    """A repository format.

    Formats provide three things:
     * An initialization routine to construct repository data on disk.
     * a format string which is used when the BzrDir supports versioned
       children.
     * an open routine which returns a Repository instance.

    Formats are placed in an dict by their format string for reference 
    during opening. These should be subclasses of RepositoryFormat
    for consistency.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the 
    object will be created every system load.

    Common instance attributes:
    _matchingbzrdir - the bzrdir format that the repository format was
    originally written to work with. This can be used if manually
    constructing a bzrdir and repository, or more commonly for test suite
    parameterisation.
    """

    _default_format = None
    """The default format used for new repositories."""

    _formats = {}
    """The known formats."""

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format

    def get_format_string(self):
        """Return the ASCII format string that identifies this format.
        
        Note that in pre format ?? repositories the format string is 
        not permitted nor written to disk.
        """
        raise NotImplementedError(self.get_format_string)

    def initialize(self, a_bzrdir):
        """Create a weave repository.
        
        TODO: when creating split out bzr branch formats, move this to a common
        base for Format5, Format6. or something like that.
        """
        from bzrlib.weavefile import write_weave_v5
        from bzrlib.weave import Weave
        
        # Create an empty weave
        sio = StringIO()
        bzrlib.weavefile.write_weave_v5(Weave(), sio)
        empty_weave = sio.getvalue()

        mutter('creating repository in %s.', a_bzrdir.transport.base)
        dirs = ['revision-store', 'weaves']
        lock_file = 'branch-lock'
        files = [('inventory.weave', StringIO(empty_weave)), 
                 ]
        
        # FIXME: RBC 20060125 dont peek under the covers
        # NB: no need to escape relative paths that are url safe.
        control_files = LockableFiles(a_bzrdir.transport, 'branch-lock')
        control_files.lock_write()
        control_files._transport.mkdir_multi(dirs,
                mode=control_files._dir_mode)
        try:
            for file, content in files:
                control_files.put(file, content)
        finally:
            control_files.unlock()
        return Repository(None, branch_format=None, _format=self, a_bzrdir=a_bzrdir)

    def is_supported(self):
        """Is this format supported?

        Supported formats must be initializable and openable.
        Unsupported formats may not support initialization or committing or 
        some other features depending on the reason for not being supported.
        """
        return True

    def open(self, a_bzrdir, _found=False):
        """Return an instance of this format for the bzrdir a_bzrdir.
        
        _found is a private parameter, do not use it.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        return Repository(None, branch_format=None, _format=self, a_bzrdir=a_bzrdir)

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


class RepositoryFormat4(RepositoryFormat):
    """Bzr repository format 4.

    This repository format has:
     - flat stores
     - TextStores for texts, inventories,revisions.

    This format is deprecated: it indexes texts using a text id which is
    removed in format 5; initializationa and write support for this format
    has been removed.
    """

    def __init__(self):
        super(RepositoryFormat4, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat4()

    def initialize(self, url):
        """Format 4 branches cannot be created."""
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Format 4 is not supported.

        It is not supported because the model changed from 4 to 5 and the
        conversion logic is expensive - so doing it on the fly was not 
        feasible.
        """
        return False


class RepositoryFormat5(RepositoryFormat):
    """Bzr control format 5.

    This repository format has:
     - weaves for file texts and inventory
     - flat stores
     - TextStores for revisions and signatures.
    """

    def __init__(self):
        super(RepositoryFormat5, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat5()


class RepositoryFormat6(RepositoryFormat):
    """Bzr control format 6.

    This repository format has:
     - weaves for file texts and inventory
     - hash subdirectory based stores.
     - TextStores for revisions and signatures.
    """

    def __init__(self):
        super(RepositoryFormat6, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat6()

# formats which have no format string are not discoverable
# and not independently creatable, so are not registered.
# __default_format = RepositoryFormatXXX()
# RepositoryFormat.register_format(__default_format)
# RepositoryFormat.set_default_format(__default_format)
_legacy_formats = [RepositoryFormat4(),
                   RepositoryFormat5(),
                   RepositoryFormat6()]


# TODO: jam 20060108 Create a new branch format, and as part of upgrade
#       make sure that ancestry.weave is deleted (it is never used, but
#       used to be created)

class RepositoryTestProviderAdapter(object):
    """A tool to generate a suite testing multiple repository formats at once.

    This is done by copying the test once for each transport and injecting
    the transport_server, transport_readonly_server, and bzrdir_format and
    repository_format classes into each copy. Each copy is also given a new id()
    to make it easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._formats = formats
    
    def adapt(self, test):
        result = TestSuite()
        for repository_format, bzrdir_format in self._formats:
            new_test = deepcopy(test)
            new_test.transport_server = self._transport_server
            new_test.transport_readonly_server = self._transport_readonly_server
            new_test.bzrdir_format = bzrdir_format
            new_test.repository_format = repository_format
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), repository_format.__class__.__name__)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result
