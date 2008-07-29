# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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

import os
from cStringIO import StringIO
import urllib

from bzrlib import (
    bzrdir,
    debug,
    errors,
    lockable_files,
    lockdir,
    osutils,
    revision as _mod_revision,
    versionedfile,
    weave,
    weavefile,
    xml5,
    )
from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.repository import (
    CommitBuilder,
    MetaDirVersionedFileRepository,
    MetaDirRepositoryFormat,
    Repository,
    RepositoryFormat,
    )
from bzrlib.store.text import TextStore
from bzrlib.trace import mutter
from bzrlib.tuned_gzip import GzipFile, bytes_to_gzip
from bzrlib.versionedfile import (
    AbsentContentFactory,
    FulltextContentFactory,
    VersionedFiles,
    )


class AllInOneRepository(Repository):
    """Legacy support - the repository behaviour for all-in-one branches."""

    _serializer = xml5.serializer_v5

    def __init__(self, _format, a_bzrdir):
        # we reuse one control files instance.
        dir_mode = a_bzrdir._get_dir_mode()
        file_mode = a_bzrdir._get_file_mode()

        def get_store(name, compressed=True, prefixed=False):
            # FIXME: This approach of assuming stores are all entirely compressed
            # or entirely uncompressed is tidy, but breaks upgrade from 
            # some existing branches where there's a mixture; we probably 
            # still want the option to look for both.
            relpath = a_bzrdir._control_files._escape(name)
            store = TextStore(a_bzrdir.transport.clone(relpath),
                              prefixed=prefixed, compressed=compressed,
                              dir_mode=dir_mode,
                              file_mode=file_mode)
            return store

        # not broken out yet because the controlweaves|inventory_store
        # and texts bits are still different.
        if isinstance(_format, RepositoryFormat4):
            # cannot remove these - there is still no consistent api 
            # which allows access to this old info.
            self.inventory_store = get_store('inventory-store')
            self._text_store = get_store('text-store')
        super(AllInOneRepository, self).__init__(_format, a_bzrdir, a_bzrdir._control_files)
        self._fetch_order = 'topological'
        self._fetch_reconcile = True

    @needs_read_lock
    def _all_possible_ids(self):
        """Return all the possible revisions that we could find."""
        if 'evil' in debug.debug_flags:
            mutter_callsite(3, "_all_possible_ids scales with size of history.")
        return [key[-1] for key in self.inventories.keys()]

    @needs_read_lock
    def _all_revision_ids(self):
        """Returns a list of all the revision ids in the repository. 

        These are in as much topological order as the underlying store can 
        present: for weaves ghosts may lead to a lack of correctness until
        the reweave updates the parents list.
        """
        return [key[-1] for key in self.revisions.keys()]

    def _activate_new_inventory(self):
        """Put a replacement inventory.new into use as inventories."""
        # Copy the content across
        t = self.bzrdir._control_files._transport
        t.copy('inventory.new.weave', 'inventory.weave')
        # delete the temp inventory
        t.delete('inventory.new.weave')
        # Check we can parse the new weave properly as a sanity check
        self.inventories.keys()

    def _backup_inventory(self):
        t = self.bzrdir._control_files._transport
        t.copy('inventory.weave', 'inventory.backup.weave')

    def _temp_inventories(self):
        t = self.bzrdir._control_files._transport
        return self._format._get_inventories(t, self, 'inventory.new')

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None):
        self._check_ascii_revisionid(revision_id, self.get_commit_builder)
        result = CommitBuilder(self, parents, config, timestamp, timezone,
                              committer, revprops, revision_id)
        self.start_write_group()
        return result

    @needs_read_lock
    def get_revisions(self, revision_ids):
        revs = self._get_revisions(revision_ids)
        return revs

    def _inventory_add_lines(self, revision_id, parents, lines,
        check_content=True):
        """Store lines in inv_vf and return the sha1 of the inventory."""
        present_parents = self.get_graph().get_parent_map(parents)
        final_parents = []
        for parent in parents:
            if parent in present_parents:
                final_parents.append((parent,))
        return self.inventories.add_lines((revision_id,), final_parents, lines,
            check_content=check_content)[0]

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
        raise errors.RepositoryUpgradeRequired(self.bzrdir.root_transport.base)

    def make_working_trees(self):
        """Returns the policy for making working trees on new branches."""
        return True

    def revision_graph_can_have_wrong_parents(self):
        # XXX: This is an old format that we don't support full checking on, so
        # just claim that checking for this inconsistency is not required.
        return False


