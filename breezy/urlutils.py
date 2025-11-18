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

"""A collection of function for handling URL operations."""

import re
import sys
from urllib import parse as urlparse

from . import errors, osutils


class InvalidURL(errors.PathError):
    """Exception raised when an invalid URL is encountered.

    This is raised when a URL string cannot be parsed or is malformed.
    """

    _fmt = 'Invalid url supplied to transport: "%(path)s"%(extra)s'


class InvalidURLJoin(errors.PathError):
    """Exception raised when a URL join operation is invalid.

    This occurs when trying to join URL components in an invalid way.
    """

    _fmt = "Invalid URL join request: %(reason)s: %(base)r + %(join_args)r"

    def __init__(self, reason, base, join_args):
        """Initialize InvalidURLJoin exception.

        Args:
            reason: Description of why the join failed.
            base: The base URL that was being joined to.
            join_args: The arguments that were being joined.
        """
        self.reason = reason
        self.base = base
        self.join_args = join_args
        errors.PathError.__init__(self, base, reason)


class InvalidRebaseURLs(errors.PathError):
    """Exception raised when URLs cannot be rebased.

    This occurs when trying to rebase URLs that differ by more than just their paths.
    """

    _fmt = "URLs differ by more than path: %(from_)r and %(to)r"

    def __init__(self, from_, to):
        """Initialize InvalidRebaseURLs exception.

        Args:
            from_: The source URL being rebased from.
            to: The target URL being rebased to.
        """
        self.from_ = from_
        self.to = to
        errors.PathError.__init__(self, from_, "URLs differ by more than path.")


quote_from_bytes = urlparse.quote_from_bytes
quote = urlparse.quote
unquote_to_bytes = urlparse.unquote_to_bytes
unquote = urlparse.unquote


from ._urlutils_rs import (  # noqa: F401
    _find_scheme_and_separator,
    basename,
    combine_paths,
    derive_to_location,
    dirname,
    escape,
    file_relpath,
    is_url,
    join,
    join_segment_parameters,
    join_segment_parameters_raw,
    joinpath,
    local_path_from_url,
    local_path_to_url,
    normalize_url,
    relative_url,
    split,
    split_segment_parameters,
    split_segment_parameters_raw,
    strip_segment_parameters,
    strip_trailing_slash,
    unescape,
)
from ._urlutils_rs import posix as posix_rs
from ._urlutils_rs import win32 as win32_rs

_posix_local_path_to_url = posix_rs.local_path_to_url
_win32_local_path_to_url = win32_rs.local_path_to_url
_win32_local_path_from_url = win32_rs.local_path_from_url
_posix_local_path_from_url = posix_rs.local_path_from_url


MIN_ABS_FILEURL_LENGTH = len("file:///")
WIN32_MIN_ABS_FILEURL_LENGTH = len("file:///C:/")

if sys.platform == "win32":
    MIN_ABS_FILEURL_LENGTH = WIN32_MIN_ABS_FILEURL_LENGTH


_url_hex_escapes_re = re.compile("(%[0-9a-fA-F]{2})")


def _unescape_safe_chars(matchobj):
    """re.sub callback to convert hex-escapes to plain characters (if safe).

    e.g. '%7E' will be converted to '~'.
    """
    hex_digits = matchobj.group(0)[1:]
    char = chr(int(hex_digits, 16))
    if char in _url_dont_escape_characters:
        return char
    else:
        return matchobj.group(0).upper()


_win32_extract_drive_letter = win32_rs.extract_drive_letter
_win32_strip_local_trailing_slash = win32_rs.strip_local_trailing_slash


# These are characters that if escaped, should stay that way
_no_decode_chars = ";/?:@&=+$,#"
_no_decode_ords = [ord(c) for c in _no_decode_chars]
_no_decode_hex = [f"{o:02x}" for o in _no_decode_ords] + [
    f"{o:02X}" for o in _no_decode_ords
]
_hex_display_map = dict(
    [(f"{o:02x}", bytes([o])) for o in range(256)]
    + [(f"{o:02X}", bytes([o])) for o in range(256)]
)
# These entries get mapped to themselves
_hex_display_map.update((hex, b"%" + hex.encode("ascii")) for hex in _no_decode_hex)

