from cStringIO import StringIO
import bz2

# The number of bytes per base64-encoded line.  We could use less, but it would
# be ugly
BASE64_LINE_BYTES = 57

from bzrlib import (
    diff,
    errors,
    iterablefile,
    multiparent,
    pack,
    revision as _mod_revision,
    testament as _mod_testament,
    trace,
    )
from bzrlib.bundle import bundle_data, serializer
from bzrlib.util import bencode


class BundleWriter(object):

    def __init__(self, fileobj):
        self._container = pack.ContainerWriter(self._write_encoded)
        self._fileobj = fileobj
        self._compressor = bz2.BZ2Compressor()
        self._base64_buffer = ''

    def begin(self):
        self._fileobj.write(serializer._get_bundle_header('1.0alpha'))
        self._fileobj.write('#\n')

    def write_patch(self, patch_text):
        """Write the human-readable patch.

        This is a required step, and it also begins the binary section.
        The patch text must not contain a line that begins with "# End of
        patch\n".  Any other string is legal.
        """
        self._fileobj.write(patch_text)
        self._fileobj.write('# End of patch\n')
        self._container.begin()

    def _write_encoded(self, bytes):
        self._base64_buffer += self._compressor.compress(bytes)
        if len(self._base64_buffer) >=  BASE64_LINE_BYTES:
            to_leave = len(self._base64_buffer) % BASE64_LINE_BYTES
            self._fileobj.write(self._base64_buffer[:-to_leave].encode(
                'base-64'))
            self._base64_buffer = self._base64_buffer[-to_leave:]

    def end(self):
        self._container.end()
        tail = self._base64_buffer+self._compressor.flush()
        self._fileobj.write(tail.encode('base-64'))

    def add_multiparent_record(self, mp_bytes, parents, repo_kind,
                               revision_id, file_id):
        self._add_record(mp_bytes, {'parents': parents}, repo_kind,
                         revision_id, file_id)

    def add_fulltext_record(self, bytes, parents, repo_kind, revision_id,
                            file_id):
        self._add_record(bytes, {'parents': parents}, repo_kind, revision_id,
                         file_id)

    @staticmethod
    def encode_parents(parents):
        return ' '.join(parents) + '\n'

    @staticmethod
    def encode_name(name_kind, revision_id, file_id=None):
        assert name_kind in ('revision', 'file', 'inventory', 'testament',
                             'signature')
        if name_kind in ('revision', 'inventory', 'testament', 'signature'):
            assert file_id is None
        else:
            assert file_id is not None
        if file_id is not None:
            file_tail = '/' + file_id
        else:
            file_tail = ''
        return name_kind + ':' + revision_id + file_tail

    def _add_record(self, bytes, metadata, repo_kind, revision_id, file_id):
        name = self.encode_name(repo_kind, revision_id, file_id)
        bytes = bencode.bencode(metadata) + '\n' + bytes
        self._container.add_bytes_record(bytes, [name])


class BundleReader(object):

    def __init__(self, fileobj):
        line = fileobj.readline()
        if line != '\n':
            fileobj.readline()
        self.patch_lines = []
        while True:
            line = fileobj.readline()
            if line.rstrip('\n') == '# End of patch':
                break
            assert line != ''
            self.patch_lines.append(line)
        self._container = pack.ContainerReader(
            StringIO(fileobj.read().decode('base-64').decode('bz2')).read)
#            Have to use StringIO for perf, until ContainerReader fixed.
#            iterablefile.IterableFile(self.iter_decode(fileobj)).read)

    @staticmethod
    def iter_decode(fileobj):
        decompressor = bz2.BZ2Decompressor()
        for line in fileobj:
            yield decompressor.decompress(line.decode('base-64'))

    @staticmethod
    def decode_name(name):
        kind, revisionfile_id = name.split(':', 1)
        revisionfile_id = revisionfile_id.split('/')
        if len(revisionfile_id) == 1:
            revision_id = revisionfile_id[0]
            file_id = None
        else:
            revision_id, file_id = revisionfile_id
        return kind, revision_id, file_id

    def decode_parents(self, parents_line):
        parents = parents_line.rstrip('\n').split(' ')
        if parents == ['']:
            parents = []
        return parents

    def iter_records(self):
        for (name,), bytes in self._container.iter_records():
            lines = bytes(None).splitlines(True)
            parents, lines = lines[0], lines[1:]
            parents = bencode.bdecode(parents.rstrip('\n')).get('parents')
            yield (''.join(lines), parents) + self.decode_name(name)


class BundleSerializerV10(serializer.BundleSerializer):

    def write(self, repository, revision_ids, forced_bases, fileobj):
        write_op = BundleWriteOperation.from_old_args(repository, revision_ids,
                                                      forced_bases, fileobj)
        return write_op.do_write()

    def write_bundle(self, repository, target, base, fileobj):
        write_op =  BundleWriteOperation(base, target, repository, fileobj)
        return write_op.do_write()

    def read(self, file):
        bundle = BundleInfoV10(file, self)
        return bundle


