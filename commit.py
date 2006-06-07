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

import svn.ra
import svn.delta

from bzrlib.repository import CommitBuilder
from bzrlib.errors import UnsupportedOperation, BzrError

class SvnCommitBuilder(CommitBuilder):
    def __init__(self, repository, branch, parents, config, revprops):
        super(SvnCommitBuilder, self).__init__(repository, parents, 
            config, None, None, None, revprops, None)

    def _generate_revision_if_needed(self):
        pass

    @staticmethod
    def done(info, pool):
        if not info.post_commit_err is None:
            raise BzrError(info.post_commit_err)

        self.revnum = info.revnum

    def set_message(self, message):
        self.editor, self.editor_baton = svn.ra.get_commit_editor2(
            self.repository.ra, message, self.done, None, False)

    def finish_inventory(self):
        # Subversion doesn't have an inventory
        pass

    def record_entry_contents(self, ie, parent_invs, path, tree):
        # Subversion doesn't have an inventory
        pass

    def modified_file_text(self, file_id, file_parents,
                           get_content_byte_lines, text_sha1=None,
                           text_size=None):
        # FIXME
        pass

    def modified_link(self, file_id, file_parents, link_target):
        # FIXME
        pass

    def modified_directory(self, file_id, file_parents):
        # FIXME
        pass

    def commit(self):
        root = svn.delta.editor_invoke_open_root(self.editor, self.editor_baton, 4)

        svn.delta.editor_invoke_close_edit(self.editor, self.editor_baton)

        return self.repository.generate_revision_id(self.revnum, 
                                                    branch.branch_path)
