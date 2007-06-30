# Copyright (C) 2007 Canonical Ltd
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

from cStringIO import StringIO
import bz2

from bzrlib import (
    diff,
    errors,
    iterablefile,
    multiparent,
    osutils,
    pack,
    revision as _mod_revision,
    trace,
    xml_serializer,
    )
from bzrlib.bundle import bundle_data, serializer
from bzrlib.util import bencode


class BundleWriter(object):

    """Writer for bundle-format files.

    This serves roughly the same purpose as ContainerReader, but acts as a
    layer on top of it.

    Provides ways of writing the spcific record types supported this bundle
    format.
    """
    def __init__(self, fileobj):
        self._container = pack.ContainerWriter(self._write_encoded)
        self._fileobj = fileobj
        self._compressor = bz2.BZ2Compressor()

    def _write_encoded(self, bytes):
        """Write bzip2-encoded bytes to the file"""
        self._fileobj.write(self._compressor.compress(bytes))

    def begin(self):
        """Start writing the bundle"""
        self._fileobj.write(serializer._get_bundle_header('4alpha'))
        self._fileobj.write('#\n')
        self._container.begin()

    def end(self):
        """Finish writing the bundle"""
        self._container.end()
        self._fileobj.write(self._compressor.flush())

    def add_multiparent_record(self, mp_bytes, sha1, parents, repo_kind,
                               revision_id, file_id):
        """Add a record for a multi-parent diff

        :mp_bytes: A multi-parent diff, as a bytestring
        :parents: a list of revision-ids of the parents
        :repo_kind: The kind of object in the repository.  May be 'file' or
            'inventory'
        :revision_id: The revision id of the mpdiff being added.
        :file_id: The file-id of the file, or None for inventories.
        """
        metadata = {'parents': parents,
                    'storage_kind': 'mpdiff',
                    'sha1': sha1}
        self._add_record(mp_bytes, metadata, repo_kind, revision_id, file_id)

    def add_fulltext_record(self, bytes, parents, repo_kind, revision_id,
                            file_id):
        """Add a record for a fulltext

        :bytes: The fulltext, as a bytestring
        :parents: a list of revision-ids of the parents
        :repo_kind: The kind of object in the repository.  May be 'revision' or
            'signature'
        :revision_id: The revision id of the fulltext being added.
        :file_id: must be None
        """
        metadata = {'parents': parents,
                    'storage_kind': 'mpdiff',
                    'sha1': sha1}
        self._add_record(bytes, {'parents': parents,
            'storage_kind': 'fulltext'}, repo_kind, revision_id, file_id)

    def add_info_record(self, **kwargs):
        """Add an info record to the bundle

        Any parameters may be supplied, except 'self' and 'storage_kind'.
        Values must be lists, strings, integers, dicts, or a combination.
        """
        kwargs['storage_kind'] = 'header'
        self._add_record(None, kwargs, 'info', None, None)

    @staticmethod
    def encode_name(content_kind, revision_id, file_id=None):
        """Encode semantic ids as a container name"""
        assert content_kind in ('revision', 'file', 'inventory', 'signature',
                                'info')

        if content_kind == 'file':
            assert file_id is not None
        else:
            assert file_id is None
        if content_kind == 'info':
            assert revision_id is None
        else:
            assert revision_id is not None
        names = [content_kind]
        if revision_id is not None:
            names.append(revision_id)
            if file_id is not None:
                names.append(file_id)
        return '/'.join(names)

    def _add_record(self, bytes, metadata, repo_kind, revision_id, file_id):
        """Add a bundle record to the container.

        Most bundle records are recorded as header/body pairs, with the
        body being nameless.  Records with storage_kind 'header' have no
        body.
        """
        name = self.encode_name(repo_kind, revision_id, file_id)
        encoded_metadata = bencode.bencode(metadata)
        self._container.add_bytes_record(encoded_metadata, [name])
        if metadata['storage_kind'] != 'header':
            self._container.add_bytes_record(bytes, [])


