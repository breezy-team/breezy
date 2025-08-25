# Copyright (C) 2005-2012 Canonical Ltd
# Copyright (C) 2020 Breezy Developers
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

"""Tag storage implementation for Bazaar branches.

This module provides the BasicTags class which implements tag storage
in an unversioned branch control file, typically stored as .bzr/branch/tags.
Tags map human-readable names to revision identifiers.
"""

import contextlib

import fastbencode as bencode

from .. import errors, trace
from .. import transport as _mod_transport
from ..tag import Tags


class BasicTags(Tags):
    """Tag storage in an unversioned branch control file."""

    def set_tag(self, tag_name, tag_target):
        """Add a tag definition to the branch.

        Behaviour if the tag is already present is not defined (yet).
        """
        # all done with a write lock held, so this looks atomic
        with self.branch.lock_write():
            master = self.branch.get_master_branch()
            if master is not None:
                master.tags.set_tag(tag_name, tag_target)
            td = self.get_tag_dict()
            td[tag_name] = tag_target
            self._set_tag_dict(td)

    def lookup_tag(self, tag_name):
        """Return the referent string of a tag."""
        td = self.get_tag_dict()
        try:
            return td[tag_name]
        except KeyError as e:
            raise errors.NoSuchTag(tag_name) from e

    def get_tag_dict(self):
        """Return a dictionary of all tags in the branch.

        Returns:
            dict: A dictionary mapping tag names (str) to revision IDs (bytes).
                Returns an empty dictionary if no tags file exists.
        """
        with self.branch.lock_read():
            try:
                tag_content = self.branch._get_tags_bytes()
            except _mod_transport.NoSuchFile:
                # ugly, but only abentley should see this :)
                trace.warning(
                    f"No branch/tags file in {self.branch}.  "
                    "This branch was probably created by bzr 0.15pre.  "
                    "Create an empty file to silence this message."
                )
                return {}
            return self._deserialize_tag_dict(tag_content)

    def delete_tag(self, tag_name):
        """Delete a tag definition."""
        with self.branch.lock_write():
            d = self.get_tag_dict()
            try:
                del d[tag_name]
            except KeyError as e:
                raise errors.NoSuchTag(tag_name) from e
            master = self.branch.get_master_branch()
            if master is not None:
                with contextlib.suppress(errors.NoSuchTag):
                    master.tags.delete_tag(tag_name)
            self._set_tag_dict(d)

    def _set_tag_dict(self, new_dict):
        """Replace all tag definitions.

        WARNING: Calling this on an unlocked branch will lock it, and will
        replace the tags without warning on conflicts.

        :param new_dict: Dictionary from tag name to target.
        """
        return self.branch._set_tags_bytes(self._serialize_tag_dict(new_dict))

    def _serialize_tag_dict(self, tag_dict):
        td = {k.encode("utf-8"): v for k, v in tag_dict.items()}
        return bencode.bencode(td)

    def _deserialize_tag_dict(self, tag_content):
        """Convert the tag file into a dictionary of tags."""
        # was a special case to make initialization easy, an empty definition
        # is an empty dictionary
        if tag_content == b"":
            return {}
        try:
            r = {}
            for k, v in bencode.bdecode(tag_content).items():
                r[k.decode("utf-8")] = v
            return r
        except ValueError as e:
            raise ValueError(
                f"failed to deserialize tag dictionary {tag_content!r}: {e}"
            ) from e
