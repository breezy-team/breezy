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

from bzrlib import (
    bzrdir,
    deprecated_graph,
    errors,
    knit,
    lockable_files,
    lockdir,
    osutils,
    transactions,
    xml5,
    xml7,
    )

from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.repository import (
    MetaDirRepository,
    MetaDirRepositoryFormat,
    RepositoryFormat,
    RootCommitBuilder,
    )
import bzrlib.revision as _mod_revision
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.trace import mutter, note, warning


class _KnitParentsProvider(object):

    def __init__(self, knit):
        self._knit = knit

    def __repr__(self):
        return 'KnitParentsProvider(%r)' % self._knit

    def get_parents(self, revision_ids):
        parents_list = []
        for revision_id in revision_ids:
            if revision_id == _mod_revision.NULL_REVISION:
                parents = []
            else:
                try:
                    parents = self._knit.get_parents_with_ghosts(revision_id)
                except errors.RevisionNotPresent:
                    parents = None
                else:
                    if len(parents) == 0:
                        parents = [_mod_revision.NULL_REVISION]
            parents_list.append(parents)
        return parents_list


class KnitRepository(MetaDirRepository):
    """Knit format repository."""

    _serializer = xml5.serializer_v5

    def _warn_if_deprecated(self):
        # This class isn't deprecated
        pass

    def _inventory_add_lines(self, inv_vf, revid, parents, lines):
        inv_vf.add_lines_with_ghosts(revid, parents, lines)

    @needs_read_lock
    def _all_revision_ids(self):
        """See Repository.all_revision_ids()."""
        # Knits get the revision graph from the index of the revision knit, so
        # it's always possible even if they're on an unlistable transport.
        return self._revision_store.all_revision_ids(self.get_transaction())

    def fileid_involved_between_revs(self, from_revid, to_revid):
        """Find file_id(s) which are involved in the changes between revisions.

        This determines the set of revisions which are involved, and then
        finds all file ids affected by those revisions.
        """
        from_revid = osutils.safe_revision_id(from_revid)
        to_revid = osutils.safe_revision_id(to_revid)
        vf = self._get_revision_vf()
        from_set = set(vf.get_ancestry(from_revid))
        to_set = set(vf.get_ancestry(to_revid))
        changed = to_set.difference(from_set)
        return self._fileid_involved_by_set(changed)

    def fileid_involved(self, last_revid=None):
        """Find all file_ids modified in the ancestry of last_revid.

        :param last_revid: If None, last_revision() will be used.
        """
        if not last_revid:
            changed = set(self.all_revision_ids())
        else:
            changed = set(self.get_ancestry(last_revid))
        if None in changed:
            changed.remove(None)
        return self._fileid_involved_by_set(changed)

    @needs_read_lock
    def get_ancestry(self, revision_id, topo_sorted=True):
        """Return a list of revision-ids integrated by a revision.
        
        This is topologically sorted, unless 'topo_sorted' is specified as
        False.
        """
        if revision_id is None:
            return [None]
        revision_id = osutils.safe_revision_id(revision_id)
        vf = self._get_revision_vf()
        try:
            return [None] + vf.get_ancestry(revision_id, topo_sorted)
        except errors.RevisionNotPresent:
            raise errors.NoSuchRevision(self, revision_id)

    @needs_read_lock
    def get_data_stream(self, revision_ids):
        """See Repository.get_data_stream."""
        # XXX: is this generic enough to move to the Repository base class?
        for knit_kind, file_id, versions in self.get_data_about_revision_ids(revision_ids):
            if knit_kind == 'file':
                name = 'file:' + file_id
                knit = self.text_store.get_weave_or_empty(
                    file_id, self.get_transaction())
            elif knit_kind == 'inventory':
                name = 'inventory'
                knit = self.get_inventory_weave()
            elif knit_kind == 'revisions':
                name = 'revisions'
                knit = self.control_weaves.get_weave(
                    'revisions', self.get_transaction())
            else:
                raise AssertionError('Unknown knit kind %r' % (knit_kind,))
            yield name, knit

    @needs_read_lock
    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        revision_id = osutils.safe_revision_id(revision_id)
        return self.get_revision_reconcile(revision_id)

    @needs_read_lock
    def get_revision_graph(self, revision_id=None):
        """Return a dictionary containing the revision graph.

        :param revision_id: The revision_id to get a graph from. If None, then
        the entire revision graph is returned. This is a deprecated mode of
        operation and will be removed in the future.
        :return: a dictionary of revision_id->revision_parents_list.
        """
        # special case NULL_REVISION
        if revision_id == _mod_revision.NULL_REVISION:
            return {}
        revision_id = osutils.safe_revision_id(revision_id)
        a_weave = self._get_revision_vf()
        entire_graph = a_weave.get_graph()
        if revision_id is None:
            return a_weave.get_graph()
        elif revision_id not in a_weave:
            raise errors.NoSuchRevision(self, revision_id)
        else:
            # add what can be reached from revision_id
            result = {}
            pending = set([revision_id])
            while len(pending) > 0:
                node = pending.pop()
                result[node] = a_weave.get_parents(node)
                for revision_id in result[node]:
                    if revision_id not in result:
                        pending.add(revision_id)
            return result

    @needs_read_lock
    def get_revision_graph_with_ghosts(self, revision_ids=None):
        """Return a graph of the revisions with ghosts marked as applicable.

        :param revision_ids: an iterable of revisions to graph or None for all.
        :return: a Graph object with the graph reachable from revision_ids.
        """
        result = deprecated_graph.Graph()
        vf = self._get_revision_vf()
        versions = set(vf.versions())
        if not revision_ids:
            pending = set(self.all_revision_ids())
            required = set([])
        else:
            pending = set(osutils.safe_revision_id(r) for r in revision_ids)
            # special case NULL_REVISION
            if _mod_revision.NULL_REVISION in pending:
                pending.remove(_mod_revision.NULL_REVISION)
            required = set(pending)
        done = set([])
        while len(pending):
            revision_id = pending.pop()
            if not revision_id in versions:
                if revision_id in required:
                    raise errors.NoSuchRevision(self, revision_id)
                # a ghost
                result.add_ghost(revision_id)
                # mark it as done so we don't try for it again.
                done.add(revision_id)
                continue
            parent_ids = vf.get_parents_with_ghosts(revision_id)
            for parent_id in parent_ids:
                # is this queued or done ?
                if (parent_id not in pending and
                    parent_id not in done):
                    # no, queue it.
                    pending.add(parent_id)
            result.add_node(revision_id, parent_ids)
            done.add(revision_id)
        return result

    def _get_revision_vf(self):
        """:return: a versioned file containing the revisions."""
        vf = self._revision_store.get_revision_file(self.get_transaction())
        return vf

    def _get_history_vf(self):
        """Get a versionedfile whose history graph reflects all revisions.

        For knit repositories, this is the revision knit.
        """
        return self._get_revision_vf()

    @needs_write_lock
    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from bzrlib.reconcile import KnitReconciler
        reconciler = KnitReconciler(self, thorough=thorough)
        reconciler.reconcile()
        return reconciler
    
    def revision_parents(self, revision_id):
        revision_id = osutils.safe_revision_id(revision_id)
        return self._get_revision_vf().get_parents(revision_id)

    def _make_parents_provider(self):
        return _KnitParentsProvider(self._get_revision_vf())


