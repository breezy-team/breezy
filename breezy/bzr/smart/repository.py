# Copyright (C) 2006-2010 Canonical Ltd
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

"""Server-side repository related request implementations."""

import bz2
import itertools
import os
import queue
import sys
import tempfile
import threading
import zlib

import fastbencode as bencode

from ... import errors, osutils, trace, ui, zlib_util
from ... import revision as _mod_revision
from ...repository import _strip_NULL_ghosts, network_format_registry
from .. import inventory as _mod_inventory
from .. import inventory_delta, pack, vf_search
from ..bzrdir import BzrDir
from ..versionedfile import (
    ChunkedContentFactory,
    NetworkRecordStream,
    record_to_fulltext_bytes,
)
from .request import (
    FailedSmartServerResponse,
    SmartServerRequest,
    SuccessfulSmartServerResponse,
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
        if search_bytes == b"everything":
            return vf_search.EverythingResult(repository), None
        lines = search_bytes.split(b"\n")
        if lines[0] == b"ancestry-of":
            heads = lines[1:]
            search_result = vf_search.PendingAncestryResult(heads, repository)
            return search_result, None
        elif lines[0] == b"search":
            return self.recreate_search_from_recipe(
                repository, lines[1:], discard_excess=discard_excess
            )
        else:
            return (None, FailedSmartServerResponse((b"BadSearch",)))

    def recreate_search_from_recipe(self, repository, lines, discard_excess=False):
        """Recreate a specific revision search (vs a from-tip search).

        :param discard_excess: If True, and the search refers to data we don't
            have, just silently accept that fact - the verb calling
            recreate_search trusts that clients will look for missing things
            they expected and get it from elsewhere.
        """
        start_keys = set(lines[0].split(b" "))
        exclude_keys = set(lines[1].split(b" "))
        revision_count = int(lines[2].decode("ascii"))
        with repository.lock_read():
            search = repository.get_graph()._make_breadth_first_searcher(start_keys)
            while True:
                try:
                    next_revs = next(search)
                except StopIteration:
                    break
                search.stop_searching_any(exclude_keys.intersection(next_revs))
            (started_keys, excludes, included_keys) = search.get_state()
            if not discard_excess and len(included_keys) != revision_count:
                # we got back a different amount of data than expected, this
                # gets reported as NoSuchRevision, because less revisions
                # indicates missing revisions, and more should never happen as
                # the excludes list considers ghosts and ensures that ghost
                # filling races are not a problem.
                return (None, FailedSmartServerResponse((b"NoSuchRevision",)))
            search_result = vf_search.SearchResult(
                started_keys, excludes, len(included_keys), included_keys
            )
            return (search_result, None)


class SmartServerRepositoryReadLocked(SmartServerRepositoryRequest):
    """Calls self.do_readlocked_repository_request."""

    def do_repository_request(self, repository, *args):
        """Read lock a repository for do_readlocked_repository_request."""
        with repository.lock_read():
            return self.do_readlocked_repository_request(repository, *args)


class SmartServerRepositoryBreakLock(SmartServerRepositoryRequest):
    """Break a repository lock."""

    def do_repository_request(self, repository):
        repository.break_lock()
        return SuccessfulSmartServerResponse((b"ok",))


_lsprof_count = 0


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
        return None  # Signal that we want a body.

    def do_body(self, body_bytes):
        """Process the current search state and perform the parent lookup.

        :return: A smart server response where the body contains an utf8
            encoded flattened list of the parents of the revisions (the same
            format as Repository.get_revision_graph) which has been bz2
            compressed.
        """
        repository = self._repository
        with repository.lock_read():
            return self._do_repository_request(body_bytes)

    def _expand_requested_revs(
        self,
        repo_graph,
        revision_ids,
        client_seen_revs,
        include_missing,
        max_size=65536,
    ):
        result = {}
        queried_revs = set()
        estimator = zlib_util.ZLibEstimator(max_size)
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
                    encoded_id = b"missing:" + revision_id
                    parents = []
                if revision_id not in client_seen_revs and (
                    not missing_rev or include_missing
                ):
                    # Client does not have this revision, give it to it.
                    # add parents to the result
                    result[encoded_id] = parents
                    # Approximate the serialized cost of this revision_id.
                    line = encoded_id + b" " + b" ".join(parents) + b"\n"
                    estimator.add_content(line)
            # get all the directly asked for parents, and then flesh out to
            # 64K (compressed) or so. We do one level of depth at a time to
            # stay in sync with the client. The 250000 magic number is
            # estimated compression ratio taken from bzr.dev itself.
            if self.no_extra_results or (first_loop_done and estimator.full()):
                trace.mutter(
                    "size: %d, z_size: %d"
                    % (
                        estimator._uncompressed_size_added,
                        estimator._compressed_size_added,
                    )
                )
                next_revs = set()
                break
            # don't query things we've already queried
            next_revs = next_revs.difference(queried_revs)
            first_loop_done = True
        return result

    def _do_repository_request(self, body_bytes):
        repository = self._repository
        revision_ids = set(self._revision_ids)
        include_missing = b"include-missing:" in revision_ids
        if include_missing:
            revision_ids.remove(b"include-missing:")
        body_lines = body_bytes.split(b"\n")
        search_result, error = self.recreate_search_from_recipe(repository, body_lines)
        if error is not None:
            return error
        # TODO might be nice to start up the search again; but thats not
        # written or tested yet.
        client_seen_revs = set(search_result.get_keys())
        # Always include the requested ids.
        client_seen_revs.difference_update(revision_ids)

        repo_graph = repository.get_graph()
        result = self._expand_requested_revs(
            repo_graph, revision_ids, client_seen_revs, include_missing
        )

        # sorting trivially puts lexographically similar revision ids together.
        # Compression FTW.
        lines = []
        for revision, parents in sorted(result.items()):
            lines.append(b" ".join((revision,) + tuple(parents)))

        return SuccessfulSmartServerResponse((b"ok",), bz2.compress(b"\n".join(lines)))


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
        search_ids = [revision_id] if revision_id else repository.all_revision_ids()
        search = graph._make_breadth_first_searcher(search_ids)
        transitive_ids = set(itertools.chain.from_iterable(search))
        parent_map = graph.get_parent_map(transitive_ids)
        revision_graph = _strip_NULL_ghosts(parent_map)
        if revision_id and revision_id not in revision_graph:
            # Note that we return an empty body, rather than omitting the body.
            # This way the client knows that it can always expect to find a body
            # in the response for this method, even in the error case.
            return FailedSmartServerResponse((b"nosuchrevision", revision_id), b"")

        for revision, parents in revision_graph.items():
            lines.append(b" ".join((revision,) + tuple(parents)))

        return SuccessfulSmartServerResponse((b"ok",), b"\n".join(lines))


class SmartServerRepositoryGetRevIdForRevno(SmartServerRepositoryReadLocked):
    def do_readlocked_repository_request(self, repository, revno, known_pair):
        """Find the revid for a given revno, given a known revno/revid pair.

        New in 1.17.
        """
        try:
            found_flag, result = repository.get_rev_id_for_revno(revno, known_pair)
        except errors.NoSuchRevision as err:
            if err.revision != known_pair[1]:
                raise AssertionError(
                    "get_rev_id_for_revno raised RevisionNotPresent for "
                    "non-initial revision: " + err.revision
                ) from err
            return FailedSmartServerResponse((b"nosuchrevision", err.revision))
        except errors.RevnoOutOfBounds as e:
            return FailedSmartServerResponse(
                (b"revno-outofbounds", e.revno, e.minimum, e.maximum)
            )
        if found_flag:
            return SuccessfulSmartServerResponse((b"ok", result))
        else:
            earliest_revno, earliest_revid = result
            return SuccessfulSmartServerResponse(
                (b"history-incomplete", earliest_revno, earliest_revid)
            )


class SmartServerRepositoryGetSerializerFormat(SmartServerRepositoryRequest):
    def do_repository_request(self, repository):
        """Return the serializer format for this repository.

        New in 2.5.0.

        :param repository: The repository to query
        :return: A smart server response (b'ok', FORMAT)
        """
        serializer = repository.get_serializer_format()
        return SuccessfulSmartServerResponse((b"ok", serializer))


class SmartServerRequestHasRevision(SmartServerRepositoryRequest):
    def do_repository_request(self, repository, revision_id):
        """Return ok if a specific revision is in the repository at path.

        :param repository: The repository to query in.
        :param revision_id: The utf8 encoded revision_id to lookup.
        :return: A smart server response of ('yes', ) if the revision is
            present. ('no', ) if it is missing.
        """
        if repository.has_revision(revision_id):
            return SuccessfulSmartServerResponse((b"yes",))
        else:
            return SuccessfulSmartServerResponse((b"no",))


class SmartServerRequestHasSignatureForRevisionId(SmartServerRepositoryRequest):
    def do_repository_request(self, repository, revision_id):
        """Return ok if a signature is present for a revision.

        Introduced in bzr 2.5.0.

        :param repository: The repository to query in.
        :param revision_id: The utf8 encoded revision_id to lookup.
        :return: A smart server response of ('yes', ) if a
            signature for the revision is present,
            ('no', ) if it is missing.
        """
        try:
            if repository.has_signature_for_revision_id(revision_id):
                return SuccessfulSmartServerResponse((b"yes",))
            else:
                return SuccessfulSmartServerResponse((b"no",))
        except errors.NoSuchRevision:
            return FailedSmartServerResponse((b"nosuchrevision", revision_id))


class SmartServerRepositoryGatherStats(SmartServerRepositoryRequest):
    def do_repository_request(self, repository, revid, committers):
        """Return the result of repository.gather_stats().

        :param repository: The repository to query in.
        :param revid: utf8 encoded rev id or an empty string to indicate None
        :param committers: 'yes' or 'no'.

        :return: A SmartServerResponse (b'ok',), a encoded body looking like
              committers: 1
              firstrev: 1234.230 0
              latestrev: 345.700 3600
              revisions: 2

              But containing only fields returned by the gather_stats() call
        """
        decoded_revision_id = None if revid == b"" else revid
        decoded_committers = True if committers == b"yes" else None
        try:
            stats = repository.gather_stats(decoded_revision_id, decoded_committers)
        except errors.NoSuchRevision:
            return FailedSmartServerResponse((b"nosuchrevision", revid))

        body = b""
        if "committers" in stats:
            body += b"committers: %d\n" % stats["committers"]
        if "firstrev" in stats:
            body += b"firstrev: %.3f %d\n" % stats["firstrev"]
        if "latestrev" in stats:
            body += b"latestrev: %.3f %d\n" % stats["latestrev"]
        if "revisions" in stats:
            body += b"revisions: %d\n" % stats["revisions"]
        if "size" in stats:
            body += b"size: %d\n" % stats["size"]

        return SuccessfulSmartServerResponse((b"ok",), body)


class SmartServerRepositoryGetRevisionSignatureText(SmartServerRepositoryRequest):
    """Return the signature text of a revision.

    New in 2.5.
    """

    def do_repository_request(self, repository, revision_id):
        """Return the result of repository.get_signature_text().

        :param repository: The repository to query in.
        :return: A smart server response of with the signature text as
            body.
        """
        try:
            text = repository.get_signature_text(revision_id)
        except errors.NoSuchRevision as err:
            return FailedSmartServerResponse((b"nosuchrevision", err.revision))
        return SuccessfulSmartServerResponse((b"ok",), text)


class SmartServerRepositoryIsShared(SmartServerRepositoryRequest):
    def do_repository_request(self, repository):
        """Return the result of repository.is_shared().

        :param repository: The repository to query in.
        :return: A smart server response of ('yes', ) if the repository is
            shared, and ('no', ) if it is not.
        """
        if repository.is_shared():
            return SuccessfulSmartServerResponse((b"yes",))
        else:
            return SuccessfulSmartServerResponse((b"no",))


class SmartServerRepositoryMakeWorkingTrees(SmartServerRepositoryRequest):
    def do_repository_request(self, repository):
        """Return the result of repository.make_working_trees().

        Introduced in bzr 2.5.0.

        :param repository: The repository to query in.
        :return: A smart server response of ('yes', ) if the repository uses
            working trees, and ('no', ) if it is not.
        """
        if repository.make_working_trees():
            return SuccessfulSmartServerResponse((b"yes",))
        else:
            return SuccessfulSmartServerResponse((b"no",))


class SmartServerRepositoryLockWrite(SmartServerRepositoryRequest):
    def do_repository_request(self, repository, token=b""):
        # XXX: this probably should not have a token.
        if token == b"":
            token = None
        try:
            token = repository.lock_write(token=token).repository_token
        except errors.LockContention:
            return FailedSmartServerResponse((b"LockContention",))
        except errors.UnlockableTransport:
            return FailedSmartServerResponse((b"UnlockableTransport",))
        except errors.LockFailed as e:
            return FailedSmartServerResponse((b"LockFailed", str(e.lock), str(e.why)))
        if token is not None:
            repository.leave_lock_in_place()
        repository.unlock()
        if token is None:
            token = b""
        return SuccessfulSmartServerResponse((b"ok", token))


class SmartServerRepositoryGetStream(SmartServerRepositoryRequest):
    def do_repository_request(self, repository, to_network_name):
        """Get a stream for inserting into a to_format repository.

        The request body is 'search_bytes', a description of the revisions
        being requested.

        In 2.3 this verb added support for search_bytes == 'everything'.  Older
        implementations will respond with a BadSearch error, and clients should
        catch this and fallback appropriately.

        :param repository: The repository to stream from.
        :param to_network_name: The network name of the format of the target
            repository.
        """
        self._to_format = network_format_registry.get(to_network_name)
        if self._should_fake_unknown():
            return FailedSmartServerResponse(
                (b"UnknownMethod", b"Repository.get_stream")
            )
        return None  # Signal that we want a body.

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
        if (  # noqa: SIM103
            to_format.supports_chks
            and from_format.repository_class is to_format.repository_class
            and from_format._revision_serializer == to_format._revision_serializer
            and from_format._inventory_serializer == to_format._inventory_serializer
        ):
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
            search_result, error = self.recreate_search(
                repository, body_bytes, discard_excess=True
            )
            if error is not None:
                repository.unlock()
                return error
            source = repository._get_source(self._to_format)
            stream = source.get_stream(search_result)
        except Exception:
            try:
                # On non-error, unlocking is done by the body stream handler.
                repository.unlock()
            finally:
                raise
        return SuccessfulSmartServerResponse(
            (b"ok",), body_stream=self.body_stream(stream, repository)
        )

    def body_stream(self, stream, repository):
        byte_stream = _stream_to_byte_stream(stream, repository._format)
        try:
            yield from byte_stream
        except errors.RevisionNotPresent as e:
            # This shouldn't be able to happen, but as we don't buffer
            # everything it can in theory happen.
            repository.unlock()
            yield FailedSmartServerResponse((b"NoSuchRevision", e.revision_id))
        else:
            repository.unlock()


class SmartServerRepositoryGetStream_1_19(SmartServerRepositoryGetStream):
    """The same as Repository.get_stream, but will return stream CHK formats to
    clients.

    See SmartServerRepositoryGetStream._should_fake_unknown.

    New in 1.19.
    """

    def _should_fake_unknown(self):
        """Returns False; we don't need to workaround bugs in 1.19+ clients."""
        return False


def _stream_to_byte_stream(stream, src_format):
    """Convert a record stream to a self delimited byte stream."""
    pack_writer = pack.ContainerSerialiser()
    yield pack_writer.begin()
    yield pack_writer.bytes_record(src_format.network_name(), b"")
    for substream_type, substream in stream:
        for record in substream:
            if record.storage_kind in ("chunked", "fulltext"):
                serialised = record_to_fulltext_bytes(record)
            elif record.storage_kind == "absent":
                raise ValueError(f"Absent factory for {record.key}")
            else:
                serialised = record.get_bytes_as(record.storage_kind)
            if serialised:
                # Some streams embed the whole stream into the wire
                # representation of the first record, which means that
                # later records have no wire representation: we skip them.
                yield pack_writer.bytes_record(
                    serialised, [(substream_type.encode("ascii"),)]
                )
    yield pack_writer.end()


class _ByteStreamDecoder:
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

    def __init__(self, byte_stream, record_counter):
        """Create a _ByteStreamDecoder."""
        self.stream_decoder = pack.ContainerPushParser()
        self.current_type = None
        self.first_bytes = None
        self.byte_stream = byte_stream
        self._record_counter = record_counter
        self.key_count = 0

    def iter_stream_decoder(self):
        """Iterate the contents of the pack from stream_decoder."""
        # dequeue pending items
        yield from self.stream_decoder.read_pending_records()
        # Pull bytes of the wire, decode them to records, yield those records.
        for bytes in self.byte_stream:
            self.stream_decoder.accept_bytes(bytes)
            yield from self.stream_decoder.read_pending_records()

    def iter_substream_bytes(self):
        if self.first_bytes is not None:
            yield self.first_bytes
            # If we run out of pack records, single the outer layer to stop.
            self.first_bytes = None
        for record in self.iter_pack_records:
            record_names, record_bytes = record
            (record_name,) = record_names
            substream_type = record_name[0]
            if substream_type != self.current_type:
                # end of a substream, seed the next substream.
                self.current_type = substream_type
                self.first_bytes = record_bytes
                return
            yield record_bytes

    def record_stream(self):
        """Yield substream_type, substream from the byte stream."""

        def wrap_and_count(pb, rc, substream):
            """Yield records from stream while showing progress."""
            counter = 0
            if rc and self.current_type != "revisions" and self.key_count != 0:
                # As we know the number of revisions now (in self.key_count)
                # we can setup and use record_counter (rc).
                if not rc.is_initialized():
                    rc.setup(self.key_count, self.key_count)
            for record in substream.read():
                if rc:
                    if rc.is_initialized() and counter == rc.STEP:
                        rc.increment(counter)
                        pb.update("Estimate", rc.current, rc.max)
                        counter = 0
                    if self.current_type == "revisions":
                        # Total records is proportional to number of revs
                        # to fetch. With remote, we used self.key_count to
                        # track the number of revs. Once we have the revs
                        # counts in self.key_count, the progress bar changes
                        # from 'Estimating..' to 'Estimate' above.
                        self.key_count += 1
                        if counter == rc.STEP:
                            pb.update("Estimating..", self.key_count)
                            counter = 0
                counter += 1
                yield record

        self.seed_state()
        with ui.ui_factory.nested_progress_bar() as pb:
            rc = self._record_counter
            try:
                # Make and consume sub generators, one per substream type:
                while self.first_bytes is not None:
                    substream = NetworkRecordStream(self.iter_substream_bytes())
                    # after substream is fully consumed, self.current_type is set
                    # to the next type, and self.first_bytes is set to the matching
                    # bytes.
                    yield (
                        self.current_type.decode("ascii"),
                        wrap_and_count(pb, rc, substream),
                    )
            finally:
                if rc:
                    pb.update("Done", rc.max, rc.max)

    def seed_state(self):
        """Prepare the _ByteStreamDecoder to decode from the pack stream."""
        # Set a single generator we can use to get data from the pack stream.
        self.iter_pack_records = self.iter_stream_decoder()
        # Seed the very first subiterator with content; after this each one
        # seeds the next.
        list(self.iter_substream_bytes())


def _byte_stream_to_stream(byte_stream, record_counter=None):
    """Convert a byte stream into a format and a stream.

    :param byte_stream: A bytes iterator, as output by _stream_to_byte_stream.
    :return: (RepositoryFormat, stream_generator)
    """
    decoder = _ByteStreamDecoder(byte_stream, record_counter)
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
        except errors.TokenMismatch:
            return FailedSmartServerResponse((b"TokenMismatch",))
        repository.dont_leave_lock_in_place()
        repository.unlock()
        return SuccessfulSmartServerResponse((b"ok",))


class SmartServerRepositoryGetPhysicalLockStatus(SmartServerRepositoryRequest):
    """Get the physical lock status for a repository.

    New in 2.5.
    """

    def do_repository_request(self, repository):
        if repository.get_physical_lock_status():
            return SuccessfulSmartServerResponse((b"yes",))
        else:
            return SuccessfulSmartServerResponse((b"no",))


class SmartServerRepositorySetMakeWorkingTrees(SmartServerRepositoryRequest):
    def do_repository_request(self, repository, str_bool_new_value):
        new_value = str_bool_new_value == b"True"
        repository.set_make_working_trees(new_value)
        return SuccessfulSmartServerResponse((b"ok",))


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
            controldir_name = tmp_dirname + "/.bzr"
            return self._tarfile_response(controldir_name, compression)
        finally:
            osutils.rmtree(tmp_dirname)

    def _copy_to_tempdir(self, from_repo):
        tmp_dirname = tempfile.mkdtemp(prefix="tmpbzrclone")
        tmp_bzrdir = from_repo.controldir._format.initialize(tmp_dirname)
        tmp_repo = from_repo._format.initialize(tmp_bzrdir)
        from_repo.copy_content_into(tmp_repo)
        return tmp_dirname, tmp_repo

    def _tarfile_response(self, tmp_dirname, compression):
        with tempfile.NamedTemporaryFile() as temp:
            self._tarball_of_dir(tmp_dirname, compression, temp.file)
            # all finished; write the tempfile out to the network
            temp.seek(0)
            return SuccessfulSmartServerResponse((b"ok",), temp.read())
            # FIXME: Don't read the whole thing into memory here; rather stream
            # it out from the file onto the network. mbp 20070411

    def _tarball_of_dir(self, dirname, compression, ofile):
        import tarfile

        filename = os.path.basename(ofile.name)
        with tarfile.open(
            fileobj=ofile, name=filename, mode="w|" + compression
        ) as tarball:
            # The tarball module only accepts ascii names, and (i guess)
            # packs them with their 8bit names.  We know all the files
            # within the repository have ASCII names so the should be safe
            # to pack in.
            dirname = dirname.encode(sys.getfilesystemencoding())
            # python's tarball module includes the whole path by default so
            # override it
            if not dirname.endswith(".bzr"):
                raise ValueError(dirname)
            tarball.add(dirname, ".bzr")  # recursive by default


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
        tokens = [token.decode("utf-8") for token in resume_tokens.split(b" ") if token]
        self.tokens = tokens
        self.repository = repository
        self.queue = queue.Queue()
        self.insert_thread = threading.Thread(target=self._inserter_thread)
        self.insert_thread.start()

    def do_chunk(self, body_stream_chunk):
        self.queue.put(body_stream_chunk)

    def _inserter_thread(self):
        try:
            src_format, stream = _byte_stream_to_stream(self.blocking_byte_stream())
            self.insert_result = self.repository._get_sink().insert_stream(
                stream, src_format, self.tokens
            )
            self.insert_ok = True
        except BaseException:
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
            (exc_type, exc_val, exc_tb) = self.insert_exception
            try:
                raise exc_val
            finally:
                del self.insert_exception
        write_group_tokens, missing_keys = self.insert_result
        if write_group_tokens or missing_keys:
            # bzip needed? missing keys should typically be a small set.
            # Should this be a streaming body response ?
            missing_keys = sorted(
                [(entry[0].encode("utf-8"),) + entry[1:] for entry in missing_keys]
            )
            bytes = bencode.bencode(
                ([token.encode("utf-8") for token in write_group_tokens], missing_keys)
            )
            self.repository.unlock()
            return SuccessfulSmartServerResponse((b"missing-basis", bytes))
        else:
            self.repository.unlock()
            return SuccessfulSmartServerResponse((b"ok",))


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
            self, repository, resume_tokens, lock_token
        )


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


