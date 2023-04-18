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

import os
import posixpath
import re
import sys
from typing import Tuple, Union
from urllib import parse as urlparse

from . import errors, osutils


class InvalidURL(errors.PathError):

    _fmt = 'Invalid url supplied to transport: "%(path)s"%(extra)s'


class InvalidURLJoin(errors.PathError):

    _fmt = "Invalid URL join request: %(reason)s: %(base)r + %(join_args)r"

    def __init__(self, reason, base, join_args):
        self.reason = reason
        self.base = base
        self.join_args = join_args
        errors.PathError.__init__(self, base, reason)


class InvalidRebaseURLs(errors.PathError):

    _fmt = "URLs differ by more than path: %(from_)r and %(to)r"

    def __init__(self, from_, to):
        self.from_ = from_
        self.to = to
        errors.PathError.__init__(
            self, from_, 'URLs differ by more than path.')


quote_from_bytes = urlparse.quote_from_bytes
quote = urlparse.quote
unquote_to_bytes = urlparse.unquote_to_bytes
unquote = urlparse.unquote


def escape(relpath: Union[bytes, str], safe: str = '/~') -> str:
    """Escape relpath to be a valid url."""
    return quote(relpath, safe=safe)


def file_relpath(base: str, path: str) -> str:
    """Compute just the relative sub-portion of a url

    This assumes that both paths are already fully specified file:// URLs.
    """
    if len(base) < MIN_ABS_FILEURL_LENGTH:
        raise ValueError('Length of base (%r) must equal or'
                         ' exceed the platform minimum url length (which is %d)' %
                         (base, MIN_ABS_FILEURL_LENGTH))
    base = osutils.normpath(local_path_from_url(base))
    path = osutils.normpath(local_path_from_url(path))
    return escape(osutils.relpath(base, path))


from ._urlutils_rs import (_find_scheme_and_separator, basename, dirname,
                           is_url, join, joinpath, split,
                           split_segment_parameters,
                           split_segment_parameters_raw,
                           strip_segment_parameters, strip_trailing_slash)


# jam 20060502 Sorted to 'l' because the final target is 'local_path_from_url'
def _posix_local_path_from_url(url):
    """Convert a url like file:///path/to/foo into /path/to/foo"""
    url = strip_segment_parameters(url)
    file_localhost_prefix = 'file://localhost/'
    if url.startswith(file_localhost_prefix):
        path = url[len(file_localhost_prefix) - 1:]
    elif not url.startswith('file:///'):
        raise InvalidURL(
            url, 'local urls must start with file:/// or file://localhost/')
    else:
        path = url[len('file://'):]
    # We only strip off 2 slashes
    return unescape(path)


def _posix_local_path_to_url(path):
    """Convert a local path like ./foo into a URL like file:///path/to/foo

    This also handles transforming escaping unicode characters, etc.
    """
    # importing directly from posixpath allows us to test this
    # on non-posix platforms
    return 'file://' + escape(posixpath.abspath(path))


def _win32_local_path_from_url(url):
    """Convert a url like file:///C:/path/to/foo into C:/path/to/foo"""
    if not url.startswith('file://'):
        raise InvalidURL(url, 'local urls must start with file:///, '
                         'UNC path urls must start with file://')
    url = strip_segment_parameters(url)
    # We strip off all 3 slashes
    win32_url = url[len('file:'):]
    # check for UNC path: //HOST/path
    if not win32_url.startswith('///'):
        if (win32_url[2] == '/'
                or win32_url[3] in '|:'):
            raise InvalidURL(url, 'Win32 UNC path urls'
                             ' have form file://HOST/path')
        return unescape(win32_url)

    # allow empty paths so we can serve all roots
    if win32_url == '///':
        return '/'

    # usual local path with drive letter
    if (len(win32_url) < 6
        or win32_url[3] not in ('abcdefghijklmnopqrstuvwxyz'
                                'ABCDEFGHIJKLMNOPQRSTUVWXYZ') or
        win32_url[4] not in '|:'
            or win32_url[5] != '/'):
        raise InvalidURL(url, 'Win32 file urls start with'
                         ' file:///x:/, where x is a valid drive letter')
    return win32_url[3].upper() + ':' + unescape(win32_url[5:])


