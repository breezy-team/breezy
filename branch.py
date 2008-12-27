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

"""An adapter between a Git Branch and a Bazaar Branch"""

from bzrlib import (
    branch,
    config,
    revision,
    tag,
    )
from bzrlib.decorators import needs_read_lock

from bzrlib.plugins.git.foreign import ForeignBranch
from bzrlib.plugins.git.mapping import default_mapping

class GitTagDict(tag.BasicTags):

    def __init__(self, branch):
        self.branch = branch
        self.repository = branch.repository

    def get_tag_dict(self):
        ret = {}
        for tag in self.repository._git.tags:
            ret[tag.name] = self.branch.mapping.revision_id_foreign_to_bzr(tag.ref)
        return ret

    def set_tag(self, name, revid):
        raise NotImplementedError(self.set_tag)


class GitBranchConfig(config.BranchConfig):
    """BranchConfig that uses locations.conf in place of branch.conf"""

    def __init__(self, branch):
        config.BranchConfig.__init__(self, branch)
        # do not provide a BranchDataConfig
        self.option_sources = self.option_sources[0], self.option_sources[2]

    def set_user_option(self, name, value, local=False):
        """Force local to True"""
        config.BranchConfig.set_user_option(self, name, value, local=True)


class GitBranchFormat(branch.BranchFormat):

    def get_format_description(self):
        return 'Git Branch'

    def supports_tags(self):
        return True


class GitBranch(ForeignBranch):
    """An adapter to git repositories for bzr Branch objects."""

    def __init__(self, bzrdir, repository, name, head, lockfiles):
        self.repository = repository
        super(GitBranch, self).__init__(default_mapping)
        self.control_files = lockfiles
        self.bzrdir = bzrdir
        self.name = name
        self.head = head
        self.base = bzrdir.transport.base
        self._format = GitBranchFormat()

    def lock_write(self):
        self.control_files.lock_write()

    def get_stacked_on_url(self):
        # Git doesn't do stacking (yet...)
        return None

    def get_parent(self):
        """See Branch.get_parent()."""
        return None

    def lock_read(self):
        self.control_files.lock_read()

    def unlock(self):
        self.control_files.unlock()

    def get_physical_lock_status(self):
        return False

 
class LocalGitBranch(GitBranch):

    @needs_read_lock
    def last_revision(self):
        # perhaps should escape this ?
        if self.head is None:
            return revision.NULL_REVISION
        return self.mapping.revision_id_foreign_to_bzr(self.head)

    def _make_tags(self):
        return GitTagDict(self)

    def _gen_revision_history(self):
        if self.head is None:
            return []
        ret = list(self.repository.iter_reverse_revision_history(self.last_revision()))
        ret.reverse()
        return ret

    def get_config(self):
        return GitBranchConfig(self)

    def get_push_location(self):
        """See Branch.get_push_location."""
        push_loc = self.get_config().get_user_option('push_location')
        return push_loc

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self.get_config().set_user_option('push_location', location,
                                          local=True)

    def supports_tags(self):
        return True

    def sprout(self, to_bzrdir, revision_id=None):
        """See Branch.sprout()."""
        result = to_bzrdir.create_branch()
        self.copy_content_into(result, revision_id=revision_id)
        result.set_parent(self.bzrdir.root_transport.base)
        return result

