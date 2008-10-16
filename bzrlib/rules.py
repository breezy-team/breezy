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

"""Rule-based definition of preferences for selected files in selected branches.

See ``bzr help rules`` for details.
"""

from bzrlib import (
    config,
    errors,
    globbing,
    osutils,
    )
from bzrlib.util.configobj import configobj


# Name of the file holding rules in a tree
RULES_TREE_FILENAME = ".bzrrules"

# Namespace prefix for per file preferences
FILE_PREFS_PREFIX = 'name '
FILE_PREFS_PREFIX_LEN = len(FILE_PREFS_PREFIX)


class _RulesSearcher(object):
    """An object that provides rule-based preferences."""

    def get_items(self, path):
        """Return the preferences for a path as name,value tuples.

        :param path: tree relative path
        :return: () if no rule matched, otherwise a sequence of name,value
          tuples.
        """
        raise NotImplementedError(self.get_items)

    def get_selected_items(self, path, names):
        """Return selected preferences for a path as name,value tuples.

        :param path: tree relative path
        :param names: the list of preferences to lookup
        :return: () if no rule matched, otherwise a sequence of name,value
          tuples. The sequence is the same length as names,
          tuple order matches the order in names, and
          undefined preferences are given the value None.
        """
        raise NotImplementedError(self.get_selected_items)


class _IniBasedRulesSearcher(_RulesSearcher):

    def __init__(self, inifile):
        """Construct a _RulesSearcher based on an ini file.

        The content will be decoded as utf-8.

        :param inifile: the name of the file or a sequence of lines.
        """
        options = {'encoding': 'utf-8'}
        self._cfg = configobj.ConfigObj(inifile, options=options)
        sections = self._cfg.keys()
        patterns = [s[FILE_PREFS_PREFIX_LEN:] for s in sections
            if s.startswith(FILE_PREFS_PREFIX)]
        if len(patterns) < len(sections):
            unknowns = [s for s in sections
                if not s.startswith(FILE_PREFS_PREFIX)]
            raise errors.UnknownRules(unknowns)
        elif patterns:
            self._globster = globbing._OrderedGlobster(patterns)
        else:
            self._globster = None

    def get_items(self, path):
        """See _RulesSearcher.get_items."""
        if self._globster is None:
            return ()
        pat = self._globster.match(path)
        if pat is None:
            return ()
        else:
            all = self._cfg[FILE_PREFS_PREFIX + pat]
            return tuple(all.items())

    def get_selected_items(self, path, names):
        """See _RulesSearcher.get_selected_items."""
        if self._globster is None:
            return ()
        pat = self._globster.match(path)
        if pat is None:
            return ()
        else:
            all = self._cfg[FILE_PREFS_PREFIX + pat]
            return tuple((k, all.get(k)) for k in names)


class _StackedRulesSearcher(_RulesSearcher):

    def __init__(self, searchers):
        """Construct a _RulesSearcher based on a stack of other ones.

        :param searchers: a sequence of searchers.
        """
        self.searchers = searchers

    def get_items(self, path):
        """See _RulesSearcher.get_items."""
        for searcher in self.searchers:
            result = searcher.get_items(path)
            if result:
                return result
        return ()

    def get_selected_items(self, path, names):
        """See _RulesSearcher.get_selected_items."""
        for searcher in self.searchers:
            result = searcher.get_selected_items(path, names)
            if result:
                return result
        return ()


def rules_filename():
    """Return the default rules filename."""
    return osutils.pathjoin(config.config_dir(), 'rules')


# The object providing default rules
_per_user_searcher = _IniBasedRulesSearcher(rules_filename())
