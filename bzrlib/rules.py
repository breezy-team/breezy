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

Rules are defined in ini file format where the sections are file glob
patterns and the contents of each section are the preferences for files
matching that pattern. For example::

    [*.txt]
    text = True

    [*.pdf]
    text = False

Patterns use the same conventions as used for ignores, namely:

 * *.xyz match any file ending in .xyz
 * foo/ matches all files in foo directories
 * to specify the top level, start a pattern with ./

Patterns are ordered and searching stops as soon as one matches.
As a consequence, more explicit patterns should be placed towards
the top of the file.

Default rules for all branches are defined in ``BZR_HOME/bazaar.rules``.
Branch-specific rules are defined in ``branch.rules``.
If a rule is matched in the branch level file, searching stops.
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
        self._globster = globbing._OrderedGlobster(patterns)

    def get_items(self, path, names=None):
        """See _RulesSearcher.get_items."""
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
        for searcher in searchers:
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


def iter_search_rules(branch, path_names, pref_names=None):
    """Find the preferences for filenames in a branch.

    :param branch: the branch, or None to only search the per user preferences
    :param path_names: an iterable of paths to find attributes for.
      Paths are given relative to the root of the tree.
    :param pref_names: the list of preferences to lookup - None for all
    :return: an iterator of tuple sequences, one per path-name.
      See _RulesSearcher.get_items for details on the tuple sequence.
    """
    # Get the searcher
    if branch is None:
        searcher = _per_user_searcher
    else:
        branch_searcher = _branch_searchers.get(branch)
        if branch_searcher is None:
            # Create and cache the branch searcher
            transport = branch.control_files._transport
            branch_inifile = TransportConfig(transport, 'branch.rules')
            branch_searcher = _IniBasedRulesSearcher(branch_inifile)
            _branch_searchers[branch] = branch_searcher
        searcher = _StackedRulesSearcher([branch_searcher, _per_user_searcher])

    # Do the searching
    for path in path_names:
        yield searcher.get_items(path, pref_names)