# These characters shouldn't be percent-encoded, and it's always safe to
# unencode them if they are.
_url_dont_escape_characters = set(
    "abcdefghijklmnopqrstuvwxyz"  # Lowercase alpha
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # Uppercase alpha
    "0123456789"  # Numbers
    "-._~"  # Unreserved characters
)


def _unescape_segment_for_display(segment, encoding):
    """Unescape a segment for display.

    Helper for unescape_for_display

    Args:
      url: A 7-bit ASCII URL
      encoding: The final output encoding

    Returns: A unicode string which can be safely encoded into the
         specified encoding.
    """
    escaped_chunks = segment.split("%")
    escaped_chunks[0] = escaped_chunks[0].encode("utf-8")
    for j in range(1, len(escaped_chunks)):
        item = escaped_chunks[j]
        try:
            escaped_chunks[j] = _hex_display_map[item[:2]]
        except KeyError:
            # Put back the percent symbol
            escaped_chunks[j] = b"%" + (item[:2].encode("utf-8"))
        except UnicodeDecodeError:
            escaped_chunks[j] = chr(int(item[:2], 16)).encode("utf-8")
        escaped_chunks[j] += item[2:].encode("utf-8")
    unescaped = b"".join(escaped_chunks)
    try:
        decoded = unescaped.decode("utf-8")
    except UnicodeDecodeError:
        # If this path segment cannot be properly utf-8 decoded
        # after doing unescaping we will just leave it alone
        return segment
    else:
        try:
            decoded.encode(encoding)
        except UnicodeEncodeError:
            # If this chunk cannot be encoded in the local
            # encoding, then we should leave it alone
            return segment
        else:
            # Otherwise take the url decoded one
            return decoded


def unescape_for_display(url, encoding):
    """Decode what you can for a URL, so that we get a nice looking path.

    This will turn file:// urls into local paths, and try to decode
    any portions of a http:// style url that it can.

    Any sections of the URL which can't be represented in the encoding or
    need to stay as escapes are left alone.

    Args:
      url: A 7-bit ASCII URL
      encoding: The final output encoding

    Returns: A unicode string which can be safely encoded into the
         specified encoding.
    """
    if encoding is None:
        raise ValueError("you cannot specify None for the display encoding")
    if url.startswith("file://"):
        try:
            path = local_path_from_url(url)
            str(path).encode(encoding)
            return path
        except UnicodeError:
            return url

    # Split into sections to try to decode utf-8
    res = url.split("/")
    for i in range(1, len(res)):
        res[i] = _unescape_segment_for_display(res[i], encoding)
    return "/".join(res)


def _is_absolute(url):
    return osutils.pathjoin("/foo", url) == url


def rebase_url(url, old_base, new_base):
    """Convert a relative path from an old base URL to a new base URL.

    The result will be a relative path.
    Absolute paths and full URLs are returned unaltered.
    """
    scheme, _separator = _find_scheme_and_separator(url)
    if scheme is not None:
        return url
    if _is_absolute(url):
        return url
    old_parsed = urlparse.urlparse(old_base)
    new_parsed = urlparse.urlparse(new_base)
    if (old_parsed[:2]) != (new_parsed[:2]):
        raise InvalidRebaseURLs(old_base, new_base)
    return determine_relative_path(new_parsed[2], join(old_parsed[2], url))


def determine_relative_path(from_path, to_path):
    """Determine a relative path from from_path to to_path."""
    from_segments = osutils.splitpath(from_path)
    to_segments = osutils.splitpath(to_path)
    count = -1
    for count, (from_element, to_element) in enumerate(  # noqa: B007
        zip(
            from_segments,
            to_segments,
            strict=False,
        )
    ):
        if from_element != to_element:
            break
    else:
        count += 1
    unique_from = from_segments[count:]
    unique_to = to_segments[count:]
    segments = [".."] * len(unique_from) + unique_to
    if len(segments) == 0:
        return "."
    return osutils.pathjoin(*segments)


