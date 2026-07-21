# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Roundtripping support.

Bazaar stores more data than Git, which means that in order to preserve
a commit when it is pushed from Bazaar into Git we have to stash
that extra metadata somewhere.

There are two kinds of metadata relevant here:
 * per-file metadata (stored by revision+path)
  - usually stored per tree
 * per-revision metadata (stored by git commit id)

Bazaar revisions have the following information that is not
present in Git commits:
 * revision ids
 * revision properties
 * ghost parents

Tree content:
 * empty directories
 * path file ids
 * path last changed revisions [1]

 [1] path last changed revision information can usually
     be induced from the existing history, unless
     ghost revisions are involved.

This extra metadata is stored in so-called "supplements":
  * CommitSupplement
  * TreeSupplement
"""

from typing import Any

from .._git_rs import (
    generate_roundtripping_metadata as _generate_roundtripping_metadata,
)
from .._git_rs import (
    parse_roundtripping_metadata as _parse_roundtripping_metadata,
)


class CommitSupplement:
    """Supplement for a Bazaar revision roundtripped into Git.

    :ivar revision_id: Revision id, as string
    :ivar properties: Revision properties, as dictionary
    :ivar explicit_parent_ids: Parent ids (needed if there are ghosts)
    :ivar verifiers: Verifier information
    """

    revision_id = None

    explicit_parent_ids = None

    def __init__(self) -> None:
        """Initialize a new CommitSupplement."""
        self.properties: dict[str, bytes] = {}
        self.verifiers: dict[str, Any] = {}

    def __nonzero__(self) -> bool:
        """Check if this supplement contains any data.

        Returns:
            bool: True if any supplemental data is present, False otherwise.
        """
        return bool(self.revision_id or self.properties or self.explicit_parent_ids)


class TreeSupplement:
    """Supplement for a Bazaar tree roundtripped into Git.

    This provides file ids (if they are different from the mapping default)
    and can provide text revisions.
    """


def parse_roundtripping_metadata(text):
    """Parse Bazaar roundtripping metadata."""
    revision_id, parent_ids, properties, testament3_sha1 = (
        _parse_roundtripping_metadata(text)
    )
    ret = CommitSupplement()
    ret.revision_id = revision_id
    if parent_ids is not None:
        ret.explicit_parent_ids = tuple(parent_ids)
    ret.properties = dict(properties)
    if testament3_sha1 is not None:
        ret.verifiers[b"testament3-sha1"] = testament3_sha1
    return ret


def generate_roundtripping_metadata(metadata, encoding):
    """Serialize the roundtripping metadata.

    :param metadata: A `CommitSupplement` instance
    :return: String with revision metadata
    """
    return _generate_roundtripping_metadata(
        metadata.revision_id,
        metadata.explicit_parent_ids,
        list(metadata.properties.items()),
        metadata.verifiers.get(b"testament3-sha1"),
    )


def extract_bzr_metadata(message):
    """Extract Bazaar metadata from a commit message.

    :param message: Commit message to extract from
    :return: tuple with original commit message and metadata object
    """
    split = message.split(b"\n--BZR--\n", 1)
    if len(split) != 2:
        return message, None
    return split[0], parse_roundtripping_metadata(split[1])


def inject_bzr_metadata(message, commit_supplement, encoding):
    """Inject Bazaar metadata into a commit message.

    Args:
        message: The original commit message.
        commit_supplement: CommitSupplement object containing metadata to inject.
        encoding: Character encoding to use.

    Returns:
        bytes: The commit message with injected metadata.

    Raises:
        TypeError: If roundtrip data is not bytes.
    """
    if not commit_supplement:
        return message
    rt_data = generate_roundtripping_metadata(commit_supplement, encoding)
    if not rt_data:
        return message
    if not isinstance(rt_data, bytes):
        raise TypeError(rt_data)
    return message + b"\n--BZR--\n" + rt_data
