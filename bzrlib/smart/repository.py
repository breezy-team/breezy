# Copyright (C) 2006, 2007 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Server-side repository related request implmentations."""

import bz2
import os
import Queue
import sys
import tarfile
import tempfile
import threading

from bzrlib import (
    bencode,
    errors,
    graph,
    osutils,
    pack,
    versionedfile,
    )
from bzrlib.bzrdir import BzrDir
from bzrlib.smart.request import (
    FailedSmartServerResponse,
    SmartServerRequest,
    SuccessfulSmartServerResponse,
    )
from bzrlib.repository import _strip_NULL_ghosts, network_format_registry
from bzrlib import revision as _mod_revision
from bzrlib.versionedfile import (
    NetworkRecordStream,
    record_to_fulltext_bytes,
    )


class SmartServerRepositoryRequest(SmartServerRequest):
    """Common base class for Repository requests."""

    def do(self, path, *args):
        """Execute a repository request.

        All Repository requests take a path to the repository as their first
        argument.  The repository must be at the exact path given by the
        client - no searching is done.

        The actual logic is delegated to self.do_repository_request.

        :param client_path: The path for the repository as received from the
            client.
        :return: A SmartServerResponse from self.do_repository_request().
        """
        transport = self.transport_from_client_path(path)
        bzrdir = BzrDir.open_from_transport(transport)
        # Save the repository for use with do_body.
        self._repository = bzrdir.open_repository()
        return self.do_repository_request(self._repository, *args)

    def do_repository_request(self, repository, *args):
        """Override to provide an implementation for a verb."""
        # No-op for verbs that take bodies (None as a result indicates a body
        # is expected)
        return None

    def recreate_search(self, repository, search_bytes, discard_excess=False):
        """Recreate a search from its serialised form.

        :param discard_excess: If True, and the search refers to data we don't
            have, just silently accept that fact - the verb calling
            recreate_search trusts that clients will look for missing things
            they expected and get it from elsewhere.
        """
        lines = search_bytes.split('\n')
        if lines[0] == 'ancestry-of':
            heads = lines[1:]
            search_result = graph.PendingAncestryResult(heads, repository)
            return search_result, None
        elif lines[0] == 'search':
            return self.recreate_search_from_recipe(repository, lines[1:],
                discard_excess=discard_excess)
        else:
            return (None, FailedSmartServerResponse(('BadSearch',)))

    def recreate_search_from_recipe(self, repository, lines,
        discard_excess=False):
        """Recreate a specific revision search (vs a from-tip search).

        :param discard_excess: If True, and the search refers to data we don't
            have, just silently accept that fact - the verb calling
            recreate_search trusts that clients will look for missing things
            they expected and get it from elsewhere.
        """
        start_keys = set(lines[0].split(' '))
        exclude_keys = set(lines[1].split(' '))
        revision_count = int(lines[2])
        repository.lock_read()
        try:
            search = repository.get_graph()._make_breadth_first_searcher(
                start_keys)
            while True:
                try:
                    next_revs = search.next()
                except StopIteration:
                    break
                search.stop_searching_any(exclude_keys.intersection(next_revs))
            search_result = search.get_result()
            if (not discard_excess and
                search_result.get_recipe()[3] != revision_count):
                # we got back a different amount of data than expected, this
                # gets reported as NoSuchRevision, because less revisions
                # indicates missing revisions, and more should never happen as
                # the excludes list considers ghosts and ensures that ghost
                # filling races are not a problem.
                return (None, FailedSmartServerResponse(('NoSuchRevision',)))
            return (search_result, None)
        finally:
            repository.unlock()


class SmartServerRepositoryReadLocked(SmartServerRepositoryRequest):
    """Calls self.do_readlocked_repository_request."""

    def do_repository_request(self, repository, *args):
        """Read lock a repository for do_readlocked_repository_request."""
        repository.lock_read()
        try:
            return self.do_readlocked_repository_request(repository, *args)
        finally:
            repository.unlock()


