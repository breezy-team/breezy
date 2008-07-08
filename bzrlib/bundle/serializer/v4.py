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
import re

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

    Provides ways of writing the specific record types supported this bundle
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
        self._fileobj.write(serializer._get_bundle_header(
            serializer.v4_string))
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
        :sha1: The sha1 hash of the fulltext
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

    def add_fulltext_record(self, bytes, parents, repo_kind, revision_id):
        """Add a record for a fulltext

        :bytes: The fulltext, as a bytestring
        :parents: a list of revision-ids of the parents
        :repo_kind: The kind of object in the repository.  May be 'revision' or
            'signature'
        :revision_id: The revision id of the fulltext being added.
        """
        metadata = {'parents': parents,
                    'storage_kind': 'mpdiff'}
        self._add_record(bytes, {'parents': parents,
            'storage_kind': 'fulltext'}, repo_kind, revision_id, None)

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
        if content_kind not in ('revision', 'file', 'inventory', 'signature',
                'info'):
            raise ValueError(content_kind)
        if content_kind == 'file':
            if file_id is None:
                raise AssertionError()
        else:
            if file_id is not None:
                raise AssertionError()
        if content_kind == 'info':
            if revision_id is not None:
                raise AssertionError()
        elif revision_id is None:
            raise AssertionError()
        names = [n.replace('/', '//') for n in
                 (content_kind, revision_id, file_id) if n is not None]
        return '/'.join(names)

    def _add_record(self, bytes, metadata, repo_kind, revision_id, file_id):
        """Add a bundle record to the container.

        Most bundle records are recorded as header/body pairs, with the
        body being nameless.  Records with storage_kind 'header' have no
        body.
        """
        name = self.encode_name(repo_kind, revision_id, file_id)
        encoded_metadata = bencode.bencode(metadata)
        self._container.add_bytes_record(encoded_metadata, [(name, )])
        if metadata['storage_kind'] != 'header':
            self._container.add_bytes_record(bytes, [])


class BundleReader(object):
    """Reader for bundle-format files.

    This serves roughly the same purpose as ContainerReader, but acts as a
    layer on top of it, providing metadata, a semantic name, and a record
    body
    """

    def __init__(self, fileobj, stream_input=True):
        """Constructor

        :param fileobj: a file containing a bzip-encoded container
        :param stream_input: If True, the BundleReader stream input rather than
            reading it all into memory at once.  Reading it into memory all at
            once is (currently) faster.
        """
        line = fileobj.readline()
        if line != '\n':
            fileobj.readline()
        self.patch_lines = []
        if stream_input:
            source_file = iterablefile.IterableFile(self.iter_decode(fileobj))
        else:
            source_file = StringIO(bz2.decompress(fileobj.read()))
        self._container_file = source_file

    @staticmethod
    def iter_decode(fileobj):
        """Iterate through decoded fragments of the file"""
        decompressor = bz2.BZ2Decompressor()
        for line in fileobj:
            try:
                yield decompressor.decompress(line)
            except EOFError:
                return

    @staticmethod
    def decode_name(name):
        """Decode a name from its container form into a semantic form

        :retval: content_kind, revision_id, file_id
        """
        segments = re.split('(//?)', name)
        names = ['']
        for segment in segments:
            if segment == '//':
                names[-1] += '/'
            elif segment == '/':
                names.append('')
            else:
                names[-1] += segment
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
        iterator = pack.iter_records_from_file(self._container_file)
        for names, bytes in iterator:
            if len(names) != 1:
                raise errors.BadBundle('Record has %d names instead of 1'
                                       % len(names))
            metadata = bencode.bdecode(bytes)
            if metadata['storage_kind'] == 'header':
                bytes = None
            else:
                _unused, bytes = iterator.next()
            yield (bytes, metadata) + self.decode_name(names[0][0])


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
        """Create a BundleWriteOperation from old-style arguments"""
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
        self.revision_keys = set([(revid,) for revid in self.revision_ids])

    def do_write(self):
        """Write all data to the bundle"""
        self.repository.lock_read()
        try:
            self.bundle.begin()
            self.write_info()
            self.write_files()
            self.write_revisions()
            self.bundle.end()
        finally:
            self.repository.unlock()
        return self.revision_ids

    def write_info(self):
        """Write format info"""
        serializer_format = self.repository.get_serializer_format()
        supports_rich_root = {True: 1, False: 0}[
            self.repository.supports_rich_root()]
        self.bundle.add_info_record(serializer=serializer_format,
                                    supports_rich_root=supports_rich_root)

    def write_files(self):
        """Write bundle records for all revisions of all files"""
        text_keys = []
        altered_fileids = self.repository.fileids_altered_by_revision_ids(
                self.revision_ids)
        for file_id, revision_ids in altered_fileids.iteritems():
            for revision_id in revision_ids:
                text_keys.append((file_id, revision_id))
        self._add_mp_records_keys('file', self.repository.texts, text_keys)

    def write_revisions(self):
        """Write bundle records for all revisions and signatures"""
        inv_vf = self.repository.inventories
        revision_order = [key[-1] for key in multiparent.topo_iter_keys(inv_vf,
            self.revision_keys)]
        if self.target is not None and self.target in self.revision_ids:
            revision_order.remove(self.target)
            revision_order.append(self.target)
        self._add_mp_records_keys('inventory', inv_vf, [(revid,) for revid in revision_order])
        parent_map = self.repository.get_parent_map(revision_order)
        for revision_id in revision_order:
            parents = parent_map.get(revision_id, None)
            revision_text = self.repository.get_revision_xml(revision_id)
            self.bundle.add_fulltext_record(revision_text, parents,
                                       'revision', revision_id)
            try:
                self.bundle.add_fulltext_record(
                    self.repository.get_signature_text(
                    revision_id), parents, 'signature', revision_id)
            except errors.NoSuchRevision:
                pass

    @staticmethod
    def get_base_target(revision_ids, forced_bases, repository):
        """Determine the base and target from old-style revision ids"""
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

    def _add_mp_records_keys(self, repo_kind, vf, keys):
        """Add multi-parent diff records to a bundle"""
        ordered_keys = list(multiparent.topo_iter_keys(vf, keys))
        mpdiffs = vf.make_mpdiffs(ordered_keys)
        sha1s = vf.get_sha1s(ordered_keys)
        parent_map = vf.get_parent_map(ordered_keys)
        for mpdiff, item_key, in zip(mpdiffs, ordered_keys):
            sha1 = sha1s[item_key]
            parents = [key[-1] for key in parent_map[item_key]]
            text = ''.join(mpdiff.to_patch())
            # Infer file id records as appropriate.
            if len(item_key) == 2:
                file_id = item_key[0]
            else:
                file_id = None
            self.bundle.add_multiparent_record(text, sha1, parents, repo_kind,
                                               item_key[-1], file_id)