def _win32_local_path_to_url(path):
    """Convert a local path like ./foo into a URL like file:///C:/path/to/foo

    This also handles transforming escaping unicode characters, etc.
    """
    # importing directly from ntpath allows us to test this
    # on non-win32 platform
    # FIXME: It turns out that on nt, ntpath.abspath uses nt._getfullpathname
    #       which actually strips trailing space characters.
    #       The worst part is that on linux ntpath.abspath has different
    #       semantics, since 'nt' is not an available module.
    if path == '/':
        return 'file:///'

    win32_path = osutils._win32_abspath(path)
    # check for UNC path \\HOST\path
    if win32_path.startswith('//'):
        return 'file:' + escape(win32_path)
    return ('file:///' + str(win32_path[0].upper()) + ':' +
            escape(win32_path[2:]))


local_path_to_url = _posix_local_path_to_url
local_path_from_url = _posix_local_path_from_url
MIN_ABS_FILEURL_LENGTH = len('file:///')
WIN32_MIN_ABS_FILEURL_LENGTH = len('file:///C:/')

if sys.platform == 'win32':
    local_path_to_url = _win32_local_path_to_url
    local_path_from_url = _win32_local_path_from_url

    MIN_ABS_FILEURL_LENGTH = WIN32_MIN_ABS_FILEURL_LENGTH


_url_scheme_re = re.compile('^(?P<scheme>[^:/]{2,}):(//)?(?P<path>.*)$')
_url_hex_escapes_re = re.compile('(%[0-9a-fA-F]{2})')


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


def normalize_url(url):
    """Make sure that a path string is in fully normalized URL form.

    This handles URLs which have unicode characters, spaces,
    special characters, etc.

    It has two basic modes of operation, depending on whether the
    supplied string starts with a url specifier (scheme://) or not.
    If it does not have a specifier it is considered a local path,
    and will be converted into a file:/// url. Non-ascii characters
    will be encoded using utf-8.
    If it does have a url specifier, it will be treated as a "hybrid"
    URL. Basically, a URL that should have URL special characters already
    escaped (like +?&# etc), but may have unicode characters, etc
    which would not be valid in a real URL.

    Args:
      url: Either a hybrid URL or a local path
    Returns: A normalized URL which only includes 7-bit ASCII characters.
    """
    scheme_end, path_start = _find_scheme_and_separator(url)
    if scheme_end is None:
        return local_path_to_url(url)
    prefix = url[:path_start]
    path = url[path_start:]
    if not isinstance(url, str):
        for c in url:
            if c not in _url_safe_characters:
                raise InvalidURL(url, 'URLs can only contain specific'
                                 ' safe characters (not %r)' % c)
        path = _url_hex_escapes_re.sub(_unescape_safe_chars, path)
        return str(prefix + ''.join(path))

    # We have a unicode (hybrid) url
    path_chars = list(path)

    for i in range(len(path_chars)):
        if path_chars[i] not in _url_safe_characters:
            path_chars[i] = ''.join(
                ['%%%02X' % c for c in bytearray(path_chars[i].encode('utf-8'))])
    path = ''.join(path_chars)
    path = _url_hex_escapes_re.sub(_unescape_safe_chars, path)
    return str(prefix + path)


def relative_url(base, other):
    """Return a path to other from base.

    If other is unrelated to base, return other. Else return a relative path.
    This assumes no symlinks as part of the url.
    """
    dummy, base_first_slash = _find_scheme_and_separator(base)
    if base_first_slash is None:
        return other

    dummy, other_first_slash = _find_scheme_and_separator(other)
    if other_first_slash is None:
        return other

    # this takes care of differing schemes or hosts
    base_scheme = base[:base_first_slash]
    other_scheme = other[:other_first_slash]
    if base_scheme != other_scheme:
        return other
    elif sys.platform == 'win32' and base_scheme == 'file://':
        base_drive = base[base_first_slash + 1:base_first_slash + 3]
        other_drive = other[other_first_slash + 1:other_first_slash + 3]
        if base_drive != other_drive:
            return other

    base_path = base[base_first_slash + 1:]
    other_path = other[other_first_slash + 1:]

    if base_path.endswith('/'):
        base_path = base_path[:-1]

    base_sections = base_path.split('/')
    other_sections = other_path.split('/')

    if base_sections == ['']:
        base_sections = []
    if other_sections == ['']:
        other_sections = []

    output_sections = []
    for b, o in zip(base_sections, other_sections):
        if b != o:
            break
        output_sections.append(b)

    match_len = len(output_sections)
    output_sections = ['..' for x in base_sections[match_len:]]
    output_sections.extend(other_sections[match_len:])

    return "/".join(output_sections) or "."


