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


from warnings import warn

from bzrlib import (
    errors,
    trace,
    )
from bzrlib.util import bencode


class _Tags(object):

    def __init__(self, branch):
        self.branch = branch

    def has_tag(self, tag_name):
        return self.get_tag_dict().has_key(tag_name)


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
    delete_tag = _not_supported

    def merge_to(self, to_tags):
        # we never have anything to copy
        pass


class BasicTags(_Tags):
    """Tag storage in an unversioned branch control file.
    """

    def supports_tags(self):
        return True

    def set_tag(self, tag_name, tag_target):
        """Add a tag definition to the branch.

        Behaviour if the tag is already present is not defined (yet).
        """
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
        td = self.get_tag_dict()
        try:
            return td[tag_name]
        except KeyError:
            raise errors.NoSuchTag(tag_name)

    def get_tag_dict(self):
        self.branch.lock_read()
        try:
            try:
                tag_content = self.branch._transport.get_bytes('tags')
            except errors.NoSuchFile, e:
                # ugly, but only abentley should see this :)
                trace.warning('No branch/tags file in %s.  '
                     'This branch was probably created by bzr 0.15pre.  '
                     'Create an empty file to silence this message.'
                     % (self.branch, ))
                return {}
            return self._deserialize_tag_dict(tag_content)
        finally:
            self.branch.unlock()
            
            
    def get_reverse_tag_dict(self):
        """Returns a dict with revisions as keys
           and a list of tags for that revision as value"""
        d = self.get_tag_dict()
        rev = {}
        for key in d:
            try:
                rev[d[key]].append(key)
            except KeyError:
                rev[d[key]] = [key]
        return rev


    def delete_tag(self, tag_name):
        """Delete a tag definition.
        """
        self.branch.lock_write()
        try:
            d = self.get_tag_dict()
            try:
                del d[tag_name]
            except KeyError:
                raise errors.NoSuchTag(tag_name)
            self._set_tag_dict(d)
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
        td = dict((k.encode('utf-8'), v)
                for k,v in tag_dict.items())
        return bencode.bencode(td)

    def _deserialize_tag_dict(self, tag_content):
        """Convert the tag file into a dictionary of tags"""
        # was a special case to make initialization easy, an empty definition
        # is an empty dictionary
        if tag_content == '':
            return {}
        try:
            r = {}
            for k, v in bencode.bdecode(tag_content).items():
                r[k.decode('utf-8')] = v
            return r
        except ValueError, e:
            raise ValueError("failed to deserialize tag dictionary %r: %s"
                % (tag_content, e))

    def merge_to(self, to_tags):
        """Copy tags between repositories if necessary and possible.
        
        This method has common command-line behaviour about handling 
        error cases.

        All new definitions are copied across, except that tags that already
        exist keep their existing definitions.

        :param to_tags: Branch to receive these tags
        :param just_warn: If the destination doesn't support tags and the 
            source does have tags, just give a warning.  Otherwise, raise
            TagsNotSupported (default).

        :returns: A list of tags that conflicted, each of which is 
            (tagname, source_target, dest_target).
        """
        if self.branch == to_tags.branch:
            return
        if not self.supports_tags():
            # obviously nothing to copy
            return
        source_dict = self.get_tag_dict()
        if not source_dict:
            # no tags in the source, and we don't want to clobber anything
            # that's in the destination
            return
        to_tags.branch.lock_write()
        try:
            dest_dict = to_tags.get_tag_dict()
            result, conflicts = self._reconcile_tags(source_dict, dest_dict)
            if result != dest_dict:
                to_tags._set_tag_dict(result)
        finally:
            to_tags.branch.unlock()
        return conflicts

    def _reconcile_tags(self, source_dict, dest_dict):
        """Do a two-way merge of two tag dictionaries.

        only in source => source value
        only in destination => destination value
        same definitions => that
        different definitions => keep destination value, give a warning

        :returns: (result_dict,
            [(conflicting_tag, source_target, dest_target)])
        """
        conflicts = []
        result = dict(dest_dict) # copy
        for name, target in source_dict.items():
            if name not in result:
                result[name] = target
            elif result[name] == target:
                pass
            else:
                conflicts.append((name, target, result[name]))
        return result, conflicts


def _merge_tags_if_possible(from_branch, to_branch):
    from_branch.tags.merge_to(to_branch.tags)