class BundleWriteOperation(object):

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
        self.base_ancestry = set(repository.get_ancestry(base))
        if revision_ids is not None:
            self.revision_ids = revision_ids
        else:
            revision_ids = set(repository.get_ancestry(target))
            self.revision_ids = revision_ids.difference(self.base_ancestry)

    def do_write(self):
        self.bundle.begin()
        self.write_patch()
        self.write_files()
        self.write_revisions()
        self.write_testament()
        self.bundle.end()
        return self.revision_ids

    def iter_file_revisions(self):
        """This is the correct approach, but not compatible.

        It does not work with bzr.dev, because certain old revisions were not
        converted correctly, and have the wrong "revision" marker in
        inventories.
        """
        transaction = self.repository.get_transaction()
        altered = self.repository.fileids_altered_by_revision_ids(
            self.revision_ids)
        for file_id, file_revision_ids in altered.iteritems():
            vf = self.repository.weave_store.get_weave(file_id, transaction)
            yield vf, file_id, file_revision_ids

    def iter_file_revisions_aggressive(self):
        """Ensure that all required revisions are fetched.

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
        for vf, file_id, revision_ids in self.iter_file_revisions_aggressive():
            self.add_mp_records('file', file_id, vf, revision_ids)

    def write_revisions(self):
        inv_vf = self.repository.get_inventory_weave()
        revision_order = list(multiparent.topo_iter(inv_vf, self.revision_ids))
        if self.target is not None:
            revision_order.remove(self.target)
            revision_order.append(self.target)
        self.add_mp_records('inventory', None, inv_vf, revision_order)
        for revision_id in revision_order:
            parents = self.repository.revision_parents(revision_id)
            revision_text = self.repository.get_revision_xml(revision_id)
            self.bundle.add_fulltext_record(revision_text, parents,
                                       'revision', revision_id, None)
            try:
                self.bundle.add_fulltext_record(
                    self.repository.get_signature_text(
                    revision_id), parents, 'signature', revision_id, None)
            except errors.NoSuchRevision:
                pass

    def write_patch(self):
        patch = StringIO()
        if self.target is not None:
            base_tree = self.repository.revision_tree(self.base)
            target_tree = self.repository.revision_tree(self.target)
            diff.show_diff_trees(base_tree, target_tree, patch)
        self.bundle.write_patch(patch.getvalue())

    def write_testament(self):
        if self.target is not None:
            t = _mod_testament.StrictTestament3.from_revision(self.repository,
                                                              self.target)
            self.bundle.add_fulltext_record(t.as_short_text(), [],
                                            'testament', '', None)

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
        revision_ids = list(multiparent.topo_iter(vf, revision_ids))
        mpdiffs = vf.make_mpdiffs(revision_ids)
        for mpdiff, revision_id in zip(mpdiffs, revision_ids):
            parents = vf.get_parents(revision_id)
            text = ''.join(mpdiff.to_patch())
            self.bundle.add_multiparent_record(text, parents, repo_kind,
                                               revision_id, file_id)


class BundleInfoV10(object):

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

    def get_bundle_reader(self):
        self._fileobj.seek(0)
        return BundleReader(self._fileobj)

    def _get_real_revisions(self):
        from bzrlib import xml7
        if self.__real_revisions is None:
            self.__real_revisions = []
            bundle_reader = self.get_bundle_reader()
            for bytes, parents, repo_kind, revision_id, file_id in \
                bundle_reader.iter_records():
                if repo_kind == 'revision':
                    rev = xml7.serializer_v7.read_revision_from_string(bytes)
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

    def install(self):
        current_file = None
        current_versionedfile = None
        pending_file_records = []
        added_inv = set()
        target_revision = None
        for bytes, parents, repo_kind, revision_id, file_id in\
            self._container.iter_records():
            if repo_kind == 'testament':
                testament = bytes
            if  repo_kind != 'file':
                self._install_mp_records(current_versionedfile,
                    pending_file_records)
                current_file = None
                current_versionedfile = None
                pending_file_records = []
                if repo_kind == 'inventory':
                    self._install_inventory(revision_id, parents, bytes,
                                            added_inv)
                    added_inv.add(revision_id)
                if repo_kind == 'revision':
                    target_revision = revision_id
                    self._install_revision(revision_id, parents, bytes)
                if repo_kind == 'signature':
                    self._install_signature(revision_id, parents, bytes)
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
                pending_file_records.append((revision_id, parents, bytes))
        self._install_mp_records(current_versionedfile, pending_file_records)
        if target_revision is not None:
            self._check_testament(target_revision, testament)
        return target_revision

    def _check_testament(self, target_revision, testament):
        t = _mod_testament.StrictTestament3.from_revision(self._repository,
                                                          target_revision)
        if testament != t.as_short_text():
            raise errors.TestamentMismatch(target_revision, testament,
                                           t.as_short_text())

    def _install_mp_records(self, current_versionedfile, records):
        for revision, parents, text in records:
            mpdiff = multiparent.MultiParent.from_patch(text)
            if revision in current_versionedfile:
                continue
            current_versionedfile.add_mpdiff(revision, parents, mpdiff)

    def _install_inventory(self, revision_id, parents, text, added):
        vf = self._repository.get_inventory_weave()
        return self._install_mp_records(vf, [(revision_id, parents, text)])

    def _install_revision(self, revision_id, parents, text):
        if self._repository.has_revision(revision_id):
            return
        self._repository._add_revision_text(revision_id, text)

    def _install_signature(self, revision_id, parents, text):
        self._repository._revision_store.add_revision_signature_text(
            revision_id, text, self._repository.get_transaction())
