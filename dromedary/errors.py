# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

"""Exception classes for dromedary transport layer."""


class TransportError(Exception):
    """Base class for transport-related errors."""

    internal_error = False

    _fmt = "Transport error: %(msg)s %(orig_error)s"

    def __init__(self, msg=None, orig_error=None):
        if msg is None and orig_error is not None:
            msg = str(orig_error)
        if orig_error is None:
            orig_error = ""
        if msg is None:
            msg = ""
        self.msg = msg
        self.orig_error = orig_error
        Exception.__init__(self)

    def _get_format_string(self):
        return self._fmt

    def __str__(self):
        fmt = self._get_format_string()
        if fmt is not None:
            d = dict(self.__dict__)
            try:
                return fmt % d
            except (KeyError, TypeError):
                pass
        if self.args:
            return str(self.args[0])
        return self.msg or ""

    def __eq__(self, other):
        if self.__class__ is not other.__class__:
            return NotImplemented
        return self.__dict__ == other.__dict__

    def __hash__(self):
        return id(self)

    def __repr__(self):
        return f"<{self.__class__.__name__}({self.__dict__!r})>"


class PathError(TransportError):
    """Generic path-related error."""

    _fmt = "Generic path error: %(path)r%(extra)s)"

    def __init__(self, path, extra=None):
        TransportError.__init__(self)
        self.path = path
        if extra:
            self.extra = ": " + str(extra)
        else:
            self.extra = ""


class NotADirectory(PathError):
    _fmt = '"%(path)s" is not a directory %(extra)s'


class DirectoryNotEmpty(PathError):
    _fmt = 'Directory not empty: "%(path)s"%(extra)s'


class ResourceBusy(PathError):
    _fmt = 'Device or resource busy: "%(path)s"%(extra)s'


class PermissionDenied(PathError):
    _fmt = 'Permission denied: "%(path)s"%(extra)s'


class NoSuchFile(PathError):
    _fmt = 'No such file or directory: "%(path)s"%(extra)s'


class FileExists(PathError):
    _fmt = 'File exists: "%(path)s"%(extra)s'


class UnsupportedProtocol(PathError):
    _fmt = 'Unsupported protocol for url "%(path)s"%(extra)s'


class ReadError(PathError):
    _fmt = "Error reading from %(path)r%(extra)s."


class ShortReadvError(PathError):
    _fmt = (
        "readv() read %(actual)s bytes rather than %(length)s bytes"
        ' at %(offset)s for "%(path)s"%(extra)s'
    )

    internal_error = True

    def __init__(self, path, offset, length, actual, extra=None):
        PathError.__init__(self, path, extra=extra)
        self.offset = offset
        self.length = length
        self.actual = actual


class PathNotChild(PathError):
    _fmt = 'Path "%(path)s" is not a child of path "%(base)s"%(extra)s'

    internal_error = False

    def __init__(self, path, base, extra=None):
        TransportError.__init__(self)
        self.path = path
        self.base = base
        if extra:
            self.extra = ": " + str(extra)
        else:
            self.extra = ""


class TransportNotPossible(TransportError):
    _fmt = "Transport operation not possible: %(msg)s %(orig_error)s"


class NotLocalUrl(TransportError):
    _fmt = "%(url)s is not a local path."

    def __init__(self, url):
        self.url = url
        TransportError.__init__(self)


class NoSmartMedium(TransportError):
    _fmt = "The transport '%(transport)s' cannot tunnel the smart protocol."

    internal_error = True

    def __init__(self, transport):
        self.transport = transport
        TransportError.__init__(self)


class DependencyNotPresent(TransportError):
    """A required dependency for a transport is not present."""

    _fmt = 'Unable to import library "%(library)s": %(error)s'

    def __init__(self, library, error):
        self.library = library
        self.error = error
        TransportError.__init__(self)


class RedirectRequested(TransportError):
    _fmt = "%(source)s is%(permanently)s redirected to %(target)s"

    def __init__(self, source, target, is_permanent=False):
        self.source = source
        self.target = target
        if is_permanent:
            self.permanently = " permanently"
        else:
            self.permanently = ""
        TransportError.__init__(self)


class TooManyRedirections(TransportError):
    _fmt = "Too many redirections"


class InProcessTransport(TransportError):
    _fmt = "The transport '%(transport)s' is only accessible within this process."

    def __init__(self, transport):
        self.transport = transport
        TransportError.__init__(self)