class SmartServerRepositoryAddSignatureText(SmartServerRepositoryRequest):
    """Add a revision signature text.

    New in 2.5.
    """

    def do_repository_request(
        self, repository, lock_token, revision_id, *write_group_tokens
    ):
        """Add a revision signature text.

        :param repository: Repository to operate on
        :param lock_token: Lock token
        :param revision_id: Revision for which to add signature
        :param write_group_tokens: Write group tokens
        """
        self._lock_token = lock_token
        self._revision_id = revision_id
        self._write_group_tokens = [
            token.decode("utf-8") for token in write_group_tokens
        ]
        return None

    def do_body(self, body_bytes):
        """Add a signature text.

        :param body_bytes: GPG signature text
        :return: SuccessfulSmartServerResponse with arguments 'ok' and
            the list of new write group tokens.
        """
        with self._repository.lock_write(token=self._lock_token):
            self._repository.resume_write_group(self._write_group_tokens)
            try:
                self._repository.add_signature_text(self._revision_id, body_bytes)
            finally:
                new_write_group_tokens = self._repository.suspend_write_group()
        return SuccessfulSmartServerResponse(
            (b"ok",)
            + tuple([token.encode("utf-8") for token in new_write_group_tokens])
        )


class SmartServerRepositoryStartWriteGroup(SmartServerRepositoryRequest):
    """Start a write group.

    New in 2.5.
    """

    def do_repository_request(self, repository, lock_token):
        """Start a write group."""
        with repository.lock_write(token=lock_token):
            repository.start_write_group()
            try:
                tokens = repository.suspend_write_group()
            except errors.UnsuspendableWriteGroup:
                return FailedSmartServerResponse((b"UnsuspendableWriteGroup",))
        return SuccessfulSmartServerResponse((b"ok", tokens))