class URL:
    """Parsed URL."""

    def __init__(
        self, scheme, quoted_user, quoted_password, quoted_host, port, quoted_path
    ):
        """Initialize URL object with parsed components.

        Args:
            scheme: URL scheme (e.g., 'http', 'https', 'file').
            quoted_user: URL-quoted username or None.
            quoted_password: URL-quoted password or None.
            quoted_host: URL-quoted hostname.
            port: Port number as integer or None.
            quoted_path: URL-quoted path component.
        """
        self.scheme = scheme
        self.quoted_host = quoted_host
        self.host = unquote(self.quoted_host)
        self.quoted_user = quoted_user
        if self.quoted_user is not None:
            self.user = unquote(self.quoted_user)
        else:
            self.user = None
        self.quoted_password = quoted_password
        if self.quoted_password is not None:
            self.password = unquote(self.quoted_password)
        else:
            self.password = None
        self.port = port
        self.quoted_path = _url_hex_escapes_re.sub(_unescape_safe_chars, quoted_path)
        self.path = unquote(self.quoted_path)

    def __eq__(self, other):
        """Check if two URL objects are equal.

        Args:
            other: Another URL object to compare with.

        Returns:
            True if the URLs are equal, False otherwise.
        """
        return (
            isinstance(other, self.__class__)
            and self.scheme == other.scheme
            and self.host == other.host
            and self.user == other.user
            and self.password == other.password
            and self.path == other.path
        )

    def __repr__(self):
        """Return a detailed string representation of the URL.

        Returns:
            String representation showing all URL components.
        """
        return "<{}({!r}, {!r}, {!r}, {!r}, {!r}, {!r})>".format(
            self.__class__.__name__,
            self.scheme,
            self.quoted_user,
            self.quoted_password,
            self.quoted_host,
            self.port,
            self.quoted_path,
        )

    @classmethod
    def from_string(cls, url):
        """Create a URL object from a string.

        Args:
          url: URL as bytestring
        """
        # GZ 2017-06-09: Actually validate ascii-ness
        # pad.lv/1696545: For the moment, accept both native strings and
        # unicode.
        if isinstance(url, str):
            pass
        elif isinstance(url, str):
            try:
                url = url.encode()
            except UnicodeEncodeError as err:
                raise InvalidURL(url) from err
        else:
            raise InvalidURL(url)
        (scheme, netloc, path, _params, _query, _fragment) = urlparse.urlparse(
            url, allow_fragments=False
        )
        user = password = host = port = None
        if "@" in netloc:
            user, host = netloc.rsplit("@", 1)
            if ":" in user:
                user, password = user.split(":", 1)
        else:
            host = netloc

        if ":" in host and not (host[0] == "[" and host[-1] == "]"):
            # there *is* port
            host, port = host.rsplit(":", 1)
            if port:
                try:
                    port = int(port)
                except ValueError as err:
                    raise InvalidURL(
                        f"invalid port number {port} in url:\n{url}"
                    ) from err
            else:
                port = None
        if host != "" and host[0] == "[" and host[-1] == "]":  # IPv6
            host = host[1:-1]

        return cls(scheme, user, password, host, port, path)

    def __str__(self):
        """Return the URL as a string.

        Note: The password is omitted from the string representation
        for security reasons.

        Returns:
            String representation of the URL.
        """
        netloc = self.quoted_host
        if ":" in netloc:
            netloc = f"[{netloc}]"
        if self.quoted_user is not None:
            # Note that we don't put the password back even if we
            # have one so that it doesn't get accidentally
            # exposed.
            netloc = f"{self.quoted_user}@{netloc}"
        if self.port is not None:
            netloc = "%s:%d" % (netloc, self.port)
        return urlparse.urlunparse(
            (self.scheme, netloc, self.quoted_path, None, None, None)
        )

    def clone(self, offset=None):
        """Return a new URL for a path relative to this URL.

        Args:
          offset: A relative path, already urlencoded
        Returns: `URL` instance
        """
        if offset is not None:
            relative = unescape(offset)
            path = combine_paths(self.path, relative)
            path = quote(path, safe="/~")
        else:
            path = self.quoted_path
        return self.__class__(
            self.scheme,
            self.quoted_user,
            self.quoted_password,
            self.quoted_host,
            self.port,
            path,
        )


def parse_url(url):
    """Extract the server address, the credentials and the path from the url.

    user, password, host and path should be quoted if they contain reserved
    chars.

    Args:
      url: an quoted url
    Returns: (scheme, user, password, host, port, path) tuple, all fields
        are unquoted.
    """
    parsed_url = URL.from_string(url)
    return (
        parsed_url.scheme,
        parsed_url.user,
        parsed_url.password,
        parsed_url.host,
        parsed_url.port,
        parsed_url.path,
    )
