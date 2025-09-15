# Copyright (C) 2008, 2009, 2011, 2013 Canonical Ltd
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

"""DAV test server.

This defines the TestingDAVRequestHandler and the DAVServer classes which
implements the DAV specification parts used by the webdav plugin.
"""

import os
import re
import shutil  # FIXME: Can't we use breezy.osutils ?
import stat
import time
import urllib.parse  # FIXME: Can't we use breezy.urlutils ?

from breezy import trace, urlutils
from breezy.tests import http_server


class TestingDAVRequestHandler(http_server.TestingHTTPRequestHandler):
    """Subclass of TestingHTTPRequestHandler handling DAV requests.

    This is not a full implementation of a DAV server, only the parts
    really used by the plugin are.
    """

    _RANGE_HEADER_RE = re.compile(r"bytes (?P<begin>\d+)-(?P<end>\d+)/(?P<size>\d+|\*)")

    delete_success_code = 204
    move_default_overwrite = True

    def date_time_string(self, timestamp=None):
        """Return the current date and time formatted for a message header."""
        if timestamp is None:
            timestamp = time.time()
        year, month, day, hh, mm, ss, wd, _y, _z = time.gmtime(timestamp)
        s = "%s, %02d %3s %4d %02d:%02d:%02d GMT" % (
            self.weekdayname[wd],
            day,
            self.monthname[month],
            year,
            hh,
            mm,
            ss,
        )
        return s

    def _read(self, length):
        """Read the client socket."""
        return self.rfile.read(length)

    def _readline(self):
        """Read a full line on the client socket."""
        return self.rfile.readline()

    def read_body(self):
        """Read the body either by chunk or as a whole."""
        content_length = self.headers.get("Content-Length")
        encoding = self.headers.get("Transfer-Encoding")
        if encoding is not None:
            if encoding != "chunked":
                raise AssertionError(
                    "Unsupported transfer encoding: {}".format(encoding)
                )
            body = []
            # We receive the content by chunk
            while True:
                length, data = self.read_chunk()
                if length == 0:
                    break
                body.append(data)
            body = "".join(body)

        else:
            if content_length is not None:
                body = self._read(int(content_length))

        return body

    def read_chunk(self):
        """Read a chunk of data.

        A chunk consists of:
        - a line containing the length of the data in hexa,
        - the data.
        - a empty line.

        An empty chunk specifies a length of zero
        """
        length = int(self._readline(), 16)
        data = None
        if length != 0:
            data = self._read(length)
            # Eats the newline following the chunk
            self._readline()
        return length, data

    def send_head(self):
        """Specialized version of SimpleHttpServer.

        We *don't* want the apache behavior of permanently redirecting
        directories without trailing slashes to directories with trailing
        slashes. That's a waste and a severe penalty for clients with high
        latency.

        The installation documentation of the plugin should mention the
        DirectorySlash apache directive and insists on turning it *Off*.
        """
        path = self.translate_path(self.path)
        f = None
        if os.path.isdir(path):
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                return self.list_directory(path)
        ctype = self.guess_type(path)
        mode = "r" if ctype.startswith("text/") else "rb"
        try:
            f = open(path, mode)
        except OSError:
            self.send_error(404, "File not found")
            return None
        self.send_response(200)
        self.send_header("Content-type", ctype)
        fs = os.fstat(f.fileno())
        self.send_header("Content-Length", str(fs[6]))
        self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
        self.end_headers()
        return f

    def do_PUT(self):
        """Serve a PUT request."""
        # FIXME: test_put_file_unicode makes us emit a traceback because a
        # UnicodeEncodeError occurs after the request headers have been sent
        # but before the body can be send. It's harmless and does not make the
        # test fails. Adressing that will mean protecting all reads from the
        # socket, which is too heavy for now -- vila 20070917
        path = self.translate_path(self.path)
        trace.mutter(f"do_PUT rel: [{self.path}], abs: [{path}]")

        do_append = False
        # Check the Content-Range header
        range_header = self.headers.get("Content-Range")
        if range_header is not None:
            match = self._RANGE_HEADER_RE.match(range_header)
            if match is None:
                # FIXME: RFC2616 says to return a 501 if we don't
                # understand the Content-Range header, but Apache
                # just ignores them (bad Apache).
                self.send_error(501, "Not Implemented")
                return
            begin = int(match.group("begin"))
            do_append = True

        if self.headers.get("Expect") == "100-continue":
            # Tell the client to go ahead, we're ready to get the content
            self.send_response(100, "Continue")
            self.end_headers()

        try:
            trace.mutter(f"do_PUT will try to open: [{path}]")
            # Always write in binary mode.
            if do_append:
                f = open(path, "ab")
                f.seek(begin)
            else:
                f = open(path, "wb")
        except OSError as e:
            trace.mutter(f"do_PUT got: [{e!r}] while opening/seeking on [{self.path}]")
            self.send_error(409, "Conflict")
            return

        try:
            data = self.read_body()
            f.write(data)
        except OSError:
            # FIXME: We leave a partially written file here
            self.send_error(409, "Conflict")
            f.close()
            return
        f.close()
        trace.mutter(f"do_PUT done: [{self.path}]")
        self.send_response(201)
        self.end_headers()

    def do_MKCOL(self):
        """Serve a MKCOL request.

        MKCOL is an mkdir in DAV terminology for our part.
        """
        path = self.translate_path(self.path)
        trace.mutter(f"do_MKCOL rel: [{self.path}], abs: [{path}]")
        try:
            os.mkdir(path)
        except FileNotFoundError:
            self.send_error(409, "Conflict")
        except (FileExistsError, NotADirectoryError):
            self.send_error(405, "Not allowed")
        else:
            self.send_response(201)
            self.end_headers()

    def do_COPY(self):
        """Serve a COPY request."""
        url_to = self.headers.get("Destination")
        if url_to is None:
            self.send_error(400, "Destination header missing")
            return
        (_scheme, _netloc, rel_to, _params, _query, _fragment) = urllib.parse.urlparse(
            url_to
        )
        trace.mutter(f"urlparse: ({url_to}) [{rel_to}]")
        trace.mutter(f"do_COPY rel_from: [{self.path}], rel_to: [{rel_to}]")
        abs_from = self.translate_path(self.path)
        abs_to = self.translate_path(rel_to)
        try:
            # TODO:  Check that rel_from  exists and  rel_to does
            # not.  In the  mean  time, just  go  along and  trap
            # exceptions
            shutil.copyfile(abs_from, abs_to)
        except FileNotFoundError:
            self.send_error(404, "File not found")
        except OSError:
            self.send_error(409, "Conflict")
        else:
            # TODO: We may be able  to return 204 "No content" if
            # rel_to was existing (even  if the "No content" part
            # seems misleading, RFC2518 says so, stop arguing :)
            self.send_response(201)
            self.end_headers()

    def do_DELETE(self):
        """Serve a DELETE request.

        We don't implement a true DELETE as DAV defines it
        because we *should* fail to delete a non empty dir.
        """
        path = self.translate_path(self.path)
        trace.mutter(f"do_DELETE rel: [{self.path}], abs: [{path}]")
        try:
            # DAV  makes no  distinction between  files  and dirs
            # when required to nuke them,  but we have to. And we
            # also watch out for symlinks.
            real_path = os.path.realpath(path)
            if os.path.isdir(real_path):
                os.rmdir(path)
            else:
                os.remove(path)
        except FileNotFoundError:
            self.send_error(404, "File not found")
        else:
            self.send_response(self.delete_success_code)
            self.end_headers()

    def do_MOVE(self):
        """Serve a MOVE request."""
        url_to = self.headers.get("Destination")
        if url_to is None:
            self.send_error(400, "Destination header missing")
            return
        overwrite_header = self.headers.get("Overwrite")
        should_overwrite = self.move_default_overwrite
        if overwrite_header == "F":
            should_overwrite = False
        elif overwrite_header == "T":
            should_overwrite = True
        (_scheme, _netloc, rel_to, _params, _query, _fragment) = urllib.parse.urlparse(
            url_to
        )
        trace.mutter(f"urlparse: ({url_to}) [{rel_to}]")
        trace.mutter(f"do_MOVE rel_from: [{self.path}], rel_to: [{rel_to}]")
        abs_from = self.translate_path(self.path)
        abs_to = self.translate_path(rel_to)
        if not should_overwrite and os.access(abs_to, os.F_OK):
            self.send_error(412, "Precondition Failed")
            return
        try:
            os.rename(abs_from, abs_to)
        except FileNotFoundError:
            self.send_error(404, "File not found")
        except OSError:
            self.send_error(409, "Conflict")
        else:
            # TODO: We may be able  to return 204 "No content" if
            # rel_to was existing (even  if the "No content" part
            # seems misleading, RFC2518 says so, stop arguing :)
            self.send_response(201)
            self.end_headers()

    def _generate_response(self, path):
        local_path = self.translate_path(path)
        st = os.stat(local_path)
        prop = {}

        def _prop(ns, name, value=None):
            if value is None:
                return f"<{ns}:{name}/>"
            else:
                return f"<{ns}:{name}>{value}</{ns}:{name}>"

        # For namespaces (and test purposes), where apache2 use:
        # - lp1, we use liveprop,
        # - lp2, we use bzr
        if stat.S_ISDIR(st.st_mode):
            dpath = path
            if not dpath.endswith("/"):
                dpath += "/"
            prop["href"] = _prop("D", "href", dpath)
            prop["type"] = _prop("liveprop", "resourcetype", "<D:collection/>")
            prop["length"] = ""
            prop["exec"] = ""
        else:
            # FIXME: assert S_ISREG ? Handle symlinks ?
            prop["href"] = _prop("D", "href", path)
            prop["type"] = _prop("liveprop", "resourcetype")
            prop["length"] = _prop("liveprop", "getcontentlength", st.st_size)
            is_exec = "T" if st.st_mode & stat.S_IXUSR else "F"
            prop["exec"] = _prop("bzr", "executable", is_exec)
        prop["status"] = _prop("D", "status", "HTTP/1.1 200 OK")

        response = f"""<D:response xmlns:liveprop="DAV:" xmlns:bzr="DAV:">
    {prop["href"]}
    <D:propstat>
        <D:prop>
             {prop["type"]}
             {prop["length"]}
             {prop["exec"]}
        </D:prop>
        {prop["status"]}
    </D:propstat>
</D:response>
"""
        return response, st

    def _generate_dir_responses(self, path, depth):
        local_path = self.translate_path(path)
        entries = os.listdir(local_path)

        for entry in entries:
            entry_path = urlutils.escape(entry)
            if path.endswith("/"):
                entry_path = path + entry_path
            else:
                entry_path = path + "/" + entry_path
            response, st = self._generate_response(entry_path)
            yield response
            if depth == "Infinity" and stat.S_ISDIR(st.st_mode):
                yield from self._generate_dir_responses(entry_path, depth)

    def do_PROPFIND(self):
        """Serve a PROPFIND request."""
        depth = self.headers.get("Depth")
        if depth is None:
            depth = "Infinity"
        if depth not in ("0", "1", "Infinity"):
            self.send_error(400, "Bad Depth")
            return

        # Don't bother parsing the body, we handle only allprop anyway.
        # FIXME: Handle the body :)
        self.read_body()

        try:
            response, st = self._generate_response(self.path)
        except FileNotFoundError:
            self.send_error(404)
            return

        if depth in ("1", "Infinity") and stat.S_ISDIR(st.st_mode):
            dir_responses = self._generate_dir_responses(self.path, depth)
        else:
            dir_responses = []

        # Generate the response, we don't care about performance, so we just
        # expand everything into a big string.
        response = f"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:ns0="DAV:">
{response}{"".join(dir_responses)}
</D:multistatus>""".encode()

        self.send_response(207)
        self.send_header("Content-length", len(response))
        self.end_headers()
        self.wfile.write(response)


class DAVServer(http_server.HttpServer):
    """Subclass of HttpServer that gives http+webdav urls.

    This is for use in testing: connections to this server will always go
    through _urllib where possible.
    """

    def __init__(self):
        # We    have   special    requests    to   handle    that
        # HttpServer_urllib doesn't know about
        super().__init__(TestingDAVRequestHandler)

    # urls returned by this server should require the webdav client impl
    _url_protocol = "http+webdav"


class QuirkyTestingDAVRequestHandler(TestingDAVRequestHandler):
    """Various quirky/slightly off-spec behaviors.

    Used to test how gracefully we handle them.
    """

    delete_success_code = 200
    move_default_overwrite = False


class QuirkyDAVServer(http_server.HttpServer):
    """DAVServer implementing various quirky/slightly off-spec behaviors.

    Used to test how gracefully we handle them.
    """

    def __init__(self):
        # We    have   special    requests    to   handle    that
        # HttpServer_urllib doesn't know about
        super().__init__(QuirkyTestingDAVRequestHandler)

    # urls returned by this server should require the webdav client impl
    _url_protocol = "http+webdav"
