# Copyright (C) 2006-2008 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Committing and pushing to Subversion repositories."""

from bzrlib import debug, osutils, urlutils, ui
from bzrlib.branch import Branch
from bzrlib.errors import (BzrError, InvalidRevisionId, DivergedBranches, 
                           UnrelatedBranches, AppendRevisionsOnlyViolation,
                           NoSuchRevision)
from bzrlib.inventory import Inventory
from bzrlib.repository import RootCommitBuilder, InterRepository
from bzrlib.revision import NULL_REVISION, ensure_null
from bzrlib.trace import mutter, warning

from cStringIO import StringIO

from bzrlib.plugins.svn import core, properties
from bzrlib.plugins.svn.core import SubversionException
from bzrlib.plugins.svn.delta import send_stream
from bzrlib.plugins.svn.errors import ChangesRootLHSHistory, MissingPrefix, RevpropChangeFailed, ERR_FS_TXN_OUT_OF_DATE, ERR_REPOS_DISABLED_FEATURE
from bzrlib.plugins.svn.svk import (generate_svk_feature, serialize_svk_features, 
                 parse_svk_features, SVN_PROP_SVK_MERGE)
from bzrlib.plugins.svn.logwalker import lazy_dict
from bzrlib.plugins.svn.mapping import parse_revision_id
from bzrlib.plugins.svn.repository import SvnRepositoryFormat, SvnRepository

import urllib


def _revision_id_to_svk_feature(revid):
    """Create a SVK feature identifier from a revision id.

    :param revid: Revision id to convert.
    :return: Matching SVK feature identifier.
    """
    assert isinstance(revid, str)
    (uuid, branch, revnum, _) = parse_revision_id(revid)
    # TODO: What about renamed revisions? Should use 
    # repository.lookup_revision_id here.
    return generate_svk_feature(uuid, branch, revnum)


def _check_dirs_exist(transport, bp_parts, base_rev):
    """Make sure that the specified directories exist.

    :param transport: SvnRaTransport to use.
    :param bp_parts: List of directory names in the format returned by 
        os.path.split()
    :param base_rev: Base revision to check.
    :return: List of the directories that exists in base_rev.
    """
    for i in range(len(bp_parts), 0, -1):
        current = bp_parts[:i]
        path = "/".join(current).strip("/")
        if transport.check_path(path, base_rev) == core.NODE_DIR:
            return current
    return []


def update_svk_features(oldvalue, merges):
    old_svk_features = parse_svk_features(oldvalue)
    svk_features = set(old_svk_features)

    # SVK compatibility
    for merge in merges:
        try:
            svk_features.add(_revision_id_to_svk_feature(merge))
        except InvalidRevisionId:
            pass

    if old_svk_features != svk_features:
        return serialize_svk_features(svk_features)
    return None


def update_mergeinfo(repository, oldvalue, baserevid, merges):
    graph = repository.get_graph()
    mergeinfo = properties.parse_mergeinfo_property(oldvalue)
    for merge in merges:
        for (revid, parents) in graph.iter_ancestry([merge]):
            if graph.is_ancestor(revid, baserevid):
                break
            try:
                (path, revnum, mapping) = repository.lookup_revision_id(revid)
            except NoSuchRevision:
                break

            properties.mergeinfo_add_revision(mergeinfo, "/" + path, revnum)
    newvalue = properties.generate_mergeinfo_property(mergeinfo)
    if newvalue != oldvalue:
        return newvalue
    return None


def set_svn_revprops(transport, revnum, revprops):
    """Attempt to change the revision properties on the
    specified revision.

    :param transport: SvnRaTransport connected to target repository
    :param revnum: Revision number of revision to change metadata of.
    :param revprops: Dictionary with revision properties to set.
    """
    for (name, value) in revprops.items():
        try:
            transport.change_rev_prop(revnum, name, value)
        except SubversionException, (_, ERR_REPOS_DISABLED_FEATURE):
            raise RevpropChangeFailed(name)


