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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Routines for saving and loading the id-map file."""

import os


def save_id_map(filename, revision_ids):
    """Save the mapping of commit ids to revision ids to a file.

    Throws the usual exceptions if the file cannot be opened,
    written to or closed.

    :param filename: name of the file to save the data to
    :param revision_ids: a dictionary of commit ids to revision ids.
    """
    with open(filename, 'wb') as f:
        for commit_id in revision_ids:
            f.write(b"%s %s\n" % (commit_id, revision_ids[commit_id]))


def load_id_map(filename):
    """Load the mapping of commit ids to revision ids from a file.

    If the file does not exist, an empty result is returned.
    If the file does exists but cannot be opened, read or closed,
    the normal exceptions are thrown.

    NOTE: It is assumed that commit-ids do not have embedded spaces.

    :param filename: name of the file to save the data to
    :result: map, count where:
      map = a dictionary of commit ids to revision ids;
      count = the number of keys in map
    """
    result = {}
    count = 0
    if os.path.exists(filename):
        with open(filename) as f:
            for line in f:
                parts = line[:-1].split(' ', 1)
                result[parts[0]] = parts[1]
                count += 1
    return result, count
