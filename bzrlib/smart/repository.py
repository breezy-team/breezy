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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Server-side repository related request implmentations."""

from cStringIO import StringIO
import os
import sys
import tempfile
import tarfile

from bzrlib import errors
from bzrlib.bzrdir import BzrDir
from bzrlib.pack import ContainerSerialiser
from bzrlib.smart.request import (
    FailedSmartServerResponse,
    SmartServerRequest,
    SuccessfulSmartServerResponse,
    )
from bzrlib import revision as _mod_revision


class SmartServerRepositoryRequest(SmartServerRequest):
    """Common base class for Repository requests."""

    def do(self, path, *args):
        """Execute a repository request.
        
        The repository must be at the exact path - no searching is done.

        The actual logic is delegated to self.do_repository_request.

        :param path: The path for the repository.
        :return: A smart server from self.do_repository_request().
        """
        transport = self._backing_transport.clone(path)
        bzrdir = BzrDir.open_from_transport(transport)
        # Save the repository for use with do_body.
        self._repository = bzrdir.open_repository()
        return self.do_repository_request(self._repository, *args)

    def do_repository_request(self, repository, *args):
        """Override to provide an implementation for a verb."""
        # No-op for verbs that take bodies (None as a result indicates a body
        # is expected)
        return None


class SmartServerRepositoryGetParentMap(SmartServerRepositoryRequest):
    
    def do_repository_request(self, repository, *revision_ids):
        repository.lock_read()
        try:
            return self._do_repository_request(repository, revision_ids)
        finally:
            repository.unlock()

    def _do_repository_request(self, repository, revision_ids):
        """Get parent details for some revisions.
        
        All the parents for revision_ids are returned. Additionally up to 64KB
        of additional parent data found by performing a breadth first search
        from revision_ids is returned.

        :param repository: The repository to query in.
        :param revision_ids: The utf8 encoded revision_id to answer for.
        :return: A smart server response where the body contains an utf8
            encoded flattened list of the parents of the revisions, (the same
            format as Repository.get_revision_graph).
        """
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
            next_revs = set()
            for revision_id, parents in parent_map.iteritems():
                # adjust for the wire
                if parents == (_mod_revision.NULL_REVISION,):
                    parents = ()
                # add parents to the result
                result[revision_id] = parents
                # prepare the next query
                next_revs.update(parents)
                # Approximate the serialized cost of this revision_id.
                size_so_far += 2 + len(revision_id) + sum(map(len, parents))
                # get all the directly asked for parents, and then flesh out to
                # 64K or so.
                if first_loop_done and size_so_far > 65000:
                    next_revs = set()
                    break
            # don't query things we've already queried
            next_revs.difference_update(queried_revs)
            first_loop_done = True

        for revision, parents in result.items():
            lines.append(' '.join((revision, ) + tuple(parents)))

        return SuccessfulSmartServerResponse(('ok', ), '\n'.join(lines))


class SmartServerRepositoryGetRevisionGraph(SmartServerRepositoryRequest):
    
    def do_repository_request(self, repository, revision_id):
        """Return the result of repository.get_revision_graph(revision_id).
        
        :param repository: The repository to query in.
        :param revision_id: The utf8 encoded revision_id to get a graph from.
        :return: A smart server response where the body contains an utf8
            encoded flattened list of the revision graph.
        """
        if not revision_id:
            revision_id = None

        lines = []
        try:
            revision_graph = repository.get_revision_graph(revision_id)
        except errors.NoSuchRevision:
            # Note that we return an empty body, rather than omitting the body.
            # This way the client knows that it can always expect to find a body
            # in the response for this method, even in the error case.
            return FailedSmartServerResponse(('nosuchrevision', revision_id), '')

        for revision, parents in revision_graph.items():
            lines.append(' '.join((revision, ) + tuple(parents)))

        return SuccessfulSmartServerResponse(('ok', ), '\n'.join(lines))


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
              size:45

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


class SmartServerRepositoryUnlock(SmartServerRepositoryRequest):

    def do_repository_request(self, repository, token):
        try:
            repository.lock_write(token=token)
        except errors.TokenMismatch, e:
            return FailedSmartServerResponse(('TokenMismatch',))
        repository.dont_leave_lock_in_place()
        repository.unlock()
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
        from bzrlib import osutils
        repo_transport = repository.control_files._transport
        tmp_dirname, tmp_repo = self._copy_to_tempdir(repository)
        try:
            controldir_name = tmp_dirname + '/.bzr'
            return self._tarfile_response(controldir_name, compression)
        finally:
            osutils.rmtree(tmp_dirname)

    def _copy_to_tempdir(self, from_repo):
        tmp_dirname = tempfile.mkdtemp(prefix='tmpbzrclone')
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
            # FIXME: Don't read the whole thing into memory here; rather stream it
            # out from the file onto the network. mbp 20070411
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
            assert dirname.endswith('.bzr')
            tarball.add(dirname, '.bzr') # recursive by default
        finally:
            tarball.close()


class SmartServerRepositoryStreamKnitDataForRevisions(SmartServerRepositoryRequest):
    """Bzr <= 1.1 streaming pull, buffers all data on server."""

    def do_repository_request(self, repository, *revision_ids):
        repository.lock_read()
        try:
            return self._do_repository_request(repository, revision_ids)
        finally:
            repository.unlock()

    def _do_repository_request(self, repository, revision_ids):
        stream = repository.get_data_stream_for_search(
            repository.revision_ids_to_search_result(set(revision_ids)))
        buffer = StringIO()
        pack = ContainerSerialiser()
        buffer.write(pack.begin())
        try:
            for name_tuple, bytes in stream:
                buffer.write(pack.bytes_record(bytes, [name_tuple]))
        except errors.RevisionNotPresent, e:
            return FailedSmartServerResponse(('NoSuchRevision', e.revision_id))
        buffer.write(pack.end())
        return SuccessfulSmartServerResponse(('ok',), buffer.getvalue())


class SmartServerRepositoryStreamRevisionsChunked(SmartServerRepositoryRequest):
    """Bzr 1.1+ streaming pull."""

    def do_body(self, body_bytes):
        lines = body_bytes.split('\n')
        start_keys = set(lines[0].split(' '))
        exclude_keys = set(lines[1].split(' '))
        revision_count = int(lines[2])
        repository = self._repository
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
            if search_result.get_recipe()[2] != revision_count:
                # we got back a different amount of data than expected, this
                # gets reported as NoSuchRevision, because less revisions
                # indicates missing revisions, and more should never happen as
                # the excludes list considers ghosts and ensures that ghost
                # filling races are not a problem.
                return FailedSmartServerResponse(('NoSuchRevision',))
            stream = repository.get_data_stream_for_search(search_result)
        except Exception:
            repository.unlock()
            raise
        return SuccessfulSmartServerResponse(('ok',),
            body_stream=self.body_stream(stream, repository))

    def body_stream(self, stream, repository):
        pack = ContainerSerialiser()
        yield pack.begin()
        try:
            for name_tuple, bytes in stream:
                yield pack.bytes_record(bytes, [name_tuple])
        except errors.RevisionNotPresent, e:
            # This shouldn't be able to happen, but as we don't buffer
            # everything it can in theory happen.
            yield FailedSmartServerResponse(('NoSuchRevision', e.revision_id))
        repository.unlock()
        pack.end()

