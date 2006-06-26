# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import svn.delta
import svn.ra

from bzrlib.errors import UnsupportedOperation, BzrError
from bzrlib.inventory import Inventory
from bzrlib.repository import CommitBuilder
from bzrlib.trace import mutter

from branch import SvnBranch
from repository import SvnRepository

class SvnCommitBuilder(CommitBuilder):
    """Commit Builder implementation wrapped around svn_delta_editor. """
    def __init__(self, repository, branch, parents, config, revprops):
        """Instantiate a new SvnCommitBuilder.

        :param repository: SvnRepository to commit to.
        :param branch: SvnBranch to commit to.
        :param parents: List of parent revision ids.
        :param config: Branch configuration to use.
        :param revprops: Revision properties to set.
        """
        super(SvnCommitBuilder, self).__init__(repository, parents, 
            config, None, None, None, revprops, None)
        assert isinstance(repository, SvnRepository)
        assert isinstance(branch, SvnBranch)
        self.branch = branch

        # TODO: Allow revision id to be specified, but only if it 
        # matches the format for Subversion revision ids, the UUID
        # matches and the revnum is in the future. Set the 
        # revision num on the delta editor using set_target_revision

        # At least one of the parents has to be the last revision on the 
        # mainline in # Subversion.
        assert len(parents) == 0 or self.branch.last_revision() in parents

        if self.branch.last_revision() is None:
            self.old_inv = Inventory()
        else:
            self.old_inv = self.repository.get_inventory(
                               self.branch.last_revision())
        
        # Fill with paths from self.old_inv
        self.missing_entries = map(lambda (x,_): x, self.old_inv.entries())
        self.added_entries = {}
        self.removed_entries = []
        self.modified_entries = []
        self.modified_dirs = []
        self.modified_links = []

    def _generate_revision_if_needed(self):
        pass

    def _add_file(self, path, copyfrom=None):
        assert not self.added_entries.has_key(path)
        self.added_entries[path] = copyfrom

    def _delete_file(self, path):
        self.removed_entries.append(path)

    def finish_inventory(self):
        # Delete missing
        for path in self.missing_entries:
            self._delete_file(path)

    def record_entry_contents(self, ie, parent_invs, new_path, tree):
        mutter('recording path %s' % new_path)
        self.new_inventory.add(ie)
        
        # File was added in this revision
        if not ie.file_id in self.old_inv:
            self._add_file(new_path)

        # Nothing changed on inventory level
        elif self.old_inv.id2path(ie.file_id) == new_path:
            self.missing_entries.remove(new_path)
        
        # File was renamed
        else:
            old_path = self.old_inv.id2path(ie.file_id)
            self._add_file(new_path, old_path)
            self._delete_file(old_path)

    def modified_file_text(self, file_id, file_parents,
                           get_content_byte_lines, text_sha1=None,
                           text_size=None):
        mutter('modifying file %s' % file_id)
        self.modified_entries.append(self.old_inv.id2path(file_id))

    def modified_link(self, file_id, file_parents, link_target):
        mutter('modifying link %s' % file_id)
        self.modified_links.append(self.old_inv.id2path(file_id))

    def modified_directory(self, file_id, file_parents):
        mutter('modifying directory %s' % file_id)
        self.modified_dirs.append(self.old_inv.id2path(file_id))

    def commit(self, message):
        def done(info, pool):
            if not info.post_commit_err is None:
                raise BzrError(info.post_commit_err)

            self.revnum = info.revision

        mutter('obtaining commit editor')
        editor, editor_baton = svn.ra.get_commit_editor2(
            self.repository.ra, message, done, None, False)

        root = svn.delta.editor_invoke_open_root(editor, editor_baton, 4)

        # FIXME: Report status

        svn.delta.editor_invoke_close_edit(editor, editor_baton)

        self._revprops['bzr:parents'] = "\n".join(self.parents)

        # FIXME: Set revision properties on new revision

        # Throw away the cache of revision ids
        self.branch._generate_revision_history()

        return self.repository.generate_revision_id(self.revnum, 
                                                    self.branch.branch_path)