class SmartServerRepositoryGetParentMap(SmartServerRepositoryRequest):
    """Bzr 1.2+ - get parent data for revisions during a graph search."""

    no_extra_results = False

    def do_repository_request(self, repository, *revision_ids):
        """Get parent details for some revisions.

        All the parents for revision_ids are returned. Additionally up to 64KB
        of additional parent data found by performing a breadth first search
        from revision_ids is returned. The verb takes a body containing the
        current search state, see do_body for details.

        If 'include-missing:' is in revision_ids, ghosts encountered in the
        graph traversal for getting parent data are included in the result with
        a prefix of 'missing:'.

        :param repository: The repository to query in.
        :param revision_ids: The utf8 encoded revision_id to answer for.
        """
        self._revision_ids = revision_ids
        return None # Signal that we want a body.

    def do_body(self, body_bytes):
        """Process the current search state and perform the parent lookup.

        :return: A smart server response where the body contains an utf8
            encoded flattened list of the parents of the revisions (the same
            format as Repository.get_revision_graph) which has been bz2
            compressed.
        """
        repository = self._repository
        repository.lock_read()
        try:
            return self._do_repository_request(body_bytes)
        finally:
            repository.unlock()

    def _do_repository_request(self, body_bytes):
        repository = self._repository
        revision_ids = set(self._revision_ids)
        include_missing = 'include-missing:' in revision_ids
        if include_missing:
            revision_ids.remove('include-missing:')
        body_lines = body_bytes.split('\n')
        search_result, error = self.recreate_search_from_recipe(
            repository, body_lines)
        if error is not None:
            return error
        # TODO might be nice to start up the search again; but thats not
        # written or tested yet.
        client_seen_revs = set(search_result.get_keys())
        # Always include the requested ids.
        client_seen_revs.difference_update(revision_ids)
        lines = []
        repo_graph = repository.get_graph()
        result = {}
        queried_revs = set()
        size_so_far = 0
        next_revs = revision_ids
        first_loop_done = False
        while next_revs:
            queried_revs.update(next_revs)
            parent_map = repo_graph.get_parent_map(next_revs)
            current_revs = next_revs
            next_revs = set()
            for revision_id in current_revs:
                missing_rev = False
                parents = parent_map.get(revision_id)
                if parents is not None:
                    # adjust for the wire
                    if parents == (_mod_revision.NULL_REVISION,):
                        parents = ()
                    # prepare the next query
                    next_revs.update(parents)
                    encoded_id = revision_id
                else:
                    missing_rev = True
                    encoded_id = "missing:" + revision_id
                    parents = []
                if (revision_id not in client_seen_revs and
                    (not missing_rev or include_missing)):
                    # Client does not have this revision, give it to it.
                    # add parents to the result
                    result[encoded_id] = parents
                    # Approximate the serialized cost of this revision_id.
                    size_so_far += 2 + len(encoded_id) + sum(map(len, parents))
            # get all the directly asked for parents, and then flesh out to
            # 64K (compressed) or so. We do one level of depth at a time to
            # stay in sync with the client. The 250000 magic number is
            # estimated compression ratio taken from bzr.dev itself.
            if self.no_extra_results or (
                first_loop_done and size_so_far > 250000):
                next_revs = set()
                break
            # don't query things we've already queried
            next_revs.difference_update(queried_revs)
            first_loop_done = True

        # sorting trivially puts lexographically similar revision ids together.
        # Compression FTW.
        for revision, parents in sorted(result.items()):
            lines.append(' '.join((revision, ) + tuple(parents)))

        return SuccessfulSmartServerResponse(
            ('ok', ), bz2.compress('\n'.join(lines)))


class SmartServerRepositoryGetRevisionGraph(SmartServerRepositoryReadLocked):

    def do_readlocked_repository_request(self, repository, revision_id):
        """Return the result of repository.get_revision_graph(revision_id).

        Deprecated as of bzr 1.4, but supported for older clients.

        :param repository: The repository to query in.
        :param revision_id: The utf8 encoded revision_id to get a graph from.
        :return: A smart server response where the body contains an utf8
            encoded flattened list of the revision graph.
        """
        if not revision_id:
            revision_id = None

        lines = []
        graph = repository.get_graph()
        if revision_id:
            search_ids = [revision_id]
        else:
            search_ids = repository.all_revision_ids()
        search = graph._make_breadth_first_searcher(search_ids)
        transitive_ids = set()
        map(transitive_ids.update, list(search))
        parent_map = graph.get_parent_map(transitive_ids)
        revision_graph = _strip_NULL_ghosts(parent_map)
        if revision_id and revision_id not in revision_graph:
            # Note that we return an empty body, rather than omitting the body.
            # This way the client knows that it can always expect to find a body
            # in the response for this method, even in the error case.
            return FailedSmartServerResponse(('nosuchrevision', revision_id), '')

        for revision, parents in revision_graph.items():
            lines.append(' '.join((revision, ) + tuple(parents)))

        return SuccessfulSmartServerResponse(('ok', ), '\n'.join(lines))