def _win32_extract_drive_letter(url_base, path):
    """On win32 the drive letter needs to be added to the url base."""
    # Strip off the drive letter
    # path is currently /C:/foo
    if len(path) < 4 or path[2] not in ':|' or path[3] != '/':
        raise InvalidURL(url_base + path,
                         'win32 file:/// paths need a drive letter')
    url_base += path[0:3]  # file:// + /C:
    path = path[3:]  # /foo
    return url_base, path


def join_segment_parameters_raw(base, *subsegments):
    """Create a new URL by adding subsegments to an existing one.

    This adds the specified subsegments to the last path in the specified
    base URL. The subsegments should be bytestrings.

    :note: You probably want to use join_segment_parameters instead.
    """
    if not subsegments:
        return base
    for subsegment in subsegments:
        if not isinstance(subsegment, str):
            raise TypeError("Subsegment %r is not a bytestring" % subsegment)
        if "," in subsegment:
            raise InvalidURLJoin(", exists in subsegments",
                                 base, subsegments)
    return ",".join((base,) + subsegments)


def join_segment_parameters(url, parameters):
    """Create a new URL by adding segment parameters to an existing one.

    The parameters of the last segment in the URL will be updated; if a
    parameter with the same key already exists it will be overwritten.

    Args:
      url: A URL, as string
      parameters: Dictionary of parameters, keys and values as bytestrings
    """
    (base, existing_parameters) = split_segment_parameters(url)
    new_parameters = {}
    new_parameters.update(existing_parameters)
    for key, value in parameters.items():
        if not isinstance(key, str):
            raise TypeError("parameter key %r is not a str" % key)
        if not isinstance(value, str):
            raise TypeError("parameter value %r for %r is not a str" %
                            (value, key))
        if "=" in key:
            raise InvalidURLJoin("= exists in parameter key", url,
                                 parameters)
        new_parameters[key] = value
    return join_segment_parameters_raw(
        base, *["%s=%s" % item for item in sorted(new_parameters.items())])


def _win32_strip_local_trailing_slash(url):
    """Strip slashes after the drive letter"""
    if len(url) > WIN32_MIN_ABS_FILEURL_LENGTH:
        return url[:-1]
    else:
        return url


def unescape(url):
    """Unescape relpath from url format.

    This returns a Unicode path from a URL
    """
    # jam 20060427 URLs are supposed to be ASCII only strings
    #       If they are passed in as unicode, unquote
    #       will return a UNICODE string, which actually contains
    #       utf-8 bytes. So we have to ensure that they are
    #       plain ASCII strings, or the final .decode will
    #       try to encode the UNICODE => ASCII, and then decode
    #       it into utf-8.

    if isinstance(url, str):
        try:
            url.encode("ascii")
        except UnicodeError as e:
            raise InvalidURL(
                url, 'URL was not a plain ASCII url: {}'.format(e))
    return urlparse.unquote(url)


# These are characters that if escaped, should stay that way
_no_decode_chars = ';/?:@&=+$,#'
_no_decode_ords = [ord(c) for c in _no_decode_chars]
_no_decode_hex = (['%02x' % o for o in _no_decode_ords]
                  + ['%02X' % o for o in _no_decode_ords])
_hex_display_map = dict([('%02x' % o, bytes([o])) for o in range(256)]
                         + [('%02X' % o, bytes([o])) for o in range(256)])
# These entries get mapped to themselves
_hex_display_map.update((hex, b'%' + hex.encode('ascii'))
                        for hex in _no_decode_hex)

