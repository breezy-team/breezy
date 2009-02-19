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


import time
from bzrlib import (
    bzrdir,
    delta,
    errors,
    osutils,
    progress,
    )
from bzrlib.repofmt import pack_repo
from bzrlib.trace import note
import bzrlib.util.configobj.configobj as configobj
from bzrlib.plugins.fastimport import (
    branch_updater,
    bzr_commit_handler,
    cache_manager,
    errors as plugin_errors,
    helpers,
    idmapfile,
    marks_file,
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
    * some basic statistics are dumped on completion.

    At checkpoints and on completion, the commit-id -> revision-id map is
    saved to a file called 'fastimport-id-map'. If the import crashes
    or is interrupted, it can be started again and this file will be
    used to skip over already loaded revisions. The format of each line
    is "commit-id revision-id" so commit-ids cannot include spaces.

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

    * import-marks - name of file to read to load mark information from

    * export-marks - name of file to write to save mark information to
    """

    known_params = [
        'info',
        'trees',
        'checkpoint',
        'count',
        'inv-cache',
        'experimental',
        'import-marks',
        'export-marks',
        ]

    def pre_process(self):
        self._start_time = time.time()
        self._load_info_and_params()
        self.cache_mgr = cache_manager.CacheManager(self.info, self.verbose,
            self.inventory_cache_size)
        
        if self.params.get("import-marks") is not None:
            mark_info = marks_file.import_marks(self.params.get("import-marks"))
            if mark_info is not None:
                self.cache_mgr.revision_ids = mark_info[0]
            self.skip_total = False
            self.first_incremental_commit = True
        else:
            self.first_incremental_commit = False
            self.skip_total = self._init_id_map()
            if self.skip_total:
                self.note("Found %d commits already loaded - "
                    "skipping over these ...", self.skip_total)
        self._revision_count = 0

        # mapping of tag name to revision_id
        self.tags = {}

        # Create the revision loader to use for committing, if any
        self.loader = self._loader_factory()

        # Disable autopacking if the repo format supports it.
        # THIS IS A HACK - there is no sanctioned way of doing this yet.
        if isinstance(self.repo, pack_repo.KnitPackRepository):
            self._original_max_pack_count = \
                self.repo._pack_collection._max_pack_count
            def _max_pack_count_for_import(total_revisions):
                return total_revisions + 1
            self.repo._pack_collection._max_pack_count = \
                _max_pack_count_for_import
        else:
            self._original_max_pack_count = None
            
        # Create a write group. This is committed at the end of the import.
        # Checkpointing closes the current one and starts a new one.
        self.repo.start_write_group()

    def _load_info_and_params(self):
        self._experimental = bool(self.params.get('experimental', False))

        # This is currently hard-coded but might be configurable via
        # parameters one day if that's needed
        repo_transport = self.repo.control_files._transport
        self.id_map_path = repo_transport.local_abspath("fastimport-id-map")

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

    def _loader_factory(self):
        """Make a RevisionLoader based on what the repository supports."""
        new_repo_api = hasattr(self.repo, 'revisions')
        if new_repo_api:
            return revisionloader.RevisionLoader2(self.repo)
        elif not self._experimental:
            return revisionloader.RevisionLoader1(self.repo)
        else:
            def fulltext_when(count):
                total = self.total_commits
                if total is not None and count == total:
                    fulltext = True
                else:
                    # Create an inventory fulltext every 200 revisions
                    fulltext = count % 200 == 0
                if fulltext:
                    self.note("%d commits - storing inventory as full-text",
                        count)
                return fulltext

            return revisionloader.ImportRevisionLoader1(
                self.repo, self.inventory_cache_size,
                fulltext_when=fulltext_when)

    def _process(self, command_iter):
        # if anything goes wrong, abort the write group if any
        try:
            processor.ImportProcessor._process(self, command_iter)
        except:
            if self.repo is not None and self.repo.is_in_write_group():
                self.repo.abort_write_group()
            raise

    def post_process(self):
        # Commit the current write group and checkpoint the id map
        self.repo.commit_write_group()
        self._save_id_map()

        if self.params.get("export-marks") is not None:
            marks_file.export_marks(self.params.get("export-marks"),
                self.cache_mgr.revision_ids)

        # Update the branches
        self.note("Updating branch information ...")
        updater = branch_updater.BranchUpdater(self.repo, self.branch,
            self.cache_mgr, helpers.invert_dictset(self.cache_mgr.heads),
            self.cache_mgr.last_ref, self.tags)
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
                self.note("\t %s = %s", head_revision, branch_name)

        # Update the working trees as requested and dump stats
        self._tree_count = 0
        remind_about_update = True
        if self._branch_count == 0:
            self.note("no branches to update")
            self.note("no working trees to update")
            remind_about_update = False
        elif self.params.get('trees', False):
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

        # Finish up by telling the user what to do next.
        if self._original_max_pack_count:
            # We earlier disabled autopacking, creating one pack every
            # checkpoint instead. We now pack the repository to optimise
            # how data is stored.
            if self._revision_count > self.checkpoint_every:
                self.note("Packing repository ...")
                self.repo.pack()
                # To be conservative, packing puts the old packs and
                # indices in obsolete_packs. We err on the side of
                # optimism and clear out that directory to save space.
                self.note("Removing obsolete packs ...")
                # TODO: Use a public API for this once one exists
                repo_transport = self.repo._pack_collection.transport
                repo_transport.clone('obsolete_packs').delete_multi(
                    repo_transport.list_dir('obsolete_packs'))
        if remind_about_update:
            # This message is explicitly not timestamped.
            note("To refresh the working tree for a branch, "
                "use 'bzr update'.")

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

    def dump_stats(self):
        time_required = progress.str_tdelta(time.time() - self._start_time)
        rc = self._revision_count - self.skip_total
        bc = self._branch_count
        wtc = self._tree_count
        self.note("Imported %d %s, updating %d %s and %d %s in %s",
            rc, helpers.single_plural(rc, "revision", "revisions"),
            bc, helpers.single_plural(bc, "branch", "branches"),
            wtc, helpers.single_plural(wtc, "tree", "trees"),
            time_required)

    def _init_id_map(self):
        """Load the id-map and check it matches the repository.
        
        :return: the number of entries in the map
        """
        # Currently, we just check the size. In the future, we might
        # decide to be more paranoid and check that the revision-ids
        # are identical as well.
        self.cache_mgr.revision_ids, known = idmapfile.load_id_map(
            self.id_map_path)
        existing_count = len(self.repo.all_revision_ids())
        if existing_count < known:
            raise plugin_errors.BadRepositorySize(known, existing_count)
        return known

    def _save_id_map(self):
        """Save the id-map."""
        # Save the whole lot every time. If this proves a problem, we can
        # change to 'append just the new ones' at a later time.
        idmapfile.save_id_map(self.id_map_path, self.cache_mgr.revision_ids)

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
        self._save_id_map()
        self.repo.start_write_group()

    def commit_handler(self, cmd):
        """Process a CommitCommand."""
        if self.skip_total and self._revision_count < self.skip_total:
            self.cache_mgr.track_heads(cmd)
            # Check that we really do know about this commit-id
            if not self.cache_mgr.revision_ids.has_key(cmd.id):
                raise plugin_errors.BadRestart(cmd.id)
            # Consume the file commands and free any non-sticky blobs
            for fc in cmd.file_iter():
                pass
            self.cache_mgr._blobs = {}
            self._revision_count += 1
            # If we're finished getting back to where we were,
            # load the file-ids cache
            if self._revision_count == self.skip_total:
                self._gen_file_ids_cache()
                self.note("Generated the file-ids cache - %d entries",
                    len(self.cache_mgr.file_ids.keys()))
            return
        if self.first_incremental_commit:
            self.first_incremental_commit = None
            parents = self.cache_mgr.track_heads(cmd)
            self._gen_file_ids_cache(parents)

        # 'Commit' the revision and report progress
        handler = bzr_commit_handler.InventoryCommitHandler(cmd,
            self.cache_mgr, self.repo, self.loader, verbose=self.verbose)
        handler.process()
        self.cache_mgr.revision_ids[cmd.id] = handler.revision_id
        self._revision_count += 1
        self.report_progress("(%s)" % cmd.id)

        # Check if we should finish up or automatically checkpoint
        if (self.max_commits is not None and
            self._revision_count >= self.max_commits):
            self.note("Stopping after reaching requested count of commits")
            self.finished = True
        elif self._revision_count % self.checkpoint_every == 0:
            self.note("%d commits - automatic checkpoint triggered",
                self._revision_count)
            self.checkpoint_handler(None)

    def _gen_file_ids_cache(self, revs=False):
        """Generate the file-id cache by searching repository inventories.
        """
        # Get the interesting revisions - the heads
        if revs:
            head_ids = revs
        else:
            head_ids = self.cache_mgr.heads.keys()
        revision_ids = [self.cache_mgr.revision_ids[h] for h in head_ids]

        # Update the fileid cache
        file_ids = {}
        for revision_id in revision_ids:
            inv = self.repo.revision_tree(revision_id).inventory
            # Cache the inventories while we're at it
            self.cache_mgr.inventories[revision_id] = inv
            for path, ie in inv.iter_entries():
                file_ids[path] = ie.file_id
        self.cache_mgr.file_ids = file_ids

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
            tag_name = cmd.ref[len('refs/tags/'):]
            if cmd.from_ is not None:
                self._set_tag(tag_name, cmd.from_)
            elif self.verbose:
                self.warning("ignoring reset refs/tags/%s - no from clause"
                    % tag_name)
            return

	# FIXME: cmd.from_ is a committish and thus could reference
	# another branch.  Create a method for resolving commitish's.
        if cmd.from_ is not None:
            self.cache_mgr.track_heads_for_ref(cmd.ref, cmd.from_)

    def tag_handler(self, cmd):
        """Process a TagCommand."""
        if cmd.from_ is not None:
            self._set_tag(cmd.id, cmd.from_)
        else:
            self.warning("ignoring tag %s - no from clause" % cmd.id)

    def _set_tag(self, name, from_):
        """Define a tag given a name and import 'from' reference."""
        bzr_tag_name = name.decode('utf-8', 'replace')
        bzr_rev_id = self.cache_mgr.revision_ids[from_]
        self.tags[bzr_tag_name] = bzr_rev_id
