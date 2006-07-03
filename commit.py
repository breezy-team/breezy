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
from svn.core import Pool, SubversionException

from bzrlib.delta import compare_trees
from bzrlib.errors import UnsupportedOperation, BzrError
from bzrlib.inventory import Inventory
import bzrlib.osutils as osutils
from bzrlib.repository import CommitBuilder
from bzrlib.trace import mutter, warning

from repository import (SvnRepository, SVN_PROP_BZR_MERGE, SVN_PROP_SVK_MERGE, 
                       SVN_PROP_BZR_REVPROP_PREFIX, revision_id_to_svk_feature)

import os

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
        self.branch = branch
        self.pool = Pool()

        self._svnprops = {}
        for prop in self._revprops:
            self._svnprops[SVN_PROP_BZR_REVPROP_PREFIX+prop] = self._revprops[prop]

        if len(parents) > 1:
            # Bazaar Parents
            (bp, revnum) = repository.parse_revision_id(branch.last_revision())
            old = repository.get_dir_prop(revnum, bp, SVN_PROP_BZR_MERGE)
            self._svnprops[SVN_PROP_BZR_MERGE] = old + "\n" + "\t".join(parents)

            old = repository.get_dir_prop(revnum, bp, SVN_PROP_SVK_MERGE)
            new = old
            # SVK compatibility
            for p in parents:
                if p == branch.last_revision():
                    continue

                try:
                    new += "%s\n" % revision_id_to_svk_feature(p)
                except NoSuchRevision:
                    pass

            if old != new:
                self._svnprops[SVN_PROP_SVK_MERGE] = new

        # At least one of the parents has to be the last revision on the 
        # mainline in # Subversion.
        assert (self.branch.last_revision() is None or 
                self.branch.last_revision() in parents)

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
        mutter('committing changes in %r' % path)
        mutter("children: %r" % self.new_inventory.entries())

        if path == self.branch.branch_path:
            # Set all the revprops
            for prop in self._svnprops:
                svn.delta.editor_invoke_change_dir_prop(self.editor, baton,
                            prop, self._svnprops[prop], self.pool)

        mutter('old root id %r, new one %r' % (self.old_inv.root.file_id, self.new_inventory.root.file_id))
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
        mutter('root_id: %r' % self.new_inventory.root.file_id)
        mutter('children: %r' % self.new_inventory[file_id].children)
        mutter('commit children for %r: %r' % (self.new_inventory.id2path(file_id), self.new_inventory.entries()))
        for child_name in self.new_inventory[file_id].children:
            child_ie = self.new_inventory.get_child(file_id, child_name)
            assert child_ie

            if not (child_ie.kind in ('file', 'symlink')):
                continue

            # add them if they didn't exist in old_inv 
            if not child_ie.file_id in self.old_inv:
                mutter('adding file %r' % self.new_inventory.id2path(child_ie.file_id))

                child_baton = svn.delta.editor_invoke_add_file(self.editor, 
                           os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)),
                           baton, None, -1, self.pool)


            # copy if they existed at different location
            elif self.old_inv.id2path(child_ie.file_id) != self.new_inventory.id2path(child_ie.file_id):
                mutter('copy file %r -> %r' % (self.old_inv.id2path(child_ie.file_id), 
                                               self.new_inventory.id2path(child_ie.file_id)))

                child_baton = svn.delta.editor_invoke_add_file(self.editor, 
                           os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)), baton, 
                           "%s/%s" % (self.branch.base, self.old_inv.id2path(child_ie.file_id)),
                           self.base_revnum, self.pool)

            # open if they existed at the same location
            elif child_ie.file_id in self.modified_files:
                mutter('open file %r' % path)

                child_baton = svn.delta.editor_invoke_open_file(self.editor,
                        os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)), 
                        baton, self.base_revnum, self.pool)

            else:
                child_baton = None

            # handle the file
            if child_ie.file_id in self.modified_files:
                self._file_process(child_ie.file_id, self.modified_files[child_ie.file_id], 
                                   child_baton)

            if child_baton:
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
                           baton, None, self.base_revnum, self.pool)

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

            # open if they existed at the same location
            else:
                mutter('open dir %r' % self.new_inventory.id2path(child_ie.file_id))

                child_baton = svn.delta.editor_invoke_open_directory(self.editor, 
                        os.path.join(self.branch.branch_path, self.new_inventory.id2path(child_ie.file_id)), 
                        baton, self.base_revnum, self.pool)

            # Handle this directory
            if child_ie.file_id in self.modified_dirs:
                self._dir_process(self.new_inventory.id2path(child_ie.file_id), 
                        child_ie.file_id, child_baton)

            svn.delta.editor_invoke_close_directory(self.editor, child_baton, 
                                             self.pool)

    def commit(self, message):
        def done(revision, date, author):
            self.revnum = revision
            assert self.revnum > 0
            self.date = date
            self.author = author
            mutter('committed %r, author: %r, date: %r' % (revision, author, date))

        mutter('obtaining commit editor')
        self.editor, editor_baton = svn.ra.get_commit_editor(
            self.repository.ra, message, done, None, False)

        if self.branch.last_revision() is None:
            self.base_revnum = 0
        else:
            self.base_revnum = self.repository.parse_revision_id(
                          self.branch.last_revision())[1]

        root = svn.delta.editor_invoke_open_root(self.editor, editor_baton, 
                                                 self.base_revnum)
        
        if self.branch.branch_path == "":
            branch_baton = root
        else:
            branch_baton = svn.delta.editor_invoke_open_directory(self.editor, 
                    self.branch.branch_path, root, self.base_revnum, self.pool)

        self._dir_process("", self.new_inventory.root.file_id, branch_baton)

        if self.branch.branch_path != "":
            svn.delta.editor_invoke_close_directory(self.editor, branch_baton, 
                                             self.pool)


        svn.delta.editor_invoke_close_directory(self.editor, root, self.pool)

        svn.delta.editor_invoke_close_edit(self.editor, editor_baton)

        revid = self.repository.generate_revision_id(self.revnum, 
                                                    self.branch.branch_path)

        self.branch._revision_history.append(revid)

        mutter('commit finished. author: %r, date: %r' % 
               (self.author, self.date))

        return revid


def push_as_merged(target, source, revision_id):
    rev = source.repository.get_revision(revision_id)
    inv = source.repository.get_inventory(revision_id)

    mutter('committing %r on top of %r' % (revision_id, 
                                  target.last_revision()))

    old_tree = source.repository.revision_tree(revision_id)
    new_tree = target.repository.revision_tree(target.last_revision())

    builder = target.get_commit_builder([revision_id, target.last_revision()])
    delta = compare_trees(old_tree, new_tree)
    builder.new_inventory = inv

    for (id, ie) in inv.entries():
        if not delta.touches_file_id(id):
            continue

        if ie.kind == 'directory':
            builder.modified_directory(ie.file_id, [])
        elif ie.kind == 'link':
            builder.modified_link(ie.file_id, [], ie.symlink_target)
        elif ie.kind == 'file':
            def get_text():
                return new_tree.get_file_text(ie.file_id)
            builder.modified_file_text(ie.file_id, [], get_text)

    return builder.commit(rev.message)