class WeaveMetaDirRepository(MetaDirVersionedFileRepository):
    """A subclass of MetaDirRepository to set weave specific policy."""

    _serializer = xml5.serializer_v5

    def __init__(self, _format, a_bzrdir, control_files):
        super(WeaveMetaDirRepository, self).__init__(_format, a_bzrdir, control_files)
        self._fetch_order = 'topological'
        self._fetch_reconcile = True

    @needs_read_lock
    def _all_possible_ids(self):
        """Return all the possible revisions that we could find."""
        if 'evil' in debug.debug_flags:
            mutter_callsite(3, "_all_possible_ids scales with size of history.")
        return [key[-1] for key in self.inventories.keys()]

    @needs_read_lock
    def _all_revision_ids(self):
        """Returns a list of all the revision ids in the repository. 

        These are in as much topological order as the underlying store can 
        present: for weaves ghosts may lead to a lack of correctness until
        the reweave updates the parents list.
        """
        return [key[-1] for key in self.revisions.keys()]

    def _activate_new_inventory(self):
        """Put a replacement inventory.new into use as inventories."""
        # Copy the content across
        t = self._transport
        t.copy('inventory.new.weave', 'inventory.weave')
        # delete the temp inventory
        t.delete('inventory.new.weave')
        # Check we can parse the new weave properly as a sanity check
        self.inventories.keys()

    def _backup_inventory(self):
        t = self._transport
        t.copy('inventory.weave', 'inventory.backup.weave')

    def _temp_inventories(self):
        t = self._transport
        return self._format._get_inventories(t, self, 'inventory.new')

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None):
        self._check_ascii_revisionid(revision_id, self.get_commit_builder)
        result = CommitBuilder(self, parents, config, timestamp, timezone,
                              committer, revprops, revision_id)
        self.start_write_group()
        return result

    @needs_read_lock
    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        r = self.get_revision_reconcile(revision_id)
        return r

    def _inventory_add_lines(self, revision_id, parents, lines,
        check_content=True):
        """Store lines in inv_vf and return the sha1 of the inventory."""
        present_parents = self.get_graph().get_parent_map(parents)
        final_parents = []
        for parent in parents:
            if parent in present_parents:
                final_parents.append((parent,))
        return self.inventories.add_lines((revision_id,), final_parents, lines,
            check_content=check_content)[0]

    def revision_graph_can_have_wrong_parents(self):
        return False