class SvnCommitBuilder(RootCommitBuilder):
    """Commit Builder implementation wrapped around svn_delta_editor. """

    def __init__(self, repository, branch, parents, config, timestamp, 
                 timezone, committer, revprops, revision_id, old_inv=None,
                 push_metadata=True):
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
        :param old_inv: Optional revision on top of which 
            the commit is happening
        :param push_metadata: Whether or not to push all bazaar metadata
                              (in svn file properties, etc).
        """
        super(SvnCommitBuilder, self).__init__(repository, parents, 
            config, timestamp, timezone, committer, revprops, revision_id)
        self.branch = branch
        self.push_metadata = push_metadata

        # Gather information about revision on top of which the commit is 
        # happening
        if parents == []:
            self.base_revid = NULL_REVISION
        else:
            self.base_revid = parents[0]

        self.base_revno = self.branch.revision_id_to_revno(self.base_revid)
        if self.base_revid == NULL_REVISION:
            self.base_revnum = -1
            self.base_path = None
            self.base_mapping = repository.get_mapping()
        else:
            (self.base_path, self.base_revnum, self.base_mapping) = \
                repository.lookup_revision_id(self.base_revid)

        if old_inv is None:
            if self.base_revid == NULL_REVISION:
                self.old_inv = Inventory(root_id=None)
            else:
                self.old_inv = self.repository.get_inventory(self.base_revid)
        else:
            self.old_inv = old_inv
            # Not all repositories appear to set Inventory.revision_id, 
            # so allow None as well.
            assert self.old_inv.revision_id in (None, self.base_revid)

        # Determine revisions merged in this one
        merges = filter(lambda x: x != self.base_revid, parents)

        self.modified_files = {}
        self.modified_dirs = set()
        if self.base_revid == NULL_REVISION:
            base_branch_props = {}
        else:
            base_branch_props = lazy_dict({}, self.repository.branchprop_list.get_properties, self.base_path, self.base_revnum)
        (self._svn_revprops, self._svnprops) = self.base_mapping.export_revision(self.branch.get_branch_path(), timestamp, timezone, committer, revprops, revision_id, self.base_revno+1, merges, base_branch_props)

        if len(merges) > 0:
            new_svk_merges = update_svk_features(base_branch_props.get(SVN_PROP_SVK_MERGE, ""), merges)
            if new_svk_merges is not None:
                self._svnprops[SVN_PROP_SVK_MERGE] = new_svk_merges

            new_mergeinfo = update_mergeinfo(self.repository, base_branch_props.get(properties.PROP_MERGEINFO, ""), self.base_revid, merges)
            if new_mergeinfo is not None:
                self._svnprops[properties.PROP_MERGEINFO] = new_mergeinfo

    def mutter(self, text, *args):
        if 'commit' in debug.debug_flags:
            mutter(text, *args)

    def _generate_revision_if_needed(self):
        """See CommitBuilder._generate_revision_if_needed()."""

    def finish_inventory(self):
        """See CommitBuilder.finish_inventory()."""

    def modified_file_text(self, file_id, file_parents,
                           get_content_byte_lines, text_sha1=None,
                           text_size=None):
        """See CommitBuilder.modified_file_text()."""
        new_lines = get_content_byte_lines()
        self.modified_files[file_id] = "".join(new_lines)
        return osutils.sha_strings(new_lines), sum(map(len, new_lines))

    def modified_link(self, file_id, file_parents, link_target):
        """See CommitBuilder.modified_link()."""
        self.modified_files[file_id] = "link %s" % link_target

    def modified_directory(self, file_id, file_parents):
        """See CommitBuilder.modified_directory()."""
        self.modified_dirs.add(file_id)

    def _file_process(self, file_id, contents, file_editor):
        """Pass the changes to a file to the Subversion commit editor.

        :param file_id: Id of the file to modify.
        :param contents: Contents of the file.
        :param file_editor: Subversion FileEditor object.
        """
        assert file_editor is not None
        txdelta = file_editor.apply_textdelta()
        digest = send_stream(StringIO(contents), txdelta)
        if 'validate' in debug.debug_flags:
            from fetch import md5_strings
            assert digest == md5_strings(contents)

    def _dir_process(self, path, file_id, dir_editor):
        """Pass the changes to a directory to the commit editor.

        :param path: Path (from repository root) to the directory.
        :param file_id: File id of the directory
        :param dir_editor: Subversion DirEditor object.
        """
        assert dir_editor is not None
        # Loop over entries of file_id in self.old_inv
        # remove if they no longer exist with the same name
        # or parents
        if file_id in self.old_inv:
            for child_name in self.old_inv[file_id].children:
                child_ie = self.old_inv.get_child(file_id, child_name)
                # remove if...
                if (
                    # ... path no longer exists
                    not child_ie.file_id in self.new_inventory or 
                    # ... parent changed
                    child_ie.parent_id != self.new_inventory[child_ie.file_id].parent_id or
                    # ... name changed
                    self.new_inventory[child_ie.file_id].name != child_name):
                    self.mutter('removing %r(%r)', (child_name, child_ie.file_id))
                    dir_editor.delete_entry(
                        urlutils.join(self.branch.get_branch_path(), path, child_name), 
                        self.base_revnum)

        # Loop over file children of file_id in self.new_inventory
        for child_name in self.new_inventory[file_id].children:
            child_ie = self.new_inventory.get_child(file_id, child_name)
            assert child_ie is not None

            if not (child_ie.kind in ('file', 'symlink')):
                continue

            new_child_path = self.new_inventory.id2path(child_ie.file_id).encode("utf-8")
            full_new_child_path = urlutils.join(self.branch.get_branch_path(), 
                                  new_child_path)
            # add them if they didn't exist in old_inv 
            if not child_ie.file_id in self.old_inv:
                self.mutter('adding %s %r', child_ie.kind, new_child_path)
                child_editor = dir_editor.add_file(full_new_child_path)

            # copy if they existed at different location
            elif (self.old_inv.id2path(child_ie.file_id) != new_child_path or
                    self.old_inv[child_ie.file_id].parent_id != child_ie.parent_id):
                self.mutter('copy %s %r -> %r', child_ie.kind, 
                                  self.old_inv.id2path(child_ie.file_id), 
                                  new_child_path)
                child_editor = dir_editor.add_file(
                        full_new_child_path, 
                    urlutils.join(self.repository.transport.svn_url, self.base_path, self.old_inv.id2path(child_ie.file_id)),
                    self.base_revnum)

            # open if they existed at the same location
            elif child_ie.revision is None:
                self.mutter('open %s %r', child_ie.kind, new_child_path)

                child_editor = dir_editor.open_file(
                        full_new_child_path, self.base_revnum)

            else:
                # Old copy of the file was retained. No need to send changes
                assert child_ie.file_id not in self.modified_files
                child_editor = None

            if child_ie.file_id in self.old_inv:
                old_executable = self.old_inv[child_ie.file_id].executable
                old_special = (self.old_inv[child_ie.file_id].kind == 'symlink')
            else:
                old_special = False
                old_executable = False

            if child_editor is not None:
                if old_executable != child_ie.executable:
                    if child_ie.executable:
                        value = properties.PROP_EXECUTABLE_VALUE
                    else:
                        value = None
                    child_editor.change_prop(
                            properties.PROP_EXECUTABLE, value)

                if old_special != (child_ie.kind == 'symlink'):
                    if child_ie.kind == 'symlink':
                        value = properties.PROP_SPECIAL_VALUE
                    else:
                        value = None

                    child_editor.change_prop(
                            properties.PROP_SPECIAL, value)

            # handle the file
            if child_ie.file_id in self.modified_files:
                self._file_process(child_ie.file_id, 
                    self.modified_files[child_ie.file_id], child_editor)

            if child_editor is not None:
                child_editor.close()

        # Loop over subdirectories of file_id in self.new_inventory
        for child_name in self.new_inventory[file_id].children:
            child_ie = self.new_inventory.get_child(file_id, child_name)
            if child_ie.kind != 'directory':
                continue

            new_child_path = self.new_inventory.id2path(child_ie.file_id)
            # add them if they didn't exist in old_inv 
            if not child_ie.file_id in self.old_inv:
                self.mutter('adding dir %r', child_ie.name)
                child_editor = dir_editor.add_directory(
                    urlutils.join(self.branch.get_branch_path(), 
                                  new_child_path))

            # copy if they existed at different location
            elif self.old_inv.id2path(child_ie.file_id) != new_child_path:
                old_child_path = self.old_inv.id2path(child_ie.file_id)
                self.mutter('copy dir %r -> %r', old_child_path, new_child_path)
                child_editor = dir_editor.add_directory(
                    urlutils.join(self.branch.get_branch_path(), new_child_path),
                    urlutils.join(self.repository.transport.svn_url, self.base_path, old_child_path), self.base_revnum)

            # open if they existed at the same location and 
            # the directory was touched
            elif self.new_inventory[child_ie.file_id].revision is None:
                self.mutter('open dir %r', new_child_path)

                child_editor = dir_editor.open_directory(
                        urlutils.join(self.branch.get_branch_path(), new_child_path), 
                        self.base_revnum)
            else:
                assert child_ie.file_id not in self.modified_dirs
                continue

            # Handle this directory
            if child_ie.file_id in self.modified_dirs:
                self._dir_process(new_child_path, child_ie.file_id, child_editor)

            child_editor.close()

    def open_branch_editors(self, root, elements, existing_elements, 
                           base_path, base_rev, replace_existing):
        """Open a specified directory given an editor for the repository root.

        :param root: Editor for the repository root
        :param elements: List of directory names to open
        :param existing_elements: List of directory names that exist
        :param base_path: Path to base top-level branch on
        :param base_rev: Revision of path to base top-level branch on
        :param replace_existing: Whether the current branch should be replaced
        """
        ret = [root]

        self.mutter('opening branch %r (base %r:%r)', elements, base_path, 
                                                   base_rev)

        # Open paths leading up to branch
        for i in range(0, len(elements)-1):
            # Does directory already exist?
            ret.append(ret[-1].open_directory(
                "/".join(existing_elements[0:i+1]), -1))

        if (len(existing_elements) != len(elements) and
            len(existing_elements)+1 != len(elements)):
            raise MissingPrefix("/".join(elements))

        # Branch already exists and stayed at the same location, open:
        # TODO: What if the branch didn't change but the new revision 
        # was based on an older revision of the branch?
        # This needs to also check that base_rev was the latest version of 
        # branch_path.
        if (len(existing_elements) == len(elements) and 
            not replace_existing):
            ret.append(ret[-1].open_directory(
                "/".join(elements), base_rev))
        else: # Branch has to be created
            # Already exists, old copy needs to be removed
            name = "/".join(elements)
            if replace_existing:
                if name == "":
                    raise ChangesRootLHSHistory()
                self.mutter("removing branch dir %r", name)
                ret[-1].delete_entry(name, -1)
            if base_path is not None:
                base_url = urlutils.join(self.repository.transport.svn_url, base_path)
            else:
                base_url = None
            self.mutter("adding branch dir %r", name)
            ret.append(ret[-1].add_directory(
                name, base_url, base_rev))

        return ret

    def commit(self, message):
        """Finish the commit.

        """
        def done(*args):
            """Callback that is called by the Subversion commit editor 
            once the commit finishes.

            :param revision_data: Revision metadata
            """
            self.revision_metadata = args
        
        bp_parts = self.branch.get_branch_path().split("/")
        repository_latest_revnum = self.repository.get_latest_revnum()
        lock = self.repository.transport.lock_write(".")
        set_revprops = self._config.get_set_revprops()
        remaining_revprops = self._svn_revprops # Keep track of the revprops that haven't been set yet

        # Store file ids
        def _dir_process_file_id(old_inv, new_inv, path, file_id):
            ret = []
            for child_name in new_inv[file_id].children:
                child_ie = new_inv.get_child(file_id, child_name)
                new_child_path = new_inv.id2path(child_ie.file_id)
                assert child_ie is not None

                if (not child_ie.file_id in old_inv or 
                    old_inv.id2path(child_ie.file_id) != new_child_path or
                    old_inv[child_ie.file_id].parent_id != child_ie.parent_id):
                    ret.append((child_ie.file_id, new_child_path))

                if (child_ie.kind == 'directory' and 
                    child_ie.file_id in self.modified_dirs):
                    ret += _dir_process_file_id(old_inv, new_inv, new_child_path, child_ie.file_id)
            return ret

        fileids = {}

        if (self.old_inv.root is None or 
            self.new_inventory.root.file_id != self.old_inv.root.file_id):
            fileids[""] = self.new_inventory.root.file_id

        for id, path in _dir_process_file_id(self.old_inv, self.new_inventory, "", self.new_inventory.root.file_id):
            fileids[path] = id

        self.base_mapping.export_fileid_map(fileids, self._svn_revprops, self._svnprops)
        if self._config.get_log_strip_trailing_newline():
            self.base_mapping.export_message(message, self._svn_revprops, self._svnprops)
            message = message.rstrip("\n")
        if not self.push_metadata:
            self._svn_revprops = {}
        self._svn_revprops[properties.PROP_REVISION_LOG] = message.encode("utf-8")

        try:
            existing_bp_parts = _check_dirs_exist(self.repository.transport, 
                                              bp_parts, -1)
            self.revision_metadata = None
            for prop in self._svn_revprops:
                if not properties.is_valid_property_name(prop):
                    warning("Setting property %r with invalid characters in name", prop)
            if self.repository.transport.has_capability("commit-revprops"):
                self.editor = self.repository.transport.get_commit_editor(
                        self._svn_revprops, done, None, False)
                self._svn_revprops = {}
            else:
                if set_revprops:
                    raise
                # Try without bzr: revprops
                self.editor = self.repository.transport.get_commit_editor({
                    properties.PROP_REVISION_LOG: self._svn_revprops[properties.PROP_REVISION_LOG]},
                    done, None, False)
                del self._svn_revprops[properties.PROP_REVISION_LOG]

            root = self.editor.open_root(self.base_revnum)

            replace_existing = False
            # See whether the base of the commit matches the lhs parent
            # if not, we need to replace the existing directory
            if len(bp_parts) == len(existing_bp_parts):
                if self.base_path.strip("/") != "/".join(bp_parts).strip("/"):
                    replace_existing = True
                elif self.base_revnum < self.repository._log.find_latest_change(self.branch.get_branch_path(), repository_latest_revnum):
                    replace_existing = True

            if replace_existing and self.branch._get_append_revisions_only():
                raise AppendRevisionsOnlyViolation(self.branch.base)

            # TODO: Accept create_prefix argument (#118787)
            branch_editors = self.open_branch_editors(root, bp_parts,
                existing_bp_parts, self.base_path, self.base_revnum, 
                replace_existing)

            self._dir_process("", self.new_inventory.root.file_id, 
                branch_editors[-1])

            # Set all the revprops
            if self.push_metadata:
                for prop, value in self._svnprops.items():
                    if not properties.is_valid_property_name(prop):
                        warning("Setting property %r with invalid characters in name", prop)
                    if value is not None:
                        value = value.encode('utf-8')
                    branch_editors[-1].change_prop(prop, value)
                    self.mutter("Setting root file property %r -> %r", prop, value)

            for dir_editor in reversed(branch_editors):
                dir_editor.close()

            self.editor.close()
        finally:
            lock.unlock()

        assert self.revision_metadata is not None

        self.repository._clear_cached_state()

        (result_revision, result_date, result_author) = self.revision_metadata

        revid = self.branch.generate_revision_id(result_revision)

        assert not self.push_metadata or self._new_revision_id is None or self._new_revision_id == revid

        self.mutter('commit %d finished. author: %r, date: %r, revid: %r',
               result_revision, result_author, 
                   result_date, revid)

        override_svn_revprops = self._config.get_override_svn_revprops()
        if override_svn_revprops is not None:
            new_revprops = {}
            if properties.PROP_REVISION_AUTHOR in override_svn_revprops:
                new_revprops[properties.PROP_REVISION_AUTHOR] = self._committer.encode("utf-8")
            if properties.PROP_REVISION_DATE in override_svn_revprops:
                new_revprops[properties.PROP_REVISION_DATE] = properties.time_to_cstring(1000000*self._timestamp)
            set_svn_revprops(self.repository.transport, result_revision, new_revprops)

        try:
            set_svn_revprops(self.repository.transport, result_revision, 
                         self._svn_revprops) 
        except RevpropChangeFailed:
            pass # Ignore for now

        return revid

    def record_entry_contents(self, ie, parent_invs, path, tree,
                              content_summary):
        """Record the content of ie from tree into the commit if needed.

        Side effect: sets ie.revision when unchanged

        :param ie: An inventory entry present in the commit.
        :param parent_invs: The inventories of the parent revisions of the
            commit.
        :param path: The path the entry is at in the tree.
        :param tree: The tree which contains this entry and should be used to 
            obtain content.
        :param content_summary: Summary data from the tree about the paths
                content - stat, length, exec, sha/link target. This is only
                accessed when the entry has a revision of None - that is when 
                it is a candidate to commit.
        """
        self.new_inventory.add(ie)


def replay_delta(builder, old_tree, new_tree):
    """Replays a delta to a commit builder.

    :param builder: The commit builder.
    :param old_tree: Original tree on top of which the delta should be applied
    :param new_tree: New tree that should be committed
    """
    for path, ie in new_tree.inventory.iter_entries():
        builder.record_entry_contents(ie.copy(), [old_tree.inventory], 
                                      path, new_tree, None)
    builder.finish_inventory()
    delta = new_tree.changes_from(old_tree)
    def touch_id(id):
        ie = builder.new_inventory[id]

        id = ie.file_id
        while builder.new_inventory[id].parent_id is not None:
            if builder.new_inventory[id].revision is None:
                break
            builder.new_inventory[id].revision = None
            if builder.new_inventory[id].kind == 'directory':
                builder.modified_directory(id, [])
            id = builder.new_inventory[id].parent_id

        assert ie.kind in ('symlink', 'file', 'directory')
        if ie.kind == 'symlink':
            builder.modified_link(ie.file_id, [], ie.symlink_target)
        elif ie.kind == 'file':
            def get_text():
                return new_tree.get_file_text(ie.file_id)
            builder.modified_file_text(ie.file_id, [], get_text)

    for (_, id, _) in delta.added:
        touch_id(id)

    for (_, id, _, _, _) in delta.modified:
        touch_id(id)

    for (oldpath, _, id, _, _, _) in delta.renamed:
        touch_id(id)
        old_parent_id = old_tree.inventory.path2id(urlutils.dirname(oldpath))
        if old_parent_id in builder.new_inventory:
            touch_id(old_parent_id)

    for (path, _, _) in delta.removed:
        old_parent_id = old_tree.inventory.path2id(urlutils.dirname(path))
        if old_parent_id in builder.new_inventory:
            touch_id(old_parent_id)


def push_new(target_repository, target_branch_path, source, stop_revision,
             push_metadata=True):
    """Push a revision into Subversion, creating a new branch.

    This will do a new commit in the target branch.

    :param target_repository: Repository to push to
    :param target_branch_path: Path to create new branch at
    :param source: Branch to pull the revision from
    """
    assert isinstance(source, Branch)
    revhistory = list(source.repository.iter_reverse_revision_history(stop_revision))
    history = list(revhistory)
    history.reverse()
    start_revid_parent = NULL_REVISION
    start_revid = stop_revision
    for revid in revhistory:
        # We've found the revision to push if there is a revision 
        # which LHS parent is present or if this is the first revision.
        if target_repository.has_revision(revid):
            start_revid_parent = revid
            break
        start_revid = revid
    assert start_revid is not None
    # Get commit builder but specify that target_branch_path should
    # be created and copied from (copy_path, copy_revnum)
    class ImaginaryBranch(object):
        """Simple branch that pretends to be empty but already exist."""
        def __init__(self, repository):
            self.repository = repository
            self._revision_history = None

        def get_config(self):
            """See Branch.get_config()."""
            return self.repository.get_config()

        def revision_id_to_revno(self, revid):
            if revid is NULL_REVISION:
                return 0
            return history.index(revid)

        def last_revision_info(self):
            """See Branch.last_revision_info()."""
            last_revid = self.last_revision()
            return (self.revision_id_to_revno(last_revid), last_revid)

        def last_revision(self):
            """See Branch.last_revision()."""
            return start_revid_parent

        def get_branch_path(self, revnum=None):
            """See SvnBranch.get_branch_path()."""
            return target_branch_path

        def generate_revision_id(self, revnum):
            """See SvnBranch.generate_revision_id()."""
            return self.repository.generate_revision_id(
                revnum, self.get_branch_path(revnum), 
                self.repository.get_mapping())

    push(ImaginaryBranch(target_repository), source, start_revid, push_metadata=push_metadata)


def dpush(target, source, stop_revision=None):
    """Push derivatives of the revisions missing from target from source into 
    target.

    :param target: Branch to push into
    :param source: Branch to retrieve revisions from
    :param stop_revision: If not None, stop at this revision.
    :return: Map of old revids to new revids.
    """
    source.lock_write()
    try:
        if stop_revision is None:
            stop_revision = ensure_null(source.last_revision())
        if target.last_revision() in (stop_revision, source.last_revision()):
            return
        graph = target.repository.get_graph()
        if not source.repository.get_graph().is_ancestor(target.last_revision(), 
                                                        stop_revision):
            if graph.is_ancestor(stop_revision, target.last_revision()):
                return
            raise DivergedBranches(source, target)
        todo = target.mainline_missing_revisions(source, stop_revision)
        revid_map = {}
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for revid in todo:
                pb.update("pushing revisions", todo.index(revid), 
                          len(todo))
                revid_map[revid] = push(target, source, revid, 
                                        push_metadata=False)
                source.repository.fetch(target.repository, 
                                        revision_id=revid_map[revid])
                target._clear_cached_state()
        finally:
            pb.finished()
        (new_revno, new_revid) = target.last_revision_info()
        return revid_map
    finally:
        source.unlock()


def push_revision_tree(target, config, source_repo, base_revid, revision_id, 
                       rev, push_metadata=True):
    old_tree = source_repo.revision_tree(revision_id)
    base_tree = source_repo.revision_tree(base_revid)

    if push_metadata:
        base_revids = rev.parent_ids
    else:
        base_revids = [base_revid]

    builder = SvnCommitBuilder(target.repository, target, 
                               base_revids,
                               config, rev.timestamp,
                               rev.timezone, rev.committer, rev.properties, 
                               revision_id, base_tree.inventory, 
                               push_metadata=push_metadata)
                         
    replay_delta(builder, base_tree, old_tree)
    try:
        revid = builder.commit(rev.message)
    except SubversionException, (_, num):
        if num == ERR_FS_TXN_OUT_OF_DATE:
            raise DivergedBranches(source, target)
        raise
    except ChangesRootLHSHistory:
        raise BzrError("Unable to push revision %r because it would change the ordering of existing revisions on the Subversion repository root. Use rebase and try again or push to a non-root path" % revision_id)
    
    if source_repo.has_signature_for_revision_id(revision_id):
        pass # FIXME: Copy revision signature for rev

    return revid


def push(target, source, revision_id, push_metadata=True):
    """Push a revision into Subversion.

    This will do a new commit in the target branch.

    :param target: Branch to push to
    :param source: Branch to pull the revision from
    :param revision_id: Revision id of the revision to push
    :return: revision id of revision that was pushed
    """
    assert isinstance(source, Branch)
    rev = source.repository.get_revision(revision_id)
    mutter('pushing %r (%r)', revision_id, rev.parent_ids)

    # revision on top of which to commit
    if push_metadata:
        if rev.parent_ids == []:
            base_revid = NULL_REVISION
        else:
            base_revid = rev.parent_ids[0]
    else:
        base_revid = target.last_revision()

    source.lock_read()
    try:
        revid = push_revision_tree(target, target.get_config(), 
                                   source.repository, base_revid, revision_id, 
                                   rev, push_metadata=push_metadata)
    finally:
        source.unlock()

    assert revid == revision_id or not push_metadata

    if 'validate' in debug.debug_flags and push_metadata:
        crev = target.repository.get_revision(revision_id)
        ctree = target.repository.revision_tree(revision_id)
        treedelta = ctree.changes_from(old_tree)
        assert not treedelta.has_changed(), "treedelta: %r" % treedelta
        assert crev.committer == rev.committer
        assert crev.timezone == rev.timezone
        assert crev.timestamp == rev.timestamp
        assert crev.message == rev.message
        assert crev.properties == rev.properties

    return revid


class InterToSvnRepository(InterRepository):
    """Any to Subversion repository actions."""

    _matching_repo_format = SvnRepositoryFormat()

    @staticmethod
    def _get_repo_format_to_test():
        """See InterRepository._get_repo_format_to_test()."""
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.source.lock_read()
        try:
            assert revision_id is not None, "fetching all revisions not supported"
            # Go back over the LHS parent until we reach a revid we know
            todo = []
            while not self.target.has_revision(revision_id):
                todo.append(revision_id)
                try:
                    revision_id = self.source.get_parent_map([revision_id])[revision_id][0]
                except KeyError:
                    # We hit a ghost
                    break
                if revision_id == NULL_REVISION:
                    raise UnrelatedBranches()
            if todo == []:
                # Nothing to do
                return
            mutter("pushing %r into svn", todo)
            target_branch = None
            for revision_id in todo:
                if pb is not None:
                    pb.update("pushing revisions", todo.index(revision_id), len(todo))
                rev = self.source.get_revision(revision_id)

                mutter('pushing %r', revision_id)

                parent_revid = rev.parent_ids[0]

                (bp, _, _) = self.target.lookup_revision_id(parent_revid)
                if target_branch is None:
                    target_branch = Branch.open(urlutils.join(self.target.base, bp))
                if target_branch.get_branch_path() != bp:
                    target_branch.set_branch_path(bp)

                push_revision_tree(target_branch, target_branch.get_config(), self.source, 
                                   parent_revid, revision_id, rev)
        finally:
            self.source.unlock()
 

    def fetch(self, revision_id=None, pb=None, find_ghosts=False):
        """Fetch revisions. """
        self.copy_content(revision_id=revision_id, pb=pb)

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with SvnRepository."""
        return isinstance(target, SvnRepository)
