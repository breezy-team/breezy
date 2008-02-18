# Copyright (C) 2005, 2006, 2007 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Deprecated weave-based repository formats.

Weave based formats scaled linearly with history size and could not represent
ghosts.
"""

from StringIO import StringIO

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    xml5,
    )
""")
from bzrlib import (
    bzrdir,
    debug,
    errors,
    lockable_files,
    lockdir,
    osutils,
    revision as _mod_revision,
    weave,
    weavefile,
    )
from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.repository import (
    CommitBuilder,
    MetaDirRepository,
    MetaDirRepositoryFormat,
    Repository,
    RepositoryFormat,
    )
from bzrlib.store.text import TextStore
from bzrlib.trace import mutter


class AllInOneRepository(Repository):
    """Legacy support - the repository behaviour for all-in-one branches."""

    @property
    def _serializer(self):
        return xml5.serializer_v5

    def __init__(self, _format, a_bzrdir, _revision_store, control_store, text_store):
        # we reuse one control files instance.
        dir_mode = a_bzrdir._control_files._dir_mode
        file_mode = a_bzrdir._control_files._file_mode

        def get_store(name, compressed=True, prefixed=False):
            # FIXME: This approach of assuming stores are all entirely compressed
            # or entirely uncompressed is tidy, but breaks upgrade from 
            # some existing branches where there's a mixture; we probably 
            # still want the option to look for both.
            relpath = a_bzrdir._control_files._escape(name)
            store = TextStore(a_bzrdir._control_files._transport.clone(relpath),
                              prefixed=prefixed, compressed=compressed,
                              dir_mode=dir_mode,
                              file_mode=file_mode)
            return store

        # not broken out yet because the controlweaves|inventory_store
        # and text_store | weave_store bits are still different.
        if isinstance(_format, RepositoryFormat4):
            # cannot remove these - there is still no consistent api 
            # which allows access to this old info.
            self.inventory_store = get_store('inventory-store')
            text_store = get_store('text-store')
        super(AllInOneRepository, self).__init__(_format, a_bzrdir, a_bzrdir._control_files, _revision_store, control_store, text_store)

    @needs_read_lock
    def _all_possible_ids(self):
        """Return all the possible revisions that we could find."""
        if 'evil' in debug.debug_flags:
            mutter_callsite(3, "_all_possible_ids scales with size of history.")
        return self.get_inventory_weave().versions()

    @needs_read_lock
    def _all_revision_ids(self):
        """Returns a list of all the revision ids in the repository. 

        These are in as much topological order as the underlying store can 
        present: for weaves ghosts may lead to a lack of correctness until
        the reweave updates the parents list.
        """
        if self._revision_store.text_store.listable():
            return self._revision_store.all_revision_ids(self.get_transaction())
        result = self._all_possible_ids()
        # TODO: jam 20070210 Ensure that _all_possible_ids returns non-unicode
        #       ids. (It should, since _revision_store's API should change to
        #       return utf8 revision_ids)
        return self._eliminate_revisions_not_present(result)

    def _check_revision_parents(self, revision, inventory):
        """Private to Repository and Fetch.
        
        This checks the parentage of revision in an inventory weave for 
        consistency and is only applicable to inventory-weave-for-ancestry
        using repository formats & fetchers.
        """
        weave_parents = inventory.get_parents(revision.revision_id)
        weave_names = inventory.versions()
        for parent_id in revision.parent_ids:
            if parent_id in weave_names:
                # this parent must not be a ghost.
                if not parent_id in weave_parents:
                    # but it is a ghost
                    raise errors.CorruptRepository(self)

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None):
        self._check_ascii_revisionid(revision_id, self.get_commit_builder)
        result = WeaveCommitBuilder(self, parents, config, timestamp, timezone,
                              committer, revprops, revision_id)
        self.start_write_group()
        return result

    @needs_read_lock
    def get_revisions(self, revision_ids):
        revs = self._get_revisions(revision_ids)
        # weave corruption can lead to absent revision markers that should be
        # present.
        # the following test is reasonably cheap (it needs a single weave read)
        # and the weave is cached in read transactions. In write transactions
        # it is not cached but typically we only read a small number of
        # revisions. For knits when they are introduced we will probably want
        # to ensure that caching write transactions are in use.
        inv = self.get_inventory_weave()
        for rev in revs:
            self._check_revision_parents(rev, inv)
        return revs

    @needs_read_lock
    def get_revision_graph(self, revision_id=None):
        """Return a dictionary containing the revision graph.
        
        :param revision_id: The revision_id to get a graph from. If None, then
        the entire revision graph is returned. This is a deprecated mode of
        operation and will be removed in the future.
        :return: a dictionary of revision_id->revision_parents_list.
        """
        if 'evil' in debug.debug_flags:
            mutter_callsite(2,
                "get_revision_graph scales with size of history.")
        # special case NULL_REVISION
        if revision_id == _mod_revision.NULL_REVISION:
            return {}
        a_weave = self.get_inventory_weave()
        all_revisions = self._eliminate_revisions_not_present(
                                a_weave.versions())
        entire_graph = dict([(node, tuple(a_weave.get_parents(node))) for 
                             node in all_revisions])
        if revision_id is None:
            return entire_graph
        elif revision_id not in entire_graph:
            raise errors.NoSuchRevision(self, revision_id)
        else:
            # add what can be reached from revision_id
            result = {}
            pending = set([revision_id])
            while len(pending) > 0:
                node = pending.pop()
                result[node] = entire_graph[node]
                for revision_id in result[node]:
                    if revision_id not in result:
                        pending.add(revision_id)
            return result

    def has_revisions(self, revision_ids):
        """See Repository.has_revisions()."""
        result = set()
        transaction = self.get_transaction()
        for revision_id in revision_ids:
            if self._revision_store.has_revision_id(revision_id, transaction):
                result.add(revision_id)
        return result

    @needs_read_lock
    def is_shared(self):
        """AllInOne repositories cannot be shared."""
        return False

    @needs_write_lock
    def set_make_working_trees(self, new_value):
        """Set the policy flag for making working trees when creating branches.

        This only applies to branches that use this repository.

        The default is 'True'.
        :param new_value: True to restore the default, False to disable making
                          working trees.
        """
        raise NotImplementedError(self.set_make_working_trees)
    
    def make_working_trees(self):
        """Returns the policy for making working trees on new branches."""
        return True

    def revision_graph_can_have_wrong_parents(self):
        # XXX: This is an old format that we don't support full checking on, so
        # just claim that checking for this inconsistency is not required.
        return False