class KnitRepository3(KnitRepository):

    def __init__(self, _format, a_bzrdir, control_files, _revision_store,
                 control_store, text_store):
        KnitRepository.__init__(self, _format, a_bzrdir, control_files,
                              _revision_store, control_store, text_store)
        self._serializer = xml7.serializer_v7

    def deserialise_inventory(self, revision_id, xml):
        """Transform the xml into an inventory object. 

        :param revision_id: The expected revision id of the inventory.
        :param xml: A serialised inventory.
        """
        result = self._serializer.read_inventory_from_string(xml)
        assert result.root.revision is not None
        return result

    def serialise_inventory(self, inv):
        """Transform the inventory object into XML text.

        :param revision_id: The expected revision id of the inventory.
        :param xml: A serialised inventory.
        """
        assert inv.revision_id is not None
        assert inv.root.revision is not None
        return KnitRepository.serialise_inventory(self, inv)

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None):
        """Obtain a CommitBuilder for this repository.
        
        :param branch: Branch to commit to.
        :param parents: Revision ids of the parents of the new revision.
        :param config: Configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        """
        revision_id = osutils.safe_revision_id(revision_id)
        return RootCommitBuilder(self, parents, config, timestamp, timezone,
                                 committer, revprops, revision_id)


class RepositoryFormatKnit(MetaDirRepositoryFormat):
    """Bzr repository knit format (generalized). 

    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock
    """

    def _get_control_store(self, repo_transport, control_files):
        """Return the control store for this repository."""
        return VersionedFileStore(
            repo_transport,
            prefixed=False,
            file_mode=control_files._file_mode,
            versionedfile_class=knit.KnitVersionedFile,
            versionedfile_kwargs={'factory':knit.KnitPlainFactory()},
            )

    def _get_revision_store(self, repo_transport, control_files):
        """See RepositoryFormat._get_revision_store()."""
        from bzrlib.store.revision.knit import KnitRevisionStore
        versioned_file_store = VersionedFileStore(
            repo_transport,
            file_mode=control_files._file_mode,
            prefixed=False,
            precious=True,
            versionedfile_class=knit.KnitVersionedFile,
            versionedfile_kwargs={'delta':False,
                                  'factory':knit.KnitPlainFactory(),
                                 },
            escaped=True,
            )
        return KnitRevisionStore(versioned_file_store)

    def _get_text_store(self, transport, control_files):
        """See RepositoryFormat._get_text_store()."""
        return self._get_versioned_file_store('knits',
                                  transport,
                                  control_files,
                                  versionedfile_class=knit.KnitVersionedFile,
                                  versionedfile_kwargs={
                                      'create_parent_dir':True,
                                      'delay_create':True,
                                      'dir_mode':control_files._dir_mode,
                                  },
                                  escaped=True)

    def initialize(self, a_bzrdir, shared=False):
        """Create a knit format 1 repository.

        :param a_bzrdir: bzrdir to contain the new repository; must already
            be initialized.
        :param shared: If true the repository will be initialized as a shared
                       repository.
        """
        mutter('creating repository in %s.', a_bzrdir.transport.base)
        dirs = ['revision-store', 'knits']
        files = []
        utf8_files = [('format', self.get_format_string())]
        
        self._upload_blank_content(a_bzrdir, dirs, files, utf8_files, shared)
        repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = lockable_files.LockableFiles(repo_transport,
                                'lock', lockdir.LockDir)
        control_store = self._get_control_store(repo_transport, control_files)
        transaction = transactions.WriteTransaction()
        # trigger a write of the inventory store.
        control_store.get_weave_or_empty('inventory', transaction)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        # the revision id here is irrelevant: it will not be stored, and cannot
        # already exist.
        _revision_store.has_revision_id('A', transaction)
        _revision_store.get_signature_file(transaction)
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
        return KnitRepository(_format=self,
                              a_bzrdir=a_bzrdir,
                              control_files=control_files,
                              _revision_store=_revision_store,
                              control_store=control_store,
                              text_store=text_store)