class SmartServerRepositoryCommitWriteGroup(SmartServerRepositoryRequest):
    """Commit a write group.

    New in 2.5.
    """

    def do_repository_request(self, repository, lock_token, write_group_tokens):
        """Commit a write group."""
        with repository.lock_write(token=lock_token):
            try:
                repository.resume_write_group(
                    [token.decode("utf-8") for token in write_group_tokens]
                )
            except errors.UnresumableWriteGroup as e:
                return FailedSmartServerResponse(
                    (
                        b"UnresumableWriteGroup",
                        [token.encode("utf-8") for token in e.write_groups],
                        e.reason.encode("utf-8"),
                    )
                )
            try:
                repository.commit_write_group()
            except:
                write_group_tokens = repository.suspend_write_group()
                # FIXME JRV 2011-11-19: What if the write_group_tokens
                # have changed?
                raise
        return SuccessfulSmartServerResponse((b"ok",))


class SmartServerRepositoryAbortWriteGroup(SmartServerRepositoryRequest):
    """Abort a write group.

    New in 2.5.
    """

    def do_repository_request(self, repository, lock_token, write_group_tokens):
        """Abort a write group."""
        with repository.lock_write(token=lock_token):
            try:
                repository.resume_write_group(
                    [token.decode("utf-8") for token in write_group_tokens]
                )
            except errors.UnresumableWriteGroup as e:
                return FailedSmartServerResponse(
                    (
                        b"UnresumableWriteGroup",
                        [token.encode("utf-8") for token in e.write_groups],
                        e.reason.encode("utf-8"),
                    )
                )
                repository.abort_write_group()
        return SuccessfulSmartServerResponse((b"ok",))