class WeaveMetaDirRepository(MetaDirRepository):
    """A subclass of MetaDirRepository to set weave specific policy."""

    @property
    def _serializer(self):
        return xml5.serializer_v5

    @needs_read_lock
    def _all_possible_ids(self):
        """Return all the possible revisions that we could find."""
        if 'evil' in debug.debug_flags:
            mutter_callsite(3, "_all_possible_ids scales with size of history.")
        return self.get_inventory_weave().versions()

    @needs_read_lock
    def _all_revision_ids(self):
        """Returns a list of all the revision ids in the repository. 

        These are in as much topological order as the underlying store can 
        present: for weaves ghosts may lead to a lack of correctness until
        the reweave updates the parents list.
        """
        if self._revision_store.text_store.listable():
            return self._revision_store.all_revision_ids(self.get_transaction())
        result = self._all_possible_ids()
        # TODO: jam 20070210 Ensure that _all_possible_ids returns non-unicode
        #       ids. (It should, since _revision_store's API should change to
        #       return utf8 revision_ids)
        return self._eliminate_revisions_not_present(result)

    def _check_revision_parents(self, revision, inventory):
        """Private to Repository and Fetch.
        
        This checks the parentage of revision in an inventory weave for 
        consistency and is only applicable to inventory-weave-for-ancestry
        using repository formats & fetchers.
        """
        weave_parents = inventory.get_parents(revision.revision_id)
        weave_names = inventory.versions()
        for parent_id in revision.parent_ids:
            if parent_id in weave_names:
                # this parent must not be a ghost.
                if not parent_id in weave_parents:
                    # but it is a ghost
                    raise errors.CorruptRepository(self)

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None):
        self._check_ascii_revisionid(revision_id, self.get_commit_builder)
        result = WeaveCommitBuilder(self, parents, config, timestamp, timezone,
                              committer, revprops, revision_id)
        self.start_write_group()
        return result

    @needs_read_lock
    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        # TODO: jam 20070210 get_revision_reconcile should do this for us
        r = self.get_revision_reconcile(revision_id)
        # weave corruption can lead to absent revision markers that should be
        # present.
        # the following test is reasonably cheap (it needs a single weave read)
        # and the weave is cached in read transactions. In write transactions
        # it is not cached but typically we only read a small number of
        # revisions. For knits when they are introduced we will probably want
        # to ensure that caching write transactions are in use.
        inv = self.get_inventory_weave()
        self._check_revision_parents(r, inv)
        return r

    @needs_read_lock
    def get_revision_graph(self, revision_id=None):
        """Return a dictionary containing the revision graph.
        
        :param revision_id: The revision_id to get a graph from. If None, then
        the entire revision graph is returned. This is a deprecated mode of
        operation and will be removed in the future.
        :return: a dictionary of revision_id->revision_parents_list.
        """
        if 'evil' in debug.debug_flags:
            mutter_callsite(3,
                "get_revision_graph scales with size of history.")
        # special case NULL_REVISION
        if revision_id == _mod_revision.NULL_REVISION:
            return {}
        a_weave = self.get_inventory_weave()
        all_revisions = self._eliminate_revisions_not_present(
                                a_weave.versions())
        entire_graph = dict([(node, tuple(a_weave.get_parents(node))) for 
                             node in all_revisions])
        if revision_id is None:
            return entire_graph
        elif revision_id not in entire_graph:
            raise errors.NoSuchRevision(self, revision_id)
        else:
            # add what can be reached from revision_id
            result = {}
            pending = set([revision_id])
            while len(pending) > 0:
                node = pending.pop()
                result[node] = entire_graph[node]
                for revision_id in result[node]:
                    if revision_id not in result:
                        pending.add(revision_id)
            return result

    def has_revisions(self, revision_ids):
        """See Repository.has_revisions()."""
        result = set()
        transaction = self.get_transaction()
        for revision_id in revision_ids:
            if self._revision_store.has_revision_id(revision_id, transaction):
                result.add(revision_id)
        return result

    def revision_graph_can_have_wrong_parents(self):
        # XXX: This is an old format that we don't support full checking on, so
        # just claim that checking for this inconsistency is not required.
        return False