class BundleInfoV4(object):

    """Provide (most of) the BundleInfo interface"""
    def __init__(self, fileobj, serializer):
        self._fileobj = fileobj
        self._serializer = serializer
        self.__real_revisions = None
        self.__revisions = None

    def install(self, repository):
        return self.install_revisions(repository)

    def install_revisions(self, repository, stream_input=True):
        """Install this bundle's revisions into the specified repository

        :param target_repo: The repository to install into
        :param stream_input: If True, will stream input rather than reading it
            all into memory at once.  Reading it into memory all at once is
            (currently) faster.
        """
        repository.lock_write()
        try:
            ri = RevisionInstaller(self.get_bundle_reader(stream_input),
                                   self._serializer, repository)
            return ri.install()
        finally:
            repository.unlock()

    def get_merge_request(self, target_repo):
        """Provide data for performing a merge

        Returns suggested base, suggested target, and patch verification status
        """
        return None, self.target, 'inapplicable'

    def get_bundle_reader(self, stream_input=True):
        """Return a new BundleReader for the associated bundle

        :param stream_input: If True, the BundleReader stream input rather than
            reading it all into memory at once.  Reading it into memory all at
            once is (currently) faster.
        """
        self._fileobj.seek(0)
        return BundleReader(self._fileobj, stream_input)

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
    """Installs revisions into a repository"""

    def __init__(self, container, serializer, repository):
        self._container = container
        self._serializer = serializer
        self._repository = repository
        self._info = None

    def install(self):
        """Perform the installation.
        
        Must be called with the Repository locked.
        """
        self._repository.start_write_group()
        try:
            result = self._install_in_write_group()
        except:
            self._repository.abort_write_group()
            raise
        self._repository.commit_write_group()
        return result

    def _install_in_write_group(self):
        current_file = None
        current_versionedfile = None
        pending_file_records = []
        inventory_vf = None
        pending_inventory_records = []
        added_inv = set()
        target_revision = None
        for bytes, metadata, repo_kind, revision_id, file_id in\
            self._container.iter_records():
            if repo_kind == 'info':
                if self._info is not None:
                    raise AssertionError()
                self._handle_info(metadata)
            if (pending_file_records and
                (repo_kind, file_id) != ('file', current_file)):
                # Flush the data for a single file - prevents memory
                # spiking due to buffering all files in memory.
                self._install_mp_records_keys(self._repository.texts,
                    pending_file_records)
                current_file = None
                del pending_file_records[:]
            if len(pending_inventory_records) > 0 and repo_kind != 'inventory':
                self._install_inventory_records(pending_inventory_records)
                pending_inventory_records = []
            if repo_kind == 'inventory':
                pending_inventory_records.append(((revision_id,), metadata, bytes))
            if repo_kind == 'revision':
                target_revision = revision_id
                self._install_revision(revision_id, metadata, bytes)
            if repo_kind == 'signature':
                self._install_signature(revision_id, metadata, bytes)
            if repo_kind == 'file':
                current_file = file_id
                pending_file_records.append(((file_id, revision_id), metadata, bytes))
        self._install_mp_records_keys(self._repository.texts, pending_file_records)
        return target_revision

    def _handle_info(self, info):
        """Extract data from an info record"""
        self._info = info
        self._source_serializer = self._serializer.get_source_serializer(info)
        if (info['supports_rich_root'] == 0 and
            self._repository.supports_rich_root()):
            self.update_root = True
        else:
            self.update_root = False

    def _install_mp_records(self, versionedfile, records):
        if len(records) == 0:
            return
        d_func = multiparent.MultiParent.from_patch
        vf_records = [(r, m['parents'], m['sha1'], d_func(t)) for r, m, t in
                      records if r not in versionedfile]
        versionedfile.add_mpdiffs(vf_records)

    def _install_mp_records_keys(self, versionedfile, records):
        d_func = multiparent.MultiParent.from_patch
        vf_records = []
        for key, meta, text in records:
            # Adapt to tuple interface: A length two key is a file_id,
            # revision_id pair, a length 1 key is a
            # revision/signature/inventory. We need to do this because
            # the metadata extraction from the bundle has not yet been updated
            # to use the consistent tuple interface itself.
            if len(key) == 2:
                prefix = key[:1]
            else:
                prefix = ()
            parents = [prefix + (parent,) for parent in meta['parents']]
            vf_records.append((key, parents, meta['sha1'], d_func(text)))
        versionedfile.add_mpdiffs(vf_records)

    def _install_inventory_records(self, records):
        if self._info['serializer'] == self._repository._serializer.format_num:
            return self._install_mp_records_keys(self._repository.inventories,
                records)
        for key, metadata, bytes in records:
            revision_id = key[-1]
            parent_ids = metadata['parents']
            parents = [self._repository.get_inventory(p)
                       for p in parent_ids]
            p_texts = [self._source_serializer.write_inventory_to_string(p)
                       for p in parents]
            target_lines = multiparent.MultiParent.from_patch(bytes).to_lines(
                p_texts)
            sha1 = osutils.sha_strings(target_lines)
            if sha1 != metadata['sha1']:
                raise errors.BadBundle("Can't convert to target format")
            target_inv = self._source_serializer.read_inventory_from_string(
                ''.join(target_lines))
            self._handle_root(target_inv, parent_ids)
            try:
                self._repository.add_inventory(revision_id, target_inv,
                                               parent_ids)
            except errors.UnsupportedInventoryKind:
                raise errors.IncompatibleRevision(repr(self._repository))

    def _handle_root(self, target_inv, parent_ids):
        revision_id = target_inv.revision_id
        if self.update_root:
            text_key = (target_inv.root.file_id, revision_id)
            parent_keys = [(target_inv.root.file_id, parent) for
                parent in parent_ids]
            self._repository.texts.add_lines(text_key, parent_keys, [])
        elif not self._repository.supports_rich_root():
            if target_inv.root.revision != revision_id:
                raise errors.IncompatibleRevision(repr(self._repository))

    def _install_revision(self, revision_id, metadata, text):
        if self._repository.has_revision(revision_id):
            return
        revision = self._source_serializer.read_revision_from_string(text)
        self._repository.add_revision(revision.revision_id, revision)

    def _install_signature(self, revision_id, metadata, text):
        transaction = self._repository.get_transaction()
        if self._repository.has_signature_for_revision_id(revision_id):
            return
        self._repository.add_signature_text(revision_id, text)
