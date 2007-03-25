# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

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
from svn.core import Pool, SubversionException

from bzrlib.errors import (UnsupportedOperation, BzrError, InvalidRevisionId, 
                           DivergedBranches)
from bzrlib.inventory import Inventory
import bzrlib.osutils as osutils
from bzrlib.repository import RootCommitBuilder
from bzrlib.trace import mutter

from repository import (SvnRepository, SVN_PROP_BZR_MERGE, SVN_PROP_BZR_FILEIDS,
                        SVN_PROP_SVK_MERGE, SVN_PROP_BZR_REVPROP_PREFIX, 
                        revision_id_to_svk_feature, escape_svn_path)

import os

class SvnCommitBuilder(RootCommitBuilder):
    """Commit Builder implementation wrapped around svn_delta_editor. """

    def __init__(self, repository, branch, parents, config, revprops, 
                 old_inv=None):
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
        self.branch = branch
        self.pool = Pool()

        self._svnprops = {}
        for prop in self._revprops:
            self._svnprops[SVN_PROP_BZR_REVPROP_PREFIX+prop] = self._revprops[prop]

        self.merges = filter(lambda x: x != self.branch.last_revision(),
                             parents)

        if len(self.merges) > 0:
            # Bazaar Parents
            if branch.last_revision():
                (bp, revnum) = repository.parse_revision_id(branch.last_revision())
                old = repository.branchprop_list.get_property(bp, revnum, SVN_PROP_BZR_MERGE, "")
            else:
                old = ""
            self._svnprops[SVN_PROP_BZR_MERGE] = old + "\t".join(self.merges) + "\n"

            if branch.last_revision() is not None:
                old = repository.branchprop_list.get_property(bp, revnum, SVN_PROP_SVK_MERGE)
            else:
                old = ""

            new = ""
            # SVK compatibility
            for p in self.merges:
                try:
                    new += "%s\n" % revision_id_to_svk_feature(p)
                except InvalidRevisionId:
                    pass

            if new != "":
                self._svnprops[SVN_PROP_SVK_MERGE] = old + new

        # At least one of the parents has to be the last revision on the 
        # mainline in # Subversion.
        assert (self.branch.last_revision() is None or 
                self.branch.last_revision() in parents)

        if old_inv is None:
            if self.branch.last_revision() is None:
                self.old_inv = Inventory(root_id=None)
            else:
                self.old_inv = self.repository.get_inventory(
                                   self.branch.last_revision())
        else:
            self.old_inv = old_inv
            assert self.old_inv.revision_id == self.branch.last_revision()

        self.modified_files = {}
        self.modified_dirs = []
        
    def _generate_revision_if_needed(self):
        pass

    def finish_inventory(self):
        pass

    def modified_file_text(self, file_id, file_parents,
                           get_content_byte_lines, text_sha1=None,
                           text_size=None):
        mutter('modifying file %s' % file_id)
        new_lines = get_content_byte_lines()
        self.modified_files[file_id] = "".join(new_lines)
        return osutils.sha_strings(new_lines), sum(map(len, new_lines))

    def modified_link(self, file_id, file_parents, link_target):
        mutter('modifying link %s' % file_id)
        self.modified_files[file_id] = "link %s" % link_target

    def modified_directory(self, file_id, file_parents):
        mutter('modifying directory %s' % file_id)
        self.modified_dirs.append(file_id)

    def _file_process(self, file_id, contents, baton):
        (txdelta, txbaton) = svn.delta.editor_invoke_apply_textdelta(
                                self.editor, baton, None, self.pool)

        svn.delta.svn_txdelta_send_string(contents, txdelta, txbaton, self.pool)

    def _dir_process(self, path, file_id, baton):
        mutter('processing %r' % path)
        if path == "":
            # Set all the revprops
            for prop, value in self._svnprops.items():
                mutter('setting %r: %r on branch' % (prop, value))
                if value is not None:
                    value = value.encode('utf-8')
                svn.delta.editor_invoke_change_dir_prop(self.editor, baton,
                            prop, value, self.pool)

        # Loop over entries of file_id in self.old_inv
        # remove if they no longer exist with the same name
        # or parents
        if file_id in self.old_inv:
            for child_name in self.old_inv[file_id].children:
                child_ie = self.old_inv.get_child(file_id, child_name)
                # remove if...
                #  ... path no longer exists
                if (not child_ie.file_id in self.new_inventory or 
                    # ... parent changed
                    child_ie.parent_id != self.new_inventory[child_ie.file_id].parent_id or
                    # ... name changed
                    self.new_inventory[child_ie.file_id].name != child_name):
                    mutter('removing %r' % child_ie.file_id)
                    svn.delta.editor_invoke_delete_entry(self.editor, 
                            os.path.join(self.branch.branch_path, self.old_inv.id2path(child_ie.file_id)), 
                            self.base_revnum, baton, self.pool)

        # Loop over file members of file_id in self.new_inventory
        for child_name in self.new_inventory[file_id].children:
            child_ie = self.new_inventory.get_child(file_id, child_name)
            assert child_ie is not None

            if not (child_ie.kind in ('file', 'symlink')):
                continue

            # add them if they didn't exist in old_inv 
            if not child_ie.file_id in self.old_inv:
                mutter('adding %s %r' % (child_ie.kind, self.new_inventory.id2path(child_ie.file_id)))

                child_baton = svn.delta.editor_invoke_add_file(self.editor, 
                           os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)),
                           baton, None, -1, self.pool)


            # copy if they existed at different location
            elif self.old_inv.id2path(child_ie.file_id) != self.new_inventory.id2path(child_ie.file_id):
                mutter('copy %s %r -> %r' % (child_ie.kind, 
                                  self.old_inv.id2path(child_ie.file_id), 
                                  self.new_inventory.id2path(child_ie.file_id)))

                child_baton = svn.delta.editor_invoke_add_file(self.editor, 
                           os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)), baton, 
                           "%s/%s" % (self.branch.base, self.old_inv.id2path(child_ie.file_id)),
                           self.base_revnum, self.pool)

            # open if they existed at the same location
            elif child_ie.revision is None:
                mutter('open %s %r' % (child_ie.kind, 
                                 self.new_inventory.id2path(child_ie.file_id)))

                child_baton = svn.delta.editor_invoke_open_file(self.editor,
                        os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)), 
                        baton, self.base_revnum, self.pool)


            else:
                child_baton = None

            if child_ie.file_id in self.old_inv:
                old_executable = self.old_inv[child_ie.file_id].executable
                old_special = (self.old_inv[child_ie.file_id].kind == 'symlink')
            else:
                old_special = False
                old_executable = False

            if child_baton is not None:
                if old_executable != child_ie.executable:
                    if child_ie.executable:
                        value = svn.core.SVN_PROP_EXECUTABLE_VALUE
                    else:
                        value = None
                    svn.delta.editor_invoke_change_file_prop(self.editor, child_baton, svn.core.SVN_PROP_EXECUTABLE, value, self.pool)

                if old_special != (child_ie.kind == 'symlink'):
                    if child_ie.kind == 'symlink':
                        value = svn.core.SVN_PROP_SPECIAL_VALUE
                    else:
                        value = None

                    svn.delta.editor_invoke_change_file_prop(self.editor, child_baton, svn.core.SVN_PROP_SPECIAL, value, self.pool)

            # handle the file
            if child_ie.file_id in self.modified_files:
                self._file_process(child_ie.file_id, self.modified_files[child_ie.file_id], 
                                   child_baton)

            if child_baton is not None:
                svn.delta.editor_invoke_close_file(self.editor, child_baton, None, self.pool)

        # Loop over subdirectories of file_id in self.new_inventory
        for child_name in self.new_inventory[file_id].children:
            child_ie = self.new_inventory.get_child(file_id, child_name)
            if child_ie.kind != 'directory':
                continue

            # add them if they didn't exist in old_inv 
            if not child_ie.file_id in self.old_inv:
                mutter('adding dir %r' % child_ie.name)
                child_baton = svn.delta.editor_invoke_add_directory(
                           self.editor, 
                           os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)),
                           baton, None, -1, self.pool)

            # copy if they existed at different location
            elif self.old_inv.id2path(child_ie.file_id) != self.new_inventory.id2path(child_ie.file_id):
                mutter('copy dir %r -> %r' % (self.old_inv.id2path(child_ie.file_id), 
                                         self.new_inventory.id2path(child_ie.file_id)))
                child_baton = svn.delta.editor_invoke_add_directory(
                           self.editor, 
                           os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)),
                           baton, 
                           "%s/%s" % (self.branch.base, self.old_inv.id2path(child_ie.file_id)),
                           self.base_revnum, self.pool)

            # open if they existed at the same location and 
            # the directory was touched
            elif self.new_inventory[child_ie.file_id].revision is None:
                mutter('open dir %r' % self.new_inventory.id2path(child_ie.file_id))

                child_baton = svn.delta.editor_invoke_open_directory(self.editor, 
                        os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)), 
                        baton, self.base_revnum, self.pool)
            else:
                continue

            # Handle this directory
            if child_ie.file_id in self.modified_dirs:
                self._dir_process(self.new_inventory.id2path(child_ie.file_id), 
                        child_ie.file_id, child_baton)

            svn.delta.editor_invoke_close_directory(self.editor, child_baton, 
                                             self.pool)

    def open_branch_batons(self, root, elements):
        ret = [root]

        mutter('opening branch %r' % elements)

        for i in range(1, len(elements)):
            if i == len(elements):
                revnum = self.base_revnum
            else:
                revnum = -1
            ret.append(svn.delta.editor_invoke_open_directory(self.editor, 
                "/".join(elements[0:i+1]), ret[-1], revnum, self.pool))

        return ret

    def commit(self, message):
        def done(revision, date, author):
            assert revision > 0
            self.revnum = revision
            self.date = date
            self.author = author
            mutter('committed %r, author: %r, date: %r' % (revision, author, date))
        
        mutter('obtaining commit editor')
        self.revnum = None
        self.editor, editor_baton = self.repository.transport.get_commit_editor(
            message.encode("utf-8"), done, None, False)

        if self.branch.last_revision() is None:
            self.base_revnum = 0
        else:
            self.base_revnum = self.repository.parse_revision_id(
                          self.branch.last_revision())[1]

        root = svn.delta.editor_invoke_open_root(self.editor, editor_baton, 
                                                 self.base_revnum)
        
        branch_batons = self.open_branch_batons(root,
                                self.branch.branch_path.split("/"))

        self._dir_process("", self.new_inventory.root.file_id, branch_batons[-1])

        branch_batons.reverse()
        for baton in branch_batons:
            svn.delta.editor_invoke_close_directory(self.editor, baton, 
                                             self.pool)

        svn.delta.editor_invoke_close_edit(self.editor, editor_baton)

        assert self.revnum is not None
        revid = self.repository.generate_revision_id(self.revnum, 
                                                    self.branch.branch_path)

        #FIXME: Use public API:
        self.branch.revision_history()
        self.branch._revision_history.append(revid)

        mutter('commit finished. author: %r, date: %r' % 
               (self.author, self.date))

        # Make sure the logwalker doesn't try to use ra 
        # during checkouts...
        self.repository._log.fetch_revisions(self.revnum)

        return revid

    def record_entry_contents(self, ie, parent_invs, path, tree):
        """Record the content of ie from tree into the commit if needed.

        Side effect: sets ie.revision when unchanged

        :param ie: An inventory entry present in the commit.
        :param parent_invs: The inventories of the parent revisions of the
            commit.
        :param path: The path the entry is at in the tree.
        :param tree: The tree which contains this entry and should be used to 
        obtain content.
        """
        assert self.new_inventory.root is not None or ie.parent_id is None
        self.new_inventory.add(ie)

        # ie.revision is always None if the InventoryEntry is considered
        # for committing. ie.snapshot will record the correct revision 
        # which may be the sole parent if it is untouched.
        mutter('recording %s' % ie.file_id)
        if ie.revision is not None:
            return

        # Make sure that ie.file_id exists in the map
        if not ie.file_id in self.old_inv:
            if not self._svnprops.has_key(SVN_PROP_BZR_FILEIDS):
                self._svnprops[SVN_PROP_BZR_FILEIDS] = ""
            mutter('adding fileid mapping %s -> %s' % (path, ie.file_id))
            self._svnprops[SVN_PROP_BZR_FILEIDS] += "%s\t%s\n" % (escape_svn_path(path), ie.file_id)

        previous_entries = ie.find_previous_heads(
            parent_invs,
            self.repository.weave_store,
            self.repository.get_transaction())

        # we are creating a new revision for ie in the history store
        # and inventory.
        ie.snapshot(self._new_revision_id, path, previous_entries, tree, self)