class BundleReader(object):

    """Reader for bundle-format files.

    This serves roughly the same purpose as ContainerReader, but acts as a
    layer on top of it, providing metadata, a semantic name, and a record
    body
    """
    def __init__(self, fileobj):
        line = fileobj.readline()
        if line != '\n':
            fileobj.readline()
        self.patch_lines = []
        self._container = pack.ContainerReader(
            iterablefile.IterableFile(self.iter_decode(fileobj)))

    @staticmethod
    def iter_decode(fileobj):
        """Iterate through decoded fragments of the file"""
        decompressor = bz2.BZ2Decompressor()
        for line in fileobj:
            yield decompressor.decompress(line)

    @staticmethod
    def decode_name(name):
        """Decode a name from its container form into a semantic form

        :retval: content_kind, revision_id, file_id
        """
        names = name.split('/')
        content_kind = names[0]
        revision_id = None
        file_id = None
        if len(names) > 1:
            revision_id = names[1]
        if len(names) > 2:
            file_id = names[2]
        return content_kind, revision_id, file_id

    def iter_records(self):
        """Iterate through bundle records

        :return: a generator of (bytes, metadata, content_kind, revision_id,
            file_id)
        """
        iterator = self._container.iter_records()
        for (name,), meta_bytes in iterator:
            metadata = bencode.bdecode(meta_bytes(None))
            if metadata['storage_kind'] == 'header':
                bytes = None
            else:
                _unused, bytes = iterator.next()
                bytes = bytes(None)
            yield (bytes, metadata) + self.decode_name(name)


class BundleSerializerV4(serializer.BundleSerializer):

    """Implement the high-level bundle interface"""
    def write(self, repository, revision_ids, forced_bases, fileobj):
        """Write a bundle to a file-like object

        For backwards-compatibility only
        """
        write_op = BundleWriteOperation.from_old_args(repository, revision_ids,
                                                      forced_bases, fileobj)
        return write_op.do_write()

    def write_bundle(self, repository, target, base, fileobj):
        """Write a bundle to a file object

        :param repository: The repository to retrieve revision data from
        :param target: The head revision to include ancestors of
        :param base: The ancestor of the target to stop including acestors
            at.
        :param fileobj: The file-like object to write to
        """
        write_op =  BundleWriteOperation(base, target, repository, fileobj)
        return write_op.do_write()

    def read(self, file):
        """return a reader object for a given file"""
        bundle = BundleInfoV4(file, self)
        return bundle

    @staticmethod
    def get_source_serializer(info):
        """Retrieve the serializer for a given info object"""
        return xml_serializer.format_registry.get(info['serializer'])