class PreSplitOutRepositoryFormat(RepositoryFormat):
    """Base class for the pre split out repository formats."""

    rich_root_data = False
    supports_tree_reference = False
    supports_ghosts = False

    def initialize(self, a_bzrdir, shared=False, _internal=False):
        """Create a weave repository."""
        if shared:
            raise errors.IncompatibleFormat(self, a_bzrdir._format)

        if not _internal:
            # always initialized when the bzrdir is.
            return self.open(a_bzrdir, _found=True)
        
        # Create an empty weave
        sio = StringIO()
        weavefile.write_weave_v5(weave.Weave(), sio)
        empty_weave = sio.getvalue()

        mutter('creating repository in %s.', a_bzrdir.transport.base)
        dirs = ['revision-store', 'weaves']
        files = [('inventory.weave', StringIO(empty_weave)),
                 ]
        
        # FIXME: RBC 20060125 don't peek under the covers
        # NB: no need to escape relative paths that are url safe.
        control_files = lockable_files.LockableFiles(a_bzrdir.transport,
                                'branch-lock', lockable_files.TransportLock)
        control_files.create_lock()
        control_files.lock_write()
        control_files._transport.mkdir_multi(dirs,
                mode=control_files._dir_mode)
        try:
            for file, content in files:
                control_files.put(file, content)
        finally:
            control_files.unlock()
        return self.open(a_bzrdir, _found=True)

    def _get_control_store(self, repo_transport, control_files):
        """Return the control store for this repository."""
        return self._get_versioned_file_store('',
                                              repo_transport,
                                              control_files,
                                              prefixed=False)

    def _get_text_store(self, transport, control_files):
        """Get a store for file texts for this format."""
        raise NotImplementedError(self._get_text_store)

    def open(self, a_bzrdir, _found=False):
        """See RepositoryFormat.open()."""
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError

        repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = a_bzrdir._control_files
        text_store = self._get_text_store(repo_transport, control_files)
        control_store = self._get_control_store(repo_transport, control_files)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        return AllInOneRepository(_format=self,
                                  a_bzrdir=a_bzrdir,
                                  _revision_store=_revision_store,
                                  control_store=control_store,
                                  text_store=text_store)

    def check_conversion_target(self, target_format):
        pass