class SmartServerRepositoryGetRevIdForRevno(SmartServerRepositoryReadLocked):

    def do_readlocked_repository_request(self, repository, revno,
            known_pair):
        """Find the revid for a given revno, given a known revno/revid pair.
        
        New in 1.17.
        """
        try:
            found_flag, result = repository.get_rev_id_for_revno(revno, known_pair)
        except errors.RevisionNotPresent, err:
            if err.revision_id != known_pair[1]:
                raise AssertionError(
                    'get_rev_id_for_revno raised RevisionNotPresent for '
                    'non-initial revision: ' + err.revision_id)
            return FailedSmartServerResponse(
                ('nosuchrevision', err.revision_id))
        if found_flag:
            return SuccessfulSmartServerResponse(('ok', result))
        else:
            earliest_revno, earliest_revid = result
            return SuccessfulSmartServerResponse(
                ('history-incomplete', earliest_revno, earliest_revid))


class SmartServerRequestHasRevision(SmartServerRepositoryRequest):

    def do_repository_request(self, repository, revision_id):
        """Return ok if a specific revision is in the repository at path.

        :param repository: The repository to query in.
        :param revision_id: The utf8 encoded revision_id to lookup.
        :return: A smart server response of ('ok', ) if the revision is
            present.
        """
        if repository.has_revision(revision_id):
            return SuccessfulSmartServerResponse(('yes', ))
        else:
            return SuccessfulSmartServerResponse(('no', ))


class SmartServerRepositoryGatherStats(SmartServerRepositoryRequest):

    def do_repository_request(self, repository, revid, committers):
        """Return the result of repository.gather_stats().

        :param repository: The repository to query in.
        :param revid: utf8 encoded rev id or an empty string to indicate None
        :param committers: 'yes' or 'no'.

        :return: A SmartServerResponse ('ok',), a encoded body looking like
              committers: 1
              firstrev: 1234.230 0
              latestrev: 345.700 3600
              revisions: 2

              But containing only fields returned by the gather_stats() call
        """
        if revid == '':
            decoded_revision_id = None
        else:
            decoded_revision_id = revid
        if committers == 'yes':
            decoded_committers = True
        else:
            decoded_committers = None
        stats = repository.gather_stats(decoded_revision_id, decoded_committers)

        body = ''
        if stats.has_key('committers'):
            body += 'committers: %d\n' % stats['committers']
        if stats.has_key('firstrev'):
            body += 'firstrev: %.3f %d\n' % stats['firstrev']
        if stats.has_key('latestrev'):
             body += 'latestrev: %.3f %d\n' % stats['latestrev']
        if stats.has_key('revisions'):
            body += 'revisions: %d\n' % stats['revisions']
        if stats.has_key('size'):
            body += 'size: %d\n' % stats['size']

        return SuccessfulSmartServerResponse(('ok', ), body)


class SmartServerRepositoryIsShared(SmartServerRepositoryRequest):

    def do_repository_request(self, repository):
        """Return the result of repository.is_shared().

        :param repository: The repository to query in.
        :return: A smart server response of ('yes', ) if the repository is
            shared, and ('no', ) if it is not.
        """
        if repository.is_shared():
            return SuccessfulSmartServerResponse(('yes', ))
        else:
            return SuccessfulSmartServerResponse(('no', ))


class SmartServerRepositoryLockWrite(SmartServerRepositoryRequest):

    def do_repository_request(self, repository, token=''):
        # XXX: this probably should not have a token.
        if token == '':
            token = None
        try:
            token = repository.lock_write(token=token)
        except errors.LockContention, e:
            return FailedSmartServerResponse(('LockContention',))
        except errors.UnlockableTransport:
            return FailedSmartServerResponse(('UnlockableTransport',))
        except errors.LockFailed, e:
            return FailedSmartServerResponse(('LockFailed',
                str(e.lock), str(e.why)))
        if token is not None:
            repository.leave_lock_in_place()
        repository.unlock()
        if token is None:
            token = ''
        return SuccessfulSmartServerResponse(('ok', token))


