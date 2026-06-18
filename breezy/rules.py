# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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

"""Rule-based definition of preferences for selected files in selected branches.

See ``bzr help rules`` for details.
"""

import configobj

from . import bedding, cmdline, errors, globbing, osutils

# Name of the file holding rules in a tree
RULES_TREE_FILENAME = ".bzrrules"

# Namespace prefix for per file preferences
FILE_PREFS_PREFIX = "name "
FILE_PREFS_PREFIX_LEN = len(FILE_PREFS_PREFIX)

# The object providing default rules
_per_user_searcher = None


class UnknownRules(errors.BzrError):
    """Exception raised when unknown rule sections are detected."""

    _fmt = "Unknown rules detected: %(unknowns_str)s."

    def __init__(self, unknowns):
        """Initialize UnknownRules exception.

        Args:
            unknowns: List of unknown rule section names.
        """
        errors.BzrError.__init__(self, unknowns_str=", ".join(unknowns))


class _RulesSearcher:
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

    def get_single_value(self, path, preference_name):
        """Get a single preference for a single file.

        :returns: The string preference value, or None.
        """
        for _key, value in self.get_selected_items(path, [preference_name]):
            return value
        return None


class _IniBasedRulesSearcher(_RulesSearcher):
    def __init__(self, inifile):
        """Construct a _RulesSearcher based on an ini file.

        The content will be decoded as utf-8.

        :param inifile: the name of the file or a sequence of lines.
        """
        self._cfg = configobj.ConfigObj(inifile, encoding="utf-8")
        sections = self._cfg.keys()
        patterns = []
        self.pattern_to_section = {}
        for s in sections:
            if s.startswith(FILE_PREFS_PREFIX):
                file_patterns = cmdline.split(s[FILE_PREFS_PREFIX_LEN:])
                patterns.extend(file_patterns)
                for fp in file_patterns:
                    self.pattern_to_section[fp] = s
        if len(patterns) < len(sections):
            unknowns = [s for s in sections if not s.startswith(FILE_PREFS_PREFIX)]
            raise UnknownRules(unknowns)
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
            all = self._cfg[self.pattern_to_section[pat]]
            return tuple(all.items())

    def get_selected_items(self, path, names):
        """See _RulesSearcher.get_selected_items."""
        if self._globster is None:
            return ()
        pat = self._globster.match(path)
        if pat is None:
            return ()
        else:
            all = self._cfg[self.pattern_to_section[pat]]
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


def rules_path():
    """Return the default rules file path."""
    return osutils.pathjoin(bedding.config_dir(), "rules")


def reset_rules():
    """Reset the global per-user rules searcher to use the default rules file."""
    global _per_user_searcher
    _per_user_searcher = _IniBasedRulesSearcher(rules_path())


reset_rules()