def push_as_merged(target, source, revision_id):
    rev = source.repository.get_revision(revision_id)
    inv = source.repository.get_inventory(revision_id)

    # revision on top of which to commit
    prev_revid = target.last_revision()

    mutter('committing %r on top of %r' % (revision_id, prev_revid))

    old_tree = source.repository.revision_tree(revision_id)
    if source.repository.has_revision(prev_revid):
        new_tree = source.repository.revision_tree(prev_revid)
    else:
        new_tree = target.repository.revision_tree(prev_revid)

    builder = SvnCommitBuilder(target.repository, target, 
                               [revision_id, prev_revid],
                               target.get_config(),
                               rev.properties, 
                               new_tree.inventory)
                         
    delta = new_tree.changes_from(old_tree)
    builder.new_inventory = inv

    for (_, ie) in inv.entries():
        if not delta.touches_file_id(ie.file_id):
            continue

        id = ie.file_id
        while inv[id].parent_id is not None:
            if inv[id].revision is None:
                break
            inv[id].revision = None
            if inv[id].kind == 'directory':
                builder.modified_directory(id, [])
            id = inv[id].parent_id

        if ie.kind == 'link':
            builder.modified_link(ie.file_id, [], ie.symlink_target)
        elif ie.kind == 'file':
            def get_text():
                return old_tree.get_file_text(ie.file_id)
            builder.modified_file_text(ie.file_id, [], get_text)

    try:
        return builder.commit(rev.message)
    except SubversionException, (_, num):
        if num == svn.core.SVN_ERR_FS_TXN_OUT_OF_DATE:
            raise DivergedBranches(source, target)
        raise

