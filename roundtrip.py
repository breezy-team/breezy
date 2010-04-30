# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
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

"""Roundtripping support."""


from cStringIO import StringIO


class BzrGitRevisionMetadata(object):
    """Metadata for a Bazaar revision roundtripped into Git.
    
    :ivar revision_id: Revision id, as string
    :ivar properties: Revision properties, as dictionary
    :ivar file_ids: File ids, as map from path -> file id
    """

    revision_id = None

    file_ids = {}

    properties = {}


def parse_roundtripping_metadata(text):
    """Parse Bazaar roundtripping metadata."""
    ret = BzrGitRevisionMetadata()
    f = StringIO(text)
    for l in f.readlines():
        (key, value) = l.split(":", 1)
        if key == "revision-id":
            ret.revision_id = value.strip()
        else:
            raise ValueError
    return ret