class SmartServerRepositoryCheckWriteGroup(SmartServerRepositoryRequest):
    """Check that a write group is still valid.

    New in 2.5.
    """

    def do_repository_request(self, repository, lock_token, write_group_tokens):
        """Abort a write group."""
        with repository.lock_write(token=lock_token):
            try:
                repository.resume_write_group(
                    [token.decode("utf-8") for token in write_group_tokens]
                )
            except errors.UnresumableWriteGroup as e:
                return FailedSmartServerResponse(
                    (
                        b"UnresumableWriteGroup",
                        [token.encode("utf-8") for token in e.write_groups],
                        e.reason.encode("utf-8"),
                    )
                )
            else:
                repository.suspend_write_group()
        return SuccessfulSmartServerResponse((b"ok",))


class SmartServerRepositoryAllRevisionIds(SmartServerRepositoryRequest):
    """Retrieve all of the revision ids in a repository.

    New in 2.5.
    """

    def do_repository_request(self, repository):
        revids = repository.all_revision_ids()
        return SuccessfulSmartServerResponse((b"ok",), b"\n".join(revids))


class SmartServerRepositoryReconcile(SmartServerRepositoryRequest):
    """Reconcile a repository.

    New in 2.5.
    """

    def do_repository_request(self, repository, lock_token):
        try:
            repository.lock_write(token=lock_token)
        except errors.TokenLockingNotSupported:
            return FailedSmartServerResponse((b"TokenLockingNotSupported",))
        try:
            reconciler = repository.reconcile()
        finally:
            repository.unlock()
        body = [
            b"garbage_inventories: %d\n" % reconciler.garbage_inventories,
            b"inconsistent_parents: %d\n" % reconciler.inconsistent_parents,
        ]
        return SuccessfulSmartServerResponse((b"ok",), b"".join(body))


