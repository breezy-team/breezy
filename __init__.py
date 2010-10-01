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

r'''Keyword Templating
==================

Keyword templating is provided as a content filter where Bazaar internally
stores a canonical format but outputs a convenience format. See
``bzr help content-filters`` for general information about using these.

Note: Content filtering is only supported in recently added formats,
e.g. 1.14.

Keyword templates are specified using the following patterns:

 * in canonical/compressed format: $Keyword$
 * in convenience/expanded format: $Keyword: value $

When expanding, the existing text is retained if an unknown keyword is
found. If the keyword is already expanded but known, the value is replaced.
When compressing, values are always removed, whether the keyword is known
or not.

Keyword filtering needs to be enabled for selected branches and files via
rules. See ``bzr help rules`` for general information on defining rules.
For example, to enable keywords for all ``txt`` files on your system, add
these lines to your ``BZR_HOME/rules`` file::

  [name *.txt]
  keywords = on

To disable keywords for ``txt`` files but enable them for ``html`` files::

  [name *.txt]
  keywords = off

  [name *.html]
  keywords = xml_escape

``xml_escape`` enables keyword expansion but it escapes special characters
in keyword values so they can be safely included in HTML or XML files.

The currently supported keywords are given below.

 =============  =========================================================
 Keyword        Description
 =============  =========================================================
 Date           the date and time the file was last modified
 Committer      the committer (name and email) of the last change
 Authors        the authors (names and emails) of the last change
 Revision-Id    the unique id of the revision that last changed the file
 Path           the relative path of the file in the tree
 Filename       just the name part of the relative path
 Directory      just the directory part of the relative path
 File-Id        the unique id assigned to this file
 Now            the current date and time
 User           the current user (name and email)
 =============  =========================================================

If you want finer control over the formatting of names and email
addresses, you can use the following keywords.

 =============    =======================================================
 Keyword          Description
 =============    =======================================================
 Committer-Name   just the name of the current committer
 Committer-Email  just the email address of the current committer
 Author1-Name     just the name of the first author
 Author1-Email    just the email address of the first author
 Author2-Name     just the name of the second author
 Author2-Email    just the email address of the second author
 Author3-Name     just the name of the third author
 Author3-Email    just the email address of the third author
 User-Name        just the name of the current user
 User-Email       just the email address of the current user
 =============    =======================================================

Note: If you have more than 3 authors for a given revision, please
ask on the Bazaar mailing list for an enhancement to support the
number you need.

By default, dates/times are output using this format::

  YYYY-MM-DD HH:MM:SS+HH:MM

To specify a custom format, add a configuration setting to
``BZR_HOME/bazaar.conf`` like this::

  keywords.format.Now = %A, %B %d, %Y

The last part of the key needs to match the keyword name. The value must be
a legal strftime (http://docs.python.org/lib/module-time.html) format.
'''


import re, time
from bzrlib import (
    builtins,
    commands,
    config,
    debug,
    filters,
    option,
    osutils,
    registry,
    trace,
    xml8,
    )


def test_suite():
    """Called by bzrlib to fetch tests for this plugin"""
    from unittest import TestSuite, TestLoader
    from bzrlib.plugins.keywords.tests import (
         test_conversion,
         test_keywords_in_trees,
         )
    loader = TestLoader()
    suite = TestSuite()
    for module in [
        test_conversion,
        test_keywords_in_trees,
        ]:
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


# Expansion styles
# Note: Round-tripping is only required between the raw and cooked styles
_keyword_style_registry = registry.Registry()
_keyword_style_registry.register('raw', '$%(name)s$')
_keyword_style_registry.register('cooked', '$%(name)s: %(value)s $')
_keyword_style_registry.register('publish', '%(name)s: %(value)s')
_keyword_style_registry.register('publish-values', '%(value)s')
_keyword_style_registry.register('publish-names', '%(name)s')
_keyword_style_registry.default_key = 'cooked'


