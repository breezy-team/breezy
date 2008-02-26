# Copyright (C) 2008 Canonical Ltd
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

"""Import processor that supports all Bazaar repository formats."""


import re
import time
from bzrlib import (
    builtins,
    bzrdir,
    delta,
    errors,
    generate_ids,
    inventory,
    lru_cache,
    osutils,
    progress,
    revision,
    revisiontree,
    transport,
    )
from bzrlib.trace import (
    note,
    warning,
    error,
    )
import bzrlib.util.configobj.configobj as configobj
from bzrlib.plugins.fastimport import (
    helpers,
    processor,
    revisionloader,
    )


# How many commits before automatically reporting progress
_DEFAULT_AUTO_PROGRESS = 1000

# How many commits before automatically checkpointing
_DEFAULT_AUTO_CHECKPOINT = 10000

# How many inventories to cache
_DEFAULT_INV_CACHE_SIZE = 10


class GenericProcessor(processor.ImportProcessor):
    """An import processor that handles basic imports.

    Current features supported:

    * blobs are cached in memory
    * files and symlinks commits are supported
    * checkpoints automatically happen at a configurable frequency
      over and above the stream requested checkpoints
    * timestamped progress reporting, both automatic and stream requested
    * LATER: reset support, tags for each branch
    * some basic statistics are dumped on completion.

    Here are the supported parameters:

    * info - name of a hints file holding the analysis generated
      by running the fast-import-info processor in verbose mode. When
      importing large repositories, this parameter is needed so
      that the importer knows what blobs to intelligently cache.

    * trees - update the working trees before completing.
      By default, the importer updates the repository
      and branches and the user needs to run 'bzr update' for the
      branches of interest afterwards.

    * checkpoint - automatically checkpoint every n commits over and
      above any checkpoints contained in the import stream.
      The default is 10000.

    * count - only import this many commits then exit. If not set
      or negative, all commits are imported.
    
    * inv-cache - number of inventories to cache.
      If not set, the default is 10.

    * experimental - enable experimental mode, i.e. use features
      not yet fully tested.
    """

    known_params = [
        'info',
        'trees',
        'checkpoint',
        'count',
        'inv-cache',
        'experimental',
        ]

    def note(self, msg, *args):
        """Output a note but timestamp it."""
        msg = "%s %s" % (self._time_of_day(), msg)
        note(msg, *args)

    def warning(self, msg, *args):
        """Output a warning but timestamp it."""
        msg = "%s WARNING: %s" % (self._time_of_day(), msg)
        warning(msg, *args)

    def _time_of_day(self):
        """Time of day as a string."""
        # Note: this is a separate method so tests can patch in a fixed value
        return time.strftime("%H:%M:%S")

    def pre_process(self):
        self._start_time = time.time()
        self._load_info_and_params()
        self.cache_mgr = GenericCacheManager(self.info, self.verbose,
            self.inventory_cache_size)
        self.loader = revisionloader.ImportRevisionLoader(self.repo,
            self.inventory_cache_size)
        self.init_stats()

        # mapping of tag name to revision_id
        self.tags = {}

        # Create a write group. This is committed at the end of the import.
        # Checkpointing closes the current one and starts a new one.
        self.repo.start_write_group()

        # Turn on caching for the inventory versioned file
        inv_vf = self.repo.get_inventory_weave()
        inv_vf.enable_cache()

    def _load_info_and_params(self):
        self._experimental = self.params.get('experimental', False)

        # Load the info file, if any
        info_path = self.params.get('info')
        if info_path is not None:
            self.info = configobj.ConfigObj(info_path)
        else:
            self.info = None

        # Decide how often to automatically report progress
        # (not a parameter yet)
        self.progress_every = _DEFAULT_AUTO_PROGRESS
        if self.verbose:
            self.progress_every = self.progress_every / 10

        # Decide how often to automatically checkpoint
        self.checkpoint_every = int(self.params.get('checkpoint',
            _DEFAULT_AUTO_CHECKPOINT))

        # Decide how big to make the inventory cache
        self.inventory_cache_size = int(self.params.get('inv-cache',
            _DEFAULT_INV_CACHE_SIZE))

        # Find the maximum number of commits to import (None means all)
        # and prepare progress reporting. Just in case the info file
        # has an outdated count of commits, we store the max counts
        # at which we need to terminate separately to the total used
        # for progress tracking.
        try:
            self.max_commits = int(self.params['count'])
            if self.max_commits < 0:
                self.max_commits = None
        except KeyError:
            self.max_commits = None
        if self.info is not None:
            self.total_commits = int(self.info['Command counts']['commit'])
            if (self.max_commits is not None and
                self.total_commits > self.max_commits):
                self.total_commits = self.max_commits
        else:
            self.total_commits = self.max_commits


    def _process(self, command_iter):
        # if anything goes wrong, abort the write group if any
        try:
            processor.ImportProcessor._process(self, command_iter)
        except:
            if self.repo is not None and self.repo.is_in_write_group():
                self.repo.abort_write_group()
            raise

    def post_process(self):
        # Commit the current write group.
        self.repo.commit_write_group()

        # Update the branches
        self.note("Updating branch information ...")
        updater = GenericBranchUpdater(self.repo, self.branch, self.cache_mgr,
            helpers.invert_dict(self.cache_mgr.heads),
            self.cache_mgr.last_ref)
        branches_updated, branches_lost = updater.update()
        self._branch_count = len(branches_updated)

        # Tell the user about branches that were not created
        if branches_lost:
            if not self.repo.is_shared():
                self.warning("Cannot import multiple branches into "
                    "an unshared repository")
            self.warning("Not creating branches for these head revisions:")
            for lost_info in branches_lost:
                head_revision = lost_info[1]
                branch_name = lost_info[0]
                note("\t %s = %s", head_revision, branch_name)

        # Update the working trees as requested and dump stats
        self._tree_count = 0
        remind_about_update = True
        if self.params.get('trees', False):
            trees = self._get_working_trees(branches_updated)
            if trees:
                self.note("Updating the working trees ...")
                if self.verbose:
                    report = delta._ChangeReporter()
                else:
                    reporter = None
                for wt in trees:
                    wt.update(reporter)
                    self._tree_count += 1
                remind_about_update = False
            else:
                self.warning("No working trees available to update")
        self.dump_stats()
        if remind_about_update:
            self.note("To refresh the working tree for a branch, "
                "use 'bzr update'")

    def _get_working_trees(self, branches):
        """Get the working trees for branches in the repository."""
        result = []
        wt_expected = self.repo.make_working_trees()
        for br in branches:
            if br == self.branch and br is not None:
                wt = self.working_tree
            elif wt_expected:
                try:
                    wt = br.bzrdir.open_workingtree()
                except errors.NoWorkingTree:
                    self.warning("No working tree for branch %s", br)
                    continue
            else:
                continue
            result.append(wt)
        return result

    def init_stats(self):
        self._revision_count = 0

    def dump_stats(self):
        time_required = progress.str_tdelta(time.time() - self._start_time)
        rc = self._revision_count
        bc = self._branch_count
        wtc = self._tree_count
        self.note("Imported %d %s, updating %d %s and %d %s in %s",
            rc, helpers.single_plural(rc, "revision", "revisions"),
            bc, helpers.single_plural(bc, "branch", "branches"),
            wtc, helpers.single_plural(wtc, "tree", "trees"),
            time_required)

    def blob_handler(self, cmd):
        """Process a BlobCommand."""
        if cmd.mark is not None:
            dataref = cmd.id
        else:
            dataref = osutils.sha_strings(cmd.data)
        self.cache_mgr.store_blob(dataref, cmd.data)

    def checkpoint_handler(self, cmd):
        """Process a CheckpointCommand."""
        # Commit the current write group and start a new one
        self.repo.commit_write_group()
        self.repo.start_write_group()

    def commit_handler(self, cmd):
        """Process a CommitCommand."""
        # 'Commit' the revision
        handler = GenericCommitHandler(cmd, self.repo, self.cache_mgr,
            self.loader, self.verbose, self._experimental)
        handler.process()

        # Update caches
        self.cache_mgr.revision_ids[cmd.id] = handler.revision_id
        self.cache_mgr.last_ids[cmd.ref] = cmd.id
        self.cache_mgr.last_ref = cmd.ref

        # Report progress
        self._revision_count += 1
        self.report_progress("(%s)" % cmd.id)

        # Check if we should finish up or automatically checkpoint
        if (self.max_commits is not None and
            self._revision_count >= self.max_commits):
            self.note("stopping after reaching requested count of commits")
            self.finished = True
        elif self._revision_count % self.checkpoint_every == 0:
            self.note("%d commits - automatic checkpoint triggered",
                self._revision_count)
            self.checkpoint_handler(None)

    def report_progress(self, details=''):
        # TODO: use a progress bar with ETA enabled
        if self._revision_count % self.progress_every == 0:
            if self.total_commits is not None:
                counts = "%d/%d" % (self._revision_count, self.total_commits)
                eta = progress.get_eta(self._start_time, self._revision_count,
                    self.total_commits)
                eta_str = progress.str_tdelta(eta)
                if eta_str.endswith('--'):
                    eta_str = ''
                else:
                    eta_str = '[%s] ' % eta_str
            else:
                counts = "%d" % (self._revision_count,)
                eta_str = ''
            self.note("%s commits processed %s%s" % (counts, eta_str, details))

    def progress_handler(self, cmd):
        """Process a ProgressCommand."""
        # We could use a progress bar here instead
        self.note("progress %s" % (cmd.message,))

    def reset_handler(self, cmd):
        """Process a ResetCommand."""
        if cmd.ref.startswith('refs/tags/'):
            self._set_tag(cmd.ref[len('refs/tags/'):], cmd.from_)
        else:
            self.warning("resets are not supported yet"
                " - ignoring reset of '%s'", cmd.ref)

    def tag_handler(self, cmd):
        """Process a TagCommand."""
        self._set_tag(cmd.id, cmd.from_)

    def _set_tag(self, name, from_):
        """Define a tag given a name an import 'from' reference."""
        bzr_tag_name = name.decode('utf-8', 'replace')
        bzr_rev_id = self.cache_mgr.revision_ids[from_]
        self.tags[bzr_tag_name] = bzr_rev_id