class ConnectionError(TransportError):
    _fmt = "Connection error: %(msg)s"


class SocketConnectionError(ConnectionError):
    """Socket connection error."""

    _fmt = "%(msg)s"

    def __init__(self, host, port=None, msg=None, orig_error=None):
        if msg is None:
            msg = "Failed to connect to"
        orig_error = "" if orig_error is None else "; " + str(orig_error)
        self.host = host
        port_str = "" if port is None else f":{port}"
        self.port = port_str
        self.msg = f"{msg} {host}{port_str}{orig_error}"
        TransportError.__init__(self, self.msg)


class UnusableRedirect(TransportError):
    _fmt = "Unable to follow redirect from %(source)s to %(target)s: %(reason)s."

    def __init__(self, source, target, reason):
        TransportError.__init__(self)
        self.source = source
        self.target = target
        self.reason = reason


# HTTP-specific errors
class InvalidHttpResponse(TransportError):
    _fmt = "Invalid http response for %(path)s: %(msg)s%(orig_error)s"

    def __init__(self, path, msg, orig_error=None, headers=None):
        self.path = path
        if orig_error is None:
            orig_error = ""
        else:
            orig_error = f": {orig_error!r}"
        self.headers = headers
        TransportError.__init__(self, msg, orig_error=orig_error)


class UnexpectedHttpStatus(InvalidHttpResponse):
    _fmt = "Unexpected HTTP status %(code)d for %(path)s: %(extra)s"

    def __init__(self, path, code, extra=None, headers=None):
        self.path = path
        self.code = code
        self.extra = extra or ""
        full_msg = "status code %d unexpected" % code
        if extra is not None:
            full_msg += ": " + extra
        InvalidHttpResponse.__init__(self, path, full_msg, headers=headers)


class InvalidHttpRange(InvalidHttpResponse):
    _fmt = "Invalid http range %(range)r for %(path)s: %(msg)s"

    def __init__(self, path, range, msg):
        self.range = range
        InvalidHttpResponse.__init__(self, path, msg)


class HttpBoundaryMissing(InvalidHttpResponse):
    _fmt = "HTTP MIME Boundary missing for %(path)s: %(msg)s"

    def __init__(self, path, msg):
        InvalidHttpResponse.__init__(self, path, msg)


class BadHttpRequest(UnexpectedHttpStatus):
    _fmt = "Bad http request for %(path)s: %(reason)s"

    def __init__(self, path, reason):
        self.path = path
        self.reason = reason
        TransportError.__init__(self, reason)


class InvalidRange(TransportError):
    _fmt = "Invalid range access in %(path)s at %(offset)s: %(msg)s"

    def __init__(self, path, offset, msg=None):
        TransportError.__init__(self, msg)
        self.path = path
        self.offset = offset


# Smart protocol errors
class SmartProtocolError(TransportError):
    _fmt = "Generic bzr smart protocol error: %(details)s"

    def __init__(self, details):
        self.details = details
        TransportError.__init__(self)


class ErrorFromSmartServer(TransportError):
    _fmt = "Error received from smart server: %(error_tuple)r"

    internal_error = True

    def __init__(self, error_tuple):
        self.error_tuple = error_tuple
        try:
            self.error_verb = error_tuple[0]
        except IndexError:
            self.error_verb = None
        self.error_args = error_tuple[1:]
        TransportError.__init__(self)


class UnexpectedSmartServerResponse(TransportError):
    _fmt = "Could not understand response from smart server: %(response_tuple)r"

    def __init__(self, response_tuple):
        self.response_tuple = response_tuple
        TransportError.__init__(self)


class UnknownSmartMethod(TransportError):
    _fmt = "The server does not recognise the '%(verb)s' request."

    internal_error = True

    def __init__(self, verb):
        self.verb = verb
        TransportError.__init__(self)


# Lock errors
class LockError(TransportError):
    _fmt = "Lock error: %(msg)s"

    def __init__(self, msg=""):
        self.msg = msg
        TransportError.__init__(self)


class LockContention(LockError):
    _fmt = 'Could not acquire lock "%(lock)s": %(msg)s'

    internal_error = False

    def __init__(self, lock, msg=""):
        self.lock = lock
        self.msg = msg
        LockError.__init__(self, msg)


class LockFailed(LockError):
    internal_error = False

    _fmt = "Cannot lock %(lock)s: %(why)s"

    def __init__(self, lock, why):
        LockError.__init__(self, "")
        self.lock = lock
        self.why = why
