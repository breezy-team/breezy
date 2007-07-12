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
"""Committing and pushing to Subversion repositories."""

import svn.delta
from svn.core import Pool, SubversionException

from bzrlib.branch import Branch
from bzrlib.errors import InvalidRevisionId, DivergedBranches
from bzrlib.inventory import Inventory
import bzrlib.osutils as osutils
from bzrlib.repository import RootCommitBuilder, InterRepository
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter

from repository import (SVN_PROP_BZR_MERGE, SVN_PROP_BZR_FILEIDS,
                        SVN_PROP_SVK_MERGE, SVN_PROP_BZR_REVISION_INFO, 
                        SVN_PROP_BZR_REVISION_ID, revision_id_to_svk_feature,
                        generate_revision_metadata, SvnRepositoryFormat, 
                        SvnRepository)
from revids import escape_svn_path

import os

class SvnCommitBuilder(RootCommitBuilder):
    """Commit Builder implementation wrapped around svn_delta_editor. """

    def __init__(self, repository, branch, parents, config, timestamp, 
                 timezone, committer, revprops, revision_id, old_inv=None):
        """Instantiate a new SvnCommitBuilder.

        :param repository: SvnRepository to commit to.
        :param branch: SvnBranch to commit to.
        :param parents: List of parent revision ids.
        :param config: Branch configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Revision properties to set.
        :param revision_id: Revision id for the new revision.
        """
        super(SvnCommitBuilder, self).__init__(repository, parents, 
            config, timestamp, timezone, committer, revprops, revision_id)
        self.branch = branch
        self.pool = Pool()

        self._svnprops = {}
        self._svnprops[SVN_PROP_BZR_REVISION_INFO] = generate_revision_metadata(timestamp, timezone, committer, revprops)

        self.merges = filter(lambda x: x != self.branch.last_revision(),
                             parents)

        if len(self.merges) > 0:
            # Bazaar Parents
            if branch.last_revision():
                (bp, revnum, scheme) = repository.lookup_revision_id(branch.last_revision())
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

        if revision_id is not None:
            (previous_revno, previous_revid) = branch.last_revision_info()
            if previous_revid is not None:
                (bp, revnum, scheme) = repository.lookup_revision_id(branch.last_revision())
                old = repository.branchprop_list.get_property(bp, revnum, 
                            SVN_PROP_BZR_REVISION_ID+str(scheme), "")
            else:
                old = ""

            self._svnprops[SVN_PROP_BZR_REVISION_ID+str(scheme)] = old + \
                    "%d %s\n" % (previous_revno+1, revision_id)

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
        (txdelta, txbaton) = self.editor.apply_textdelta(baton, None, self.pool)

        svn.delta.svn_txdelta_send_string(contents, txdelta, txbaton, self.pool)

    def _dir_process(self, path, file_id, baton):
        mutter('processing %r' % path)
        if path == "":
            # Set all the revprops
            for prop, value in self._svnprops.items():
                mutter('setting %r: %r on branch' % (prop, value))
                if value is not None:
                    value = value.encode('utf-8')
                self.editor.change_dir_prop(baton, prop, value, self.pool)

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
                    self.editor.delete_entry(
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

                child_baton = self.editor.add_file(
                           os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)),
                           baton, None, -1, self.pool)


            # copy if they existed at different location
            elif self.old_inv.id2path(child_ie.file_id) != self.new_inventory.id2path(child_ie.file_id):
                mutter('copy %s %r -> %r' % (child_ie.kind, 
                                  self.old_inv.id2path(child_ie.file_id), 
                                  self.new_inventory.id2path(child_ie.file_id)))

                child_baton = self.editor.add_file(
                           os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)), baton, 
                           "%s/%s" % (self.branch.base, self.old_inv.id2path(child_ie.file_id)),
                           self.base_revnum, self.pool)

            # open if they existed at the same location
            elif child_ie.revision is None:
                mutter('open %s %r' % (child_ie.kind, 
                                 self.new_inventory.id2path(child_ie.file_id)))

                child_baton = self.editor.open_file(
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
                    self.editor.change_file_prop(child_baton, 
                            svn.core.SVN_PROP_EXECUTABLE, value, self.pool)

                if old_special != (child_ie.kind == 'symlink'):
                    if child_ie.kind == 'symlink':
                        value = svn.core.SVN_PROP_SPECIAL_VALUE
                    else:
                        value = None

                    self.editor.change_file_prop(child_baton, 
                            svn.core.SVN_PROP_SPECIAL, value, self.pool)

            # handle the file
            if child_ie.file_id in self.modified_files:
                self._file_process(child_ie.file_id, self.modified_files[child_ie.file_id], 
                                   child_baton)

            if child_baton is not None:
                self.editor.close_file(child_baton, None, self.pool)

        # Loop over subdirectories of file_id in self.new_inventory
        for child_name in self.new_inventory[file_id].children:
            child_ie = self.new_inventory.get_child(file_id, child_name)
            if child_ie.kind != 'directory':
                continue

            # add them if they didn't exist in old_inv 
            if not child_ie.file_id in self.old_inv:
                mutter('adding dir %r' % child_ie.name)
                child_baton = self.editor.add_directory(
                           os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)),
                           baton, None, -1, self.pool)

            # copy if they existed at different location
            elif self.old_inv.id2path(child_ie.file_id) != self.new_inventory.id2path(child_ie.file_id):
                mutter('copy dir %r -> %r' % (self.old_inv.id2path(child_ie.file_id), 
                                         self.new_inventory.id2path(child_ie.file_id)))
                child_baton = self.editor.add_directory(
                           os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)),
                           baton, 
                           "%s/%s" % (self.branch.base, self.old_inv.id2path(child_ie.file_id)),
                           self.base_revnum, self.pool)

            # open if they existed at the same location and 
            # the directory was touched
            elif self.new_inventory[child_ie.file_id].revision is None:
                mutter('open dir %r' % self.new_inventory.id2path(child_ie.file_id))

                child_baton = self.editor.open_directory(
                        os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)), 
                        baton, self.base_revnum, self.pool)
            else:
                continue

            # Handle this directory
            if child_ie.file_id in self.modified_dirs:
                self._dir_process(self.new_inventory.id2path(child_ie.file_id), 
                        child_ie.file_id, child_baton)

            self.editor.close_directory(child_baton, self.pool)

    def open_branch_batons(self, root, elements):
        """Open a specified directory given a baton for the repository root.

        :param root: Baton for the repository root
        :param elements: List of directory names to open
        """
        ret = [root]

        mutter('opening branch %r' % elements)

        for i in range(1, len(elements)):
            if i == len(elements):
                revnum = self.base_revnum
            else:
                revnum = -1
            ret.append(self.editor.open_directory(
                "/".join(elements[0:i+1]), ret[-1], revnum, self.pool))

        return ret

    def commit(self, message):
        def done(revision, date, author):
            assert revision > 0
            self.revnum = revision
            self.date = date
            self.author = author
        
        mutter('obtaining commit editor')
        self.revnum = None
        self.editor = self.repository.transport.get_commit_editor(
            message.encode("utf-8"), done, None, False)

        if self.branch.last_revision() is None:
            self.base_revnum = 0
        else:
            self.base_revnum = self.branch.lookup_revision_id(
                          self.branch.last_revision())

        root = self.editor.open_root(self.base_revnum)
        
        branch_batons = self.open_branch_batons(root,
                                self.branch.branch_path.split("/"))

        self._dir_process("", self.new_inventory.root.file_id, branch_batons[-1])

        branch_batons.reverse()
        for baton in branch_batons:
            self.editor.close_directory(baton, self.pool)

        self.editor.close()

        assert self.revnum is not None
        revid = self.branch.generate_revision_id(self.revnum)

        self.repository._latest_revnum = self.revnum

        #FIXME: Use public API:
        if self.branch._revision_history is not None:
            self.branch._revision_history.append(revid)

        mutter('commit %d finished. author: %r, date: %r' % 
               (self.revnum, self.author, self.date))

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


