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

"""Attributes to associate with files based on file glob patterns.

Patterns and the attributes for each are defined in ini file format in
BZR_HOME/attributes. For example::

    [*.txt]
    text = True

    [*.pdf]
    text = False

Patterns use the same conventions as BZR_HOME/ignore, namely:

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


class _AttributesProvider(object):
    """An object that provides attributes for a file."""

    def get_attributes(self, path, names=None):
        """Return the dictionary of attributes for a path.

        :param path: tree relative path
        :param names: the list of attributes to lookup - None for all
        :return: a dictionary where:
          the keys are the requested attribute names and
          the values are the attribute values or None if undefined
        """
        raise NotImplementedError(self.get_attributes)


class _FileBasedAttributesProvider(_AttributesProvider):

    def __init__(self, filename):
        """Create a provider of attributes.

        :param filename: the ini file holding the patterns and the
          attributes that apply to each.
        """
        self._cfg = configobj.ConfigObj(filename)
        patterns = self._cfg.keys()
        self._globster = globbing._OrderedGlobster(patterns)

    def get_attributes(self, path, names=None):
        """See _AttributesProvider.get_attributes."""
        pat = self._globster.match(path)
        if pat is None:
            all = {}
        else:
            all = self._cfg[pat]
        if names is None:
            return all
        else:
            return dict((k, all.get(k)) for k in names)


def attributes_filename():
    """Return per-user attributes file filename."""
    return osutils.pathjoin(config.config_dir(), 'attributes')


# The object providing per-user attributes
_user_attributes_provider = _FileBasedAttributesProvider(attributes_filename())