class GenericCacheManager(object):
    """A manager of caches for the GenericProcessor."""

    def __init__(self, info, verbose=False, inventory_cache_size=10):
        """Create a manager of caches.

        :param info: a ConfigObj holding the output from
            the --info processor, or None if no hints are available
        """
        self.verbose = verbose

        # dataref -> data. datref is either :mark or the sha-1.
        # Sticky blobs aren't removed after being referenced.
        self._blobs = {}
        self._sticky_blobs = {}

        # revision-id -> Inventory cache
        # these are large and we probably don't need too many as
        # most parents are recent in history
        self.inventories = lru_cache.LRUCache(inventory_cache_size)

        # import-ref -> revision-id lookup table
        # we need to keep all of these but they are small
        self.revision_ids = {}

        # path -> file-ids - as generated
        self.file_ids = {}

        # Head tracking: last ref, last id per ref & map of commit mark to ref
        self.last_ref = None
        self.last_ids = {}
        self.heads = {}

        # Work out the blobs to make sticky - None means all
        self._blobs_to_keep = None
        if info is not None:
            try:
                self._blobs_to_keep = info['Blob usage tracking']['multi']
            except KeyError:
                # info not in file - possible when no blobs used
                pass

    def store_blob(self, id, data):
        """Store a blob of data."""
        if (self._blobs_to_keep is None or data == '' or
            id in self._blobs_to_keep):
            self._sticky_blobs[id] = data
        else:
            self._blobs[id] = data

    def fetch_blob(self, id):
        """Fetch a blob of data."""
        try:
            return self._sticky_blobs[id]
        except KeyError:
            return self._blobs.pop(id)

    def _delete_path(self, path):
        """Remove a path from caches."""
        # we actually want to remember what file-id we gave a path,
        # even when that file is deleted, so doing nothing is correct
        pass

    def _rename_path(self, old_path, new_path):
        """Rename a path in the caches."""
        # we actually want to remember what file-id we gave a path,
        # even when that file is renamed, so both paths should have
        # the same value and we don't delete any information
        self.file_ids[new_path] = self.file_ids[old_path]