class SmartServerRepositoryGetStream(SmartServerRepositoryRequest):

    def do_repository_request(self, repository, to_network_name):
        """Get a stream for inserting into a to_format repository.

        :param repository: The repository to stream from.
        :param to_network_name: The network name of the format of the target
            repository.
        """
        self._to_format = network_format_registry.get(to_network_name)
        if self._should_fake_unknown():
            return FailedSmartServerResponse(
                ('UnknownMethod', 'Repository.get_stream'))
        return None # Signal that we want a body.

    def _should_fake_unknown(self):
        """Return True if we should return UnknownMethod to the client.
        
        This is a workaround for bugs in pre-1.19 clients that claim to
        support receiving streams of CHK repositories.  The pre-1.19 client
        expects inventory records to be serialized in the format defined by
        to_network_name, but in pre-1.19 (at least) that format definition
        tries to use the xml5 serializer, which does not correctly handle
        rich-roots.  After 1.19 the client can also accept inventory-deltas
        (which avoids this issue), and those clients will use the
        Repository.get_stream_1.19 verb instead of this one.
        So: if this repository is CHK, and the to_format doesn't match,
        we should just fake an UnknownSmartMethod error so that the client
        will fallback to VFS, rather than sending it a stream we know it
        cannot handle.
        """
        from_format = self._repository._format
        to_format = self._to_format
        if not from_format.supports_chks:
            # Source not CHK: that's ok
            return False
        if (to_format.supports_chks and
            from_format.repository_class is to_format.repository_class and
            from_format._serializer == to_format._serializer):
            # Source is CHK, but target matches: that's ok
            # (e.g. 2a->2a, or CHK2->2a)
            return False
        # Source is CHK, and target is not CHK or incompatible CHK.  We can't
        # generate a compatible stream.
        return True

    def do_body(self, body_bytes):
        repository = self._repository
        repository.lock_read()
        try:
            search_result, error = self.recreate_search(repository, body_bytes,
                discard_excess=True)
            if error is not None:
                repository.unlock()
                return error
            source = repository._get_source(self._to_format)
            stream = source.get_stream(search_result)
        except Exception:
            exc_info = sys.exc_info()
            try:
                # On non-error, unlocking is done by the body stream handler.
                repository.unlock()
            finally:
                raise exc_info[0], exc_info[1], exc_info[2]
        return SuccessfulSmartServerResponse(('ok',),
            body_stream=self.body_stream(stream, repository))

    def body_stream(self, stream, repository):
        byte_stream = _stream_to_byte_stream(stream, repository._format)
        try:
            for bytes in byte_stream:
                yield bytes
        except errors.RevisionNotPresent, e:
            # This shouldn't be able to happen, but as we don't buffer
            # everything it can in theory happen.
            repository.unlock()
            yield FailedSmartServerResponse(('NoSuchRevision', e.revision_id))
        else:
            repository.unlock()


class SmartServerRepositoryGetStream_1_19(SmartServerRepositoryGetStream):

    def _should_fake_unknown(self):
        """Returns False; we don't need to workaround bugs in 1.19+ clients."""
        return False


def _stream_to_byte_stream(stream, src_format):
    """Convert a record stream to a self delimited byte stream."""
    pack_writer = pack.ContainerSerialiser()
    yield pack_writer.begin()
    yield pack_writer.bytes_record(src_format.network_name(), '')
    for substream_type, substream in stream:
        for record in substream:
            if record.storage_kind in ('chunked', 'fulltext'):
                serialised = record_to_fulltext_bytes(record)
            elif record.storage_kind == 'inventory-delta':
                serialised = record_to_inventory_delta_bytes(record)
            elif record.storage_kind == 'absent':
                raise ValueError("Absent factory for %s" % (record.key,))
            else:
                serialised = record.get_bytes_as(record.storage_kind)
            if serialised:
                # Some streams embed the whole stream into the wire
                # representation of the first record, which means that
                # later records have no wire representation: we skip them.
                yield pack_writer.bytes_record(serialised, [(substream_type,)])
    yield pack_writer.end()


