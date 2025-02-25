# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

"""RemoteTransport client for the smart-server.

This module shouldn't be accessed directly.  The classes defined here should be
imported from breezy.bzr.smart.
"""

__all__ = ["RemoteTransport", "RemoteTCPTransport", "RemoteSSHTransport"]

from io import BytesIO

from .. import config, debug, errors, trace, transport, urlutils
from ..bzr import remote
from ..bzr.smart import client, medium


class _SmartStat:
    def __init__(self, size, mode):
        self.st_size = size
        self.st_mode = mode


class RemoteTransport(transport.ConnectedTransport):
    """Connection to a smart server.

    The connection holds references to the medium that can be used to send
    requests to the server.

    The connection has a notion of the current directory to which it's
    connected; this is incorporated in filenames passed to the server.

    This supports some higher-level RPC operations and can also be treated
    like a Transport to do file-like operations.

    The connection can be made over a tcp socket, an ssh pipe or a series of
    http requests.  There are concrete subclasses for each type:
    RemoteTCPTransport, etc.
    """

    # When making a readv request, cap it at requesting 5MB of data
    _max_readv_bytes = 5 * 1024 * 1024

    # IMPORTANT FOR IMPLEMENTORS: RemoteTransport MUST NOT be given encoding
    # responsibilities: Put those on SmartClient or similar. This is vital for
    # the ability to support multiple versions of the smart protocol over time:
    # RemoteTransport is an adapter from the Transport object model to the
    # SmartClient model, not an encoder.

    # FIXME: the medium parameter should be private, only the tests requires
    # it. It may be even clearer to define a TestRemoteTransport that handles
    # the specific cases of providing a _client and/or a _medium, and leave
    # RemoteTransport as an abstract class.
    def __init__(self, url, _from_transport=None, medium=None, _client=None):
        """Constructor.

        :param _from_transport: Another RemoteTransport instance that this
            one is being cloned from.  Attributes such as the medium will
            be reused.

        :param medium: The medium to use for this RemoteTransport.  If None,
            the medium from the _from_transport is shared.  If both this
            and _from_transport are None, a new medium will be built.
            _from_transport and medium cannot both be specified.

        :param _client: Override the _SmartClient used by this transport.  This
            should only be used for testing purposes; normally this is
            determined from the medium.
        """
        super().__init__(url, _from_transport=_from_transport)

        # The medium is the connection, except when we need to share it with
        # other objects (RemoteBzrDir, RemoteRepository etc). In these cases
        # what we want to share is really the shared connection.

        if _from_transport is not None and isinstance(_from_transport, RemoteTransport):
            _client = _from_transport._client
        elif _from_transport is None:
            # If no _from_transport is specified, we need to intialize the
            # shared medium.
            credentials = None
            if medium is None:
                medium, credentials = self._build_medium()
                if debug.debug_flag_enabled("hpss"):
                    trace.mutter(
                        "hpss: Built a new medium: %s", medium.__class__.__name__
                    )
            self._shared_connection = transport._SharedConnection(
                medium, credentials, self.base
            )
        elif medium is None:
            # No medium was specified, so share the medium from the
            # _from_transport.
            medium = self._shared_connection.connection
        else:
            raise AssertionError(
                "Both _from_transport ({!r}) and medium ({!r}) passed to "
                "RemoteTransport.__init__, but these parameters are mutally "
                "exclusive.".format(_from_transport, medium)
            )

        if _client is None:
            self._client = client._SmartClient(medium)
        else:
            self._client = _client

    def _build_medium(self):
        """Create the medium if _from_transport does not provide one.

        The medium is analogous to the connection for ConnectedTransport: it
        allows connection sharing.
        """
        # No credentials
        return None, None

    def _report_activity(self, bytes, direction):
        """See Transport._report_activity.

        Does nothing; the smart medium will report activity triggered by a
        RemoteTransport.
        """
        pass

    def is_readonly(self):
        """Smart server transport can do read/write file operations."""
        try:
            resp = self._call2(b"Transport.is_readonly")
        except errors.UnknownSmartMethod:
            # XXX: nasty hack: servers before 0.16 don't have a
            # 'Transport.is_readonly' verb, so we do what clients before 0.16
            # did: assume False.
            return False
        if resp == (b"yes",):
            return True
        elif resp == (b"no",):
            return False
        else:
            raise errors.UnexpectedSmartServerResponse(resp)

    def get_smart_client(self):
        return self._get_connection()

    def get_smart_medium(self):
        return self._get_connection()

    def _remote_path(self, relpath):
        """Returns the Unicode version of the absolute path for relpath."""
        path = urlutils.combine_paths(self._parsed_url.path, relpath)
        if not isinstance(path, bytes):
            path = path.encode()
        return path

    def _call(self, method, *args):
        resp = self._call2(method, *args)
        self._ensure_ok(resp)

    def _call2(self, method, *args):
        """Call a method on the remote server."""
        try:
            return self._client.call(method, *args)
        except errors.ErrorFromSmartServer as err:
            # The first argument, if present, is always a path.
            context = {"relpath": args[0].decode("utf-8")} if args else {}
            self._translate_error(err, **context)

    def _call_with_body_bytes(self, method, args, body):
        """Call a method on the remote server with body bytes."""
        try:
            return self._client.call_with_body_bytes(method, args, body)
        except errors.ErrorFromSmartServer as err:
            # The first argument, if present, is always a path.
            context = {"relpath": args[0]} if args else {}
            self._translate_error(err, **context)

    def has(self, relpath):
        """Indicate whether a remote file of the given name exists or not.

        :see: Transport.has()
        """
        resp = self._call2(b"has", self._remote_path(relpath))
        if resp == (b"yes",):
            return True
        elif resp == (b"no",):
            return False
        else:
            raise errors.UnexpectedSmartServerResponse(resp)

    def get(self, relpath):
        """Return file-like object reading the contents of a remote file.

        :see: Transport.get_bytes()/get_file()
        """
        return BytesIO(self.get_bytes(relpath))

    def get_bytes(self, relpath):
        remote = self._remote_path(relpath)
        try:
            resp, response_handler = self._client.call_expecting_body(b"get", remote)
        except errors.ErrorFromSmartServer as err:
            self._translate_error(err, relpath)
        if resp != (b"ok",):
            response_handler.cancel_read_body()
            raise errors.UnexpectedSmartServerResponse(resp)
        return response_handler.read_body_bytes()

    def _serialise_optional_mode(self, mode):
        if mode is None:
            return b""
        else:
            return ("%d" % mode).encode("ascii")

    def mkdir(self, relpath, mode=None):
        self._call2(
            b"mkdir", self._remote_path(relpath), self._serialise_optional_mode(mode)
        )

    def open_write_stream(self, relpath, mode=None):
        """See Transport.open_write_stream."""
        self.put_bytes(relpath, b"", mode)
        result = transport.AppendBasedFileStream(self, relpath)
        transport._file_streams[self.abspath(relpath)] = result
        return result

    def put_bytes(self, relpath: str, raw_bytes: bytes, mode=None):
        if not isinstance(raw_bytes, bytes):
            raise TypeError(f"raw_bytes must be bytes string, not {type(raw_bytes)}")
        resp = self._call_with_body_bytes(
            b"put",
            (self._remote_path(relpath), self._serialise_optional_mode(mode)),
            raw_bytes,
        )
        self._ensure_ok(resp)
        return len(raw_bytes)

    def put_bytes_non_atomic(
        self,
        relpath: str,
        raw_bytes: bytes,
        mode=None,
        create_parent_dir=False,
        dir_mode=None,
    ):
        """See Transport.put_bytes_non_atomic."""
        # FIXME: no encoding in the transport!
        create_parent_str = b"F"
        if create_parent_dir:
            create_parent_str = b"T"

        resp = self._call_with_body_bytes(
            b"put_non_atomic",
            (
                self._remote_path(relpath),
                self._serialise_optional_mode(mode),
                create_parent_str,
                self._serialise_optional_mode(dir_mode),
            ),
            raw_bytes,
        )
        self._ensure_ok(resp)

    def put_file(self, relpath, upload_file, mode=None):
        # its not ideal to seek back, but currently put_non_atomic_file depends
        # on transports not reading before failing - which is a faulty
        # assumption I think - RBC 20060915
        pos = upload_file.tell()
        try:
            return self.put_bytes(relpath, upload_file.read(), mode)
        except:
            upload_file.seek(pos)
            raise

    def put_file_non_atomic(
        self, relpath, f, mode=None, create_parent_dir=False, dir_mode=None
    ):
        return self.put_bytes_non_atomic(
            relpath,
            f.read(),
            mode=mode,
            create_parent_dir=create_parent_dir,
            dir_mode=dir_mode,
        )

    def append_file(self, relpath, from_file, mode=None):
        return self.append_bytes(relpath, from_file.read(), mode)

    def append_bytes(self, relpath, bytes, mode=None):
        resp = self._call_with_body_bytes(
            b"append",
            (self._remote_path(relpath), self._serialise_optional_mode(mode)),
            bytes,
        )
        if resp[0] == b"appended":
            return int(resp[1])
        raise errors.UnexpectedSmartServerResponse(resp)

    def delete(self, relpath):
        resp = self._call2(b"delete", self._remote_path(relpath))
        self._ensure_ok(resp)

    def external_url(self):
        """See breezy.transport.Transport.external_url."""
        # the external path for RemoteTransports is the base
        return self.base

    def recommended_page_size(self):
        """Return the recommended page size for this transport."""
        return 64 * 1024

    def _readv(self, relpath, offsets):
        if not offsets:
            return

        offsets = list(offsets)

        sorted_offsets = sorted(offsets)
        coalesced = list(
            self._coalesce_offsets(
                sorted_offsets,
                limit=self._max_readv_combine,
                fudge_factor=self._bytes_to_read_before_seek,
                max_size=self._max_readv_bytes,
            )
        )

        # now that we've coallesced things, avoid making enormous requests
        requests = []
        cur_request = []
        cur_len = 0
        for c in coalesced:
            if c.length + cur_len > self._max_readv_bytes:
                requests.append(cur_request)
                cur_request = [c]
                cur_len = c.length
                continue
            cur_request.append(c)
            cur_len += c.length
        if cur_request:
            requests.append(cur_request)
        if debug.debug_flag_enabled("hpss"):
            trace.mutter(
                "%s.readv %s offsets => %s coalesced => %s requests (%s)",
                self.__class__.__name__,
                len(offsets),
                len(coalesced),
                len(requests),
                sum(map(len, requests)),
            )
        # Cache the results, but only until they have been fulfilled
        data_map = {}
        # turn the list of offsets into a single stack to iterate
        offset_stack = iter(offsets)
        # using a list so it can be modified when passing down and coming back
        next_offset = [next(offset_stack)]
        for cur_request in requests:
            try:
                result = self._client.call_with_body_readv_array(
                    (
                        b"readv",
                        self._remote_path(relpath),
                    ),
                    [(c.start, c.length) for c in cur_request],
                )
                resp, response_handler = result
            except errors.ErrorFromSmartServer as err:
                self._translate_error(err, relpath)

            if resp[0] != b"readv":
                # This should raise an exception
                response_handler.cancel_read_body()
                raise errors.UnexpectedSmartServerResponse(resp)

            yield from self._handle_response(
                offset_stack, cur_request, response_handler, data_map, next_offset
            )

    def _handle_response(
        self, offset_stack, coalesced, response_handler, data_map, next_offset
    ):
        cur_offset_and_size = next_offset[0]
        # FIXME: this should know how many bytes are needed, for clarity.
        data = response_handler.read_body_bytes()
        data_offset = 0
        for c_offset in coalesced:
            if len(data) < c_offset.length:
                raise errors.ShortReadvError(
                    relpath, c_offset.start, c_offset.length, actual=len(data)
                )
            for suboffset, subsize in c_offset.ranges:
                key = (c_offset.start + suboffset, subsize)
                this_data = data[
                    data_offset + suboffset : data_offset + suboffset + subsize
                ]
                # Special case when the data is in-order, rather than packing
                # into a map and then back out again. Benchmarking shows that
                # this has 100% hit rate, but leave in the data_map work just
                # in case.
                # TODO: Could we get away with using buffer() to avoid the
                #       memory copy?  Callers would need to realize they may
                #       not have a real string.
                if key == cur_offset_and_size:
                    yield cur_offset_and_size[0], this_data
                    try:
                        cur_offset_and_size = next_offset[0] = next(offset_stack)
                    except StopIteration:
                        return
                else:
                    data_map[key] = this_data
            data_offset += c_offset.length

            # Now that we've read some data, see if we can yield anything back
            while cur_offset_and_size in data_map:
                this_data = data_map.pop(cur_offset_and_size)
                yield cur_offset_and_size[0], this_data
                try:
                    cur_offset_and_size = next_offset[0] = next(offset_stack)
                except StopIteration:
                    return

    def rename(self, rel_from, rel_to):
        self._call(b"rename", self._remote_path(rel_from), self._remote_path(rel_to))

    def move(self, rel_from, rel_to):
        self._call(b"move", self._remote_path(rel_from), self._remote_path(rel_to))

    def rmdir(self, relpath):
        self._call(b"rmdir", self._remote_path(relpath))

    def _ensure_ok(self, resp):
        if resp[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(resp)

    def _translate_error(self, err, relpath=None):
        remote._translate_error(err, path=relpath)

    def disconnect(self):
        m = self.get_smart_medium()
        if m is not None:
            m.disconnect()

    def stat(self, relpath):
        resp = self._call2(b"stat", self._remote_path(relpath))
        if resp[0] == b"stat":
            return _SmartStat(int(resp[1]), int(resp[2], 8))
        raise errors.UnexpectedSmartServerResponse(resp)

    # def lock_read(self, relpath):
    # """Lock the given file for shared (read) access.
    # :return: A lock object, which should be passed to Transport.unlock()
    # """
    # The old RemoteBranch ignore lock for reading, so we will
    # continue that tradition and return a bogus lock object.
    # class BogusLock(object):
    # def __init__(self, path):
    ##             self.path = path
    # def unlock(self):
    # pass
    # return BogusLock(relpath)

    def listable(self):
        return True

    def list_dir(self, relpath):
        resp = self._call2(b"list_dir", self._remote_path(relpath))
        if resp[0] == b"names":
            return [name.decode("utf-8") for name in resp[1:]]
        raise errors.UnexpectedSmartServerResponse(resp)

    def iter_files_recursive(self):
        resp = self._call2(b"iter_files_recursive", self._remote_path(""))
        if resp[0] == b"names":
            return [name.decode("utf-8") for name in resp[1:]]
        raise errors.UnexpectedSmartServerResponse(resp)


class RemoteTCPTransport(RemoteTransport):
    """Connection to smart server over plain tcp.

    This is essentially just a factory to get 'RemoteTransport(url,
        SmartTCPClientMedium).
    """

    def _build_medium(self):
        client_medium = medium.SmartTCPClientMedium(
            self._parsed_url.host, self._parsed_url.port, self.base
        )
        return client_medium, None


class RemoteTCPTransportV2Only(RemoteTransport):
    """Connection to smart server over plain tcp with the client hard-coded to
    assume protocol v2 and remote server version <= 1.6.

    This should only be used for testing.
    """

    def _build_medium(self):
        client_medium = medium.SmartTCPClientMedium(
            self._parsed_url.host, self._parsed_url.port, self.base
        )
        client_medium._protocol_version = 2
        client_medium._remember_remote_is_before((1, 6))
        return client_medium, None


class RemoteSSHTransport(RemoteTransport):
    """Connection to smart server over SSH.

    This is essentially just a factory to get 'RemoteTransport(url,
        SmartSSHClientMedium).
    """

    def _build_medium(self):
        location_config = config.LocationConfig(self.base)
        bzr_remote_path = location_config.get_bzr_remote_path()
        user = self._parsed_url.user
        if user is None:
            auth = config.AuthenticationConfig()
            user = auth.get_user("ssh", self._parsed_url.host, self._parsed_url.port)
        ssh_params = medium.SSHParams(
            self._parsed_url.host,
            self._parsed_url.port,
            user,
            self._parsed_url.password,
            bzr_remote_path,
        )
        client_medium = medium.SmartSSHClientMedium(self.base, ssh_params)
        return client_medium, (user, self._parsed_url.password)


class RemoteHTTPTransport(RemoteTransport):
    """Just a way to connect between a bzr+http:// url and http://.

    This connection operates slightly differently than the RemoteSSHTransport.
    It uses a plain http:// transport underneath, which defines what remote
    .bzr/smart URL we are connected to. From there, all paths that are sent are
    sent as relative paths, this way, the remote side can properly
    de-reference them, since it is likely doing rewrite rules to translate an
    HTTP path into a local path.
    """

    def __init__(self, base, _from_transport=None, http_transport=None):
        if http_transport is None:
            # FIXME: the password may be lost here because it appears in the
            # url only for an intial construction (when the url came from the
            # command-line).
            http_url = base[len("bzr+") :]
            self._http_transport = transport.get_transport_from_url(http_url)
        else:
            self._http_transport = http_transport
        super().__init__(base, _from_transport=_from_transport)

    def _build_medium(self):
        # We let http_transport take care of the credentials
        return self._http_transport.get_smart_medium(), None

    def _remote_path(self, relpath):
        """After connecting, HTTP Transport only deals in relative URLs."""
        # Adjust the relpath based on which URL this smart transport is
        # connected to.
        http_base = urlutils.normalize_url(self.get_smart_medium().base)
        url = urlutils.join(self.base[len("bzr+") :], relpath)
        url = urlutils.normalize_url(url)
        return urlutils.relative_url(http_base, url)

    def clone(self, relative_url):
        """Make a new RemoteHTTPTransport related to me.

        This is re-implemented rather than using the default
        RemoteTransport.clone() because we must be careful about the underlying
        http transport.

        Also, the cloned smart transport will POST to the same .bzr/smart
        location as this transport (although obviously the relative paths in the
        smart requests may be different).  This is so that the server doesn't
        have to handle .bzr/smart requests at arbitrary places inside .bzr
        directories, just at the initial URL the user uses.
        """
        abs_url = self.abspath(relative_url) if relative_url else self.base
        return RemoteHTTPTransport(
            abs_url, _from_transport=self, http_transport=self._http_transport
        )

    def _redirected_to(self, source, target):
        """See transport._redirected_to."""
        redirected = self._http_transport._redirected_to(source, target)
        if redirected is not None and isinstance(
            redirected, type(self._http_transport)
        ):
            return RemoteHTTPTransport(
                "bzr+" + redirected.external_url(), http_transport=redirected
            )
        else:
            # Either None or a transport for a different protocol
            return redirected


class HintingSSHTransport(transport.Transport):
    """Simple transport that handles ssh:// and points out bzr+ssh:// and git+ssh://."""

    # TODO(jelmer): Implement support for detecting whether the repository at the
    # other end is a git or bzr repository.

    def __init__(self, url):
        raise transport.UnsupportedProtocol(
            url,
            f'Use bzr+ssh for Bazaar operations over SSH, e.g. "bzr+{url}". '
            f'Use git+ssh for Git operations over SSH, e.g. "git+{url}".',
        )


def get_test_permutations():
    """Return (transport, server) permutations for testing."""
    # We may need a little more test framework support to construct an
    # appropriate RemoteTransport in the future.
    from ..tests import test_server

    return [(RemoteTCPTransport, test_server.SmartTCPServer_for_testing)]