class SmartServerRepositoryPack(SmartServerRepositoryRequest):
    """Pack a repository.

    New in 2.5.
    """

    def do_repository_request(self, repository, lock_token, clean_obsolete_packs):
        self._repository = repository
        self._lock_token = lock_token
        if clean_obsolete_packs == b"True":
            self._clean_obsolete_packs = True
        else:
            self._clean_obsolete_packs = False
        return None

    def do_body(self, body_bytes):
        hint = None if body_bytes == "" else body_bytes.splitlines()
        with self._repository.lock_write(token=self._lock_token):
            self._repository.pack(hint, self._clean_obsolete_packs)
        return SuccessfulSmartServerResponse(
            (b"ok",),
        )


class SmartServerRepositoryIterFilesBytes(SmartServerRepositoryRequest):
    r"""Iterate over the contents of files.

    The client sends a list of desired files to stream, one
    per line, and as tuples of file id and revision, separated by
    \0.

    The server replies with a stream. Each entry is preceded by a header,
    which can either be:

    * "ok\x00IDX\n" where IDX is the index of the entry in the desired files
        list sent by the client. This header is followed by the contents of
        the file, bzip2-compressed.
    * "absent\x00FILEID\x00REVISION\x00IDX" to indicate a text is missing.
        The client can then raise an appropriate RevisionNotPresent error
        or check its fallback repositories.

    New in 2.5.
    """

    def body_stream(self, repository, desired_files):
        with self._repository.lock_read():
            text_keys = {}
            for i, key in enumerate(desired_files):
                text_keys[key] = i
            for record in repository.texts.get_record_stream(
                text_keys, "unordered", True
            ):
                identifier = text_keys[record.key]
                if record.storage_kind == "absent":
                    yield b"absent\0%s\0%s\0%d\n" % (
                        record.key[0],
                        record.key[1],
                        identifier,
                    )
                    # FIXME: Way to abort early?
                    continue
                yield b"ok\0%d\n" % identifier
                compressor = zlib.compressobj()
                for bytes in record.iter_bytes_as("chunked"):
                    data = compressor.compress(bytes)
                    if data:
                        yield data
                data = compressor.flush()
                if data:
                    yield data

    def do_body(self, body_bytes):
        desired_files = [tuple(l.split(b"\0")) for l in body_bytes.splitlines()]
        return SuccessfulSmartServerResponse(
            (b"ok",), body_stream=self.body_stream(self._repository, desired_files)
        )

    def do_repository_request(self, repository):
        # Signal that we want a body
        return None