class _ByteStreamDecoder(object):
    """Helper for _byte_stream_to_stream.

    The expected usage of this class is via the function _byte_stream_to_stream
    which creates a _ByteStreamDecoder, pops off the stream format and then
    yields the output of record_stream(), the main entry point to
    _ByteStreamDecoder.

    Broadly this class has to unwrap two layers of iterators:
    (type, substream)
    (substream details)

    This is complicated by wishing to return type, iterator_for_type, but
    getting the data for iterator_for_type when we find out type: we can't
    simply pass a generator down to the NetworkRecordStream parser, instead
    we have a little local state to seed each NetworkRecordStream instance,
    and gather the type that we'll be yielding.

    :ivar byte_stream: The byte stream being decoded.
    :ivar stream_decoder: A pack parser used to decode the bytestream
    :ivar current_type: The current type, used to join adjacent records of the
        same type into a single stream.
    :ivar first_bytes: The first bytes to give the next NetworkRecordStream.
    """

    def __init__(self, byte_stream):
        """Create a _ByteStreamDecoder."""
        self.stream_decoder = pack.ContainerPushParser()
        self.current_type = None
        self.first_bytes = None
        self.byte_stream = byte_stream

    def iter_stream_decoder(self):
        """Iterate the contents of the pack from stream_decoder."""
        # dequeue pending items
        for record in self.stream_decoder.read_pending_records():
            yield record
        # Pull bytes of the wire, decode them to records, yield those records.
        for bytes in self.byte_stream:
            self.stream_decoder.accept_bytes(bytes)
            for record in self.stream_decoder.read_pending_records():
                yield record

    def iter_substream_bytes(self):
        if self.first_bytes is not None:
            yield self.first_bytes
            # If we run out of pack records, single the outer layer to stop.
            self.first_bytes = None
        for record in self.iter_pack_records:
            record_names, record_bytes = record
            record_name, = record_names
            substream_type = record_name[0]
            if substream_type != self.current_type:
                # end of a substream, seed the next substream.
                self.current_type = substream_type
                self.first_bytes = record_bytes
                return
            yield record_bytes

    def record_stream(self):
        """Yield substream_type, substream from the byte stream."""
        self.seed_state()
        # Make and consume sub generators, one per substream type:
        while self.first_bytes is not None:
            substream = NetworkRecordStream(self.iter_substream_bytes())
            # after substream is fully consumed, self.current_type is set to
            # the next type, and self.first_bytes is set to the matching bytes.
            yield self.current_type, substream.read()

    def seed_state(self):
        """Prepare the _ByteStreamDecoder to decode from the pack stream."""
        # Set a single generator we can use to get data from the pack stream.
        self.iter_pack_records = self.iter_stream_decoder()
        # Seed the very first subiterator with content; after this each one
        # seeds the next.
        list(self.iter_substream_bytes())


def _byte_stream_to_stream(byte_stream):
    """Convert a byte stream into a format and a stream.

    :param byte_stream: A bytes iterator, as output by _stream_to_byte_stream.
    :return: (RepositoryFormat, stream_generator)
    """
    decoder = _ByteStreamDecoder(byte_stream)
    for bytes in byte_stream:
        decoder.stream_decoder.accept_bytes(bytes)
        for record in decoder.stream_decoder.read_pending_records(max=1):
            record_names, src_format_name = record
            src_format = network_format_registry.get(src_format_name)
            return src_format, decoder.record_stream()


class SmartServerRepositoryUnlock(SmartServerRepositoryRequest):

    def do_repository_request(self, repository, token):
        try:
            repository.lock_write(token=token)
        except errors.TokenMismatch, e:
            return FailedSmartServerResponse(('TokenMismatch',))
        repository.dont_leave_lock_in_place()
        repository.unlock()
        return SuccessfulSmartServerResponse(('ok',))


class SmartServerRepositorySetMakeWorkingTrees(SmartServerRepositoryRequest):

    def do_repository_request(self, repository, str_bool_new_value):
        if str_bool_new_value == 'True':
            new_value = True
        else:
            new_value = False
        repository.set_make_working_trees(new_value)
        return SuccessfulSmartServerResponse(('ok',))


class SmartServerRepositoryTarball(SmartServerRepositoryRequest):
    """Get the raw repository files as a tarball.

    The returned tarball contains a .bzr control directory which in turn
    contains a repository.

    This takes one parameter, compression, which currently must be
    "", "gz", or "bz2".

    This is used to implement the Repository.copy_content_into operation.
    """

    def do_repository_request(self, repository, compression):
        tmp_dirname, tmp_repo = self._copy_to_tempdir(repository)
        try:
            controldir_name = tmp_dirname + '/.bzr'
            return self._tarfile_response(controldir_name, compression)
        finally:
            osutils.rmtree(tmp_dirname)

    def _copy_to_tempdir(self, from_repo):
        tmp_dirname = osutils.mkdtemp(prefix='tmpbzrclone')
        tmp_bzrdir = from_repo.bzrdir._format.initialize(tmp_dirname)
        tmp_repo = from_repo._format.initialize(tmp_bzrdir)
        from_repo.copy_content_into(tmp_repo)
        return tmp_dirname, tmp_repo

    def _tarfile_response(self, tmp_dirname, compression):
        temp = tempfile.NamedTemporaryFile()
        try:
            self._tarball_of_dir(tmp_dirname, compression, temp.file)
            # all finished; write the tempfile out to the network
            temp.seek(0)
            return SuccessfulSmartServerResponse(('ok',), temp.read())
            # FIXME: Don't read the whole thing into memory here; rather stream
            # it out from the file onto the network. mbp 20070411
        finally:
            temp.close()

    def _tarball_of_dir(self, dirname, compression, ofile):
        filename = os.path.basename(ofile.name)
        tarball = tarfile.open(fileobj=ofile, name=filename,
            mode='w|' + compression)
        try:
            # The tarball module only accepts ascii names, and (i guess)
            # packs them with their 8bit names.  We know all the files
            # within the repository have ASCII names so the should be safe
            # to pack in.
            dirname = dirname.encode(sys.getfilesystemencoding())
            # python's tarball module includes the whole path by default so
            # override it
            if not dirname.endswith('.bzr'):
                raise ValueError(dirname)
            tarball.add(dirname, '.bzr') # recursive by default
        finally:
            tarball.close()