class BundleWriteOperation(object):

    """Perform the operation of writing revisions to a bundle"""
    @classmethod
    def from_old_args(cls, repository, revision_ids, forced_bases, fileobj):
        base, target = cls.get_base_target(revision_ids, forced_bases,
                                           repository)
        return BundleWriteOperation(base, target, repository, fileobj,
                                    revision_ids)

    def __init__(self, base, target, repository, fileobj, revision_ids=None):
        self.base = base
        self.target = target
        self.repository = repository
        bundle = BundleWriter(fileobj)
        self.bundle = bundle
        self.base_ancestry = set(repository.get_ancestry(base,
                                                         topo_sorted=False))
        if revision_ids is not None:
            self.revision_ids = revision_ids
        else:
            revision_ids = set(repository.get_ancestry(target,
                                                       topo_sorted=False))
            self.revision_ids = revision_ids.difference(self.base_ancestry)

    def do_write(self):
        """Write all data to the bundle"""
        self.bundle.begin()
        self.write_info()
        self.write_files()
        self.write_revisions()
        self.bundle.end()
        return self.revision_ids

    def write_info(self):
        """Write format info"""
        serializer_format = self.repository.get_serializer_format()
        supports_rich_root = {True: 1, False: 0}[
            self.repository.supports_rich_root()]
        self.bundle.add_info_record(serializer=serializer_format,
                                    supports_rich_root=supports_rich_root)

    def iter_file_revisions(self):
        """Iterate through all relevant revisions of all files.

        This is the correct implementation, but is not compatible with bzr.dev,
        because certain old revisions were not converted correctly, and have
        the wrong "revision" marker in inventories.
        """
        transaction = self.repository.get_transaction()
        altered = self.repository.fileids_altered_by_revision_ids(
            self.revision_ids)
        for file_id, file_revision_ids in altered.iteritems():
            vf = self.repository.weave_store.get_weave(file_id, transaction)
            yield vf, file_id, file_revision_ids

    def iter_file_revisions_aggressive(self):
        """Iterate through all relevant revisions of all files.

        This uses the standard iter_file_revisions to determine what revisions
        are referred to by inventories, but then uses the versionedfile to
        determine what the build-dependencies of each required revision.

        All build dependencies which are not ancestors of the base revision
        are emitted.
        """
        for vf, file_id, file_revision_ids in self.iter_file_revisions():
            new_revision_ids = set()
            pending = list(file_revision_ids)
            while len(pending) > 0:
                revision_id = pending.pop()
                if revision_id in new_revision_ids:
                    continue
                if revision_id in self.base_ancestry:
                    continue
                new_revision_ids.add(revision_id)
                pending.extend(vf.get_parents(revision_id))
            yield vf, file_id, new_revision_ids

    def write_files(self):
        """Write bundle records for all revisions of all files"""
        for vf, file_id, revision_ids in self.iter_file_revisions_aggressive():
            self.add_mp_records('file', file_id, vf, revision_ids)

    def write_revisions(self):
        """Write bundle records for all revisions and signatures"""
        inv_vf = self.repository.get_inventory_weave()
        revision_order = list(multiparent.topo_iter(inv_vf, self.revision_ids))
        if self.target is not None and self.target in self.revision_ids:
            revision_order.remove(self.target)
            revision_order.append(self.target)
        self.add_mp_records('inventory', None, inv_vf, revision_order)
        parents_list = self.repository.get_parents(revision_order)
        for parents, revision_id in zip(parents_list, revision_order):
            revision_text = self.repository.get_revision_xml(revision_id)
            self.bundle.add_fulltext_record(revision_text, parents,
                                       'revision', revision_id, None)
            try:
                self.bundle.add_fulltext_record(
                    self.repository.get_signature_text(
                    revision_id), parents, 'signature', revision_id, None)
            except errors.NoSuchRevision:
                pass

    @staticmethod
    def get_base_target(revision_ids, forced_bases, repository):
        if len(revision_ids) == 0:
            return None, None
        target = revision_ids[0]
        base = forced_bases.get(target)
        if base is None:
            parents = repository.get_revision(target).parent_ids
            if len(parents) == 0:
                base = _mod_revision.NULL_REVISION
            else:
                base = parents[0]
        return base, target

    def add_mp_records(self, repo_kind, file_id, vf, revision_ids):
        """Add multi-parent diff records to a bundle"""
        revision_ids = list(multiparent.topo_iter(vf, revision_ids))
        mpdiffs = vf.make_mpdiffs(revision_ids)
        sha1s = vf.get_sha1s(revision_ids)
        for mpdiff, revision_id, sha1, in zip(mpdiffs, revision_ids, sha1s):
            parents = vf.get_parents(revision_id)
            text = ''.join(mpdiff.to_patch())
            self.bundle.add_multiparent_record(text, sha1, parents, repo_kind,
                                               revision_id, file_id)


class BundleInfoV4(object):

    """Provide (most of) the BundleInfo interface"""
    def __init__(self, fileobj, serializer):
        self._fileobj = fileobj
        self._serializer = serializer
        self.__real_revisions = None
        self.__revisions = None

    def install(self, repository):
        return self.install_revisions(repository)

    def install_revisions(self, repository):
        repository.lock_write()
        try:
            ri = RevisionInstaller(self.get_bundle_reader(),
                                   self._serializer, repository)
            return ri.install()
        finally:
            repository.unlock()

    def get_merge_request(self, target_repo):
        """Provide data for performing a merge

        Returns suggested base, suggested target, and patch verification status
        """
        return None, self.target, 'inapplicable'


    def get_bundle_reader(self):
        self._fileobj.seek(0)
        return BundleReader(self._fileobj)

    def _get_real_revisions(self):
        if self.__real_revisions is None:
            self.__real_revisions = []
            bundle_reader = self.get_bundle_reader()
            for bytes, metadata, repo_kind, revision_id, file_id in \
                bundle_reader.iter_records():
                if repo_kind == 'info':
                    serializer =\
                        self._serializer.get_source_serializer(metadata)
                if repo_kind == 'revision':
                    rev = serializer.read_revision_from_string(bytes)
                    self.__real_revisions.append(rev)
        return self.__real_revisions
    real_revisions = property(_get_real_revisions)

    def _get_revisions(self):
        if self.__revisions is None:
            self.__revisions = []
            for revision in self.real_revisions:
                self.__revisions.append(
                    bundle_data.RevisionInfo.from_revision(revision))
        return self.__revisions

    revisions = property(_get_revisions)

    def _get_target(self):
        return self.revisions[-1].revision_id

    target = property(_get_target)