class SmartServerRepositoryIterRevisions(SmartServerRepositoryRequest):
    """Stream a list of revisions.

    The client sends a list of newline-separated revision ids in the
    body of the request and the server replies with the serializer format,
    and a stream of bzip2-compressed revision texts (using the specified
    serializer format).

    Any revisions the server does not have are omitted from the stream.

    New in 2.5.
    """

    def do_repository_request(self, repository):
        self._repository = repository
        # Signal there is a body
        return None

    def do_body(self, body_bytes):
        revision_ids = body_bytes.split(b"\n")
        return SuccessfulSmartServerResponse(
            (b"ok", self._repository.get_serializer_format()),
            body_stream=self.body_stream(self._repository, revision_ids),
        )

    def body_stream(self, repository, revision_ids):
        with self._repository.lock_read():
            for record in repository.revisions.get_record_stream(
                [(revid,) for revid in revision_ids], "unordered", True
            ):
                if record.storage_kind == "absent":
                    continue
                yield zlib.compress(record.get_bytes_as("fulltext"))


class SmartServerRepositoryGetInventories(SmartServerRepositoryRequest):
    """Get the inventory deltas for a set of revision ids.

    This accepts a list of revision ids, and then sends a chain
    of deltas for the inventories of those revisions. The first
    revision will be empty.

    The server writes back zlibbed serialized inventory deltas,
    in the ordering specified. The base for each delta is the
    inventory generated by the previous delta.

    New in 2.5.
    """

    def _inventory_delta_stream(self, repository, ordering, revids):
        prev_inv = _mod_inventory.Inventory(
            root_id=None, revision_id=_mod_revision.NULL_REVISION
        )
        serializer = inventory_delta.InventoryDeltaSerializer(
            repository.supports_rich_root(), repository._format.supports_tree_reference
        )
        with repository.lock_read():
            for inv, _revid in repository._iter_inventories(revids, ordering):
                if inv is None:
                    continue
                inv_delta = _mod_inventory._make_delta(inv, prev_inv)
                lines = serializer.delta_to_lines(
                    prev_inv.revision_id, inv.revision_id, inv_delta
                )
                yield ChunkedContentFactory((inv.revision_id,), None, None, lines)
                prev_inv = inv

    def body_stream(self, repository, ordering, revids):
        substream = self._inventory_delta_stream(repository, ordering, revids)
        return _stream_to_byte_stream(
            [("inventory-deltas", substream)], repository._format
        )

    def do_body(self, body_bytes):
        return SuccessfulSmartServerResponse(
            (b"ok",),
            body_stream=self.body_stream(
                self._repository, self._ordering, body_bytes.splitlines()
            ),
        )

    def do_repository_request(self, repository, ordering):
        ordering = ordering.decode("ascii")
        if ordering == "unordered":
            # inventory deltas for a topologically sorted stream
            # are likely to be smaller
            ordering = "topological"
        self._ordering = ordering
        # Signal that we want a body
        return None


