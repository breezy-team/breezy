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


"""Old repository formats fused with the branch and workingtree."""

from StringIO import StringIO

from bzrlib import (
    bzrdir,
    lockable_files,
    lockdir,
    weave,
    weavefile,
    )
from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.repository import (
    MetaDirRepository,
    MetaDirRepositoryFormat,
    Repository,
    RepositoryFormat,
    )
from bzrlib.store.text import TextStore
from bzrlib.trace import mutter


class AllInOneRepository(Repository):
    """Legacy support - the repository behaviour for all-in-one branches."""

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
            #if self._transport.should_cache():
            #    cache_path = os.path.join(self.cache_root, name)
            #    os.mkdir(cache_path)
            #    store = bzrlib.store.CachedStore(store, cache_path)
            return store

        # not broken out yet because the controlweaves|inventory_store
        # and text_store | weave_store bits are still different.
        if isinstance(_format, RepositoryFormat4):
            # cannot remove these - there is still no consistent api 
            # which allows access to this old info.
            self.inventory_store = get_store('inventory-store')
            text_store = get_store('text-store')
        super(AllInOneRepository, self).__init__(_format, a_bzrdir, a_bzrdir._control_files, _revision_store, control_store, text_store)

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None):
        self._check_ascii_revisionid(revision_id, self.get_commit_builder)
        return Repository.get_commit_builder(self, branch, parents, config,
            timestamp, timezone, committer, revprops, revision_id)

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


class WeaveMetaDirRepository(MetaDirRepository):
    """A subclass of MetaDirRepository to set weave specific policy."""

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None):
        self._check_ascii_revisionid(revision_id, self.get_commit_builder)
        return MetaDirRepository.get_commit_builder(self, branch, parents,
            config, timestamp, timezone, committer, revprops, revision_id)


class PreSplitOutRepositoryFormat(RepositoryFormat):
    """Base class for the pre split out repository formats."""

    rich_root_data = False

    def initialize(self, a_bzrdir, shared=False, _internal=False):
        """Create a weave repository.
        
        TODO: when creating split out bzr branch formats, move this to a common
        base for Format5, Format6. or something like that.
        """
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

    def __init__(self):
        super(RepositoryFormat4, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat4()

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

    def __init__(self):
        super(RepositoryFormat5, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat5()

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

    def __init__(self):
        super(RepositoryFormat6, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat6()

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


RepositoryFormat7_instance = RepositoryFormat7()


_legacy_formats = [RepositoryFormat4(),
                   RepositoryFormat5(),
                   RepositoryFormat6()]