class RevisionInstaller(object):

    def __init__(self, container, serializer, repository):
        self._container = container
        self._serializer = serializer
        self._repository = repository
        self._info = None

    def handle_info(self, info):
        self._info = info
        self._source_serializer = self._serializer.get_source_serializer(info)
        if (info['supports_rich_root'] == 0 and
            self._repository.supports_rich_root()):
            self.update_root = True
        else:
            self.update_root = False

    def install(self):
        current_file = None
        current_versionedfile = None
        pending_file_records = []
        added_inv = set()
        target_revision = None
        for bytes, metadata, repo_kind, revision_id, file_id in\
            self._container.iter_records():
            if repo_kind == 'info':
                assert self._info is None
                self.handle_info(metadata)
            if repo_kind != 'file':
                self._install_mp_records(current_versionedfile,
                    pending_file_records)
                current_file = None
                current_versionedfile = None
                pending_file_records = []
                if repo_kind == 'inventory':
                    self._install_inventory(revision_id, metadata, bytes)
                if repo_kind == 'revision':
                    target_revision = revision_id
                    self._install_revision(revision_id, metadata, bytes)
                if repo_kind == 'signature':
                    self._install_signature(revision_id, metadata, bytes)
            if repo_kind == 'file':
                if file_id != current_file:
                    self._install_mp_records(current_versionedfile,
                        pending_file_records)
                    current_file = file_id
                    current_versionedfile = \
                        self._repository.weave_store.get_weave_or_empty(
                        file_id, self._repository.get_transaction())
                    pending_file_records = []
                if revision_id in current_versionedfile:
                    continue
                pending_file_records.append((revision_id, metadata, bytes))
        self._install_mp_records(current_versionedfile, pending_file_records)
        return target_revision

    def _install_mp_records(self, versionedfile, records):
        if len(records) == 0:
            return
        d_func = multiparent.MultiParent.from_patch
        vf_records = [(r, m['parents'], m['sha1'], d_func(t)) for r, m, t in
                      records if r not in versionedfile]
        versionedfile.add_mpdiffs(vf_records)

    def _install_inventory(self, revision_id, metadata, text):
        vf = self._repository.get_inventory_weave()
        if revision_id in vf:
            return
        parent_ids = metadata['parents']
        if self._info['serializer'] == self._repository._serializer.format_num:
            return self._install_mp_records(vf, [(revision_id, metadata,
                                                  text)])
        parents = [self._repository.get_inventory(p)
                   for p in parent_ids]
        parent_texts = [self._source_serializer.write_inventory_to_string(p)
                        for p in parents]
        target_lines = multiparent.MultiParent.from_patch(text).to_lines(
            parent_texts)
        sha1 = osutils.sha_strings(target_lines)
        if sha1 != metadata['sha1']:
            raise BadBundle("Can't convert to target format")
        target_inv = self._source_serializer.read_inventory_from_string(
            ''.join(target_lines))
        self._handle_root(target_inv, parent_ids)
        self._repository.add_inventory(revision_id, target_inv, parent_ids)

    def _handle_root(self, target_inv, parent_ids):
        revision_id = target_inv.revision_id
        if self.update_root:
            target_inv.root.revision = revision_id
            store = self._repository.weave_store
            transaction = self._repository.get_transaction()
            vf = store.get_weave_or_empty(target_inv.root.file_id, transaction)
            vf.add_lines(revision_id, parent_ids, [])
        elif not self._repository.supports_rich_root():
            if target_inv.root.revision != revision_id:
                raise errors.IncompatibleRevision(repr(self._repository))


    def _install_revision(self, revision_id, metadata, text):
        if self._repository.has_revision(revision_id):
            return
        self._repository._add_revision_text(revision_id, text)

    def _install_signature(self, revision_id, metadata, text):
        transaction = self._repository.get_transaction()
        if self._repository._revision_store.has_signature(revision_id,
                                                          transaction):
            return
        self._repository._revision_store.add_revision_signature_text(
            revision_id, text, transaction)