# Regular expressions for matching the raw and cooked patterns
_KW_RAW_RE = re.compile(r'\$([\w\-]+)(:[^$]*)?\$')
_KW_COOKED_RE = re.compile(r'\$([\w\-]+):([^$]+)\$')


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
    result = ''
    rest = s
    while (True):
        match = _KW_COOKED_RE.search(rest)
        if not match:
            break
        result += rest[:match.start()]
        keyword = match.group(1)
        expansion = _get_from_dicts(keyword_dicts, keyword)
        if expansion is None:
            # Unknown expansion - leave as is
            result += match.group(0)
        else:
            result += _raw_style % {'name': keyword}
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
    result = ''
    rest = s
    while (True):
        match = _KW_RAW_RE.search(rest)
        if not match:
            break
        result += rest[:match.start()]
        keyword = match.group(1)
        expansion = _get_from_dicts(keyword_dicts, keyword)
        if callable(expansion):
            try:
                expansion = expansion(context)
            except AttributeError, err:
                if 'error' in debug.debug_flags:
                    trace.note("error evaluating %s for keyword %s: %s",
                        expansion, keyword, err)
                expansion = "(evaluation error)"
        if expansion is None:
            # Unknown expansion - leave as is
            result += match.group(0)
            rest = rest[match.end():]
            continue
        if '$' in expansion:
            # Expansion is not safe to be collapsed later
            expansion = "(value unsafe to expand)"
        if encoder is not None:
            expansion = encoder(expansion)
        params = {'name': keyword, 'value': expansion}
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
    # Complie the regular expressions if not already done
    xml8._ensure_utf8_re()
    # Convert and strip the trailing quote
    return xml8._encode_and_escape(s)[:-1]


def _kw_compressor(chunks, context=None):
    """Filter that replaces keywords with their compressed form."""
    text = ''.join(chunks)
    return [compress_keywords(text, [keyword_registry])]


def _kw_expander(chunks, context, encoder=None):
    """Keyword expander."""
    text = ''.join(chunks)
    return [expand_keywords(text, [keyword_registry], context=context,
        encoder=encoder)]


def _normal_kw_expander(chunks, context=None):
    """Filter that replaces keywords with their expanded form."""
    return _kw_expander(chunks, context)


def _xml_escape_kw_expander(chunks, context=None):
    """Filter that replaces keywords with a form suitable for use in XML."""
    return _kw_expander(chunks, context, encoder=_xml_escape)


# Define and register the filter stack map
def _keywords_filter_stack_lookup(k):
    filter_stack_map = {
        'off': [],
        'on':
            [filters.ContentFilter(_kw_compressor, _normal_kw_expander)],
        'xml_escape':
            [filters.ContentFilter(_kw_compressor, _xml_escape_kw_expander)],
        }
    return filter_stack_map.get(k)


filters.register_filter_stack_map('keywords', _keywords_filter_stack_lookup)


class cmd_cat(builtins.cmd_cat):
    """
    The ``--keywords`` option specifies the keywords expansion
    style. By default (``raw`` style), no expansion is done.
    Other styles enable expansion in a ``cooked`` mode where both
    the keyword and its value are displayed inside $ markers, or in
    numerous publishing styles - ``publish``, ``publish-values`` and
    ``publish-names`` - where the $ markers are completely removed.
    The publishing styles do not support round-tripping back to the
    raw content but are useful for improving the readability of
    published web pages for example.

    Note: Files must have the ``keywords`` preference defined for them
    in order for the ``--keywords`` option to take effect. In particular,
    the preference specifies how keyword values are encoded for different
    filename patterns. See ``bzr help keywords`` for more information on
    how to specify the required preference using rules.
    """

    # Add a new option to the builtin command and
    # override the inherited run() and help() methods

    takes_options = builtins.cmd_cat.takes_options + [
             option.RegistryOption('keywords',
                 registry=_keyword_style_registry,
                 converter=lambda s: s,
                 help='Keyword expansion style.')]
  
    def run(self, *args, **kwargs):
        """Process special options and delegate to superclass."""
        if 'keywords' in kwargs:
            # Implicitly set the filters option
            kwargs['filters'] = True
            style = kwargs['keywords']
            _keyword_style_registry.default_key = style
            del kwargs['keywords']
        return super(cmd_cat, self).run(*args, **kwargs)
  
    def help(self):
      """Return help message including text from superclass."""
      from inspect import getdoc
      return getdoc(super(cmd_cat, self)) + '\n\n' + getdoc(self)


class cmd_export(builtins.cmd_export):
    # Add a new option to the builtin command and
    # override the inherited run() and help() methods

    takes_options = builtins.cmd_export.takes_options + [
             option.RegistryOption('keywords',
                 registry=_keyword_style_registry,
                 converter=lambda s: s,
                 help='Keyword expansion style.')]
  
    def run(self, *args, **kwargs):
        """Process special options and delegate to superclass."""
        if 'keywords' in kwargs:
            # Implicitly set the filters option
            kwargs['filters'] = True
            style = kwargs['keywords']
            _keyword_style_registry.default_key = style
            del kwargs['keywords']
        return super(cmd_export, self).run(*args, **kwargs)
  
    def help(self):
      """Return help message including text from superclass."""
      from inspect import getdoc
      # NOTE: Reuse of cmd_cat help below is deliberate, not a bug
      return getdoc(super(cmd_export, self)) + '\n\n' + getdoc(cmd_cat)


# Register the command wrappers
commands.register_command(cmd_cat, decorate=False)
commands.register_command(cmd_export, decorate=False)
