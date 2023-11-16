# Copyright (C) 2006-2009, 2011 Canonical Ltd
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

"""Tests for WSGI application."""

from io import BytesIO

from .. import tests
from ..bzr.smart import medium, protocol
from ..transport import chroot, memory
from ..transport.http import wsgi


class WSGITestMixin:
    def build_environ(self, updates=None):
        """Builds an environ dict with all fields required by PEP 333.

        :param updates: a dict to that will be incorporated into the returned
            dict using dict.update(updates).
        """
        environ = {
            # Required CGI variables
            "REQUEST_METHOD": "GET",
            "SCRIPT_NAME": "/script/name/",
            "PATH_INFO": "path/info",
            "SERVER_NAME": "test",
            "SERVER_PORT": "9999",
            "SERVER_PROTOCOL": "HTTP/1.0",
            # Required WSGI variables
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": BytesIO(b""),
            "wsgi.errors": BytesIO(),
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": True,
        }
        if updates is not None:
            environ.update(updates)
        return environ

    def read_response(self, iterable):
        response = b""
        for string in iterable:
            response += string
        return response

    def start_response(self, status, headers):
        self.status = status
        self.headers = headers


class TestWSGI(tests.TestCaseInTempDir, WSGITestMixin):
    def setUp(self):
        super().setUp()
        self.status = None
        self.headers = None

    def test_construct(self):
        app = wsgi.SmartWSGIApp(FakeTransport())
        self.assertIsInstance(app.backing_transport, chroot.ChrootTransport)

    def test_http_get_rejected(self):
        # GET requests are rejected.
        app = wsgi.SmartWSGIApp(FakeTransport())
        environ = self.build_environ({"REQUEST_METHOD": "GET"})
        iterable = app(environ, self.start_response)
        self.read_response(iterable)
        self.assertEqual("405 Method not allowed", self.status)
        self.assertIn(("Allow", "POST"), self.headers)

    def _fake_make_request(self, transport, write_func, bytes, rcp):
        request = FakeRequest(transport, write_func)
        request.accept_bytes(bytes)
        self.request = request
        return request

    def test_smart_wsgi_app_uses_given_relpath(self):
        # The SmartWSGIApp should use the "breezy.relpath" field from the
        # WSGI environ to clone from its backing transport to get a specific
        # transport for this request.
        transport = FakeTransport()
        wsgi_app = wsgi.SmartWSGIApp(transport)
        wsgi_app.backing_transport = transport
        wsgi_app.make_request = self._fake_make_request
        fake_input = BytesIO(b"fake request")
        environ = self.build_environ(
            {
                "REQUEST_METHOD": "POST",
                "CONTENT_LENGTH": len(fake_input.getvalue()),
                "wsgi.input": fake_input,
                "breezy.relpath": "foo/bar",
            }
        )
        iterable = wsgi_app(environ, self.start_response)
        self.read_response(iterable)
        self.assertEqual([("clone", "foo/bar/")], transport.calls)

    def test_smart_wsgi_app_request_and_response(self):
        # SmartWSGIApp reads the smart request from the 'wsgi.input' file-like
        # object in the environ dict, and returns the response via the iterable
        # returned to the WSGI handler.
        transport = memory.MemoryTransport()
        transport.put_bytes("foo", b"some bytes")
        wsgi_app = wsgi.SmartWSGIApp(transport)
        wsgi_app.make_request = self._fake_make_request
        fake_input = BytesIO(b"fake request")
        environ = self.build_environ(
            {
                "REQUEST_METHOD": "POST",
                "CONTENT_LENGTH": len(fake_input.getvalue()),
                "wsgi.input": fake_input,
                "breezy.relpath": "foo",
            }
        )
        iterable = wsgi_app(environ, self.start_response)
        response = self.read_response(iterable)
        self.assertEqual("200 OK", self.status)
        self.assertEqual(b"got bytes: fake request", response)

    def test_relpath_setter(self):
        # wsgi.RelpathSetter is WSGI "middleware" to set the 'breezy.relpath'
        # variable.
        calls = []

        def fake_app(environ, start_response):
            calls.append(environ["breezy.relpath"])

        wrapped_app = wsgi.RelpathSetter(fake_app, prefix="/abc/", path_var="FOO")
        wrapped_app({"FOO": "/abc/xyz/.bzr/smart"}, None)
        self.assertEqual(["xyz"], calls)

    def test_relpath_setter_bad_path_prefix(self):
        # wsgi.RelpathSetter will reject paths with that don't match the prefix
        # with a 404.  This is probably a sign of misconfiguration; a server
        # shouldn't ever be invoking our WSGI application with bad paths.
        def fake_app(environ, start_response):
            self.fail("The app should never be called when the path is wrong")

        wrapped_app = wsgi.RelpathSetter(fake_app, prefix="/abc/", path_var="FOO")
        iterable = wrapped_app({"FOO": "AAA/abc/xyz/.bzr/smart"}, self.start_response)
        self.read_response(iterable)
        self.assertTrue(self.status.startswith("404"))

    def test_relpath_setter_bad_path_suffix(self):
        # Similar to test_relpath_setter_bad_path_prefix: wsgi.RelpathSetter
        # will reject paths with that don't match the suffix '.bzr/smart' with a
        # 404 as well.  Again, this shouldn't be seen by our WSGI application if
        # the server is configured correctly.
        def fake_app(environ, start_response):
            self.fail("The app should never be called when the path is wrong")

        wrapped_app = wsgi.RelpathSetter(fake_app, prefix="/abc/", path_var="FOO")
        iterable = wrapped_app({"FOO": "/abc/xyz/.bzr/AAA"}, self.start_response)
        self.read_response(iterable)
        self.assertTrue(self.status.startswith("404"))

    def test_make_app(self):
        # The make_app helper constructs a SmartWSGIApp wrapped in a
        # RelpathSetter.
        app = wsgi.make_app(root="a root", prefix="a prefix", path_var="a path_var")
        self.assertIsInstance(app, wsgi.RelpathSetter)
        self.assertIsInstance(app.app, wsgi.SmartWSGIApp)
        self.assertStartsWith(app.app.backing_transport.base, "chroot-")
        backing_transport = app.app.backing_transport
        chroot_backing_transport = backing_transport.server.backing_transport
        self.assertEndsWith(chroot_backing_transport.base, "a%20root/")
        self.assertEqual(app.app.root_client_path, "a prefix")
        self.assertEqual(app.path_var, "a path_var")

    def test_incomplete_request(self):
        transport = FakeTransport()
        wsgi_app = wsgi.SmartWSGIApp(transport)

        def make_request(transport, write_func, bytes, root_client_path):
            request = IncompleteRequest(transport, write_func)
            request.accept_bytes(bytes)
            self.request = request
            return request

        wsgi_app.make_request = make_request

        fake_input = BytesIO(b"incomplete request")
        environ = self.build_environ(
            {
                "REQUEST_METHOD": "POST",
                "CONTENT_LENGTH": len(fake_input.getvalue()),
                "wsgi.input": fake_input,
                "breezy.relpath": "foo/bar",
            }
        )
        iterable = wsgi_app(environ, self.start_response)
        response = self.read_response(iterable)
        self.assertEqual("200 OK", self.status)
        self.assertEqual(b"error\x01incomplete request\n", response)

    def test_protocol_version_detection_one(self):
        # SmartWSGIApp detects requests that don't start with
        # REQUEST_VERSION_TWO as version one.
        transport = memory.MemoryTransport()
        wsgi_app = wsgi.SmartWSGIApp(transport)
        fake_input = BytesIO(b"hello\n")
        environ = self.build_environ(
            {
                "REQUEST_METHOD": "POST",
                "CONTENT_LENGTH": len(fake_input.getvalue()),
                "wsgi.input": fake_input,
                "breezy.relpath": "foo",
            }
        )
        iterable = wsgi_app(environ, self.start_response)
        response = self.read_response(iterable)
        self.assertEqual("200 OK", self.status)
        # Expect a version 1-encoded response.
        self.assertEqual(b"ok\x012\n", response)

    def test_protocol_version_detection_two(self):
        # SmartWSGIApp detects requests that start with REQUEST_VERSION_TWO
        # as version two.
        transport = memory.MemoryTransport()
        wsgi_app = wsgi.SmartWSGIApp(transport)
        fake_input = BytesIO(protocol.REQUEST_VERSION_TWO + b"hello\n")
        environ = self.build_environ(
            {
                "REQUEST_METHOD": "POST",
                "CONTENT_LENGTH": len(fake_input.getvalue()),
                "wsgi.input": fake_input,
                "breezy.relpath": "foo",
            }
        )
        iterable = wsgi_app(environ, self.start_response)
        response = self.read_response(iterable)
        self.assertEqual("200 OK", self.status)
        # Expect a version 2-encoded response.
        self.assertEqual(
            protocol.RESPONSE_VERSION_TWO + b"success\nok\x012\n", response
        )


