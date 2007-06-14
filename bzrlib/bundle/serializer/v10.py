from cStringIO import StringIO

from bzrlib import (
    multiparent,
    pack,
    timestamp,
    )
from bzrlib.bundle import bundle_data, serializer


class ContainerWriter(object):

    def __init__(self, write_func):
        self._container = pack.ContainerWriter(write_func)

    def begin(self):
        self._container.begin()

    def end(self):
        self._container.end()

    def add_multiparent_record(self, mp_bytes, parents, repo_kind,
                               revision_id, file_id):
        self._add_record(mp_bytes, parents, repo_kind, revision_id, file_id)

    def add_fulltext_record(self, bytes, parents, repo_kind, revision_id,
                            file_id):
        self._add_record(bytes, parents, repo_kind, revision_id, file_id)

    @staticmethod
    def encode_parents(parents):
        return ' '.join(parents) + '\n'

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

    def _add_record(self, bytes, parents, repo_kind, revision_id, file_id):
        name = self.encode_name(repo_kind, revision_id, file_id)
        parents = self.encode_parents(parents)
        bytes = parents + bytes
        self._container.add_bytes_record(bytes, [name])


class BundleSerializerV10(serializer.BundleSerializer):

    def write(self, repository, revision_ids, forced_bases, fileobj):
        fileobj.write(serializer._get_bundle_header('1.0alpha'))
        fileobj.write('#\n')
        s = StringIO()
        container = ContainerWriter(s.write)
        container.begin()
        transaction = repository.get_transaction()
        altered = repository.fileids_altered_by_revision_ids(revision_ids)
        for file_id, file_revision_ids in altered.iteritems():
            vf = repository.weave_store.get_weave(file_id, transaction)
            file_revision_ids = [r for r in revision_ids if r in
                                 file_revision_ids]
            self.add_mp_records(container, 'file', file_id, vf,
                                file_revision_ids)
        inv_vf = repository.get_inventory_weave()
        self.add_mp_records(container, 'inventory', None, inv_vf, revision_ids)
        for revision_id in revision_ids:
            parents = repository.revision_parents(revision_id)
            revision_text = repository.get_revision_xml(revision_id)
            container.add_fulltext_record(revision_text, parents,
                                          'revision', revision_id, None)
        container.end()
        fileobj.write(s.getvalue().encode('bz2').encode('base-64'))

    def add_mp_records(self, container, repo_kind, file_id, vf,
                       revision_ids):
        for revision_id in revision_ids:
            parents = vf.get_parents(revision_id)
            text = ''.join(vf.make_mpdiff(revision_id).to_patch())
            container.add_multiparent_record(text, parents, repo_kind,
                                             revision_id, file_id)

    def decode_parents(self, parents_line):
        parents = parents_line.rstrip('\n').split(' ')
        if parents == ['']:
            parents = []
        return parents

    def read(self, file):
        container = BundleInfoV10(file, self)
        return container

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
            ri = RevisionInstaller(self._get_container_reader(),
                                   self._serializer, repository)
            return ri.install()
        finally:
            repository.unlock()

    def _get_container_reader(self):
        self._fileobj.seek(0)
        line = self._fileobj.readline()
        if line != '\n':
            self._fileobj.readline()
        s = StringIO(self._fileobj.read().decode('base-64').decode('bz2'))
        return pack.ContainerReader(s.read)

    def _get_real_revisions(self):
        from bzrlib import xml7
        if self.__real_revisions is None:
            self.__real_revisions = []
            container = self._get_container_reader()
            for (name,), bytes in container.iter_records():
                kind, revision_id, file_id = self._serializer.decode_name(name)
                if kind == 'revision':
                    rev = xml7.serializer_v7.read_revision_from_string(bytes)
                    self.__real_revisions.append(rev)
        return self.__real_revisions
    real_revisions = property(_get_real_revisions)

    def _get_revisions(self):
        if self.__revisions is None:
            self.__revisions = []
            for revision in self.real_revisions:
                self.__revisions.append(bundle_data.RevisionInfo(
                    revision.revision_id))
                date = timestamp.format_highres_date(revision.timestamp,
                                                     revision.timezone)
                self.__revisions[-1].date = date
                self.__revisions[-1].timezone = revision.timezone
                self.__revisions[-1].timestamp = revision.timestamp
        return self.__revisions

    revisions = property(_get_revisions)


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
        for names, bytes in self._container.iter_records():
            assert len(names) == 1, repr(names)
            (name,) = names
            kind, revision_id, file_id = self._serializer.decode_name(name)
            if  kind != 'file':
                self._install_mp_records(current_versionedfile,
                    pending_file_records)
                current_file = None
                current_versionedfile = None
                pending_file_records = []
                if kind == 'inventory':
                    self._install_inventory(revision_id, bytes, added_inv)
                    added_inv.add(revision_id)
                if kind == 'revision':
                    if target_revision is None:
                        target_revision = revision_id
                    self._install_revision(revision_id, bytes)
            if kind == 'file':
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
                pending_file_records.append((revision_id, bytes))
        self._install_mp_records(current_versionedfile, pending_file_records)
        return target_revision

    def _install_mp_records(self, current_versionedfile, records):
        for revision, text in records:
            mpdiff_text = text.splitlines(True)
            parents, mpdiff_text = mpdiff_text[0], mpdiff_text[1:]
            parents = self._serializer.decode_parents(parents)
            mpdiff = multiparent.MultiParent.from_patch(mpdiff_text)
            current_versionedfile.add_mpdiff(revision, parents, mpdiff)

    def _install_inventory(self, revision_id, text, added):
        vf = self._repository.get_inventory_weave()
        return self._install_mp_records(vf, [(revision_id, text)])

    def _install_revision(self, revision_id, text):
        if self._repository.has_revision(revision_id):
            return
        lines = text.splitlines(True)
        parents = self._serializer.decode_parents(lines[0])
        text = ''.join(lines[1:])
        self._repository._add_revision_text(revision_id, text)
