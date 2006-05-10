# Bazaar-NG -- distributed version control
#
# Copyright (C) 2006 by Canonical Ltd
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

"""A collection of function for handling URL operations."""

import os
from posixpath import split as _posix_split
import re
import sys
import urllib

import bzrlib.errors as errors
import bzrlib.osutils


def basename(url, exclude_trailing_slash=True):
    """Return the last component of a URL.

    :param url: The URL in question
    :param exclude_trailing_slash: If the url looks like "path/to/foo/"
        ignore the final slash and return 'foo' rather than ''
    :return: Just the final component of the URL. This can return ''
        if you don't exclude_trailing_slash, or if you are at the
        root of the URL.
    """
    return split(url, exclude_trailing_slash=exclude_trailing_slash)[1]


def dirname(url, exclude_trailing_slash=True):
    """Return the parent directory of the given path.

    :param url: Relative or absolute URL
    :param exclude_trailing_slash: Remove a final slash
        (treat http://host/foo/ as http://host/foo, but
        http://host/ stays http://host/)
    :return: Everything in the URL except the last path chunk
    """
    # TODO: jam 20060502 This was named dirname to be consistent
    #       with the os functions, but maybe "parent" would be better
    return split(url, exclude_trailing_slash=exclude_trailing_slash)[0]


def escape(relpath):
    """Escape relpath to be a valid url."""
    if isinstance(relpath, unicode):
        relpath = relpath.encode('utf-8')
    # After quoting and encoding, the path should be perfectly
    # safe as a plain ASCII string, str() just enforces this
    return str(urllib.quote(relpath))


def file_relpath(base, path):
    """Compute just the relative sub-portion of a url
    
    This assumes that both paths are already fully specified file:// URLs.
    """
    assert len(base) >= MIN_ABS_FILEURL_LENGTH, ('Length of base must be equal or'
        ' exceed the platform minimum url length (which is %d)' % 
        MIN_ABS_FILEURL_LENGTH)

    base = local_path_from_url(base)
    path = local_path_from_url(path)
    return escape(bzrlib.osutils.relpath(base, path))


def _find_scheme_and_separator(url):
    """Find the scheme separator (://) and the first path separator

    This is just a helper functions for other path utilities.
    It could probably be replaced by urlparse
    """
    m = _url_scheme_re.match(url)
    if not m:
        return None, None

    scheme = m.group('scheme')
    path = m.group('path')

    # Find the path separating slash
    # (first slash after the ://)
    first_path_slash = path.find('/')
    if first_path_slash == -1:
        return scheme_loc, None
    return scheme_loc, first_path_slash+len(scheme)+3


# jam 20060502 Sorted to 'l' because the final target is 'local_path_from_url'
def _posix_local_path_from_url(url):
    """Convert a url like file:///path/to/foo into /path/to/foo"""
    if not url.startswith('file:///'):
        raise errors.InvalidURL(url, 'local urls must start with file:///')
    # We only strip off 2 slashes
    return unescape(url[len('file://'):])


def _posix_local_path_to_url(path):
    """Convert a local path like ./foo into a URL like file:///path/to/foo

    This also handles transforming escaping unicode characters, etc.
    """
    # importing directly from posixpath allows us to test this 
    # on non-posix platforms
    from posixpath import normpath
    return 'file://' + escape(normpath(bzrlib.osutils._posix_abspath(path)))


def _win32_local_path_from_url(url):
    """Convert a url like file:///C|/path/to/foo into C:/path/to/foo"""
    if not url.startswith('file:///'):
        raise errors.InvalidURL(url, 'local urls must start with file:///')
    # We strip off all 3 slashes
    win32_url = url[len('file:///'):]
    if (win32_url[0] not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
        or win32_url[1] not in  '|:'
        or win32_url[2] != '/'):
        raise errors.InvalidURL(url, 'Win32 file urls start with file:///X|/, where X is a valid drive letter')
    # TODO: jam 20060426, we could .upper() or .lower() the drive letter
    #       for better consistency.
    return win32_url[0].upper() + u':' + unescape(win32_url[2:])


def _win32_local_path_to_url(path):
    """Convert a local path like ./foo into a URL like file:///C|/path/to/foo

    This also handles transforming escaping unicode characters, etc.
    """
    # importing directly from ntpath allows us to test this 
    # on non-win32 platforms
    # TODO: jam 20060426 consider moving this import outside of the function
    win32_path = bzrlib.osutils._nt_normpath(
        bzrlib.osutils._win32_abspath(path)).replace('\\', '/')
    return 'file:///' + win32_path[0].upper() + '|' + escape(win32_path[2:])


local_path_to_url = _posix_local_path_to_url
local_path_from_url = _posix_local_path_from_url
MIN_ABS_FILEURL_LENGTH = len('file:///')

if sys.platform == 'win32':
    local_path_to_url = _win32_local_path_to_url
    local_path_from_url = _win32_local_path_from_url

    MIN_ABS_FILEURL_LENGTH = len('file:///C|/')


