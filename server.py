# Copyright (C) 2008 Jelmer Vernooij
# Copyright (C) 2008 John Carr
# Copyright (C) 2008 Canonical Ltd
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

from __future__ import absolute_import

from dulwich.server import TCPGitServer

import sys

from bzrlib import (
    errors,
    trace,
    )

from bzrlib.bzrdir import (
    BzrDir,
    )

from bzrlib.plugins.git.mapping import (
    default_mapping,
    )
from bzrlib.plugins.git.object_store import (
    get_object_store,
    )
from bzrlib.plugins.git.refs import (
    get_refs_container,
    )

from dulwich.protocol import Protocol
from dulwich.server import (
    Backend,
    BackendRepo,
    ReceivePackHandler,
    UploadPackHandler,
    )

class BzrBackend(Backend):
    """A git serve backend that can use a Bazaar repository."""

    def __init__(self, transport):
        self.transport = transport
        self.mapping = default_mapping

    def open_repository(self, path):
        # FIXME: More secure path sanitization
        transport = self.transport.clone(path.lstrip("/"))
        trace.mutter('client opens %r: %r', path, transport)
        return BzrBackendRepo(transport, self.mapping)


class BzrBackendRepo(BackendRepo):

    def __init__(self, transport, mapping):
        self.mapping = mapping
        self.repo_dir = BzrDir.open_from_transport(transport)
        self.repo = self.repo_dir.find_repository()
        self.object_store = get_object_store(self.repo)
        self.refs = get_refs_container(self.repo_dir, self.object_store)

    def get_refs(self):
        self.object_store.lock_read()
        try:
            return self.refs.as_dict()
        finally:
            self.object_store.unlock()

    def get_peeled(self, name):
        cached = self.refs.get_peeled(name)
        if cached is not None:
            return cached
        return self.object_store.peel_sha(self.refs[name]).id

    def fetch_objects(self, determine_wants, graph_walker, progress,
        get_tagged=None):
        """Yield git objects to send to client """
        self.object_store.lock_read()
        try:
            wants = determine_wants(self.get_refs())
            have = self.object_store.find_common_revisions(graph_walker)
            if wants is None:
                return
            return self.object_store.generate_pack_contents(have, wants, progress,
                get_tagged, lossy=(not self.mapping.roundtripping))
        finally:
            self.object_store.unlock()


class BzrTCPGitServer(TCPGitServer):

    def handle_error(self, request, client_address):
        trace.log_exception_quietly()
        trace.warning('Exception happened during processing of request '
                      'from %s', client_address)


def serve_git(transport, host=None, port=None, inet=False, timeout=None):
    backend = BzrBackend(transport)

    if host is None:
        host = 'localhost'
    if port:
        server = BzrTCPGitServer(backend, host, port)
    else:
        server = BzrTCPGitServer(backend, host)
    server.serve_forever()


def git_http_hook(branch, method, path):
    from dulwich.web import HTTPGitApplication, HTTPGitRequest, DEFAULT_HANDLERS
    handler = None
    for (smethod, spath) in HTTPGitApplication.services:
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
        req = HTTPGitRequest(environ, start_response, dumb=False,
                             handlers=DEFAULT_HANDLERS)
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
        raise errors.BzrCommandError(
            "git-receive-pack only works in inetd mode")
    backend = BzrBackend(transport)
    sys.exit(serve_command(ReceivePackHandler, backend=backend))


def serve_git_upload_pack(transport, host=None, port=None, inet=False):
    if not inet:
        raise errors.BzrCommandError(
            "git-receive-pack only works in inetd mode")
    backend = BzrBackend(transport)
    sys.exit(serve_command(UploadPackHandler, backend=backend))
