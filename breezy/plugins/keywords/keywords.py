# Copyright (C) 2008 Canonical Ltd
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

from __future__ import absolute_import

import re, time
from ... import (
    debug,
    osutils,
    registry,
    trace,
    )
from ...sixish import text_type

# Expansion styles
# Note: Round-tripping is only required between the raw and cooked styles
_keyword_style_registry = registry.Registry()
_keyword_style_registry.register('raw', b'$%(name)s$')
_keyword_style_registry.register('cooked', b'$%(name)s: %(value)s $')
_keyword_style_registry.register('publish', b'%(name)s: %(value)s')
_keyword_style_registry.register('publish-values', b'%(value)s')
_keyword_style_registry.register('publish-names', b'%(name)s')
_keyword_style_registry.default_key = 'cooked'


# Regular expressions for matching the raw and cooked patterns
_KW_RAW_RE = re.compile(b'\\$([\\w\\-]+)(:[^$]*)?\\$')
_KW_COOKED_RE = re.compile(b'\\$([\\w\\-]+):([^$]+)\\$')


# The registry of keywords. Other plugins may wish to add entries to this.
keyword_registry = registry.Registry()

# Revision-related keywords
keyword_registry.register('Date',
    lambda c: format_date(c.revision().timestamp, c.revision().timezone,
    c.config(), 'Date'))
keyword_registry.register('Committer',
    lambda c: c.revision().committer)
keyword_registry.register('Authors',
    lambda c: ", ".join(c.revision().get_apparent_authors()))
keyword_registry.register('Revision-Id',
    lambda c: c.revision_id())
keyword_registry.register('Path',
    lambda c: c.relpath())
keyword_registry.register('Directory',
    lambda c: osutils.split(c.relpath())[0])
keyword_registry.register('Filename',
    lambda c: osutils.split(c.relpath())[1])
keyword_registry.register('File-Id',
    lambda c: c.file_id())

# Environment-related keywords
keyword_registry.register('Now',
    lambda c: format_date(time.time(), time.timezone, c.config(), 'Now'))
keyword_registry.register('User',
    lambda c: c.config().username())

# Keywords for finer control over name & address formatting
keyword_registry.register('Committer-Name',
    lambda c: extract_name(c.revision().committer))
keyword_registry.register('Committer-Email',
    lambda c: extract_email(c.revision().committer))
keyword_registry.register('Author1-Name',
    lambda c: extract_name_item(c.revision().get_apparent_authors(), 0))
keyword_registry.register('Author1-Email',
    lambda c: extract_email_item(c.revision().get_apparent_authors(), 0))
keyword_registry.register('Author2-Name',
    lambda c: extract_name_item(c.revision().get_apparent_authors(), 1))
keyword_registry.register('Author2-Email',
    lambda c: extract_email_item(c.revision().get_apparent_authors(), 1))
keyword_registry.register('Author3-Name',
    lambda c: extract_name_item(c.revision().get_apparent_authors(), 2))
keyword_registry.register('Author3-Email',
    lambda c: extract_email_item(c.revision().get_apparent_authors(), 2))
keyword_registry.register('User-Name',
    lambda c: extract_name(c.config().username()))
keyword_registry.register('User-Email',
    lambda c: extract_email(c.config().username()))


def format_date(timestamp, offset=0, cfg=None, name=None):
    """Return a formatted date string.

    :param timestamp: Seconds since the epoch.
    :param offset: Timezone offset in seconds east of utc.
    """
    if cfg is not None and name is not None:
        cfg_key = 'keywords.format.%s' % (name,)
        format = cfg.get_user_option(cfg_key)
    else:
        format = None
    return osutils.format_date(timestamp, offset, date_fmt=format)


def extract_name(userid):
    """Extract the name out of a user-id string.

    user-id strings have the format 'name <email>'.
    """
    if userid and userid[-1] == '>':
        return userid[:-1].rsplit('<', 1)[0].rstrip()
    else:
        return userid


def extract_email(userid):
    """Extract the email address out of a user-id string.

    user-id strings have the format 'name <email>'.
    """
    if userid and userid[-1] == '>':
        return userid[:-1].rsplit('<', 1)[1]
    else:
        return userid

