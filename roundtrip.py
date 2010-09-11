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
    :ivar explicit_parent_ids: Parent ids (needed if there are ghosts)
    :ivar verifiers: Verifier information
    """

    revision_id = None

    explicit_parent_ids = None

    verifiers = {}

    def __init__(self):
        self.properties = {}

    def __nonzero__(self):
        return bool(self.revision_id or self.properties)


def parse_roundtripping_metadata(text):
    """Parse Bazaar roundtripping metadata."""
    ret = BzrGitRevisionMetadata()
    f = StringIO(text)
    for l in f.readlines():
        (key, value) = l.split(":", 1)
        if key == "revision-id":
            ret.revision_id = value.strip()
        elif key == "parent-ids":
            ret.explicit_parent_ids = tuple(value.strip().split(" "))
        elif key == "testament3-sha1":
            ret.verifiers["testament3-sha1"] = value.strip()
        elif key.startswith("property-"):
            ret.properties[key[len("property-"):]] = value[1:].rstrip("\n")
        else:
            raise ValueError
    return ret


def generate_roundtripping_metadata(metadata, encoding):
    """Serialize the roundtripping metadata.

    :param metadata: A `BzrGitRevisionMetadata` instance
    :return: String with revision metadata
    """
    lines = []
    if metadata.revision_id:
        lines.append("revision-id: %s\n" % metadata.revision_id)
    if metadata.explicit_parent_ids:
        lines.append("parent-ids: %s\n" % " ".join(metadata.explicit_parent_ids))
    for key in sorted(metadata.properties.keys()):
        lines.append("property-%s: %s\n" % (key.encode(encoding), metadata.properties[key].encode(encoding)))
    if "testament3-sha1" in metadata.verifiers:
        lines.append("testament3-sha1: %s\n" %
                     metadata.verifiers["testament3-sha1"])
    return "".join(lines)


def extract_bzr_metadata(message):
    """Extract Bazaar metadata from a commit message.

    :param message: Commit message to extract from
    :return: Tuple with original commit message and metadata object
    """
    split = message.split("\n--BZR--\n", 1)
    if len(split) != 2:
        return message, None
    return split[0], parse_roundtripping_metadata(split[1])


def inject_bzr_metadata(message, metadata, encoding):
    if not metadata:
        return message
    rt_data = generate_roundtripping_metadata(metadata, encoding)
    if not rt_data:
        return message
    assert type(rt_data) == str
    return message + "\n--BZR--\n" + rt_data


def serialize_fileid_map(file_ids):
    """Serialize a file id map."""
    lines = []
    for path in sorted(file_ids.keys()):
        lines.append("%s\0%s\n" % (path, file_ids[path]))
    return lines


def deserialize_fileid_map(filetext):
    """Deserialize a file id map."""
    ret = {}
    f = StringIO(filetext)
    lines = f.readlines()
    for l in lines:
        (path, file_id) = l.rstrip("\n").split("\0")
        ret[path] = file_id
    return ret
