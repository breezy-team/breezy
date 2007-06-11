from bzrlib.bundle import serializer
from bzrlib.util import bencode

class BundleSerializerV10(serializer.BundleSerializer):

    def write(self, repository, revision_ids, forced_bases, fileobj):
        container = _PseudoContainer(fileobj)
        transaction = repository.get_transaction()
        for file_id, file_revision_ids in \
            repository.fileids_altered_by_revision_ids(revision_ids).iteritems():
            vf = repository.weave_store.get_weave(file_id, transaction)
            file_revision_ids = [r for r in revision_ids if r in
                                 file_revision_ids]
            for file_revision_id in file_revision_ids:
                text = ''.join(vf.make_mpdiff(file_revision_id).to_patch())
                container.add_record('M', len(text), ['file:%s/%s' %
                                     (file_id, file_revision_id)], text)
        container.finish()

    def read(self, file)
        

class _PseudoContainer(object):
    
    def __init__(self, fileobj):
        self._records = []
        self._fileobj = fileobj

    def add_record(self, type, size, names, text):
        self._records.append((type, size, names, text))

    def finish(self):
        self._fileobj.write(bencode.bencode([list(e) for e in self._records]))