_url_scheme_re = re.compile(r'^(?P<scheme>[^:/]{2,})://(?P<path>.*)$')


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

    :param url: Either a hybrid URL or a local path
    :return: A normalized URL which only includes 7-bit ASCII characters.
    """
    m = _url_scheme_re.match(url)
    if not m:
        return local_path_to_url(url)
    if not isinstance(url, unicode):
        # TODO: jam 20060510 We need to test for ascii characters that
        #       shouldn't be allowed in URLs
        for c in url:
            if c not in _url_safe_characters:
                raise errors.InvalidURL(url, 'URLs can only contain specific safe characters')
        return url
    # We have a unicode (hybrid) url
    scheme = m.group('scheme')
    path = list(m.group('path'))

    for i in xrange(len(path)):
        if path[i] not in _url_safe_characters:
            chars = path[i].encode('utf-8')
            path[i] = ''.join(['%%%02X' % ord(c) for c in path[i].encode('utf-8')])
    return scheme + '://' + ''.join(path)


def split(url, exclude_trailing_slash=True):
    """Split a URL into its parent directory and a child directory.

    :param url: A relative or absolute URL
    :param exclude_trailing_slash: Strip off a final '/' if it is part
        of the path (but not if it is part of the protocol specification)
    """
    scheme_loc, first_path_slash = _find_scheme_and_separator(url)

    if first_path_slash is None:
        # We have either a relative path, or no separating slash
        if scheme_loc is None:
            # Relative path
            if exclude_trailing_slash and url.endswith('/'):
                url = url[:-1]
            return _posix_split(url)
        else:
            # Scheme with no path
            return url, ''

    # We have a fully defined path
    url_base = url[:first_path_slash] # http://host, file://
    path = url[first_path_slash:] # /file/foo

    if sys.platform == 'win32' and url.startswith('file:///'):
        # Strip off the drive letter
        if path[2:3] not in '\\/':
            raise errors.InvalidURL(url, 
                'win32 file:/// paths need a drive letter')
        url_base += path[1:4] # file:///C|/
        path = path[3:]

    if exclude_trailing_slash and len(path) > 1 and path.endswith('/'):
        path = path[:-1]
    head, tail = _posix_split(path)
    return url_base + head, tail


def strip_trailing_slash(url):
    """Strip trailing slash, except for root paths.

    The definition of 'root path' is platform-dependent.
    This assumes that all URLs are valid netloc urls, such that they
    form:
    scheme://host/path
    It searches for ://, and then refuses to remove the next '/'.
    It can also handle relative paths
    Examples:
        path/to/foo       => path/to/foo
        path/to/foo/      => path/to/foo
        http://host/path/ => http://host/path
        http://host/path  => http://host/path
        http://host/      => http://host/
        file:///          => file:///
        file:///foo/      => file:///foo
        # This is unique on win32 platforms, and is the only URL
        # format which does it differently.
        file:///C|/       => file:///C|/
    """
    if not url.endswith('/'):
        # Nothing to do
        return url
    if sys.platform == 'win32' and url.startswith('file:///'):
        # This gets handled specially, because the 'top-level'
        # of a win32 path is actually the drive letter
        if len(url) > MIN_ABS_FILEURL_LENGTH:
            return url[:-1]
        else:
            return url
    scheme_loc, first_path_slash = _find_scheme_and_separator(url)
    if scheme_loc is None:
        # This is a relative path, as it has no scheme
        # so just chop off the last character
        return url[:-1]

    if first_path_slash is None or first_path_slash == len(url)-1:
        # Don't chop off anything if the only slash is the path
        # separating slash
        return url

    return url[:-1]


def unescape(url):
    """Unescape relpath from url format.

    This returns a Unicode path from a URL
    """
    # jam 20060427 URLs are supposed to be ASCII only strings
    #       If they are passed in as unicode, urllib.unquote
    #       will return a UNICODE string, which actually contains
    #       utf-8 bytes. So we have to ensure that they are
    #       plain ASCII strings, or the final .decode will
    #       try to encode the UNICODE => ASCII, and then decode
    #       it into utf-8.
    try:
        url = str(url)
    except UnicodeError, e:
        raise errors.InvalidURL(url, 'URL was not a plain ASCII url: %s' % (e,))
    unquoted = urllib.unquote(url)
    try:
        unicode_path = unquoted.decode('utf-8')
    except UnicodeError, e:
        raise errors.InvalidURL(url, 'Unable to encode the URL as utf-8: %s' % (e,))
    return unicode_path


# These are characters that if escaped, should stay that way
_no_decode_chars = ';/?:@&=+$,#'
_no_decode_ords = [ord(c) for c in _no_decode_chars]
_no_decode_hex = (['%02x' % o for o in _no_decode_ords] 
                + ['%02X' % o for o in _no_decode_ords])
_hex_display_map = dict(([('%02x' % o, chr(o)) for o in range(256)]
                    + [('%02X' % o, chr(o)) for o in range(256)]))
#These entries get mapped to themselves
_hex_display_map.update((hex,'%'+hex) for hex in _no_decode_hex)

# These characters should not be escaped
_url_safe_characters = set('abcdefghijklmnopqrstuvwxyz'
                        'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                        '0123456789' '_.-/'
                        ';?:@&=+$,%#')


def unescape_for_display(url):
    """Decode what you can for a URL, so that we get a nice looking path.

    This will turn file:// urls into local paths, and try to decode
    any portions of a http:// style url that it can.
    """
    if url.startswith('file://'):
        return local_path_from_url(url)

    # Split into sections to try to decode utf-8
    res = url.split('/')
    for i in xrange(1, len(res)):
        escaped_chunks = res[i].split('%')
        for j in xrange(1, len(escaped_chunks)):
            item = escaped_chunks[j]
            try:
                escaped_chunks[j] = _hex_display_map[item[:2]] + item[2:]
            except KeyError:
                # Put back the percent symbol
                escaped_chunks[j] = '%' + item
            except UnicodeDecodeError:
                escaped_chunks[j] = unichr(int(item[:2], 16)) + item[2:]
        unescaped = ''.join(escaped_chunks)
        try:
            res[i] = unescaped.decode('utf-8')
        except UnicodeDecodeError:
            # If this path segment cannot be properly utf-8 decoded
            # after doing unescaping we will just leave it alone
            pass
    return '/'.join(res)


