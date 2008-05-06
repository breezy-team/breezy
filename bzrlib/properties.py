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

"""Properties to associate with files based on file glob patterns.

Patterns and the properties for each are defined in ini file format in
BZR_HOME/.bzrproperties. For example::

    [*.txt]
    text = True

    [*.pdf]
    text = False

Patterns use the same conventions as .bzrignore, namely:

 * *.xyz match any file ending in .xyz
 * foo/ matches all files in foo directories
 * to specify the top level, start a pattern with ./

Patterns are ordered and searching stops as soon as one matches.
As a consequence, more explicit patterns should be placed towards
the top of the file.
"""

from bzrlib import (
    config,
    globbing,
    osutils,
    )
from bzrlib.util.configobj import configobj


class _PropertiesProvider(object):
    """An object that provides properties for a file."""

    def __init__(self, filename):
        """Create a provider of properties.

        :param filename: the ini file holding the patterns and the
          properties that apply to each.
        """
        self._cfg = configobj.ConfigObj(filename)
        patterns = self._cfg.keys()
        self._globster = globbing._OrderedGlobster(patterns)

    def get_properties(self, path):
        """Return the dictionary of properties for a path.

        :param path: tree relative path
        :return: the properties or {} if none
        """
        pat = self._globster.match(path)
        if pat is None:
            return {}
        else:
            return self._cfg[pat]


def properties_filename():
    """Return per-user properties file filename."""
    return osutils.pathjoin(config.config_dir(), '.bzrproperties')


# The object providing per-user properties
_user_properties_provider = _PropertiesProvider(properties_filename())