class PreSplitOutRepositoryFormat(RepositoryFormat):
    """Base class for the pre split out repository formats."""

    rich_root_data = False
    supports_tree_reference = False
    supports_ghosts = False
    supports_external_lookups = False

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
        
        # FIXME: RBC 20060125 don't peek under the covers
        # NB: no need to escape relative paths that are url safe.
        control_files = lockable_files.LockableFiles(a_bzrdir.transport,
            'branch-lock', lockable_files.TransportLock)
        control_files.create_lock()
        control_files.lock_write()
        transport = a_bzrdir.transport
        try:
            transport.mkdir_multi(['revision-store', 'weaves'],
                mode=a_bzrdir._get_dir_mode())
            transport.put_bytes_non_atomic('inventory.weave', empty_weave)
        finally:
            control_files.unlock()
        return self.open(a_bzrdir, _found=True)

    def open(self, a_bzrdir, _found=False):
        """See RepositoryFormat.open()."""
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError

        repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = a_bzrdir._control_files
        result = AllInOneRepository(_format=self, a_bzrdir=a_bzrdir)
        result.revisions = self._get_revisions(repo_transport, result)
        result.signatures = self._get_signatures(repo_transport, result)
        result.inventories = self._get_inventories(repo_transport, result)
        result.texts = self._get_texts(repo_transport, result)
        return result

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
        self._fetch_order = 'topological'
        self._fetch_reconcile = True

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

    def _get_inventories(self, repo_transport, repo, name='inventory'):
        # No inventories store written so far.
        return None

    def _get_revisions(self, repo_transport, repo):
        from bzrlib.xml4 import serializer_v4
        return RevisionTextStore(repo_transport.clone('revision-store'),
            serializer_v4, True, versionedfile.PrefixMapper(),
            repo.is_locked, repo.is_write_locked)

    def _get_signatures(self, repo_transport, repo):
        return SignatureTextStore(repo_transport.clone('revision-store'),
            False, versionedfile.PrefixMapper(),
            repo.is_locked, repo.is_write_locked)

    def _get_texts(self, repo_transport, repo):
        return None


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
        self._fetch_order = 'topological'
        self._fetch_reconcile = True

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 5"

    def _get_inventories(self, repo_transport, repo, name='inventory'):
        mapper = versionedfile.ConstantMapper(name)
        return versionedfile.ThunkedVersionedFiles(repo_transport,
            weave.WeaveFile, mapper, repo.is_locked)

    def _get_revisions(self, repo_transport, repo):
        from bzrlib.xml5 import serializer_v5
        return RevisionTextStore(repo_transport.clone('revision-store'),
            serializer_v5, False, versionedfile.PrefixMapper(),
            repo.is_locked, repo.is_write_locked)

    def _get_signatures(self, repo_transport, repo):
        return SignatureTextStore(repo_transport.clone('revision-store'),
            False, versionedfile.PrefixMapper(),
            repo.is_locked, repo.is_write_locked)

    def _get_texts(self, repo_transport, repo):
        mapper = versionedfile.PrefixMapper()
        base_transport = repo_transport.clone('weaves')
        return versionedfile.ThunkedVersionedFiles(base_transport,
            weave.WeaveFile, mapper, repo.is_locked)


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
        self._fetch_order = 'topological'
        self._fetch_reconcile = True

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 6"

    def _get_inventories(self, repo_transport, repo, name='inventory'):
        mapper = versionedfile.ConstantMapper(name)
        return versionedfile.ThunkedVersionedFiles(repo_transport,
            weave.WeaveFile, mapper, repo.is_locked)

    def _get_revisions(self, repo_transport, repo):
        from bzrlib.xml5 import serializer_v5
        return RevisionTextStore(repo_transport.clone('revision-store'),
            serializer_v5, False, versionedfile.HashPrefixMapper(),
            repo.is_locked, repo.is_write_locked)

    def _get_signatures(self, repo_transport, repo):
        return SignatureTextStore(repo_transport.clone('revision-store'),
            False, versionedfile.HashPrefixMapper(),
            repo.is_locked, repo.is_write_locked)

    def _get_texts(self, repo_transport, repo):
        mapper = versionedfile.HashPrefixMapper()
        base_transport = repo_transport.clone('weaves')
        return versionedfile.ThunkedVersionedFiles(base_transport,
            weave.WeaveFile, mapper, repo.is_locked)


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

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar-NG Repository format 7"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Weave repository format 7"

    def check_conversion_target(self, target_format):
        pass

    def _get_inventories(self, repo_transport, repo, name='inventory'):
        mapper = versionedfile.ConstantMapper(name)
        return versionedfile.ThunkedVersionedFiles(repo_transport,
            weave.WeaveFile, mapper, repo.is_locked)

    def _get_revisions(self, repo_transport, repo):
        from bzrlib.xml5 import serializer_v5
        return RevisionTextStore(repo_transport.clone('revision-store'),
            serializer_v5, True, versionedfile.HashPrefixMapper(),
            repo.is_locked, repo.is_write_locked)

    def _get_signatures(self, repo_transport, repo):
        return SignatureTextStore(repo_transport.clone('revision-store'),
            True, versionedfile.HashPrefixMapper(),
            repo.is_locked, repo.is_write_locked)

    def _get_texts(self, repo_transport, repo):
        mapper = versionedfile.HashPrefixMapper()
        base_transport = repo_transport.clone('weaves')
        return versionedfile.ThunkedVersionedFiles(base_transport,
            weave.WeaveFile, mapper, repo.is_locked)

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
        if _override_transport is not None:
            repo_transport = _override_transport
        else:
            repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = lockable_files.LockableFiles(repo_transport,
                                'lock', lockdir.LockDir)
        result = WeaveMetaDirRepository(_format=self, a_bzrdir=a_bzrdir,
            control_files=control_files)
        result.revisions = self._get_revisions(repo_transport, result)
        result.signatures = self._get_signatures(repo_transport, result)
        result.inventories = self._get_inventories(repo_transport, result)
        result.texts = self._get_texts(repo_transport, result)
        result._transport = repo_transport
        return result