class TestWSGIJail(tests.TestCaseWithMemoryTransport, WSGITestMixin):
    def make_hpss_wsgi_request(self, wsgi_relpath, *args):
        write_buf = BytesIO()
        request_medium = medium.SmartSimplePipesClientMedium(
            None, write_buf, "fake:" + wsgi_relpath
        )
        request_encoder = protocol.ProtocolThreeRequester(request_medium.get_request())
        request_encoder.call(*args)
        write_buf.seek(0)
        environ = self.build_environ(
            {
                "REQUEST_METHOD": "POST",
                "CONTENT_LENGTH": len(write_buf.getvalue()),
                "wsgi.input": write_buf,
                "breezy.relpath": wsgi_relpath,
            }
        )
        return environ

    def test_jail_root(self):
        """The WSGI HPSS glue allows access to the whole WSGI backing
        transport, regardless of which HTTP path the request was delivered
        to.
        """
        # make a branch in a shared repo
        self.make_repository("repo", shared=True)
        branch = self.make_controldir("repo/branch").create_branch()
        # serve the repo via bzr+http WSGI
        wsgi_app = wsgi.SmartWSGIApp(self.get_transport())
        # send a request to /repo/branch that will have to access /repo.
        environ = self.make_hpss_wsgi_request(
            "/repo/branch", b"BzrDir.open_branchV2", b"."
        )
        iterable = wsgi_app(environ, self.start_response)
        response_bytes = self.read_response(iterable)
        self.assertEqual("200 OK", self.status)
        # expect a successful response, rather than a jail break error
        from ..bzr.tests.test_smart_transport import LoggingMessageHandler

        message_handler = LoggingMessageHandler()
        decoder = protocol.ProtocolThreeDecoder(
            message_handler, expect_version_marker=True
        )
        decoder.accept_bytes(response_bytes)
        self.assertIn(
            ("structure", (b"branch", branch._format.network_name())),
            message_handler.event_log,
        )


class FakeRequest:
    def __init__(self, transport, write_func):
        self.transport = transport
        self.write_func = write_func
        self.accepted_bytes = b""

    def accept_bytes(self, bytes):
        self.accepted_bytes = bytes
        self.write_func(b"got bytes: " + bytes)

    def next_read_size(self):
        return 0


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.base = "fake:///"

    def abspath(self, relpath):
        return "fake:///" + relpath

    def clone(self, relpath):
        self.calls.append(("clone", relpath))
        return self


class IncompleteRequest(FakeRequest):
    """A request-like object that always expects to read more bytes."""

    def next_read_size(self):
        # this request always asks for more
        return 1
