# Copyright (C) 2006 Canonical Ltd
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

# TODO: Some kind of command-line display of revision properties:
# perhaps show them in log -v and allow them as options to the commit command.

"""Some functions to enable caching the conversion between unicode to utf8."""

from codecs import utf_8_decode as _utf8_decode
from codecs import utf_8_encode as _utf8_encode


def _utf8_decode_with_None(bytestring, _utf8_decode=_utf8_decode):
    """Wrap _utf8_decode to support None->None for optional strings.

    Also, only return the Unicode portion, since we don't care about the second
    return value.
    """
    if bytestring is None:
        return None
    else:
        return _utf8_decode(bytestring)[0]


# Map revisions from and to utf8 encoding
# Whenever we do an encode/decode operation, we save the result, so that
# we don't have to do it again.
_unicode_to_utf8_map: dict[str, bytes] = {}
_utf8_to_unicode_map: dict[bytes, str] = {}


def encode(
    unicode_str,
    _uni_to_utf8=_unicode_to_utf8_map,
    _utf8_to_uni=_utf8_to_unicode_map,
    _utf8_encode=_utf8_encode,
):
    """Take this unicode revision id, and get a unicode version."""
    # If the key is in the cache try/KeyError is 50% faster than
    # val = dict.get(key), if val is None:
    # On jam's machine the difference is
    # try/KeyError:  900ms
    #      if None: 1250ms
    # Since these are primarily used when iterating over a knit entry
    # *most* of the time the key will already be in the cache, so use the
    # fast path
    try:
        return _uni_to_utf8[unicode_str]
    except KeyError:
        _uni_to_utf8[unicode_str] = utf8_str = _utf8_encode(unicode_str)[0]
        _utf8_to_uni[utf8_str] = unicode_str
        return utf8_str


def decode(
    utf8_str,
    _uni_to_utf8=_unicode_to_utf8_map,
    _utf8_to_uni=_utf8_to_unicode_map,
    _utf8_decode=_utf8_decode,
):
    """Take a utf8 revision id, and decode it, but cache the result."""
    try:
        return _utf8_to_uni[utf8_str]
    except KeyError:
        unicode_str = _utf8_decode(utf8_str)[0]
        _utf8_to_uni[utf8_str] = unicode_str
        _uni_to_utf8[unicode_str] = utf8_str
        return unicode_str


def get_cached_unicode(unicode_str):
    """Return a cached version of the unicode string.

    This has a similar idea to that of intern() in that it tries
    to return a singleton string. Only it works for unicode strings.
    """
    # This might return the same object, or it might return the cached one
    # the decode() should just be a hash lookup, because the encode() side
    # should add the entry to the maps
    return decode(encode(unicode_str))


def get_cached_utf8(utf8_str):
    """Return a cached version of the utf-8 string.

    Get a cached version of this string (similar to intern()).
    At present, this will be decoded to ensure it is a utf-8 string. In the
    future this might change to simply caching the string.
    """
    return encode(decode(utf8_str))


def get_cached_ascii(
    ascii_str, _uni_to_utf8=_unicode_to_utf8_map, _utf8_to_uni=_utf8_to_unicode_map
):
    """This is a string which is identical in utf-8 and unicode."""
    # We don't need to do any encoding, but we want _utf8_to_uni to return a
    # real Unicode string. Unicode and plain strings of this type will have the
    # same hash, so we can just use it as the key in _uni_to_utf8, but we need
    # the return value to be different in _utf8_to_uni
    uni_str = ascii_str.decode("ascii")
    ascii_str = _uni_to_utf8.setdefault(uni_str, ascii_str)
    _utf8_to_uni.setdefault(ascii_str, uni_str)
    return ascii_str


def clear_encoding_cache():
    """Clear the encoding and decoding caches."""
    _unicode_to_utf8_map.clear()
    _utf8_to_unicode_map.clear()
