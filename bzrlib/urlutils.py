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
from posixpath import split as _posix_split, normpath as _posix_normpath
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
        return len(scheme), None
    return len(scheme), first_path_slash+len(scheme)+3


def join(base, *args):
    """Create a URL by joining sections.

    This will normalize '..', assuming that paths are absolute
    (it assumes no symlinks in either path)

    If any of *args is an absolute URL, it will be treated correctly.
    Example:
        join('http://foo', 'http://bar') => 'http://bar'
        join('http://foo', 'bar') => 'http://foo/bar'
        join('http://foo', 'bar', '../baz') => 'http://foo/baz'
    """
    m = _url_scheme_re.match(base)
    scheme = None
    if m:
        scheme = m.group('scheme')
        path = m.group('path').split('/')
        if path[-1:] == ['']:
            # Strip off a trailing slash
            # This helps both when we are at the root, and when
            # 'base' has an extra slash at the end
            path = path[:-1]
    else:
        path = base.split('/')

    for arg in args:
        m = _url_scheme_re.match(arg)
        if m:
            # Absolute URL
            scheme = m.group('scheme')
            path = m.group('path').split('/')
        else:
            for chunk in arg.split('/'):
                if chunk == '.':
                    continue
                elif chunk == '..':
                    if len(path) >= 2:
                        # Don't pop off the host portion
                        path.pop()
                    else:
                        raise errors.InvalidURLJoin('Cannot go above root',
                                base, args)
                else:
                    path.append(chunk)

    if scheme is None:
        return '/'.join(path)
    return scheme + '://' + '/'.join(path)


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
    return 'file://' + escape(_posix_normpath(
        bzrlib.osutils._posix_abspath(path)))


def _win32_local_path_from_url(url):
    """Convert a url like file:///C:/path/to/foo into C:/path/to/foo"""
    if not url.startswith('file:///'):
        raise errors.InvalidURL(url, 'local urls must start with file:///')
    # We strip off all 3 slashes
    win32_url = url[len('file:///'):]
    if (win32_url[0] not in ('abcdefghijklmnopqrstuvwxyz'
                             'ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        or win32_url[1] not in  '|:'
        or win32_url[2] != '/'):
        raise errors.InvalidURL(url, 'Win32 file urls start with'
                ' file:///x:/, where x is a valid drive letter')
    return win32_url[0].upper() + u':' + unescape(win32_url[2:])


def _win32_local_path_to_url(path):
    """Convert a local path like ./foo into a URL like file:///C:/path/to/foo

    This also handles transforming escaping unicode characters, etc.
    """
    # importing directly from ntpath allows us to test this 
    # on non-win32 platform
    # FIXME: It turns out that on nt, ntpath.abspath uses nt._getfullpathname
    #       which actually strips trailing space characters.
    #       The worst part is that under linux ntpath.abspath has different
    #       semantics, since 'nt' is not an available module.
    win32_path = bzrlib.osutils._nt_normpath(
        bzrlib.osutils._win32_abspath(path)).replace('\\', '/')
    return 'file:///' + win32_path[0].upper() + ':' + escape(win32_path[2:])


local_path_to_url = _posix_local_path_to_url
local_path_from_url = _posix_local_path_from_url
MIN_ABS_FILEURL_LENGTH = len('file:///')
WIN32_MIN_ABS_FILEURL_LENGTH = len('file:///C:/')

if sys.platform == 'win32':
    local_path_to_url = _win32_local_path_to_url
    local_path_from_url = _win32_local_path_from_url

    MIN_ABS_FILEURL_LENGTH = WIN32_MIN_ABS_FILEURL_LENGTH


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
        for c in url:
            if c not in _url_safe_characters:
                raise errors.InvalidURL(url, 'URLs can only contain specific'
                                            ' safe characters (not %r)' % c)
        return url
    # We have a unicode (hybrid) url
    scheme = m.group('scheme')
    path = list(m.group('path'))

    for i in xrange(len(path)):
        if path[i] not in _url_safe_characters:
            chars = path[i].encode('utf-8')
            path[i] = ''.join(['%%%02X' % ord(c) for c in path[i].encode('utf-8')])
    return scheme + '://' + ''.join(path)


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

    base_path = base[base_first_slash+1:]
    other_path = other[other_first_slash+1:]

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
    if len(path) < 3 or path[2] not in ':|' or path[3] != '/':
        raise errors.InvalidURL(url_base + path, 
            'win32 file:/// paths need a drive letter')
    url_base += path[0:3] # file:// + /C:
    path = path[3:] # /foo
    return url_base, path


def split(url, exclude_trailing_slash=True):
    """Split a URL into its parent directory and a child directory.

    :param url: A relative or absolute URL
    :param exclude_trailing_slash: Strip off a final '/' if it is part
        of the path (but not if it is part of the protocol specification)

    :return: (parent_url, child_dir).  child_dir may be the empty string if we're at 
        the root.
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
        # url_base is currently file://
        # path is currently /C:/foo
        url_base, path = _win32_extract_drive_letter(url_base, path)
        # now it should be file:///C: and /foo

    if exclude_trailing_slash and len(path) > 1 and path.endswith('/'):
        path = path[:-1]
    head, tail = _posix_split(path)
    return url_base + head, tail


def _win32_strip_local_trailing_slash(url):
    """Strip slashes after the drive letter"""
    if len(url) > WIN32_MIN_ABS_FILEURL_LENGTH:
        return url[:-1]
    else:
        return url


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
        file:///c|/       => file:///c:/
    """
    if not url.endswith('/'):
        # Nothing to do
        return url
    if sys.platform == 'win32' and url.startswith('file:///'):
        return _win32_strip_local_trailing_slash(url)

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


def unescape_for_display(url, encoding):
    """Decode what you can for a URL, so that we get a nice looking path.

    This will turn file:// urls into local paths, and try to decode
    any portions of a http:// style url that it can.

    Any sections of the URL which can't be represented in the encoding or 
    need to stay as escapes are left alone.

    :param url: A 7-bit ASCII URL
    :param encoding: The final output encoding

    :return: A unicode string which can be safely encoded into the 
         specified encoding.
    """
    assert encoding is not None, 'you cannot specify None for the display encoding.'
    if url.startswith('file://'):
        try:
            path = local_path_from_url(url)
            path.encode(encoding)
            return path
        except UnicodeError:
            return url

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
            decoded = unescaped.decode('utf-8')
        except UnicodeDecodeError:
            # If this path segment cannot be properly utf-8 decoded
            # after doing unescaping we will just leave it alone
            pass
        else:
            try:
                decoded.encode(encoding)
            except UnicodeEncodeError:
                # If this chunk cannot be encoded in the local
                # encoding, then we should leave it alone
                pass
            else:
                # Otherwise take the url decoded one
                res[i] = decoded
    return u'/'.join(res)