class SmartServerRepositoryGetStreamForMissingKeys(SmartServerRepositoryRequest):
    def do_repository_request(self, repository, to_network_name):
        """Get a stream for missing keys.

        :param repository: The repository to stream from.
        :param to_network_name: The network name of the format of the target
            repository.
        """
        try:
            self._to_format = network_format_registry.get(to_network_name)
        except KeyError:
            return FailedSmartServerResponse(
                (b"UnknownFormat", b"repository", to_network_name)
            )
        return None  # Signal that we want a body.

    def do_body(self, body_bytes):
        repository = self._repository
        repository.lock_read()
        try:
            source = repository._get_source(self._to_format)
            keys = []
            for entry in body_bytes.split(b"\n"):
                (kind, revid) = entry.split(b"\t")
                keys.append((kind.decode("utf-8"), revid))
            stream = source.get_stream_for_missing_keys(keys)
        except Exception:
            try:
                # On non-error, unlocking is done by the body stream handler.
                repository.unlock()
            finally:
                raise
        return SuccessfulSmartServerResponse(
            (b"ok",), body_stream=self.body_stream(stream, repository)
        )

    def body_stream(self, stream, repository):
        byte_stream = _stream_to_byte_stream(stream, repository._format)
        try:
            yield from byte_stream
        except errors.RevisionNotPresent as e:
            # This shouldn't be able to happen, but as we don't buffer
            # everything it can in theory happen.
            repository.unlock()
            yield FailedSmartServerResponse((b"NoSuchRevision", e.revision_id))
        else:
            repository.unlock()


