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
    globbing,
    osutils,
    )
from bzrlib.util.configobj import configobj


class _RulesSearcher(object):
    """An object that provides rule-based preferences."""

    def get_items(self, path, names=None):
        """Return the preferences for a path as a sequence of name,value tuples.

        :param path: tree relative path
        :param names: the list of preferences to lookup - None for all
        :return: None if no rule matched, otherwise a sequence of name,value
          tuples. If names is not None, the sequence is the same length as
          names, tuple order matches the order in names, and undefined
          preferences are given the value None.
        """
        raise NotImplementedError(self.get_items)


class _IniBasedRulesSearcher(_RulesSearcher):

    def __init__(self, inifile):
        """Construct a _RulesSearcher based on an ini file.

        :param inifile: the name of the file or a sequence of lines.
        """
        self._cfg = configobj.ConfigObj(inifile)
        patterns = self._cfg.keys()
        if patterns:
            self._globster = globbing._OrderedGlobster(patterns)
        else:
            self._globster = None

    def get_items(self, path, names=None):
        """See _RulesSearcher.get_items."""
        if self._globster is None:
            return None
        pat = self._globster.match(path)
        if pat is None:
            return None
        else:
            all = self._cfg[pat]
            if names is None:
                return tuple(all.items())
            else:
                return tuple((k, all.get(k)) for k in names)


class _StackedRulesSearcher(_RulesSearcher):

    def __init__(self, searchers):
        """Construct a _RulesSearcher based on a stack of other ones.

        :param searchers: a sequence of searchers.
        """
        self.searchers = searchers

    def get_items(self, path, names=None):
        """See _RulesSearcher.get_items."""
        for searcher in self.searchers:
            result = searcher.get_items(path, names)
            if result is not None:
                return result
        return None


def rules_filename():
    """Return the default rules filename."""
    return osutils.pathjoin(config.config_dir(), 'bazaar.rules')


# The object providing default rules
_per_user_searcher = _IniBasedRulesSearcher(rules_filename())


# The cache of branch-specific rule searchers
_branch_searchers = {}


def iter_search_rules(branch, path_names, pref_names=None,
    _default_searcher=_per_user_searcher):
    """Find the preferences for filenames in a branch.

    :param branch: the branch, or None to only search the per user preferences
    :param path_names: an iterable of paths to find attributes for.
      Paths are given relative to the root of the tree.
    :param pref_names: the list of preferences to lookup - None for all
    :param _default_searcher: private parameter to assist testing - don't use
    :return: an iterator of tuple sequences, one per path-name.
      See _RulesSearcher.get_items for details on the tuple sequence.
    """
    # Get the searcher
    if branch is None:
        searcher = _default_searcher
    else:
        branch_searcher = _branch_searchers.get(branch)
        if branch_searcher is None:
            # Create and cache the branch searcher
            branch.lock_read()
            try:
                ini_file = branch.control_files.get('branch.rules')
            finally:
                branch.unlock()
            branch_searcher = _IniBasedRulesSearcher(ini_file)
            _branch_searchers[branch] = branch_searcher
        # If branch.rules is missing or empty, skip searching it
        if branch_searcher._globster is None:
            searcher = _default_searcher
        else:
            searcher = _StackedRulesSearcher(
                [branch_searcher, _default_searcher])

    # Do the searching
    for path in path_names:
        yield searcher.get_items(path, pref_names)