class TextVersionedFiles(VersionedFiles):
    """Just-a-bunch-of-files based VersionedFile stores."""

    def __init__(self, transport, compressed, mapper, is_locked, can_write):
        self._compressed = compressed
        self._transport = transport
        self._mapper = mapper
        if self._compressed:
            self._ext = '.gz'
        else:
            self._ext = ''
        self._is_locked = is_locked
        self._can_write = can_write

    def add_lines(self, key, parents, lines):
        """Add a revision to the store."""
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        if not self._can_write():
            raise errors.ReadOnlyError(self)
        if '/' in key[-1]:
            raise ValueError('bad idea to put / in %r' % (key,))
        text = ''.join(lines)
        if self._compressed:
            text = bytes_to_gzip(text)
        path = self._map(key)
        self._transport.put_bytes_non_atomic(path, text, create_parent_dir=True)

    def insert_record_stream(self, stream):
        adapters = {}
        for record in stream:
            # Raise an error when a record is missing.
            if record.storage_kind == 'absent':
                raise errors.RevisionNotPresent([record.key[0]], self)
            # adapt to non-tuple interface
            if record.storage_kind == 'fulltext':
                self.add_lines(record.key, None,
                    osutils.split_lines(record.get_bytes_as('fulltext')))
            else:
                adapter_key = record.storage_kind, 'fulltext'
                try:
                    adapter = adapters[adapter_key]
                except KeyError:
                    adapter_factory = adapter_registry.get(adapter_key)
                    adapter = adapter_factory(self)
                    adapters[adapter_key] = adapter
                lines = osutils.split_lines(adapter.get_bytes(
                    record, record.get_bytes_as(record.storage_kind)))
                try:
                    self.add_lines(record.key, None, lines)
                except RevisionAlreadyPresent:
                    pass

    def _load_text(self, key):
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        path = self._map(key)
        try:
            text = self._transport.get_bytes(path)
            compressed = self._compressed
        except errors.NoSuchFile:
            if self._compressed:
                # try without the .gz
                path = path[:-3]
                try:
                    text = self._transport.get_bytes(path)
                    compressed = False
                except errors.NoSuchFile:
                    return None
            else:
                return None
        if compressed:
            text = GzipFile(mode='rb', fileobj=StringIO(text)).read()
        return text

    def _map(self, key):
        return self._mapper.map(key) + self._ext


class RevisionTextStore(TextVersionedFiles):
    """Legacy thunk for format 4 repositories."""

    def __init__(self, transport, serializer, compressed, mapper, is_locked,
        can_write):
        """Create a RevisionTextStore at transport with serializer."""
        TextVersionedFiles.__init__(self, transport, compressed, mapper,
            is_locked, can_write)
        self._serializer = serializer

    def _load_text_parents(self, key):
        text = self._load_text(key)
        if text is None:
            return None, None
        parents = self._serializer.read_revision_from_string(text).parent_ids
        return text, tuple((parent,) for parent in parents)

    def get_parent_map(self, keys):
        result = {}
        for key in keys:
            parents = self._load_text_parents(key)[1]
            if parents is None:
                continue
            result[key] = parents
        return result
    
    def get_record_stream(self, keys, sort_order, include_delta_closure):
        for key in keys:
            text, parents = self._load_text_parents(key)
            if text is None:
                yield AbsentContentFactory(key)
            else:
                yield FulltextContentFactory(key, parents, None, text)

    def keys(self):
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        relpaths = set()
        for quoted_relpath in self._transport.iter_files_recursive():
            relpath = urllib.unquote(quoted_relpath)
            path, ext = os.path.splitext(relpath)
            if ext == '.gz':
                relpath = path
            if '.sig' not in relpath:
                relpaths.add(relpath)
        paths = list(relpaths)
        return set([self._mapper.unmap(path) for path in paths])


class SignatureTextStore(TextVersionedFiles):
    """Legacy thunk for format 4-7 repositories."""

    def __init__(self, transport, compressed, mapper, is_locked, can_write):
        TextVersionedFiles.__init__(self, transport, compressed, mapper,
            is_locked, can_write)
        self._ext = '.sig' + self._ext

    def get_parent_map(self, keys):
        result = {}
        for key in keys:
            text = self._load_text(key)
            if text is None:
                continue
            result[key] = None
        return result
    
    def get_record_stream(self, keys, sort_order, include_delta_closure):
        for key in keys:
            text = self._load_text(key)
            if text is None:
                yield AbsentContentFactory(key)
            else:
                yield FulltextContentFactory(key, None, None, text)

    def keys(self):
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)
        relpaths = set()
        for quoted_relpath in self._transport.iter_files_recursive():
            relpath = urllib.unquote(quoted_relpath)
            path, ext = os.path.splitext(relpath)
            if ext == '.gz':
                relpath = path
            if not relpath.endswith('.sig'):
                continue
            relpaths.add(relpath[:-4])
        paths = list(relpaths)
        return set([self._mapper.unmap(path) for path in paths])

_legacy_formats = [RepositoryFormat4(),
                   RepositoryFormat5(),
                   RepositoryFormat6()]