class SmartServerRepositoryInsertStreamLocked(SmartServerRepositoryRequest):
    """Insert a record stream from a RemoteSink into a repository.

    This gets bytes pushed to it by the network infrastructure and turns that
    into a bytes iterator using a thread. That is then processed by
    _byte_stream_to_stream.

    New in 1.14.
    """

    def do_repository_request(self, repository, resume_tokens, lock_token):
        """StreamSink.insert_stream for a remote repository."""
        repository.lock_write(token=lock_token)
        self.do_insert_stream_request(repository, resume_tokens)

    def do_insert_stream_request(self, repository, resume_tokens):
        tokens = [token for token in resume_tokens.split(' ') if token]
        self.tokens = tokens
        self.repository = repository
        self.queue = Queue.Queue()
        self.insert_thread = threading.Thread(target=self._inserter_thread)
        self.insert_thread.start()

    def do_chunk(self, body_stream_chunk):
        self.queue.put(body_stream_chunk)

    def _inserter_thread(self):
        try:
            src_format, stream = _byte_stream_to_stream(
                self.blocking_byte_stream())
            self.insert_result = self.repository._get_sink().insert_stream(
                stream, src_format, self.tokens)
            self.insert_ok = True
        except:
            self.insert_exception = sys.exc_info()
            self.insert_ok = False

    def blocking_byte_stream(self):
        while True:
            bytes = self.queue.get()
            if bytes is StopIteration:
                return
            else:
                yield bytes

    def do_end(self):
        self.queue.put(StopIteration)
        if self.insert_thread is not None:
            self.insert_thread.join()
        if not self.insert_ok:
            exc_info = self.insert_exception
            raise exc_info[0], exc_info[1], exc_info[2]
        write_group_tokens, missing_keys = self.insert_result
        if write_group_tokens or missing_keys:
            # bzip needed? missing keys should typically be a small set.
            # Should this be a streaming body response ?
            missing_keys = sorted(missing_keys)
            bytes = bencode.bencode((write_group_tokens, missing_keys))
            self.repository.unlock()
            return SuccessfulSmartServerResponse(('missing-basis', bytes))
        else:
            self.repository.unlock()
            return SuccessfulSmartServerResponse(('ok', ))


class SmartServerRepositoryInsertStream_1_19(SmartServerRepositoryInsertStreamLocked):
    """Insert a record stream from a RemoteSink into a repository.

    Same as SmartServerRepositoryInsertStreamLocked, except:
     - the lock token argument is optional
     - servers that implement this verb accept 'inventory-delta' records in the
       stream.

    New in 1.19.
    """

    def do_repository_request(self, repository, resume_tokens, lock_token=None):
        """StreamSink.insert_stream for a remote repository."""
        SmartServerRepositoryInsertStreamLocked.do_repository_request(
            self, repository, resume_tokens, lock_token)


class SmartServerRepositoryInsertStream(SmartServerRepositoryInsertStreamLocked):
    """Insert a record stream from a RemoteSink into an unlocked repository.

    This is the same as SmartServerRepositoryInsertStreamLocked, except it
    takes no lock_tokens; i.e. it works with an unlocked (or lock-free, e.g.
    like pack format) repository.

    New in 1.13.
    """

    def do_repository_request(self, repository, resume_tokens):
        """StreamSink.insert_stream for a remote repository."""
        repository.lock_write()
        self.do_insert_stream_request(repository, resume_tokens)


