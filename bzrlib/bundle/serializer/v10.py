from bzrlib import multiparent
from bzrlib.bundle import serializer
from bzrlib.util import bencode


class BundleSerializerV10(serializer.BundleSerializer):

    def write(self, repository, revision_ids, forced_bases, fileobj):
        container = _PseudoContainer(fileobj)
        transaction = repository.get_transaction()
        altered = repository.fileids_altered_by_revision_ids(revision_ids)
        for file_id, file_revision_ids in altered.iteritems():
            vf = repository.weave_store.get_weave(file_id, transaction)
            file_revision_ids = [r for r in revision_ids if r in
                                 file_revision_ids]
            for file_revision_id in file_revision_ids:
                parents = vf.get_parents(file_revision_id)
                text = ''.join(vf.make_mpdiff(file_revision_id).to_patch())
                container_name = self.encode_name('file', file_revision_id,
                                                  file_id)
                self.add_record(container, 'M', container_name, parents, text)
        for revision_id in revision_ids:
            parents = repository.revision_parents(revision_id)
            container_name = self.encode_name('inventory', revision_id)
            inventory_text = repository.get_inventory_xml(revision_id)
            self.add_record(container, 'B', container_name, parents,
                            inventory_text)
        for revision_id in revision_ids:
            parents = repository.revision_parents(revision_id)
            container_name = self.encode_name('revision', revision_id)
            revision_text = repository.get_revision_xml(revision_id)
            self.add_record(container, 'B', container_name, parents,
                            revision_text)
        container.finish()

    def add_record(self, container, type_, name, parents, text):
        parents = self.encode_parents(parents)
        text = parents + text
        container.add_record(type_, len(text), [name], text)

    def encode_parents(self, parents):
        return ' '.join(parents) + '\n'

    def decode_parents(self, parents_line):
        parents = parents_line.rstrip('\n').split(' ')
        if parents == ['']:
            parents = []
        return parents

    def read(self, file):
        container = _RecordReader(file, self)
        return container

    @staticmethod
    def encode_name(name_kind, revision_id, file_id=None):
        assert name_kind in ('revision', 'file', 'inventory')
        if name_kind in ('revision', 'inventory'):
            assert file_id is None
        else:
            assert file_id is not None
        if file_id is not None:
            file_tail = '/' + file_id
        else:
            file_tail = ''
        return name_kind + ':' + revision_id + file_tail

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


class _PseudoContainer(object):
    
    def __init__(self, fileobj):
        self._records = []
        self._fileobj = fileobj

    def add_record(self, type, size, names, text):
        self._records.append((type, size, names, text))

    def finish(self):
        self._fileobj.write(bencode.bencode([list(e) for e in self._records]))


class _RecordReader(object):

    def __init__(self, fileobj, serializer):
        self._records = [tuple(e) for e in bencode.bdecode(fileobj.read())]
        self._record_iter = iter(self._records)
        self._current_text = None
        self._serializer = serializer

    def iter_records(self):
        for type, size, names, text in self._records:
            self._current_text = text
            yield type, size, names
        yield 'E', None, None

    def read_record(self):
        return self._current_text

    def install(self, repository):
        current_file = None
        current_versionedfile = None
        pending_file_records = []
        added_inv = set()
        for type_, size, names  in self.iter_records():
            if type_ == 'E':
                self._install_file_records(current_versionedfile,
                    pending_file_records)
                break
            (name,) = names
            kind, revision_id, file_id = self._serializer.decode_name(name)
            if  kind != 'file':
                self._install_file_records(current_versionedfile,
                    pending_file_records)
                current_file = None
                current_versionedfile = None
                pending_file_records = []
                if kind == 'inventory':
                    self._install_inventory(repository, type_, revision_id,
                        self.read_record(), added_inv)
                    added_inv.add(revision_id)
                if kind == 'revision':
                    self._install_revision(repository, type_, revision_id,
                        self.read_record())
            if kind == 'file':
                if file_id != current_file:
                    self._install_file_records(current_versionedfile,
                        pending_file_records)
                    current_file = file_id
                    current_versionedfile = \
                        repository.weave_store.get_weave_or_empty(file_id,
                        repository.get_transaction())
                    pending_file_records = []
                if revision_id in current_versionedfile:
                    continue
                pending_file_records.append((type_, revision_id,
                                            self.read_record()))


    def _install_file_records(self, current_versionedfile,
                              pending_file_records):
        for type_, revision, text in pending_file_records:
            assert type_ == 'M'
            mpdiff_text = text.splitlines(True)
            parents, mpdiff_text = mpdiff_text[0], mpdiff_text[1:]
            parents = self._serializer.decode_parents(parents)
            mpdiff = multiparent.MultiParent.from_patch(mpdiff_text)
            current_versionedfile.add_mpdiff(revision, parents, mpdiff)

    def _install_inventory(self, repository, type_, revision_id, text, added):
        lines = text.splitlines(True)
        parents = self._serializer.decode_parents(lines[0])
        present_parents = [p for p in parents if
            (p in added or repository.has_revision(p))]
        text = ''.join(lines[1:])
        inv = repository.deserialise_inventory(revision_id, text)
        repository.add_inventory(revision_id, inv, present_parents)

    def _install_revision(self, repository, type_, revision_id, text):
        lines = text.splitlines(True)
        parents = self._serializer.decode_parents(lines[0])
        text = ''.join(lines[1:])
        repository._add_revision_text(revision_id, text)
