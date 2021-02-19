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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Import processor that supports all Bazaar repository formats."""


import time
from .... import (
    debug,
    delta,
    errors,
    osutils,
    progress,
    revision as _mod_revision,
    )
from ....bzr.knitpack_repo import KnitPackRepository
from ....trace import (
    mutter,
    note,
    warning,
    )
import configobj
from .. import (
    branch_updater,
    cache_manager,
    helpers,
    idmapfile,
    marks_file,
    revision_store,
    )
from fastimport import (
    commands,
    errors as plugin_errors,
    processor,
    )
from fastimport.helpers import (
    invert_dictset,
    )


# How many commits before automatically reporting progress
_DEFAULT_AUTO_PROGRESS = 1000

# How many commits before automatically checkpointing
_DEFAULT_AUTO_CHECKPOINT = 10000

# How many checkpoints before automatically packing
_DEFAULT_AUTO_PACK = 4

# How many inventories to cache
_DEFAULT_INV_CACHE_SIZE = 1
_DEFAULT_CHK_INV_CACHE_SIZE = 1


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

    * count - only import this many commits then exit. If not set
      or negative, all commits are imported.

    * checkpoint - automatically checkpoint every n commits over and
      above any checkpoints contained in the import stream.
      The default is 10000.

    * autopack - pack every n checkpoints. The default is 4.

    * inv-cache - number of inventories to cache.
      If not set, the default is 1.

    * mode - import algorithm to use: default or experimental.

    * import-marks - name of file to read to load mark information from

    * export-marks - name of file to write to save mark information to
    """

    known_params = [
        'info',
        'trees',
        'count',
        'checkpoint',
        'autopack',
        'inv-cache',
        'mode',
        'import-marks',
        'export-marks',
        ]

    def __init__(self, bzrdir, params=None, verbose=False, outf=None,
                 prune_empty_dirs=True):
        processor.ImportProcessor.__init__(self, params, verbose)
        self.prune_empty_dirs = prune_empty_dirs
        self.controldir = bzrdir
        try:
            # Might be inside a branch
            (self.working_tree, self.branch) = bzrdir._get_tree_branch()
            self.repo = self.branch.repository
        except errors.NotBranchError:
            # Must be inside a repository
            self.working_tree = None
            self.branch = None
            self.repo = bzrdir.open_repository()

    def pre_process(self):
        self._start_time = time.time()
        self._load_info_and_params()
        if self.total_commits:
            self.note("Starting import of %d commits ..." %
                      (self.total_commits,))
        else:
            self.note("Starting import ...")
        self.cache_mgr = cache_manager.CacheManager(self.info, self.verbose,
                                                    self.inventory_cache_size)

        if self.params.get("import-marks") is not None:
            mark_info = marks_file.import_marks(
                self.params.get("import-marks"))
            if mark_info is not None:
                self.cache_mgr.marks = mark_info
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

        # Create the revision store to use for committing, if any
        self.rev_store = self._revision_store_factory()

        # Disable autopacking if the repo format supports it.
        # THIS IS A HACK - there is no sanctioned way of doing this yet.
        if isinstance(self.repo, KnitPackRepository):
            self._original_max_pack_count = \
                self.repo._pack_collection._max_pack_count

            def _max_pack_count_for_import(total_revisions):
                return total_revisions + 1
            self.repo._pack_collection._max_pack_count = \
                _max_pack_count_for_import
        else:
            self._original_max_pack_count = None

        # Make groupcompress use the fast algorithm during importing.
        # We want to repack at the end anyhow when more information
        # is available to do a better job of saving space.
        try:
            from .... import groupcompress
            groupcompress._FAST = True
        except ImportError:
            pass

        # Create a write group. This is committed at the end of the import.
        # Checkpointing closes the current one and starts a new one.
        self.repo.start_write_group()

    def _load_info_and_params(self):
        from .. import bzr_commit_handler
        # This is currently hard-coded but might be configurable via
        # parameters one day if that's needed
        repo_transport = self.repo.control_transport
        self.id_map_path = repo_transport.local_abspath("fastimport-id-map")

        # Load the info file, if any
        info_path = self.params.get('info')
        if info_path is not None:
            self.info = configobj.ConfigObj(info_path)
        else:
            self.info = None

        self.supports_chk = self.repo._format.supports_chks
        self.commit_handler_factory = bzr_commit_handler.CommitHandler

        # Decide how often to automatically report progress
        # (not a parameter yet)
        self.progress_every = _DEFAULT_AUTO_PROGRESS
        if self.verbose:
            self.progress_every = self.progress_every / 10

        # Decide how often (# of commits) to automatically checkpoint
        self.checkpoint_every = int(self.params.get('checkpoint',
                                                    _DEFAULT_AUTO_CHECKPOINT))

        # Decide how often (# of checkpoints) to automatically pack
        self.checkpoint_count = 0
        self.autopack_every = int(self.params.get('autopack',
                                                  _DEFAULT_AUTO_PACK))

        # Decide how big to make the inventory cache
        cache_size = int(self.params.get('inv-cache', -1))
        if cache_size == -1:
            if self.supports_chk:
                cache_size = _DEFAULT_CHK_INV_CACHE_SIZE
            else:
                cache_size = _DEFAULT_INV_CACHE_SIZE
        self.inventory_cache_size = cache_size

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
            if (self.max_commits is not None
                    and self.total_commits > self.max_commits):
                self.total_commits = self.max_commits
        else:
            self.total_commits = self.max_commits

    def _revision_store_factory(self):
        """Make a RevisionStore based on what the repository supports."""
        return revision_store.RevisionStore(self.repo)

    def process(self, command_iter):
        """Import data into Bazaar by processing a stream of commands.

        :param command_iter: an iterator providing commands
        """
        if self.working_tree is not None:
            self.working_tree.lock_write()
        elif self.branch is not None:
            self.branch.lock_write()
        elif self.repo is not None:
            self.repo.lock_write()
        try:
            super(GenericProcessor, self)._process(command_iter)
        finally:
            # If an unhandled exception occurred, abort the write group
            if self.repo is not None and self.repo.is_in_write_group():
                self.repo.abort_write_group()
            # Release the locks
            if self.working_tree is not None:
                self.working_tree.unlock()
            elif self.branch is not None:
                self.branch.unlock()
            elif self.repo is not None:
                self.repo.unlock()

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
                                    self.cache_mgr.marks)

        if self.cache_mgr.reftracker.last_ref is None:
            """Nothing to refresh"""
            return

        # Update the branches
        self.note("Updating branch information ...")
        updater = branch_updater.BranchUpdater(self.repo, self.branch,
                                               self.cache_mgr, invert_dictset(
                                                   self.cache_mgr.reftracker.heads),
                                               self.cache_mgr.reftracker.last_ref, self.tags)
        branches_updated, branches_lost = updater.update()
        self._branch_count = len(branches_updated)

        # Tell the user about branches that were not created
        if branches_lost:
            if not self.repo.is_shared():
                self.warning("Cannot import multiple branches into "
                             "a standalone branch")
            self.warning("Not creating branches for these head revisions:")
            for lost_info in branches_lost:
                head_revision = lost_info[1]
                branch_name = lost_info[0]
                self.note("\t %s = %s", head_revision, branch_name)

        # Update the working trees as requested
        self._tree_count = 0
        remind_about_update = True
        if self._branch_count == 0:
            self.note("no branches to update")
            self.note("no working trees to update")
            remind_about_update = False
        elif self.params.get('trees', False):
            trees = self._get_working_trees(branches_updated)
            if trees:
                self._update_working_trees(trees)
                remind_about_update = False
            else:
                self.warning("No working trees available to update")
        else:
            # Update just the trunk. (This is always the first branch
            # returned by the branch updater.)
            trunk_branch = branches_updated[0]
            trees = self._get_working_trees([trunk_branch])
            if trees:
                self._update_working_trees(trees)
                remind_about_update = self._branch_count > 1

        # Dump the cache stats now because we clear it before the final pack
        if self.verbose:
            self.cache_mgr.dump_stats()
        if self._original_max_pack_count:
            # We earlier disabled autopacking, creating one pack every
            # checkpoint instead. We now pack the repository to optimise
            # how data is stored.
            self.cache_mgr.clear_all()
            self._pack_repository()

        # Finish up by dumping stats & telling the user what to do next.
        self.dump_stats()
        if remind_about_update:
            # This message is explicitly not timestamped.
            note("To refresh the working tree for other branches, "
                 "use 'bzr update' inside that branch.")

    def _update_working_trees(self, trees):
        if self.verbose:
            reporter = delta._ChangeReporter()
        else:
            reporter = None
        for wt in trees:
            self.note("Updating the working tree for %s ...", wt.basedir)
            wt.update(reporter)
            self._tree_count += 1

    def _pack_repository(self, final=True):
        # Before packing, free whatever memory we can and ensure
        # that groupcompress is configured to optimise disk space
        import gc
        if final:
            try:
                from .... import groupcompress
            except ImportError:
                pass
            else:
                groupcompress._FAST = False
        gc.collect()
        self.note("Packing repository ...")
        self.repo.pack()

        # To be conservative, packing puts the old packs and
        # indices in obsolete_packs. We err on the side of
        # optimism and clear out that directory to save space.
        self.note("Removing obsolete packs ...")
        # TODO: Use a public API for this once one exists
        repo_transport = self.repo._pack_collection.transport
        obsolete_pack_transport = repo_transport.clone('obsolete_packs')
        for name in obsolete_pack_transport.list_dir('.'):
            obsolete_pack_transport.delete(name)

        # If we're not done, free whatever memory we can
        if not final:
            gc.collect()

    def _get_working_trees(self, branches):
        """Get the working trees for branches in the repository."""
        result = []
        wt_expected = self.repo.make_working_trees()
        for br in branches:
            if br is None:
                continue
            elif br == self.branch:
                if self.working_tree:
                    result.append(self.working_tree)
            elif wt_expected:
                try:
                    result.append(br.controldir.open_workingtree())
                except errors.NoWorkingTree:
                    self.warning("No working tree for branch %s", br)
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
        self.cache_mgr.marks, known = idmapfile.load_id_map(
            self.id_map_path)
        if self.cache_mgr.add_mark(b'0', _mod_revision.NULL_REVISION):
            known += 1

        existing_count = len(self.repo.all_revision_ids())
        if existing_count < known:
            raise plugin_errors.BadRepositorySize(known, existing_count)
        return known

    def _save_id_map(self):
        """Save the id-map."""
        # Save the whole lot every time. If this proves a problem, we can
        # change to 'append just the new ones' at a later time.
        idmapfile.save_id_map(self.id_map_path, self.cache_mgr.marks)

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
        # track the number of automatic checkpoints done
        if cmd is None:
            self.checkpoint_count += 1
            if self.checkpoint_count % self.autopack_every == 0:
                self._pack_repository(final=False)
        self.repo.start_write_group()

    def commit_handler(self, cmd):
        """Process a CommitCommand."""
        mark = cmd.id.lstrip(b':')
        if self.skip_total and self._revision_count < self.skip_total:
            self.cache_mgr.reftracker.track_heads(cmd)
            # Check that we really do know about this commit-id
            if mark not in self.cache_mgr.marks:
                raise plugin_errors.BadRestart(mark)
            self.cache_mgr._blobs = {}
            self._revision_count += 1
            if cmd.ref.startswith(b'refs/tags/'):
                tag_name = cmd.ref[len(b'refs/tags/'):]
                self._set_tag(tag_name, cmd.id)
            return
        if self.first_incremental_commit:
            self.first_incremental_commit = None
            parents = self.cache_mgr.reftracker.track_heads(cmd)

        # 'Commit' the revision and report progress
        handler = self.commit_handler_factory(cmd, self.cache_mgr,
                                              self.rev_store, verbose=self.verbose,
                                              prune_empty_dirs=self.prune_empty_dirs)
        try:
            handler.process()
        except:
            print("ABORT: exception occurred processing commit %s" % (cmd.id))
            raise
        self.cache_mgr.add_mark(mark, handler.revision_id)
        self._revision_count += 1
        self.report_progress("(%s)" % cmd.id.lstrip(b':'))

        if cmd.ref.startswith(b'refs/tags/'):
            tag_name = cmd.ref[len(b'refs/tags/'):]
            self._set_tag(tag_name, cmd.id)

        # Check if we should finish up or automatically checkpoint
        if (self.max_commits is not None
                and self._revision_count >= self.max_commits):
            self.note("Stopping after reaching requested count of commits")
            self.finished = True
        elif self._revision_count % self.checkpoint_every == 0:
            self.note("%d commits - automatic checkpoint triggered",
                      self._revision_count)
            self.checkpoint_handler(None)

    def report_progress(self, details=''):
        if self._revision_count % self.progress_every == 0:
            if self.total_commits is not None:
                counts = "%d/%d" % (self._revision_count, self.total_commits)
            else:
                counts = "%d" % (self._revision_count,)
            minutes = (time.time() - self._start_time) / 60
            revisions_added = self._revision_count - self.skip_total
            rate = revisions_added * 1.0 / minutes
            if rate > 10:
                rate_str = "at %.0f/minute " % rate
            else:
                rate_str = "at %.1f/minute " % rate
            self.note("%s commits processed %s%s" %
                      (counts, rate_str, details))

    def progress_handler(self, cmd):
        """Process a ProgressCommand."""
        # Most progress messages embedded in streams are annoying.
        # Ignore them unless in verbose mode.
        if self.verbose:
            self.note("progress %s" % (cmd.message,))

    def reset_handler(self, cmd):
        """Process a ResetCommand."""
        if cmd.ref.startswith(b'refs/tags/'):
            tag_name = cmd.ref[len(b'refs/tags/'):]
            if cmd.from_ is not None:
                self._set_tag(tag_name, cmd.from_)
            elif self.verbose:
                self.warning("ignoring reset refs/tags/%s - no from clause"
                             % tag_name)
            return

        if cmd.from_ is not None:
            self.cache_mgr.reftracker.track_heads_for_ref(cmd.ref, cmd.from_)

    def tag_handler(self, cmd):
        """Process a TagCommand."""
        if cmd.from_ is not None:
            self._set_tag(cmd.id, cmd.from_)
        else:
            self.warning("ignoring tag %s - no from clause" % cmd.id)

    def _set_tag(self, name, from_):
        """Define a tag given a name and import 'from' reference."""
        bzr_tag_name = name.decode('utf-8', 'replace')
        bzr_rev_id = self.cache_mgr.lookup_committish(from_)
        self.tags[bzr_tag_name] = bzr_rev_id

    def feature_handler(self, cmd):
        """Process a FeatureCommand."""
        feature = cmd.feature_name
        if feature not in commands.FEATURE_NAMES:
            raise plugin_errors.UnknownFeature(feature)

    def debug(self, msg, *args):
        """Output a debug message if the appropriate -D option was given."""
        if "fast-import" in debug.debug_flags:
            msg = "%s DEBUG: %s" % (self._time_of_day(), msg)
            mutter(msg, *args)

    def note(self, msg, *args):
        """Output a note but timestamp it."""
        msg = "%s %s" % (self._time_of_day(), msg)
        note(msg, *args)

    def warning(self, msg, *args):
        """Output a warning but timestamp it."""
        msg = "%s WARNING: %s" % (self._time_of_day(), msg)
        warning(msg, *args)
