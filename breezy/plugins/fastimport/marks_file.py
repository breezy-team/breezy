# Copyright (C) 2009 Canonical Ltd
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

"""Routines for reading/writing a marks file."""

from __future__ import absolute_import

from ...trace import warning


def import_marks(filename):
    """Read the mapping of marks to revision-ids from a file.

    :param filename: the file to read from
    :return: None if an error is encountered or a dictionary with marks
        as keys and revision-ids as values
    """
    # Check that the file is readable and in the right format
    try:
        f = open(filename, 'r')
    except IOError:
        warning("Could not import marks file %s - not importing marks",
                filename)
        return None

    try:
        # Read the revision info
        revision_ids = {}

        line = f.readline()
        if line == 'format=1\n':
            # Cope with old-style marks files
            # Read the branch info
            branch_names = {}
            for string in f.readline().rstrip('\n').split('\0'):
                if not string:
                    continue
                name, integer = string.rsplit('.', 1)
                branch_names[name] = int(integer)
            line = f.readline()

        while line:
            line = line.rstrip('\n')
            mark, revid = line.split(' ', 1)
            mark = mark.lstrip(':')
            revision_ids[mark] = revid.encode('utf-8')
            line = f.readline()
    finally:
        f.close()
    return revision_ids


def export_marks(filename, revision_ids):
    """Save marks to a file.

    :param filename: filename to save data to
    :param revision_ids: dictionary mapping marks -> bzr revision-ids
    """
    try:
        f = open(filename, 'w')
    except IOError:
        warning("Could not open export-marks file %s - not exporting marks",
                filename)
        return

    try:
        # Write the revision info
        for mark in revision_ids:
            f.write(':%s %s\n' % (mark.lstrip(b':').decode('utf-8'),
                                  revision_ids[mark].decode('utf-8')))
    finally:
        f.close()
