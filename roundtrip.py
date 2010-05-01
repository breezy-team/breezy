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

    def __nonzero__(self):
        return bool(self.revision_id is None or self.file_ids or
                    self.properties)


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


def generate_roundtripping_metadata(metadata):
    """Serialize the roundtripping metadata.

    :param metadata: A `BzrGitRevisionMetadata` instance
    :return: String with revision metadata
    """
    return "revision-id: %s\n" % metadata.revision_id


def extract_bzr_metadata(message):
    """Extract Bazaar metadata from a commit message.

    :param message: Commit message to extract from
    :return: Tuple with original commit message and metadata object
    """
    split = message.split("\n--BZR--\n", 1)
    if len(split) != 2:
        return message, None
    return split[0], parse_roundtripping_metadata(split[1])


def inject_bzr_metadata(message, metadata):
    if not metadata:
        return message
    return message + "\n--BZR--\n" + generate_roundtripping_metadata(metadata)
