# Copyright (C) 2012 Jelmer Vernooij <jelmer@samba.org>
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


"""Support for pristine tar deltas."""

from base64 import (
    standard_b64decode,
    )


def revision_pristine_tar_data(rev):
    """Export the pristine tar data from a revision."""
    if 'deb-pristine-delta' in rev.properties:
        uuencoded = rev.properties['deb-pristine-delta']
    elif 'deb-pristine-delta-bz2' in rev.properties:
        uuencoded = rev.properties['deb-pristine-delta-bz2']
    elif 'deb-pristine-delta-xz' in rev.properties:
        uuencoded = rev.properties['deb-pristine-delta-xz']
    else:
        raise KeyError

    return standard_b64decode(uuencoded)