def replay_delta(builder, delta, old_tree):
    """Replays a delta to a commit builder.

    :param builder: The commit builder.
    :param delta: Treedelta to apply
    :param old_tree: Original tree on top of which the delta should be applied
    """
    for (_, ie) in builder.new_inventory.entries():
        if not delta.touches_file_id(ie.file_id):
            continue

        id = ie.file_id
        while builder.new_inventory[id].parent_id is not None:
            if builder.new_inventory[id].revision is None:
                break
            builder.new_inventory[id].revision = None
            if builder.new_inventory[id].kind == 'directory':
                builder.modified_directory(id, [])
            id = builder.new_inventory[id].parent_id

        if ie.kind == 'link':
            builder.modified_link(ie.file_id, [], ie.symlink_target)
        elif ie.kind == 'file':
            def get_text():
                return old_tree.get_file_text(ie.file_id)
            builder.modified_file_text(ie.file_id, [], get_text)


def push_as_merged(target, source, revision_id):
    """Push a revision as merged revision.

    This will create a new revision in the target repository that 
    merges the specified revision but does not contain any other differences. 
    This is done so that the revision that is being pushed does not need 
    to completely match the target revision and so it can not have the 
    same revision id.

    :param target: Repository to push to
    :param source: Repository to pull the revision from
    :param revision_id: Revision id of the revision to push
    :return: The revision id of the created revision
    """
    assert isinstance(source, Branch)
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
                               None,
                               None,
                               None,
                               rev.properties, 
                               None,
                               new_tree.inventory)
                         
    delta = new_tree.changes_from(old_tree)
    builder.new_inventory = inv
    replay_delta(builder, delta, old_tree)

    try:
        return builder.commit(rev.message)
    except SubversionException, (_, num):
        if num == svn.core.SVN_ERR_FS_TXN_OUT_OF_DATE:
            raise DivergedBranches(source, target)
        raise

