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
When compressing, the values of known keywords are removed.

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

from __future__ import absolute_import


from ... import (
    builtins,
    commands,
    filters,
    option,
    )


def test_suite():
    """Called by breezy to fetch tests for this plugin"""
    from unittest import TestSuite, TestLoader
    from .tests import (
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


# Define and register the filter stack map
def _keywords_filter_stack_lookup(k):
    from .keywords import (
        _kw_compressor,
        _normal_kw_expander,
        _xml_escape_kw_expander,
        )
    filter_stack_map = {
        'off': [],
        'on':
            [filters.ContentFilter(_kw_compressor, _normal_kw_expander)],
        'xml_escape':
            [filters.ContentFilter(_kw_compressor, _xml_escape_kw_expander)],
        }
    return filter_stack_map.get(k)

try:
    register_filter = filters.filter_stacks_registry.register
except AttributeError:
    register_filter = filters.register_filter_stack_map

register_filter('keywords', _keywords_filter_stack_lookup)


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
             lazy_registry=(__name__ + ".keywords",
                 "_keyword_style_registry"),
             converter=lambda s: s,
             help='Keyword expansion style.')]

    def run(self, *args, **kwargs):
        """Process special options and delegate to superclass."""
        if 'keywords' in kwargs:
            from .keywords import (
                _keyword_style_registry,
                )
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
             lazy_registry=(__name__ + ".keywords",
                 "_keyword_style_registry"),
                 converter=lambda s: s,
                 help='Keyword expansion style.')]

    def run(self, *args, **kwargs):
        """Process special options and delegate to superclass."""
        if 'keywords' in kwargs:
            from .keywords import (
                _keyword_style_registry,
                )
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
