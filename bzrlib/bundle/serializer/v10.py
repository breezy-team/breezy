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
                text = ''.join(vf.make_mpdiff(file_revision_id).to_patch())
                container_name = self.encode_name('file', file_revision_id,
                                                  file_id)
                container.add_record('M', len(text), [container_name], text)
        container.finish()

    def read(self, file):
        container = _RecordReader(file, self)
        return container

    @staticmethod
    def encode_name(name_kind, revision_id, file_id=None):
        assert name_kind in ('revision', 'file')
        if name_kind in ('revision',):
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
                pending_file_records.append((type_, revision_id, [],
                                            self.read_record()))


    def _install_file_records(self, current_versionedfile,
                              pending_file_records):
        for type_, revision, parents, text in pending_file_records:
            assert type_ == 'M'
            mpdiff = multiparent.MultiParent.from_lines(text)
            current_versionedfile.add_mpdiff(revision, parents, mpdiff)