class RepositoryFormat4(PreSplitOutRepositoryFormat):
    """Bzr repository format 4.

    This repository format has:
     - flat stores
     - TextStores for texts, inventories,revisions.

    This format is deprecated: it indexes texts using a text id which is
    removed in format 5; initialization and write support for this format
    has been removed.
    """

    _matchingbzrdir = bzrdir.BzrDirFormat4()

    def __init__(self):
        super(RepositoryFormat4, self).__init__()

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Repository format 4"

    def initialize(self, url, shared=False, _internal=False):
        """Format 4 branches cannot be created."""
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Format 4 is not supported.

        It is not supported because the model changed from 4 to 5 and the
        conversion logic is expensive - so doing it on the fly was not 
        feasible.
        """
        return False

    def _get_control_store(self, repo_transport, control_files):
        """Format 4 repositories have no formal control store at this point.
        
        This will cause any control-file-needing apis to fail - this is desired.
        """
        return None
    
    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        from bzrlib.xml4 import serializer_v4
        return self._get_text_rev_store(repo_transport,
                                        control_files,
                                        'revision-store',
                                        serializer=serializer_v4)

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""


class RepositoryFormat5(PreSplitOutRepositoryFormat):
    """Bzr control format 5.

    This repository format has:
     - weaves for file texts and inventory
     - flat stores
     - TextStores for revisions and signatures.
    """

    _versionedfile_class = weave.WeaveFile
    _matchingbzrdir = bzrdir.BzrDirFormat5()

    def __init__(self):
        super(RepositoryFormat5, self).__init__()

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 5"

    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        """Return the revision store object for this a_bzrdir."""
        return self._get_text_rev_store(repo_transport,
                                        control_files,
                                        'revision-store',
                                        compressed=False)

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""
        return self._get_versioned_file_store('weaves', transport, control_files, prefixed=False)


class RepositoryFormat6(PreSplitOutRepositoryFormat):
    """Bzr control format 6.

    This repository format has:
     - weaves for file texts and inventory
     - hash subdirectory based stores.
     - TextStores for revisions and signatures.
    """

    _versionedfile_class = weave.WeaveFile
    _matchingbzrdir = bzrdir.BzrDirFormat6()

    def __init__(self):
        super(RepositoryFormat6, self).__init__()

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 6"

    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        return self._get_text_rev_store(repo_transport,
                                        control_files,
                                        'revision-store',
                                        compressed=False,
                                        prefixed=True)

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""
        return self._get_versioned_file_store('weaves', transport, control_files)

class RepositoryFormat7(MetaDirRepositoryFormat):
    """Bzr repository 7.

    This repository format has:
     - weaves for file texts and inventory
     - hash subdirectory based stores.
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
    """

    _versionedfile_class = weave.WeaveFile
    supports_ghosts = False

    def _get_control_store(self, repo_transport, control_files):
        """Return the control store for this repository."""
        return self._get_versioned_file_store('',
                                              repo_transport,
                                              control_files,
                                              prefixed=False)

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar-NG Repository format 7"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 7"

    def check_conversion_target(self, target_format):
        pass

    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        return self._get_text_rev_store(repo_transport,
                                        control_files,
                                        'revision-store',
                                        compressed=False,
                                        prefixed=True,
                                        )

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""
        return self._get_versioned_file_store('weaves',
                                              transport,
                                              control_files)

    def initialize(self, a_bzrdir, shared=False):
        """Create a weave repository.

        :param shared: If true the repository will be initialized as a shared
                       repository.
        """
        # Create an empty weave
        sio = StringIO()
        weavefile.write_weave_v5(weave.Weave(), sio)
        empty_weave = sio.getvalue()

        mutter('creating repository in %s.', a_bzrdir.transport.base)
        dirs = ['revision-store', 'weaves']
        files = [('inventory.weave', StringIO(empty_weave)), 
                 ]
        utf8_files = [('format', self.get_format_string())]
 
        self._upload_blank_content(a_bzrdir, dirs, files, utf8_files, shared)
        return self.open(a_bzrdir=a_bzrdir, _found=True)

    def open(self, a_bzrdir, _found=False, _override_transport=None):
        """See RepositoryFormat.open().
        
        :param _override_transport: INTERNAL USE ONLY. Allows opening the
                                    repository at a slightly different url
                                    than normal. I.e. during 'upgrade'.
        """
        if not _found:
            format = RepositoryFormat.find_format(a_bzrdir)
            assert format.__class__ ==  self.__class__
        if _override_transport is not None:
            repo_transport = _override_transport
        else:
            repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = lockable_files.LockableFiles(repo_transport,
                                'lock', lockdir.LockDir)
        text_store = self._get_text_store(repo_transport, control_files)
        control_store = self._get_control_store(repo_transport, control_files)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        return WeaveMetaDirRepository(_format=self,
            a_bzrdir=a_bzrdir,
            control_files=control_files,
            _revision_store=_revision_store,
            control_store=control_store,
            text_store=text_store)


class WeaveCommitBuilder(CommitBuilder):
    """A builder for weave based repos that don't support ghosts."""

    def _add_text_to_weave(self, file_id, new_lines, parents, nostore_sha):
        versionedfile = self.repository.weave_store.get_weave_or_empty(
            file_id, self.repository.get_transaction())
        result = versionedfile.add_lines(
            self._new_revision_id, parents, new_lines,
            nostore_sha=nostore_sha)[0:2]
        versionedfile.clear_cache()
        return result


_legacy_formats = [RepositoryFormat4(),
                   RepositoryFormat5(),
                   RepositoryFormat6()]