class SmartServerRepositoryRevisionArchive(SmartServerRepositoryRequest):
    def do_repository_request(
        self, repository, revision_id, format, name, root, subdir=None, force_mtime=None
    ):
        """Stream an archive file for a specific revision.
        :param repository: The repository to stream from.
        :param revision_id: Revision for which to export the tree
        :param format: Format (tar, tgz, tbz2, etc)
        :param name: Target file name
        :param root: Name of root directory (or '')
        :param subdir: Subdirectory to export, if not the root.
        """
        tree = repository.revision_tree(revision_id)
        if subdir is not None:
            subdir = subdir.decode("utf-8")
        if root is not None:
            root = root.decode("utf-8")
        name = name.decode("utf-8")
        return SuccessfulSmartServerResponse(
            (b"ok",),
            body_stream=self.body_stream(
                tree,
                format.decode("utf-8"),
                os.path.basename(name),
                root,
                subdir,
                force_mtime,
            ),
        )

    def body_stream(self, tree, format, name, root, subdir=None, force_mtime=None):
        with tree.lock_read():
            return tree.archive(format, name, root, subdir, force_mtime)


class SmartServerRepositoryAnnotateFileRevision(SmartServerRepositoryRequest):
    def do_repository_request(
        self, repository, revision_id, tree_path, file_id=None, default_revision=None
    ):
        """Stream an archive file for a specific revision.

        :param repository: The repository to stream from.
        :param revision_id: Revision for which to export the tree
        :param tree_path: The path inside the tree
        :param file_id: Optional file_id for the file
        :param default_revision: Default revision
        """
        tree = repository.revision_tree(revision_id)
        with tree.lock_read():
            body = bencode.bencode(
                list(tree.annotate_iter(tree_path.decode("utf-8"), default_revision))
            )
            return SuccessfulSmartServerResponse((b"ok",), body=body)
