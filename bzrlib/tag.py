# Copyright (C) 2007 Canonical Ltd
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


# NOTE: Don't try to call this 'tags.py', vim seems to get confused about
# whether it's a tag or source file.


from bzrlib import (
    errors,
    )


######################################################################
# tag storage


class _TagStore(object):
    def __init__(self, repository):
        self.repository = repository

class DisabledTagStore(_TagStore):
    """Tag storage that refuses to store anything.

    This is used by older formats that can't store tags.
    """

    def _not_supported(self, *a, **k):
        raise errors.TagsNotSupported(self.repository)

    def supports_tags(self):
        return False

    set_tag = _not_supported
    get_tag_dict = _not_supported
    _set_tag_dict = _not_supported
    lookup_tag = _not_supported


class BasicTagStore(_TagStore):
    """Tag storage in an unversioned repository control file.
    """

    def supports_tags(self):
        return True

    def set_tag(self, tag_name, tag_target):
        """Add a tag definition to the repository.

        Behaviour if the tag is already present is not defined (yet).
        """
        # all done with a write lock held, so this looks atomic
        self.repository.lock_write()
        try:
            td = self.get_tag_dict()
            td[tag_name] = tag_target
            self._set_tag_dict(td)
        finally:
            self.repository.unlock()

    def lookup_tag(self, tag_name):
        """Return the referent string of a tag"""
        td = self.get_tag_dict()
        try:
            return td[tag_name]
        except KeyError:
            raise errors.NoSuchTag(tag_name)

    def get_tag_dict(self):
        self.repository.lock_read()
        try:
            tag_content = self.repository.control_files.get_utf8('tags').read()
            return self._deserialize_tag_dict(tag_content)
        finally:
            self.repository.unlock()

    def _set_tag_dict(self, new_dict):
        """Replace all tag definitions

        :param new_dict: Dictionary from tag name to target.
        """
        self.repository.lock_read()
        try:
            self.repository.control_files.put_utf8('tags',
                self._serialize_tag_dict(new_dict))
        finally:
            self.repository.unlock()

    def _serialize_tag_dict(self, tag_dict):
        s = []
        for tag, target in sorted(tag_dict.items()):
            # TODO: check that tag names and targets are acceptable
            s.append(tag + '\t' + target + '\n')
        return ''.join(s)

    def _deserialize_tag_dict(self, tag_content):
        """Convert the tag file into a dictionary of tags"""
        d = {}
        for l in tag_content.splitlines():
            tag, target = l.split('\t', 1)
            d[tag] = target
        return d