class RepositoryFormatKnit1(RepositoryFormatKnit):
    """Bzr repository knit format 1.

    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock

    This format was introduced in bzr 0.8.
    """

    def __ne__(self, other):
        return self.__class__ is not other.__class__

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar-NG Knit Repository Format 1"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Knit repository format 1"

    def check_conversion_target(self, target_format):
        pass


class RepositoryFormatKnit3(RepositoryFormatKnit):
    """Bzr repository knit format 2.

    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock
     - support for recording full info about the tree root
     - support for recording tree-references
    """

    repository_class = KnitRepository3
    rich_root_data = True
    supports_tree_reference = True

    def _get_matching_bzrdir(self):
        return bzrdir.format_registry.make_bzrdir('dirstate-with-subtree')

    def _ignore_setting_bzrdir(self, format):
        pass

    _matchingbzrdir = property(_get_matching_bzrdir, _ignore_setting_bzrdir)

    def check_conversion_target(self, target_format):
        if not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)
        if not getattr(target_format, 'supports_tree_reference', False):
            raise errors.BadConversionTarget(
                'Does not support nested trees', target_format)
            
    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar Knit Repository Format 3 (bzr 0.15)\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Knit repository format 3"

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
        control_files = lockable_files.LockableFiles(repo_transport, 'lock',
                                                     lockdir.LockDir)
        text_store = self._get_text_store(repo_transport, control_files)
        control_store = self._get_control_store(repo_transport, control_files)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        return self.repository_class(_format=self,
                                     a_bzrdir=a_bzrdir,
                                     control_files=control_files,
                                     _revision_store=_revision_store,
                                     control_store=control_store,
                                     text_store=text_store)
