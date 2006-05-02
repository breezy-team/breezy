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

import urllib
import sys

import bzrlib.errors as errors
import bzrlib.osutils


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
    assert len(base) >= MIN_ABS_URLPATHLENGTH, ('Length of base must be equal or'
        ' exceed the platform minimum url length (which is %d)' % 
        MIN_ABS_URLPATHLENGTH)

    base = local_path_from_url(base)
    path = local_path_from_url(path)
    return escape(bzrlib.osutils.relpath(base, path))


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
MIN_ABS_URLPATHLENGTH = len('file:///')

if sys.platform == 'win32':
    local_path_to_url = _win32_local_path_to_url
    local_path_from_url = _win32_local_path_from_url

    MIN_ABS_URLPATHLENGTH = len('file:///C|/')


def strip_trailing_slash(url):
    """Strip trailing slash, except for root paths.

    The definition of 'root path' is platform-dependent.
    But the passed in URL must be a file:/// url.
    """
    assert url.startswith('file:///'), \
        'strip_trailing_slash expects file:// urls (%s)' % url
    if len(url) != MIN_ABS_URLPATHLENGTH and url[-1] == '/':
        return url[:-1]
    else:
        return url


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
_hex_display_map = urllib._hextochr.copy()
_hex_display_map.update((hex,'%'+hex) for hex in _no_decode_hex)
#These entries get mapped to themselves


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


