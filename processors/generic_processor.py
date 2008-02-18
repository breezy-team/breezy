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
    delta,
    errors,
    generate_ids,
    inventory,
    lru_cache,
    osutils,
    revision,
    revisiontree,
    )
from bzrlib.trace import (
    note,
    warning,
    )
import bzrlib.util.configobj.configobj as configobj
from bzrlib.plugins.fastimport import (
    processor,
    revisionloader,
    )


def _single_plural(n, single, plural):
    """Return a single or plural form of a noun based on number."""
    if n == 1:
        return single
    else:
        return plural


class GenericProcessor(processor.ImportProcessor):
    """An import processor that handles basic imports.

    Current features supported:

    * timestamped progress reporting
    * blobs are cached in memory
    * commits are processed
    * tags are stored in the current branch
    * LATER: named branch support
    * checkpoints are ignored
    * some basic statistics are dumped on completion.

    Here are the supported parameters:

    * info - name of a config file holding the analysis generated
      by running the --info processor (this is important for knowing
      what to intelligently cache)
    """

    known_params = ['info']

    def pre_process(self):
        # Load the info file, if any
        info_path = self.params.get('info')
        if info_path is not None:
            self.info = configobj.ConfigObj(info_path)
        else:
            self.info = None

        self.cache_mgr = GenericCacheManager(self.info, verbose=self.verbose)
        self.active_branch = self.branch
        self.init_stats()
        # mapping of tag name to revision_id
        self.tags = {}

        # Prepare progress reporting
        if self.info is not None:
            self.total_commits = int(self.info['Command counts']['commit'])
        else:
            self.total_commits = None

    def post_process(self):
        self.dump_stats()
        # Update the branches, assuming the last revision is the head
        note("Updating branch information ...")
        # TODO - loop over the branches created/modified
        last_rev_id = self.cache_mgr.last_revision_ids[self.branch]
        revno = len(list(self.repo.iter_reverse_revision_history(last_rev_id)))
        self.branch.set_last_revision_info(revno, last_rev_id)
        if self.tags:
            self.branch.tags._set_tag_dict(self.tags)
        # Update the working tree, if any
        if self.working_tree:
            self.working_tree.update(delta._ChangeReporter())

    def init_stats(self):
        self._revision_count = 0
        self._branch_count = 1
        self._tag_count = 0

    def dump_stats(self):
        rc = self._revision_count
        bc = self._branch_count
        tc = self._tag_count
        note("Imported %d %s into %d %s with %d %s.",
            rc, _single_plural(rc, "revision", "revisions"),
            bc, _single_plural(bc, "branch", "branches"),
            tc, _single_plural(tc, "tag", "tags"))

    def blob_handler(self, cmd):
        """Process a BlobCommand."""
        if cmd.mark is not None:
            dataref = ":%s" % (cmd.mark,)
        else:
            dataref = osutils.sha_strings(cmd.data)
        self.cache_mgr.store_blob(dataref, cmd.data)

    def checkpoint_handler(self, cmd):
        """Process a CheckpointCommand."""
        warning("ignoring checkpoint")

    def commit_handler(self, cmd):
        """Process a CommitCommand."""
        handler = GenericCommitHandler(cmd, self.repo, self.cache_mgr,
            self.active_branch, self.verbose)
        # For now, put a write group around every commit. In the future,
        # we might only start/commit one every N to sppeed things up
        self.repo.start_write_group()
        try:
            handler.process()
            rev_id = handler.revision_id
            self.cache_mgr.revision_ids[cmd.ref] = rev_id
            if cmd.mark is not None:
                self.cache_mgr.revision_ids[":" + cmd.mark] = rev_id
            self.cache_mgr.last_revision_ids[self.active_branch] = rev_id
            self._revision_count += 1
            self.report_progress("(%s)" % cmd.mark)
        except:
            self.repo.abort_write_group()
            raise
        else:
            self.repo.commit_write_group()

    def report_progress(self, details=''):
        #if self._revision_count % 10 != 0:
        #    return
        # TODO: use a progress bar with ETA enabled
        if self.total_commits is not None:
            counts = "%d/%d" % (self._revision_count, self.total_commits)
        else:
            counts = "%d" % (self._revision_count,)
        note("%s %s commits loaded %s" % (self._time_of_day(), counts,
            details))

    def progress_handler(self, cmd):
        """Process a ProgressCommand."""
        # We could use a progress bar here but timestamped messages
        # is more useful for determining when things might complete
        note("%s progress %s" % (self._time_of_day(), cmd.message))

    def _time_of_day(self):
        """Time of day as a string."""
        # Note: this is a separate method so tests can patch in a fixed value
        return time.strftime("%H:%M:%S")

    def reset_handler(self, cmd):
        """Process a ResetCommand."""
        if cmd.ref.startswith('refs/tags/'):
            self._set_tag(cmd.ref[len('refs/tags/'):], cmd.from_)
        else:
            warning("named branches are not supported yet"
                " - ignoring reset of '%s'", cmd.ref)

    def tag_handler(self, cmd):
        """Process a TagCommand."""
        self._set_tag(cmd.id, cmd.from_)

    def _set_tag(self, name, from_):
        """Define a tag given a name an import 'from' reference."""
        bzr_tag_name = name.decode('utf-8', 'replace')
        bzr_rev_id = self.cache_mgr.revision_ids[from_]
        self.tags[bzr_tag_name] = bzr_rev_id
        self._tag_count += 1


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

        # branch -> last revision-id lookup table
        self.last_revision_ids = {}

        # path -> file-ids - as generated
        self.file_ids = {}

        # Work out the blobs to make sticky - None means all
        #print "%r" % (info,)
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
            if self.verbose:
                print "making blob %s sticky" % (id,)
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

    def __init__(self, command, repo, cache_mgr, active_branch, verbose=False):
        processor.CommitHandler.__init__(self, command)
        self.repo = repo
        self.cache_mgr = cache_mgr
        self.active_branch = active_branch
        self.verbose = verbose
        # smart loader that uses these caches
        self.loader = revisionloader.RevisionLoader(repo,
            lambda revision_ids: self._get_inventories(revision_ids))

    def pre_process_files(self):
        """Prepare for committing."""
        self.revision_id = self.gen_revision_id()
        self.inv_delta = []
        # cache of texts for this commit, indexed by file-id
        self.lines_for_commit = {}

        # Get the parent inventories
        if self.command.parents:
            self.parents = [self.cache_mgr.revision_ids[ref]
                for ref in self.command.parents]
        else:
            # if no parents are given, the last revision on
            # the current branch is assumed according to the spec
            last_rev = self.cache_mgr.last_revision_ids.get(
                    self.active_branch)
            if last_rev:
                self.parents = [last_rev]
            else:
                self.parents = []

        # Seed the inventory from the previous one
        if len(self.parents) == 0:
            self.inventory = self.gen_initial_inventory()
        else:
            # use the bzr_revision_id to lookup the inv cache
            self.inventory = self.get_inventory(self.parents[0]).copy()
        if not self.repo.supports_rich_root():
            # In this repository, root entries have no knit or weave. When
            # serializing out to disk and back in, root.revision is always
            # the new revision_id.
            self.inventory.root.revision = self.revision_id

        # directory-path -> inventory-entry for current inventory
        self.directory_entries = dict(self.inventory.directories())

    def post_process_files(self):
        """Save the revision."""
        if self.verbose:
            note("applying inventory delta ...")
            for entry in self.inv_delta:
                note("  %r" % (entry,))
        self.inventory.apply_delta(self.inv_delta)
        self.cache_mgr.inventories[self.revision_id] = self.inventory
        if self.verbose:
            note("created inventory ...")
            for entry in self.inventory:
                note("  %r" % (entry,))

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
            lambda file_id: self._get_lines(file_id))

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
        except errors.NoSuchId:
            warning("ignoring delete of %s - not in inventory" % (path,))
        finally:
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
            print "Hmm - get_inventory cache miss for %s" % revision_id
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
                print "Hmm - get_inventories cache miss for %s" % revision_id
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
        #print "adding dir %s" % path
        self.inventory.add(ie)
        return basename, ie