class GenericCommitHandler(processor.CommitHandler):

    def __init__(self, command, repo, cache_mgr, loader, verbose=False,
        _experimental=False):
        processor.CommitHandler.__init__(self, command)
        self.repo = repo
        self.cache_mgr = cache_mgr
        self.loader = loader
        self.verbose = verbose
        self._experimental = _experimental

    def note(self, msg, *args):
        """Output a note but add context."""
        msg = "%s (%s)" % (msg, self.command.id)
        note(msg, *args)

    def warning(self, msg, *args):
        """Output a warning but add context."""
        msg = "WARNING: %s (%s)" % (msg, self.command.id)
        warning(msg, *args)

    def pre_process_files(self):
        """Prepare for committing."""
        self.revision_id = self.gen_revision_id()
        self.inv_delta = []
        # cache of texts for this commit, indexed by file-id
        self.lines_for_commit = {}

        # Work out the true set of parents
        cmd = self.command
        if cmd.mark is None:
            last_id = self.cache_mgr.last_ids.get(cmd.ref)
            if last_id is not None:
                parents = [last_id]
            else:
                parents = []
        else:
            parents = cmd.parents

        # Track the heads
        for parent in parents:
            try:
                del self.cache_mgr.heads[parent]
            except KeyError:
                # it's ok if the parent isn't there - another
                # commit may have already removed it
                pass
        self.cache_mgr.heads[cmd.id] = cmd.ref

        # Get the parent inventories
        if parents:
            self.parents = [self.cache_mgr.revision_ids[p]
                for p in parents]
        else:
            self.parents = []

        # Seed the inventory from the previous one
        if len(self.parents) == 0:
            self.inventory = self.gen_initial_inventory()
        else:
            # use the bzr_revision_id to lookup the inv cache
            inv = self.get_inventory(self.parents[0])
            # TODO: Shallow copy - deep inventory copying is expensive
            self.inventory = inv.copy()
        if not self.repo.supports_rich_root():
            # In this repository, root entries have no knit or weave. When
            # serializing out to disk and back in, root.revision is always
            # the new revision_id.
            self.inventory.root.revision = self.revision_id

        # directory-path -> inventory-entry for current inventory
        self.directory_entries = dict(self.inventory.directories())

    def post_process_files(self):
        """Save the revision."""
        self.inventory.apply_delta(self.inv_delta)
        self.cache_mgr.inventories[self.revision_id] = self.inventory

        # Load the revision into the repository
        rev_props = {}
        committer = self.command.committer
        who = "%s <%s>" % (committer[0],committer[1])
        author = self.command.author
        if author is not None:
            author_id = "%s <%s>" % (author[0],author[1])
            if author_id != who:
                rev_props['author'] = author_id
        rev = revision.Revision(
           timestamp=committer[2],
           timezone=committer[3],
           committer=who,
           message=self._escape_commit_message(self.command.message),
           revision_id=self.revision_id,
           properties=rev_props,
           parent_ids=self.parents)
        self.loader.load(rev, self.inventory, None,
            lambda file_id: self._get_lines(file_id),
            lambda revision_ids: self._get_inventories(revision_ids))

    def _escape_commit_message(self, message):
        """Replace xml-incompatible control characters."""
        # It's crap that we need to do this at this level (but we do)
        # Code copied from bzrlib.commit.
        
        # Python strings can include characters that can't be
        # represented in well-formed XML; escape characters that
        # aren't listed in the XML specification
        # (http://www.w3.org/TR/REC-xml/#NT-Char).
        message, _ = re.subn(
            u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
            lambda match: match.group(0).encode('unicode_escape'),
            message)
        return message

    def modify_handler(self, filecmd):
        if filecmd.dataref is not None:
            data = self.cache_mgr.fetch_blob(filecmd.dataref)
        else:
            data = filecmd.data
        self._modify_inventory(filecmd.path, filecmd.kind,
            filecmd.is_executable, data)

    def delete_handler(self, filecmd):
        path = filecmd.path
        try:
            del self.inventory[self.bzr_file_id(path)]
        except KeyError:
            self.warning("ignoring delete of %s as not in inventory", path)
        except errors.NoSuchId:
            self.warning("ignoring delete of %s as not in inventory", path)
        try:
            self.cache_mgr._delete_path(path)
        except KeyError:
            pass

    def copy_handler(self, filecmd):
        raise NotImplementedError(self.copy_handler)

    def rename_handler(self, filecmd):
        old_path = filecmd.old_path
        new_path = filecmd.new_path
        file_id = self.bzr_file_id(old_path)
        ie = self.inventory[file_id]
        self.inv_delta.append((old_path, new_path, file_id, ie))
        self.cache_mgr._rename_path(old_path, new_path)

    def deleteall_handler(self, filecmd):
        raise NotImplementedError(self.deleteall_handler)

    def bzr_file_id_and_new(self, path):
        """Get a Bazaar file identifier and new flag for a path.
        
        :return: file_id, is_new where
          is_new = True if the file_id is newly created
        """
        try:
            return self.cache_mgr.file_ids[path], False
        except KeyError:
            id = generate_ids.gen_file_id(path)
            self.cache_mgr.file_ids[path] = id
            return id, True

    def bzr_file_id(self, path):
        """Get a Bazaar file identifier for a path."""
        return self.bzr_file_id_and_new(path)[0]

    def gen_initial_inventory(self):
        """Generate an inventory for a parentless revision."""
        inv = inventory.Inventory(revision_id=self.revision_id)
        return inv

    def gen_revision_id(self):
        """Generate a revision id.

        Subclasses may override this to produce deterministic ids say.
        """
        committer = self.command.committer
        # Perhaps 'who' being the person running the import is ok? If so,
        # it might be a bit quicker and give slightly better compression?
        who = "%s <%s>" % (committer[0],committer[1])
        timestamp = committer[2]
        return generate_ids.gen_revision_id(who, timestamp)

    def get_inventory(self, revision_id):
        """Get the inventory for a revision id."""
        try:
            inv = self.cache_mgr.inventories[revision_id]
        except KeyError:
            if self.verbose:
                self.note("get_inventory cache miss for %s", revision_id)
            # Not cached so reconstruct from repository
            inv = self.repo.revision_tree(revision_id).inventory
            self.cache_mgr.inventories[revision_id] = inv
        return inv

    def _get_inventories(self, revision_ids):
        """Get the inventories for revision-ids.
        
        This is a callback used by the RepositoryLoader to
        speed up inventory reconstruction."""
        present = []
        inventories = []
        # If an inventory is in the cache, we assume it was
        # successfully loaded into the repsoitory
        for revision_id in revision_ids:
            try:
                inv = self.cache_mgr.inventories[revision_id]
                present.append(revision_id)
            except KeyError:
                if self.verbose:
                    self.note("get_inventories cache miss for %s", revision_id)
                # Not cached so reconstruct from repository
                if self.repo.has_revision(revision_id):
                    rev_tree = self.repo.revision_tree(revision_id)
                    present.append(revision_id)
                else:
                    rev_tree = self.repo.revision_tree(None)
                inv = rev_tree.inventory
                self.cache_mgr.inventories[revision_id] = inv
            inventories.append(inv)
        return present, inventories

    def _get_lines(self, file_id):
        """Get the lines for a file-id."""
        return self.lines_for_commit[file_id]

    def _modify_inventory(self, path, kind, is_executable, data):
        """Add to or change an item in the inventory."""
        # Create the new InventoryEntry
        basename, parent_ie = self._ensure_directory(path)
        file_id = self.bzr_file_id(path)
        ie = inventory.make_entry(kind, basename, parent_ie.file_id, file_id)
        ie.revision = self.revision_id
        if isinstance(ie, inventory.InventoryFile):
            ie.executable = is_executable
            lines = osutils.split_lines(data)
            ie.text_sha1 = osutils.sha_strings(lines)
            ie.text_size = sum(map(len, lines))
            self.lines_for_commit[file_id] = lines
        elif isinstance(ie, inventory.InventoryLnk):
            ie.symlink_target = data
        else:
            raise errors.BzrError("Cannot import items of kind '%s' yet" %
                (kind,))

        # Record this new inventory entry
        if file_id in self.inventory:
            # HACK: no API for this (del+add does more than it needs to)
            self.inventory._byid[file_id] = ie
        else:
            self.inventory.add(ie)

    def _ensure_directory(self, path):
        """Ensure that the containing directory exists for 'path'"""
        dirname, basename = osutils.split(path)
        if dirname == '':
            # the root node doesn't get updated
            return basename, self.inventory.root
        try:
            ie = self.directory_entries[dirname]
        except KeyError:
            # We will create this entry, since it doesn't exist
            pass
        else:
            return basename, ie

        # No directory existed, we will just create one, first, make sure
        # the parent exists
        dir_basename, parent_ie = self._ensure_directory(dirname)
        dir_file_id = self.bzr_file_id(dirname)
        ie = inventory.entry_factory['directory'](dir_file_id,
                                                  dir_basename,
                                                  parent_ie.file_id)
        ie.revision = self.revision_id
        self.directory_entries[dirname] = ie
        # There are no lines stored for a directory so
        # make sure the cache used by get_lines knows that
        self.lines_for_commit[dir_file_id] = []
        #print "adding dir for %s" % path
        self.inventory.add(ie)
        return basename, ie


