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

"""Tag strategies.

These are contained within a branch and normally constructed 
when the branch is opened.  Clients should typically do 

  Branch.tags.add('name', 'value')
"""

# NOTE: I was going to call this tags.py, but vim seems to think all files
# called tags* are ctags files... mbp 20070220.


from bzrlib import (
    errors,
    )
from bzrlib.util import bencode


class _Tags(object):
    def __init__(self, branch):
        self.branch = branch


class DisabledTags(_Tags):
    """Tag storage that refuses to store anything.

    This is used by older formats that can't store tags.
    """

    def _not_supported(self, *a, **k):
        raise errors.TagsNotSupported(self.branch)

    def supports_tags(self):
        return False

    set_tag = _not_supported
    get_tag_dict = _not_supported
    _set_tag_dict = _not_supported
    lookup_tag = _not_supported


class BasicTags(_Tags):
    """Tag storage in an unversioned branch control file.
    """

    def supports_tags(self):
        return True

    def set_tag(self, tag_name, tag_target):
        """Add a tag definition to the branch.

        Behaviour if the tag is already present is not defined (yet).
        """
        if isinstance(tag_name, unicode):
            tag_name = tag_name.encode('utf-8')
        # all done with a write lock held, so this looks atomic
        self.branch.lock_write()
        try:
            td = self.get_tag_dict()
            td[tag_name] = tag_target
            self._set_tag_dict(td)
        finally:
            self.branch.unlock()

    def lookup_tag(self, tag_name):
        """Return the referent string of a tag"""
        if isinstance(tag_name, unicode):
            tag_name = tag_name.encode('utf-8')
        td = self.get_tag_dict()
        try:
            return td[tag_name]
        except KeyError:
            raise errors.NoSuchTag(tag_name)

    def get_tag_dict(self):
        self.branch.lock_read()
        try:
            tag_content = self.branch._transport.get_bytes('tags')
            return self._deserialize_tag_dict(tag_content)
        finally:
            self.branch.unlock()

    def _set_tag_dict(self, new_dict):
        """Replace all tag definitions

        :param new_dict: Dictionary from tag name to target.
        """
        self.branch.lock_read()
        try:
            self.branch._transport.put_bytes('tags',
                self._serialize_tag_dict(new_dict))
        finally:
            self.branch.unlock()

    def _serialize_tag_dict(self, tag_dict):
        return bencode.bencode(tag_dict)

    def _deserialize_tag_dict(self, tag_content):
        """Convert the tag file into a dictionary of tags"""
        # as a special case to make initialization easy, an empty definition
        # is an empty dictionary
        if tag_content == '':
            return {}
        try:
            return bencode.bdecode(tag_content)
        except ValueError:
            raise ValueError("failed to deserialize tag dictionary %r" % tag_content)
