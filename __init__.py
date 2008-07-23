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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

r'''Keywords
========

Keyword templating is provided as a content filter where Bazaar internally
stores a canonical format but outputs a convenience format. See
``bzr help content-filters`` for general information about using these.

Keyword templates are specified using the following patterns:

 * in canonical/compressed format: $Keyword$
 * in convenience/expanded format: $Keyword: value $

When expanding, the existing text is retained if an unknown keyword is
found or if the keyword has already been expanded. When compressing,
values are always removed, whether the keyword is known or not.

Keyword filtering needs to be enabled for selected branches and files via
rules. See ``bzr help rules`` for general information on defining rules.
For example, to enable keywords for all ``txt`` files on your system, add
these lines to your ``BZR_HOME/rules`` file::

  [name *.txt]
  keywords = on

You can also enable or disable them on a per branch basis by adding lines
to ``.bzrrules``. For example, to disable keywords for ``txt`` files
but enable them for ``html`` files::

  [name *.txt]
  keywords = off

  [name *.html]
  keywords = escape

``escape`` enables keyword expansion but it escapes special characters
in keyword values so they can be safely included in HTML or XML files.

The currently supported keywords are given below.

 =============  =====================================================
 Keyword        Description
 =============  =====================================================
 Now            the current date and time
 User           the current user (name and email)
 UserEmail      just the email address of the current user
 File           the relative path of the file or dir in the tree
 FileName       just the name part of the relative path
 FileDir        just the directory part of the relative path
 =============  =====================================================

By default, dates/times are output using this format::

  YYYY-MM-DD HH:MM:SS+HH:MM

To specify a custom format, add a configuration setting to
``BZR_HOME/bazaar.conf`` like this::

  keywords.format.Now = %A, %B %d, %Y

The last part of the key needs to match the keyword name. The value must be
a legal strftime (http://docs.python.org/lib/module-time.html) format.
'''


import datetime, re
from bzrlib import (
    builtins,
    commands,
    config,
    filters,
    option,
    osutils,
    registry,
    )


def test_suite():
    """Called by bzrlib to fetch tests for this plugin"""
    from unittest import TestSuite, TestLoader
    from bzrlib.plugins.keywords.tests import (
         test_conversion,
         )
    loader = TestLoader()
    suite = TestSuite()
    for module in [
        test_conversion,
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
_KW_RAW_RE = re.compile(r'\$(\w+)\$')
_KW_COOKED_RE = re.compile(r'\$(\w+):([^$]+)\$')


def compress_keywords(s):
    """Replace cooked style keywords with raw style in a string.
    
    :param s: the string
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
        result += _raw_style % {'name': keyword}
        rest = rest[match.end():]
    return result + rest


def expand_keywords(s, keyword_dicts, style=None):
    """Replace raw style keywords with another style in a string.
    
    Note: If the keyword is already in the expanded style, the value is
    not replaced.

    :param s: the string
    :param keyword_dicts: an iterable of keyword dictionaries
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
        if expansion is None:
            # Unknown expansion - leave as is
            result += match.group(0)
        elif '$' in expansion:
            # Expansion is not safe to be collapsed later
            # TODO: output a warning or some trace here?
            result += match.group(0)
        else:
            params = {'name': keyword, 'value': expansion}
            result += _expanded_style % params
        rest = rest[match.end():]
    return result + rest


def _get_from_dicts(dicts, key, default=None):
    """Search a sequence of dictionaries for a key.

    :return: the value, or default if not found
    """
    for dict in dicts:
        if dict.has_key(key):
            return dict[key]
    return default


# Keywords that are file independent - None until first initialised
_global_keywords = None


def _init_global_keywords(_now_fn=datetime.datetime.now):
    global _global_keywords, _global_escaped_keywords
    if _global_keywords is None:
        cfg = config.GlobalConfig()
        now = _format_datetime_keyword(_now_fn(), 'Now', cfg)
        user = cfg.username()
        email = cfg.user_email()
        _global_keywords = {
            'Now': now,
            'User': user,
            'UserEmail': email,
            }
        _global_escaped_keywords = {
            'Now': _escape(now),
            'User': _escape(user),
            'UserEmail': _escape(email),
            }


def _format_datetime_keyword(dt, name, cfg):
    cfg_key = 'keywords.format.%s' % (name,)
    format = cfg.get_user_option(cfg_key)
    if format is None:
        return str(dt)
    else:
        return dt.strftime(format)


def _escape(s):
    """Escape a string so it can be included safely in XML/HTML."""
    # TODO
    return s


def _kw_compressor(chunks, context=None):
    """Filter that replaces keywords with their compressed form."""
    text = ''.join(chunks)
    return [compress_keywords(text)]


def _normal_kw_expander(chunks, context=None):
    """Filter that replaces keywords with their expanded form."""
    _init_global_keywords()
    path = context.relpath()
    dir, base = osutils.split(path)
    local_keywords = {
        'File': path,
        'FileName': base,
        'FileDir': dir,
        }
    text = ''.join(chunks)
    return [expand_keywords(text, [local_keywords, _global_keywords])]


def _escaped_kw_expander(chunks, context=None):
    """Filter that replaces keywords with their escaped, expanded form."""
    _init_global_keywords()
    path = context.relpath()
    dir, base = osutils.split(path)
    local_keywords = {
        'File': _escape(path),
        'FileName': _escape(base),
        'FileDir': _escape(dir),
        }
    text = ''.join(chunks)
    return [expand_keywords(text, [local_keywords, _global_escaped_keywords])]


# Define and register the filter stack map
_filter_stack_map = {
    'off':    [],
    'on':     [filters.ContentFilter(_kw_compressor, _normal_kw_expander)],
    'escape': [filters.ContentFilter(_kw_compressor, _escaped_kw_expander)],
    }
filters.register_filter_stack_map('keywords', _filter_stack_map)


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