def extract_name_item(seq, n):
    """Extract the name out of the nth item in a sequence of user-ids.

    :return: the user-name or an empty string
    """
    try:
        return extract_name(seq[n])
    except IndexError:
        return ""


def extract_email_item(seq, n):
    """Extract the email out of the nth item in a sequence of user-ids.

    :return: the email address or an empty string
    """
    try:
        return extract_email(seq[n])
    except IndexError:
        return ""


def compress_keywords(s, keyword_dicts):
    """Replace cooked style keywords with raw style in a string.

    Note: If the keyword is not known, the text is not modified.

    :param s: the string
    :param keyword_dicts: an iterable of keyword dictionaries.
    :return: the string with keywords compressed
    """
    _raw_style = _keyword_style_registry.get('raw')
    result = b''
    rest = s
    while True:
        match = _KW_COOKED_RE.search(rest)
        if not match:
            break
        result += rest[:match.start()]
        keyword = match.group(1)
        expansion = _get_from_dicts(keyword_dicts, keyword.decode('ascii'))
        if expansion is None:
            # Unknown expansion - leave as is
            result += match.group(0)
        else:
            result += _raw_style % {b'name': keyword}
        rest = rest[match.end():]
    return result + rest


def expand_keywords(s, keyword_dicts, context=None, encoder=None, style=None):
    """Replace raw style keywords with another style in a string.

    Note: If the keyword is already in the expanded style, the value is
    not replaced.

    :param s: the string
    :param keyword_dicts: an iterable of keyword dictionaries. If values
      are callables, they are executed to find the real value.
    :param context: the parameter to pass to callable values
    :param style: the style of expansion to use of None for the default
    :return: the string with keywords expanded
    """
    _expanded_style = _keyword_style_registry.get(style)
    result = b''
    rest = s
    while True:
        match = _KW_RAW_RE.search(rest)
        if not match:
            break
        result += rest[:match.start()]
        keyword = match.group(1)
        expansion = _get_from_dicts(keyword_dicts, keyword.decode('ascii'))
        if callable(expansion):
            try:
                expansion = expansion(context)
            except AttributeError as err:
                if 'error' in debug.debug_flags:
                    trace.note("error evaluating %s for keyword %s: %s",
                        expansion, keyword, err)
                expansion = b"(evaluation error)"
        if isinstance(expansion, text_type):
            expansion = expansion.encode('utf-8')
        if expansion is None:
            # Unknown expansion - leave as is
            result += match.group(0)
            rest = rest[match.end():]
            continue
        if b'$' in expansion:
            # Expansion is not safe to be collapsed later
            expansion = b"(value unsafe to expand)"
        if encoder is not None:
            expansion = encoder(expansion)
        params = {b'name': keyword, b'value': expansion}
        result += _expanded_style % params
        rest = rest[match.end():]
    return result + rest


def _get_from_dicts(dicts, key, default=None):
    """Search a sequence of dictionaries or registries for a key.

    :return: the value, or default if not found
    """
    for dict in dicts:
        if key in dict:
            return dict.get(key)
    return default


def _xml_escape(s):
    """Escape a string so it can be included safely in XML/HTML."""
    # Compile the regular expressions if not already done
    from ... import xml8
    xml8._ensure_utf8_re()
    # Convert and strip the trailing quote
    return xml8._encode_and_escape(s)[:-1]


def _kw_compressor(chunks, context=None):
    """Filter that replaces keywords with their compressed form."""
    text = b''.join(chunks)
    return [compress_keywords(text, [keyword_registry])]


def _kw_expander(chunks, context, encoder=None):
    """Keyword expander."""
    text = b''.join(chunks)
    return [expand_keywords(text, [keyword_registry], context=context,
        encoder=encoder)]


def _normal_kw_expander(chunks, context=None):
    """Filter that replaces keywords with their expanded form."""
    return _kw_expander(chunks, context)


def _xml_escape_kw_expander(chunks, context=None):
    """Filter that replaces keywords with a form suitable for use in XML."""
    return _kw_expander(chunks, context, encoder=_xml_escape)