class GenericBranchUpdater(object):

    def __init__(self, repo, branch, cache_mgr, heads_by_ref, last_ref):
        """Create an object responsible for updating branches.

        :param heads_by_ref: a dictionary where
          names are git-style references like refs/heads/master;
          values are one item lists of commits marks.
        """
        self.repo = repo
        self.branch = branch
        self.cache_mgr = cache_mgr
        self.heads_by_ref = heads_by_ref
        self.last_ref = last_ref

    def update(self):
        """Update the Bazaar branches and tips matching the heads.

        If the repository is shared, this routine creates branches
        as required. If it isn't, warnings are produced about the
        lost of information.

        :return: updated, lost_heads where
          updated = the list of branches updated
          lost_heads = a list of (bazaar-name,revision) for branches that
            would have been created had the repository been shared
        """
        updated = []
        branch_tips, lost_heads = self._get_matching_branches()
        for br, tip in branch_tips:
            self._update_branch(br, tip)
            updated.append(br)
        return updated, lost_heads

    def _get_matching_branches(self):
        """Get the Bazaar branches.

        :return: default_tip, branch_tips, lost_tips where
          default_tip = the last commit mark for the default branch
          branch_tips = a list of (branch,tip) tuples for other branches.
          lost_heads = a list of (bazaar-name,revision) for branches that
            would have been created had the repository been shared and
            everything succeeded
        """
        branch_tips = []
        lost_heads = []
        ref_names = self.heads_by_ref.keys()
        if self.branch is not None:
            trunk = self.select_trunk(ref_names)
            default_tip = self.heads_by_ref[trunk][0]
            branch_tips.append((self.branch, default_tip))
            ref_names.remove(trunk)

        # Convert the reference names into Bazaar speak
        bzr_names = self._get_bzr_names_from_ref_names(ref_names)

        # Policy for locating branches
        def dir_under_current(name, ref_name):
            # Using the Bazaar name, get a directory under the current one
            return name
        def dir_sister_branch(name, ref_name):
            # Using the Bazaar name, get a sister directory to the branch
            return osutils.pathjoin(self.branch.base, "..", name)
        if self.branch is not None:
            dir_policy = dir_sister_branch
        else:
            dir_policy = dir_under_current

        # Create/track missing branches
        shared_repo = self.repo.is_shared()
        for name in sorted(bzr_names.keys()):
            ref_name = bzr_names[name]
            tip = self.heads_by_ref[ref_name][0]
            if shared_repo:
                location = dir_policy(name, ref_name)
                try:
                    br = self.make_branch(location)
                    branch_tips.append((br,tip))
                    continue
                except errors.BzrError, ex:
                    error("ERROR: failed to create branch %s: %s",
                        location, ex)
            lost_head = self.cache_mgr.revision_ids[tip]
            lost_info = (name, lost_head)
            lost_heads.append(lost_info)
        return branch_tips, lost_heads

    def select_trunk(self, ref_names):
        """Given a set of ref names, choose one as the trunk."""
        for candidate in ['refs/heads/master']:
            if candidate in ref_names:
                return candidate
        # Use the last reference in the import stream
        return self.last_ref

    def make_branch(self, location):
        """Create a branch in the repository."""
        return bzrdir.BzrDir.create_branch_convenience(location)

    def _get_bzr_names_from_ref_names(self, ref_names):
        """Generate Bazaar branch names from import ref names.
        
        :return: a dictionary with Bazaar names as keys and
          the original reference names as values.
        """
        bazaar_names = {}
        for ref_name in sorted(ref_names):
            parts = ref_name.split('/')
            if parts[0] == 'refs':
                parts.pop(0)
            full_name = "--".join(parts)
            bazaar_name = parts[-1]
            if bazaar_name in bazaar_names:
                bazaar_name = full_name
            bazaar_names[bazaar_name] = ref_name
        return bazaar_names

    def _update_branch(self, br, last_mark):
        """Update a branch with last revision and tag information."""
        last_rev_id = self.cache_mgr.revision_ids[last_mark]
        revno = len(list(self.repo.iter_reverse_revision_history(last_rev_id)))
        br.set_last_revision_info(revno, last_rev_id)
        # TODO: apply tags known in this branch
        #if self.tags:
        #    br.tags._set_tag_dict(self.tags)
        note("\t branch %s has %d revisions", br.nick, revno)
