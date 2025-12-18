# Copyright (C) 2008-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# Copyright (C) 2008 John Carr
# Copyright (C) 2008-2011 Canonical Ltd
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

import sys

from dulwich.object_store import MissingObjectFinder, peel_sha
from dulwich.protocol import Protocol
from dulwich.server import (
    Backend,
    BackendRepo,
    ReceivePackHandler,
    TCPGitServer,
    UploadPackHandler,
)

from .. import errors, trace
from ..controldir import ControlDir
from .mapping import decode_git_path, default_mapping
from .object_store import BazaarObjectStore, get_object_store
from .refs import get_refs_container


class BzrBackend(Backend):
    """A git serve backend that can use a Bazaar repository."""

    def __init__(self, transport):
        self.transport = transport
        self.mapping = default_mapping

    def open_repository(self, path):
        # FIXME: More secure path sanitization
        transport = self.transport.clone(decode_git_path(path).lstrip("/"))
        trace.mutter("client opens %r: %r", path, transport)
        return BzrBackendRepo(transport, self.mapping)


class BzrBackendRepo(BackendRepo):
    def __init__(self, transport, mapping):
        self.mapping = mapping
        self.repo_dir = ControlDir.open_from_transport(transport)
        self.repo = self.repo_dir.find_repository()
        self.object_store = get_object_store(self.repo)
        self.refs = get_refs_container(self.repo_dir, self.object_store)
        self.object_format = self.object_store.object_format

    def get_refs(self):
        with self.object_store.lock_read():
            return self.refs.as_dict()

    def get_peeled(self, name):
        cached = self.refs.get_peeled(name)
        if cached is not None:
            return cached
        return peel_sha(self.object_store, self.refs[name])[1].id

    def find_missing_objects(
        self, determine_wants, graph_walker, progress, get_tagged=None
    ):
        """Yield git objects to send to client."""
        with self.object_store.lock_read():
            wants = determine_wants(self.get_refs())
            have = self.object_store.find_common_revisions(graph_walker)
            if wants is None:
                return
            shallows = getattr(graph_walker, "shallow", frozenset())
            if isinstance(self.object_store, BazaarObjectStore):
                return self.object_store.find_missing_objects(
                    have,
                    wants,
                    shallow=shallows,
                    progress=progress,
                    get_tagged=get_tagged,
                    lossy=True,
                )
            else:
                return MissingObjectFinder(
                    self.object_store, have, wants, shallow=shallows, progress=progress
                )


class BzrTCPGitServer(TCPGitServer):
    def handle_error(self, request, client_address):
        trace.log_exception_quietly()
        trace.warning(
            "Exception happened during processing of request from %s", client_address
        )


def serve_git(transport, host=None, port=None, inet=False, timeout=None):
    backend = BzrBackend(transport)

    if host is None:
        host = "localhost"
    if port:
        server = BzrTCPGitServer(backend, host, port)
    else:
        server = BzrTCPGitServer(backend, host)
    server.serve_forever()


def git_http_hook(branch, method, path):
    from dulwich.web import DEFAULT_HANDLERS, HTTPGitApplication, HTTPGitRequest

    handler = None
    for smethod, spath in HTTPGitApplication.services:
        if smethod != method:
            continue
        mat = spath.search(path)
        if mat:
            handler = HTTPGitApplication.services[smethod, spath]
            break
    if handler is None:
        return None
    backend = BzrBackend(branch.user_transport)

    def git_call(environ, start_response):
        req = HTTPGitRequest(
            environ, start_response, dumb=False, handlers=DEFAULT_HANDLERS
        )
        return handler(req, backend, mat)

    return git_call


def serve_command(handler_cls, backend, inf=sys.stdin, outf=sys.stdout):
    """Serve a single command.

    This is mostly useful for the implementation of commands used by e.g. git+ssh.

    :param handler_cls: `Handler` class to use for the request
    :param argv: execv-style command-line arguments. Defaults to sys.argv.
    :param backend: `Backend` to use
    :param inf: File-like object to read from, defaults to standard input.
    :param outf: File-like object to write to, defaults to standard output.
    :return: Exit code for use with sys.exit. 0 on success, 1 on failure.
    """

    def send_fn(data):
        outf.write(data)
        outf.flush()

    proto = Protocol(inf.read, send_fn)
    handler = handler_cls(backend, ["/"], proto)
    # FIXME: Catch exceptions and write a single-line summary to outf.
    handler.handle()
    return 0


def serve_git_receive_pack(transport, host=None, port=None, inet=False):
    if not inet:
        raise errors.CommandError("git-receive-pack only works in inetd mode")
    backend = BzrBackend(transport)
    sys.exit(serve_command(ReceivePackHandler, backend=backend))


def serve_git_upload_pack(transport, host=None, port=None, inet=False):
    if not inet:
        raise errors.CommandError("git-receive-pack only works in inetd mode")
    backend = BzrBackend(transport)
    sys.exit(serve_command(UploadPackHandler, backend=backend))
