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

"""Smart protocol medium classes for HTTP transport."""

import weakref

from dromedary import urlutils
from dromedary.errors import (
    InvalidHttpResponse,
    SmartProtocolError,
    UnexpectedHttpStatus,
)

from .medium import SmartClientMedium, SmartClientMediumRequest, _get_line


class SmartClientHTTPMedium(SmartClientMedium):
    """A SmartClientMedium that works over HTTP transport."""

    def __init__(self, http_transport):
        """Create a medium wrapping ``http_transport``."""
        super().__init__(http_transport.base)
        # We don't want to create a circular reference between the http
        # transport and its associated medium. Since the transport will live
        # longer than the medium, the medium keep only a weak reference to its
        # transport.
        self._http_transport_ref = weakref.ref(http_transport)

    def get_request(self):
        """Return a new request object to send a smart request on this medium."""
        return SmartClientHTTPMediumRequest(self)

    def should_probe(self):
        """Return whether this medium should probe for bzr smart support."""
        return True

    def remote_path_from_transport(self, transport):
        """Return the remote path of ``transport`` relative to this medium."""
        transport_base = transport.base
        if transport_base.startswith("bzr+"):
            transport_base = transport_base[4:]
        rel_url = urlutils.relative_url(self.base, transport_base)
        return urlutils.unquote(rel_url)

    def send_http_smart_request(self, bytes):
        """POST ``bytes`` as a smart request body and return the response body."""
        try:
            t = self._http_transport_ref()
            code, body_filelike = t._post(bytes)
            if code != 200:
                raise UnexpectedHttpStatus(t._remote_path(".bzr/smart"), code)
        except (InvalidHttpResponse, ConnectionResetError) as e:
            raise SmartProtocolError(str(e)) from e
        return body_filelike

    def _report_activity(self, bytes, direction):
        # Does nothing; the underlying plain HTTP transport will report the
        # activity that this medium would report.
        pass

    def disconnect(self):
        """Disconnect the underlying HTTP transport."""
        t = self._http_transport_ref()
        t.disconnect()


class SmartClientHTTPMediumRequest(SmartClientMediumRequest):
    """A SmartClientMediumRequest that works with an HTTP medium."""

    def __init__(self, client_medium):
        """Create a request bound to ``client_medium``."""
        SmartClientMediumRequest.__init__(self, client_medium)
        self._buffer = b""

    def _accept_bytes(self, bytes):
        self._buffer += bytes

    def _finished_writing(self):
        data = self._medium.send_http_smart_request(self._buffer)
        self._response_body = data

    def _read_bytes(self, count):
        return self._response_body.read(count)

    def _read_line(self):
        line, excess = _get_line(self._response_body.read)
        if excess != b"":
            raise AssertionError(
                "_get_line returned excess bytes, but this mediumrequest "
                f"cannot handle excess. ({excess!r})"
            )
        return line

    def _finished_reading(self):
        pass