def push(target, source, revision_id):
    """Push a revision into Subversion.

    This will do a new commit in the target branch.

    :param target: Branch to push to
    :param source: Branch to pull the revision from
    :param revision_id: Revision id of the revision to push
    """
    assert isinstance(source, Branch)
    rev = source.repository.get_revision(revision_id)
    inv = source.repository.get_inventory(revision_id)

    # revision on top of which to commit
    assert target.last_revision() in rev.parent_ids

    mutter('pushing %r' % (revision_id))

    old_tree = source.repository.revision_tree(revision_id)
    new_tree = source.repository.revision_tree(target.last_revision())

    builder = SvnCommitBuilder(target.repository, target, 
                               rev.parent_ids,
                               target.get_config(),
                               rev.timestamp,
                               rev.timezone,
                               rev.committer,
                               rev.properties, 
                               revision_id,
                               new_tree.inventory)
                         
    delta = new_tree.changes_from(old_tree)
    builder.new_inventory = inv
    replay_delta(builder, delta, old_tree)
    try:
        return builder.commit(rev.message)
    except SubversionException, (_, num):
        if num == svn.core.SVN_ERR_FS_TXN_OUT_OF_DATE:
            raise DivergedBranches(source, target)
        raise

class InterToSvnRepository(InterRepository):
    """Any to Subversion repository actions."""

    _matching_repo_format = SvnRepositoryFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, basis=None, pb=None):
        """See InterRepository.copy_content."""
        assert revision_id is not None, "fetching all revisions not supported"
        # Go back over the LHS parent until we reach a revid we know
        todo = []
        while not self.target.has_revision(revision_id):
            todo.append(revision_id)
            revision_id = self.source.revision_parents(revision_id)[0]
            if revision_id == NULL_REVISION:
                raise "Unrelated repositories."
        todo.reverse()
        mutter("pushing %r into svn" % todo)
        while len(todo) > 0:
            revision_id = todo.pop()

            rev = self.source.get_revision(revision_id)
            inv = self.source.get_inventory(revision_id)

            mutter('pushing %r' % (revision_id))

            old_tree = self.source.revision_tree(revision_id)
            parent_revid = self.source.revision_parents(revision_id)[0]
            new_tree = self.source.revision_tree(parent_revid)

            (bp, _, scheme) = self.target.lookup_revision_id(parent_revid)
            target_branch = Branch.open("%s/%s" % (self.target.base, bp))

            builder = SvnCommitBuilder(self.target, target_branch, 
                               rev.parent_ids,
                               target_branch.get_config(),
                               rev.timestamp,
                               rev.timezone,
                               rev.committer,
                               rev.properties, 
                               revision_id,
                               new_tree.inventory)
                         
            delta = new_tree.changes_from(old_tree)
            builder.new_inventory = inv
            replay_delta(builder, delta, old_tree)
            builder.commit(rev.message)
 

    def fetch(self, revision_id=None, pb=None):
        """Fetch revisions. """
        self.copy_content(revision_id=revision_id, pb=pb)

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with SvnRepository."""
        return isinstance(target, SvnRepository)
