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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# TODO: Some kind of command-line display of revision properties: 
# perhaps show them in log -v and allow them as options to the commit command.

"""Some functions to enable caching the conversion between unicode to utf8"""

import codecs


_utf8_encode = codecs.getencoder("utf-8")
_utf8_decode = codecs.getdecoder("utf-8")

# Map revisions from and to utf8 encoding
# Whenever we do an encode/decode operation, we save the result, so that
# we don't have to do it again.
_unicode_to_utf8_map = {}
_utf8_to_unicode_map = {}


def encode(unicode_str,
           _uni_to_utf8=_unicode_to_utf8_map,
           _utf8_to_uni=_utf8_to_unicode_map,
           _utf8_encode=_utf8_encode):
    """Take this unicode revision id, and get a unicode version"""
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


def decode(utf8_str,
           _uni_to_utf8=_unicode_to_utf8_map,
           _utf8_to_uni=_utf8_to_unicode_map,
           _utf8_decode=_utf8_decode):
    """Take a utf8 revision id, and decode it, but cache the result"""
    try:
        return _utf8_to_uni[utf8_str]
    except KeyError:
        _utf8_to_uni[utf8_str] = unicode_str = _utf8_decode(utf8_str)[0]
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


def clear_encoding_cache():
    """Clear the encoding and decoding caches"""
    _unicode_to_utf8_map.clear()
    _utf8_to_unicode_map.clear()