# These characters shouldn't be percent-encoded, and it's always safe to
# unencode them if they are.
_url_dont_escape_characters = set(
    "abcdefghijklmnopqrstuvwxyz"  # Lowercase alpha
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # Uppercase alpha
    "0123456789"  # Numbers
    "-._~"  # Unreserved characters
)

# These characters should not be escaped
_url_safe_characters = set(
    "abcdefghijklmnopqrstuvwxyz"  # Lowercase alpha
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # Uppercase alpha
    "0123456789"  # Numbers
    "_.-!~*'()"  # Unreserved characters
    "/;?:@&=+$,"  # Reserved characters
    "%#"         # Extra reserved characters
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
    escaped_chunks = segment.split('%')
    escaped_chunks[0] = escaped_chunks[0].encode('utf-8')
    for j in range(1, len(escaped_chunks)):
        item = escaped_chunks[j]
        try:
            escaped_chunks[j] = _hex_display_map[item[:2]]
        except KeyError:
            # Put back the percent symbol
            escaped_chunks[j] = b'%' + (item[:2].encode('utf-8'))
        except UnicodeDecodeError:
            escaped_chunks[j] = chr(int(item[:2], 16)).encode('utf-8')
        escaped_chunks[j] += (item[2:].encode('utf-8'))
    unescaped = b''.join(escaped_chunks)
    try:
        decoded = unescaped.decode('utf-8')
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
        raise ValueError('you cannot specify None for the display encoding')
    if url.startswith('file://'):
        try:
            path = local_path_from_url(url)
            path.encode(encoding)
            return path
        except UnicodeError:
            return url

    # Split into sections to try to decode utf-8
    res = url.split('/')
    for i in range(1, len(res)):
        res[i] = _unescape_segment_for_display(res[i], encoding)
    return '/'.join(res)


def derive_to_location(from_location):
    """Derive a TO_LOCATION given a FROM_LOCATION.

    The normal case is a FROM_LOCATION of http://foo/bar => bar.
    The Right Thing for some logical destinations may differ though
    because no / may be present at all. In that case, the result is
    the full name without the scheme indicator, e.g. lp:foo-bar => foo-bar.
    This latter case also applies when a Windows drive
    is used without a path, e.g. c:foo-bar => foo-bar.
    If no /, path separator or : is found, the from_location is returned.
    """
    from_location = strip_segment_parameters(from_location)
    if from_location.find("/") >= 0 or from_location.find(os.sep) >= 0:
        return os.path.basename(from_location.rstrip("/\\"))
    else:
        sep = from_location.find(":")
        if sep > 0:
            return from_location[sep + 1:]
        else:
            return from_location


def _is_absolute(url):
    return (osutils.pathjoin('/foo', url) == url)


def rebase_url(url, old_base, new_base):
    """Convert a relative path from an old base URL to a new base URL.

    The result will be a relative path.
    Absolute paths and full URLs are returned unaltered.
    """
    scheme, separator = _find_scheme_and_separator(url)
    if scheme is not None:
        return url
    if _is_absolute(url):
        return url
    old_parsed = urlparse.urlparse(old_base)
    new_parsed = urlparse.urlparse(new_base)
    if (old_parsed[:2]) != (new_parsed[:2]):
        raise InvalidRebaseURLs(old_base, new_base)
    return determine_relative_path(new_parsed[2],
                                   join(old_parsed[2], url))


def determine_relative_path(from_path, to_path):
    """Determine a relative path from from_path to to_path."""
    from_segments = osutils.splitpath(from_path)
    to_segments = osutils.splitpath(to_path)
    count = -1
    for count, (from_element, to_element) in enumerate(zip(from_segments,
                                                           to_segments)):
        if from_element != to_element:
            break
    else:
        count += 1
    unique_from = from_segments[count:]
    unique_to = to_segments[count:]
    segments = (['..'] * len(unique_from) + unique_to)
    if len(segments) == 0:
        return '.'
    return osutils.pathjoin(*segments)


class URL:
    """Parsed URL."""

    def __init__(self, scheme, quoted_user, quoted_password, quoted_host,
                 port, quoted_path):
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
        self.quoted_path = _url_hex_escapes_re.sub(
            _unescape_safe_chars, quoted_path)
        self.path = unquote(self.quoted_path)

    def __eq__(self, other):
        return (isinstance(other, self.__class__) and
                self.scheme == other.scheme and
                self.host == other.host and
                self.user == other.user and
                self.password == other.password and
                self.path == other.path)

    def __repr__(self):
        return "<{}({!r}, {!r}, {!r}, {!r}, {!r}, {!r})>".format(
            self.__class__.__name__,
            self.scheme, self.quoted_user, self.quoted_password,
            self.quoted_host, self.port, self.quoted_path)

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
            except UnicodeEncodeError:
                raise InvalidURL(url)
        else:
            raise InvalidURL(url)
        (scheme, netloc, path, params,
         query, fragment) = urlparse.urlparse(url, allow_fragments=False)
        user = password = host = port = None
        if '@' in netloc:
            user, host = netloc.rsplit('@', 1)
            if ':' in user:
                user, password = user.split(':', 1)
        else:
            host = netloc

        if ':' in host and not (host[0] == '[' and host[-1] == ']'):
            # there *is* port
            host, port = host.rsplit(':', 1)
            if port:
                try:
                    port = int(port)
                except ValueError:
                    raise InvalidURL('invalid port number %s in url:\n%s' %
                                     (port, url))
            else:
                port = None
        if host != "" and host[0] == '[' and host[-1] == ']':  # IPv6
            host = host[1:-1]

        return cls(scheme, user, password, host, port, path)

    def __str__(self):
        netloc = self.quoted_host
        if ":" in netloc:
            netloc = "[%s]" % netloc
        if self.quoted_user is not None:
            # Note that we don't put the password back even if we
            # have one so that it doesn't get accidentally
            # exposed.
            netloc = '{}@{}'.format(self.quoted_user, netloc)
        if self.port is not None:
            netloc = '%s:%d' % (netloc, self.port)
        return urlparse.urlunparse(
            (self.scheme, netloc, self.quoted_path, None, None, None))

    @staticmethod
    def _combine_paths(base_path: str, relpath: str) -> str:
        """Transform a Transport-relative path to a remote absolute path.

        This does not handle substitution of ~ but does handle '..' and '.'
        components.

        Examples::

            t._combine_paths('/home/sarah', 'project/foo')
                => '/home/sarah/project/foo'
            t._combine_paths('/home/sarah', '../../etc')
                => '/etc'
            t._combine_paths('/home/sarah', '/etc')
                => '/etc'

        Args:
          base_path: base path
          relpath: relative url string for relative part of remote path.
        Returns: urlencoded string for final path.
        """
        if not isinstance(relpath, str):
            raise InvalidURL(relpath)
        relpath = _url_hex_escapes_re.sub(_unescape_safe_chars, relpath)
        if relpath.startswith('/'):
            base_parts = []
        else:
            base_parts = base_path.split('/')
        if len(base_parts) > 0 and base_parts[-1] == '':
            base_parts = base_parts[:-1]
        for p in relpath.split('/'):
            if p == '..':
                if len(base_parts) == 0:
                    # In most filesystems, a request for the parent
                    # of root, just returns root.
                    continue
                base_parts.pop()
            elif p == '.':
                continue  # No-op
            elif p != '':
                base_parts.append(p)
        path = '/'.join(base_parts)
        if not path.startswith('/'):
            path = '/' + path
        return path

    def clone(self, offset=None):
        """Return a new URL for a path relative to this URL.

        Args:
          offset: A relative path, already urlencoded
        Returns: `URL` instance
        """
        if offset is not None:
            relative = unescape(offset)
            path = self._combine_paths(self.path, relative)
            path = quote(path, safe="/~")
        else:
            path = self.quoted_path
        return self.__class__(self.scheme, self.quoted_user,
                              self.quoted_password, self.quoted_host, self.port,
                              path)


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
    return (parsed_url.scheme, parsed_url.user, parsed_url.password,
            parsed_url.host, parsed_url.port, parsed_url.path)
