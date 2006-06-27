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
from svn.core import Pool

from bzrlib.errors import UnsupportedOperation, BzrError
from bzrlib.inventory import Inventory
import bzrlib.osutils as osutils
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
        self.pool = Pool()

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

        self.modified_files = {}
        self.modified_dirs = []
        
    def _generate_revision_if_needed(self):
        pass

    def finish_inventory(self):
        pass

    def _file_get_md5(self, file_id):
        contents = self.modified_files[file_id]
        import md5
        return md5.new(contents).hexdigest()

    def modified_file_text(self, file_id, file_parents,
                           get_content_byte_lines, text_sha1=None,
                           text_size=None):
        mutter('modifying file %s' % file_id)
        new_lines = get_content_byte_lines()
        self.modified_files[file_id] = "\n".join(new_lines)
        return osutils.sha_strings(new_lines), sum(map(len, new_lines))


    def modified_link(self, file_id, file_parents, link_target):
        mutter('modifying link %s' % file_id)
        self.modified_files[file_id] = "link %s" % link_target

    def modified_directory(self, file_id, file_parents):
        mutter('modifying directory %s' % file_id)
        self.modified_dirs.append(file_id)

    def _file_process(self, file_id, contents, baton):
        (txdelta, txbaton) = svn.delta.editor_invoke_apply_textdelta(
                                self.editor, baton, 
                                self._file_get_md5(file_id), self.pool)

        svn.delta.svn_txdelta_send_string(contents, txdelta, txbaton, self.pool)

    def _dir_process(self, path, file_id, baton):
        mutter('committing changes in %r' % path)

        # Loop over entries of file_id in self.old_inv
        # remove if they no longer exist at the same path
        if file_id in self.old_inv:
            for child_id in self.old_inv[file_id].children:
                if (not child_id in self.new_inventory or 
                    self.new_inventory.id2path(child_id) != \
                            self.old_inv.id2path(path)):
                       mutter('removing %r' % child_id)
                       svn.delta.editor_invoke_delete_entry(self.editor, 
                               self.old_inv[child_id].name, 0, baton, 
                               self.pool)

        # Loop over file members of file_id in self.new_inventory
        for child_id in self.new_inventory[file_id].children:
            if (self.new_inventory[child_id].kind != 'file' and 
                self.new_inventory[child_id].kind != 'symlink'):
                continue

            # add them if they didn't exist in old_inv 
            if not child_id in self.old_inv:
                mutter('adding file %r' % self.new_inventory.id2path(child_id))

                child_baton = svn.delta.editor_invoke_add_file(self.editor, 
                           self.new_inventory.id2path(child_id), baton, None, 0, 
                           self.pool)


            # copy if they existed at different location
            elif self.old_inv.id2path(child_id) != path:
                mutter('copy file %r -> %r' % (self.old_inv.id2path(child_id), path))

                child_baton = svn.delta.editor_invoke_add_file(self.editor, 
                           self.new_inventory.id2path(child_id), baton, 
                           self.old_inv.id2path(child_id), self.base_revnum, 
                           self.pool)

            # open if they existed at the same location
            else:
                mutter('open file %r' % path)

                child_baton = svn.delta.editor_invoke_open_file(self.editor,
                        self.new_inventory[child_id].name, baton,
                        self.pool)

            # handle the file
            if child_id in self.modified_files:
                self._file_process(child_id, self.modified_files[child_id], 
                                   child_baton)

            svn.delta.editor_invoke_close_file(self.editor, child_baton, 
                                        self._file_get_md5(child_id), 
                                        self.pool)

        # Loop over subdirectories of file_id in self.new_inventory
        for child_id in self.new_inventory[file_id].children:
            if self.new_inventory[child_id].kind != 'directory':
                continue

            # add them if they didn't exist in old_inv 
            if not child_id in self.old_inv:
                mutter('adding dir %r' % self.new_inventory[child_id].name)
                child_baton = svn.delta.editor_invoke_add_directory(
                           self.editor, self.new_inventory[child_id].name, 
                           baton, None, 0, self.pool)

            # copy if they existed at different location
            elif self.old_inv.id2path(child_id) != self.new_inventory.id2path(child_id):
                mutter('copy dir %r -> %r' % (self.old_inv.id2path(child_id), 
                                         self.new_inventory.id2path(child_id)))
                child_baton = svn.delta.editor_invoke_add_directory(
                           self.editor, self.new_inventory[child_id].name, 
                           baton, self.old_inv.id2path(child_id), 
                           self.base_revnum, self.pool)

            # open if they existed at the same location
            else:
                mutter('open dir %r' % self.new_inventory.id2path(child_id))

                child_baton = svn.delta.editor_invoke_open_directory(
                        self.editor, self.new_inventory[child_id].name, baton, 
                        0, self.pool)

            # Handle this directory
            if child_id in self.modified_dirs:
                self._dir_process(self.new_inventory.id2path(child_id), 
                        child_id, child_baton)

            svn.delta.editor_invoke_close_directory(self.editor, child_baton, 
                                             self.pool)

    def commit(self, message):
        def done(info, pool):
            if not info.post_commit_err is None:
                raise BzrError(info.post_commit_err)

            self.revnum = info.revision

        mutter('obtaining commit editor')
        self.editor, editor_baton = svn.ra.get_commit_editor2(
            self.repository.ra, message, done, None, False)

        if self.branch.last_revision() is None:
            self.base_revnum = 0
        else:
            self.base_revnum = self.repository.parse_revision_id(
                          self.branch.last_revision())[1]

        root = svn.delta.editor_invoke_open_root(self.editor, editor_baton, 
                                                 self.base_revnum)

        self._dir_process("", self.new_inventory.path2id(""), root)

        svn.delta.editor_invoke_close_edit(self.editor, editor_baton)

        self._revprops['bzr:parents'] = "\n".join(self.parents)

        # FIXME: Set revision properties on new revision

        revid = self.repository.generate_revision_id(self.revnum, 
                                                    self.branch.branch_path)

        self.branch._revision_history.append(revid)

        return revid
