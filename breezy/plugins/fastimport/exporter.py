# -*- coding: utf-8 -*-

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
#
# Based on bzr-fast-export
# Copyright (c) 2008 Adeodato Simó
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# vim: fileencoding=utf-8

"""Core engine for the fast-export command."""

# TODO: if a new_git_branch below gets merged repeatedly, the tip of the branch
# is not updated (because the parent of commit is already merged, so we don't
# set new_git_branch to the previously used name)

from email.utils import parseaddr
import sys
import time
import re

import breezy.branch
import breezy.revision
from ... import (
    builtins,
    errors,
    lazy_import,
    lru_cache,
    osutils,
    progress,
    trace,
    transport as _mod_transport,
    )

from . import (
    helpers,
    marks_file,
    )

lazy_import.lazy_import(globals(),
                        """
from fastimport import commands
""")

REVISIONS_CHUNK_SIZE = 1000


def _get_output_stream(destination):
    if destination is None or destination == '-':
        return helpers.binary_stream(getattr(sys.stdout, "buffer", sys.stdout))
    elif destination.endswith('.gz'):
        import gzip
        return gzip.open(destination, 'wb')
    else:
        return open(destination, 'wb')

# from dulwich.repo:


def check_ref_format(refname):
    """Check if a refname is correctly formatted.

    Implements all the same rules as git-check-ref-format[1].

    [1] http://www.kernel.org/pub/software/scm/git/docs/git-check-ref-format.html

    :param refname: The refname to check
    :return: True if refname is valid, False otherwise
    """
    # These could be combined into one big expression, but are listed separately
    # to parallel [1].
    if b'/.' in refname or refname.startswith(b'.'):
        return False
    if b'/' not in refname:
        return False
    if b'..' in refname:
        return False
    for i in range(len(refname)):
        if ord(refname[i:i + 1]) < 0o40 or refname[i] in b'\177 ~^:?*[':
            return False
    if refname[-1] in b'/.':
        return False
    if refname.endswith(b'.lock'):
        return False
    if b'@{' in refname:
        return False
    if b'\\' in refname:
        return False
    return True


def sanitize_ref_name_for_git(refname):
    """Rewrite refname so that it will be accepted by git-fast-import.
    For the detailed rules see check_ref_format.

    By rewriting the refname we are breaking uniqueness guarantees provided by bzr
    so we have to manually
    verify that resulting ref names are unique.

    :param refname: refname to rewrite
    :return: new refname
    """
    import struct
    new_refname = re.sub(
        # '/.' in refname or startswith '.'
        br"/\.|^\."
        # '..' in refname
        br"|\.\."
        # ord(c) < 040
        br"|[" + b"".join([bytes([x]) for x in range(0o40)]) + br"]"
        # c in '\177 ~^:?*['
        br"|[\177 ~^:?*[]"
        # last char in "/."
        br"|[/.]$"
        # endswith '.lock'
        br"|.lock$"
        # "@{" in refname
        br"|@{"
        # "\\" in refname
        br"|\\",
        b"_", refname)
    return new_refname


class BzrFastExporter(object):

    def __init__(self, source, outf, ref=None, checkpoint=-1,
                 import_marks_file=None, export_marks_file=None, revision=None,
                 verbose=False, plain_format=False, rewrite_tags=False,
                 no_tags=False, baseline=False):
        """Export branch data in fast import format.

        :param plain_format: if True, 'classic' fast-import format is
            used without any extended features; if False, the generated
            data is richer and includes information like multiple
            authors, revision properties, etc.
        :param rewrite_tags: if True and if plain_format is set, tag names
            will be rewritten to be git-compatible.
            Otherwise tags which aren't valid for git will be skipped if
            plain_format is set.
        :param no_tags: if True tags won't be exported at all
        """
        self.branch = source
        self.outf = outf
        self.ref = ref
        self.checkpoint = checkpoint
        self.import_marks_file = import_marks_file
        self.export_marks_file = export_marks_file
        self.revision = revision
        self.excluded_revisions = set()
        self.plain_format = plain_format
        self.rewrite_tags = rewrite_tags
        self.no_tags = no_tags
        self.baseline = baseline
        self.tree_cache = lru_cache.LRUCache(max_cache=20)
        self._multi_author_api_available = hasattr(breezy.revision.Revision,
                                                   'get_apparent_authors')
        self.properties_to_exclude = ['authors', 'author']

        # Progress reporting stuff
        self.verbose = verbose
        if verbose:
            self.progress_every = 100
        else:
            self.progress_every = 1000
        self._start_time = time.time()
        self._commit_total = 0

        # Load the marks and initialise things accordingly
        self.revid_to_mark = {}
        self.branch_names = {}
        if self.import_marks_file:
            marks_info = marks_file.import_marks(self.import_marks_file)
            if marks_info is not None:
                self.revid_to_mark = dict((r, m) for m, r in
                                          marks_info.items())
                # These are no longer included in the marks file
                #self.branch_names = marks_info[1]

    def interesting_history(self):
        if self.revision:
            rev1, rev2 = builtins._get_revision_range(
                self.revision, self.branch, "fast-export")
            start_rev_id = rev1.rev_id
            end_rev_id = rev2.rev_id
        else:
            start_rev_id = None
            end_rev_id = None
        self.note("Calculating the revisions to include ...")
        view_revisions = [rev_id for rev_id, _, _, _ in
                          self.branch.iter_merge_sorted_revisions(end_rev_id, start_rev_id)]
        view_revisions.reverse()
        # If a starting point was given, we need to later check that we don't
        # start emitting revisions from before that point. Collect the
        # revisions to exclude now ...
        if start_rev_id is not None:
            self.note("Calculating the revisions to exclude ...")
            self.excluded_revisions = set(
                [rev_id for rev_id, _, _, _ in self.branch.iter_merge_sorted_revisions(start_rev_id)])
            if self.baseline:
                # needed so the first relative commit knows its parent
                self.excluded_revisions.remove(start_rev_id)
                view_revisions.insert(0, start_rev_id)
        return list(view_revisions)

    def emit_commits(self, interesting):
        if self.baseline:
            revobj = self.branch.repository.get_revision(interesting.pop(0))
            self.emit_baseline(revobj, self.ref)
        for i in range(0, len(interesting), REVISIONS_CHUNK_SIZE):
            chunk = interesting[i:i + REVISIONS_CHUNK_SIZE]
            history = dict(self.branch.repository.iter_revisions(chunk))
            trees_needed = set()
            trees = {}
            for revid in chunk:
                trees_needed.update(self.preprocess_commit(revid, history[revid], self.ref))

            for tree in self._get_revision_trees(trees_needed):
                trees[tree.get_revision_id()] = tree

            for revid in chunk:
                revobj = history[revid]
                if len(revobj.parent_ids) == 0:
                    parent = breezy.revision.NULL_REVISION
                else:
                    parent = revobj.parent_ids[0]
                self.emit_commit(revobj, self.ref, trees[parent], trees[revid])

    def run(self):
        # Export the data
        with self.branch.repository.lock_read():
            interesting = self.interesting_history()
            self._commit_total = len(interesting)
            self.note("Starting export of %d revisions ..." %
                      self._commit_total)
            if not self.plain_format:
                self.emit_features()
            self.emit_commits(interesting)
            if self.branch.supports_tags() and not self.no_tags:
                self.emit_tags()

        # Save the marks if requested
        self._save_marks()
        self.dump_stats()

    def note(self, msg, *args):
        """Output a note but timestamp it."""
        msg = "%s %s" % (self._time_of_day(), msg)
        trace.note(msg, *args)

    def warning(self, msg, *args):
        """Output a warning but timestamp it."""
        msg = "%s WARNING: %s" % (self._time_of_day(), msg)
        trace.warning(msg, *args)

    def _time_of_day(self):
        """Time of day as a string."""
        # Note: this is a separate method so tests can patch in a fixed value
        return time.strftime("%H:%M:%S")

    def report_progress(self, commit_count, details=''):
        if commit_count and commit_count % self.progress_every == 0:
            if self._commit_total:
                counts = "%d/%d" % (commit_count, self._commit_total)
            else:
                counts = "%d" % (commit_count,)
            minutes = (time.time() - self._start_time) / 60
            rate = commit_count * 1.0 / minutes
            if rate > 10:
                rate_str = "at %.0f/minute " % rate
            else:
                rate_str = "at %.1f/minute " % rate
            self.note("%s commits exported %s%s" % (counts, rate_str, details))

    def dump_stats(self):
        time_required = progress.str_tdelta(time.time() - self._start_time)
        rc = len(self.revid_to_mark)
        self.note("Exported %d %s in %s",
                  rc, helpers.single_plural(rc, "revision", "revisions"),
                  time_required)

    def print_cmd(self, cmd):
        self.outf.write(b"%s\n" % cmd)

    def _save_marks(self):
        if self.export_marks_file:
            revision_ids = dict((m, r) for r, m in self.revid_to_mark.items())
            marks_file.export_marks(self.export_marks_file, revision_ids)

    def is_empty_dir(self, tree, path):
        # Continue if path is not a directory
        try:
            if tree.kind(path) != 'directory':
                return False
        except _mod_transport.NoSuchFile:
            self.warning("Skipping empty_dir detection - no file_id for %s" %
                         (path,))
            return False

        # Use treewalk to find the contents of our directory
        contents = list(tree.walkdirs(prefix=path))[0]
        if len(contents[1]) == 0:
            return True
        else:
            return False

    def emit_features(self):
        for feature in sorted(commands.FEATURE_NAMES):
            self.print_cmd(commands.FeatureCommand(feature))

    def emit_baseline(self, revobj, ref):
        # Emit a full source tree of the first commit's parent
        mark = 1
        self.revid_to_mark[revobj.revision_id] = b"%d" % mark
        tree_old = self.branch.repository.revision_tree(
            breezy.revision.NULL_REVISION)
        [tree_new] = list(self._get_revision_trees([revobj.revision_id]))
        file_cmds = self._get_filecommands(tree_old, tree_new)
        self.print_cmd(commands.ResetCommand(ref, None))
        self.print_cmd(self._get_commit_command(ref, mark, revobj, file_cmds))

    def preprocess_commit(self, revid, revobj, ref):
        if self.revid_to_mark.get(revid) or revid in self.excluded_revisions:
            return []
        if revobj is None:
            # This is a ghost revision. Mark it as not found and next!
            self.revid_to_mark[revid] = None
            return []
        # Get the primary parent
        # TODO: Consider the excluded revisions when deciding the parents.
        # Currently, a commit with parents that are excluded ought to be
        # triggering the ref calculation below (and it is not).
        # IGC 20090824
        if len(revobj.parent_ids) == 0:
            parent = breezy.revision.NULL_REVISION
        else:
            parent = revobj.parent_ids[0]

        # Print the commit
        self.revid_to_mark[revobj.revision_id] = b"%d" % (
            len(self.revid_to_mark) + 1)
        return [parent, revobj.revision_id]

    def emit_commit(self, revobj, ref, tree_old, tree_new):
        # For parentless commits we need to issue reset command first, otherwise
        # git-fast-import will assume previous commit was this one's parent
        if tree_old.get_revision_id() == breezy.revision.NULL_REVISION:
            self.print_cmd(commands.ResetCommand(ref, None))

        file_cmds = self._get_filecommands(tree_old, tree_new)
        mark = self.revid_to_mark[revobj.revision_id]
        self.print_cmd(self._get_commit_command(ref, mark, revobj, file_cmds))

        # Report progress and checkpoint if it's time for that
        ncommits = len(self.revid_to_mark)
        self.report_progress(ncommits)
        if (self.checkpoint is not None and self.checkpoint > 0 and ncommits and
                ncommits % self.checkpoint == 0):
            self.note("Exported %i commits - adding checkpoint to output"
                      % ncommits)
            self._save_marks()
            self.print_cmd(commands.CheckpointCommand())

    def _get_name_email(self, user):
        if user.find('<') == -1:
            # If the email isn't inside <>, we need to use it as the name
            # in order for things to round-trip correctly.
            # (note: parseaddr('a@b.com') => name:'', email: 'a@b.com')
            name = user
            email = ''
        else:
            name, email = parseaddr(user)
        return name.encode("utf-8"), email.encode("utf-8")

    def _get_commit_command(self, git_ref, mark, revobj, file_cmds):
        # Get the committer and author info
        committer = revobj.committer
        name, email = self._get_name_email(committer)
        committer_info = (name, email, revobj.timestamp, revobj.timezone)
        if self._multi_author_api_available:
            more_authors = revobj.get_apparent_authors()
            author = more_authors.pop(0)
        else:
            more_authors = []
            author = revobj.get_apparent_author()
        if not self.plain_format and more_authors:
            name, email = self._get_name_email(author)
            author_info = (name, email, revobj.timestamp, revobj.timezone)
            more_author_info = []
            for a in more_authors:
                name, email = self._get_name_email(a)
                more_author_info.append(
                    (name, email, revobj.timestamp, revobj.timezone))
        elif author != committer:
            name, email = self._get_name_email(author)
            author_info = (name, email, revobj.timestamp, revobj.timezone)
            more_author_info = None
        else:
            author_info = None
            more_author_info = None

        # Get the parents in terms of marks
        non_ghost_parents = []
        for p in revobj.parent_ids:
            if p in self.excluded_revisions:
                continue
            try:
                parent_mark = self.revid_to_mark[p]
                non_ghost_parents.append(b":%s" % parent_mark)
            except KeyError:
                # ghost - ignore
                continue
        if non_ghost_parents:
            from_ = non_ghost_parents[0]
            merges = non_ghost_parents[1:]
        else:
            from_ = None
            merges = None

        # Filter the revision properties. Some metadata (like the
        # author information) is already exposed in other ways so
        # don't repeat it here.
        if self.plain_format:
            properties = None
        else:
            properties = revobj.properties
            for prop in self.properties_to_exclude:
                try:
                    del properties[prop]
                except KeyError:
                    pass

        # Build and return the result
        return commands.CommitCommand(
            git_ref, mark, author_info, committer_info,
            revobj.message.encode("utf-8"), from_, merges, file_cmds,
            more_authors=more_author_info, properties=properties)

    def _get_revision_trees(self, revids):
        missing = []
        by_revid = {}
        for revid in revids:
            if revid == breezy.revision.NULL_REVISION:
                by_revid[revid] = self.branch.repository.revision_tree(revid)
            elif revid not in self.tree_cache:
                missing.append(revid)

        for tree in self.branch.repository.revision_trees(missing):
            by_revid[tree.get_revision_id()] = tree

        for revid in revids:
            try:
                yield self.tree_cache[revid]
            except KeyError:
                yield by_revid[revid]

        for revid, tree in by_revid.items():
            self.tree_cache[revid] = tree

    def _get_filecommands(self, tree_old, tree_new):
        """Get the list of FileCommands for the changes between two revisions."""
        changes = tree_new.changes_from(tree_old)

        my_modified = list(changes.modified)

        # The potential interaction between renames and deletes is messy.
        # Handle it here ...
        file_cmds, rd_modifies, renamed = self._process_renames_and_deletes(
            changes.renamed, changes.removed, tree_new.get_revision_id(), tree_old)

        for cmd in file_cmds:
            yield cmd

        # Map kind changes to a delete followed by an add
        for change in changes.kind_changed:
            path = self._adjust_path_for_renames(
                change.path[0], renamed, tree_new.get_revision_id())
            # IGC: I don't understand why a delete is needed here.
            # In fact, it seems harmful? If you uncomment this line,
            # please file a bug explaining why you needed to.
            # yield commands.FileDeleteCommand(path)
            my_modified.append(change)

        # Record modifications
        files_to_get = []
        for change in changes.added + changes.copied + my_modified + rd_modifies:
            if change.kind[1] == 'file':
                files_to_get.append(
                    (change.path[1],
                     (change.path[1], helpers.kind_to_mode(
                         'file', change.executable[1]))))
            elif change.kind[1] == 'symlink':
                yield commands.FileModifyCommand(
                    change.path[1].encode("utf-8"),
                    helpers.kind_to_mode('symlink', False),
                    None, tree_new.get_symlink_target(
                        change.path[1]).encode('utf-8'))
            elif change.kind[1] == 'directory':
                if not self.plain_format:
                    yield commands.FileModifyCommand(
                        change.path[1].encode("utf-8"),
                        helpers.kind_to_mode('directory', False), None,
                        None)
            else:
                self.warning("cannot export '%s' of kind %s yet - ignoring" %
                             (change.path[1], change.kind[1]))

        # TODO(jelmer): Improve performance on remote repositories
        # by using Repository.iter_files_bytes for bzr repositories here.
        for (path, mode), chunks in tree_new.iter_files_bytes(files_to_get):
            yield commands.FileModifyCommand(
                path.encode("utf-8"), mode, None, b''.join(chunks))

    def _process_renames_and_deletes(self, renames, deletes,
                                     revision_id, tree_old):
        file_cmds = []
        modifies = []
        renamed = []

        # See https://bugs.edge.launchpad.net/bzr-fastimport/+bug/268933.
        # In a nutshell, there are several nasty cases:
        #
        # 1) bzr rm a; bzr mv b a; bzr commit
        # 2) bzr mv x/y z; bzr rm x; commmit
        #
        # The first must come out with the delete first like this:
        #
        # D a
        # R b a
        #
        # The second case must come out with the rename first like this:
        #
        # R x/y z
        # D x
        #
        # So outputting all deletes first or all renames first won't work.
        # Instead, we need to make multiple passes over the various lists to
        # get the ordering right.

        must_be_renamed = {}
        old_to_new = {}
        deleted_paths = set([change.path[0] for change in deletes])
        for change in renames:
            emit = change.kind[1] != 'directory' or not self.plain_format
            if change.path[1] in deleted_paths:
                if emit:
                    file_cmds.append(commands.FileDeleteCommand(
                        change.path[1].encode("utf-8")))
                deleted_paths.remove(change.path[1])
            if (self.is_empty_dir(tree_old, change.path[0])):
                self.note("Skipping empty dir %s in rev %s" % (change.path[0],
                                                               revision_id))
                continue
            # oldpath = self._adjust_path_for_renames(oldpath, renamed,
            #    revision_id)
            renamed.append(change.path)
            old_to_new[change.path[0]] = change.path[1]
            if emit:
                file_cmds.append(
                    commands.FileRenameCommand(change.path[0].encode("utf-8"), change.path[1].encode("utf-8")))
            if change.changed_content or change.meta_modified():
                modifies.append(change)

            # Renaming a directory implies all children must be renamed.
            # Note: changes_from() doesn't handle this
            if change.kind == ('directory', 'directory'):
                for p, e in tree_old.iter_entries_by_dir(specific_files=[change.path[0]]):
                    if e.kind == 'directory' and self.plain_format:
                        continue
                    old_child_path = osutils.pathjoin(change.path[0], p)
                    new_child_path = osutils.pathjoin(change.path[1], p)
                    must_be_renamed[old_child_path] = new_child_path

        # Add children not already renamed
        if must_be_renamed:
            renamed_already = set(old_to_new.keys())
            still_to_be_renamed = set(must_be_renamed.keys()) - renamed_already
            for old_child_path in sorted(still_to_be_renamed):
                new_child_path = must_be_renamed[old_child_path]
                if self.verbose:
                    self.note("implicitly renaming %s => %s" % (old_child_path,
                                                                new_child_path))
                file_cmds.append(commands.FileRenameCommand(old_child_path.encode("utf-8"),
                                                            new_child_path.encode("utf-8")))

        # Record remaining deletes
        for change in deletes:
            if change.path[0] not in deleted_paths:
                continue
            if change.kind[0] == 'directory' and self.plain_format:
                continue
            #path = self._adjust_path_for_renames(path, renamed, revision_id)
            file_cmds.append(commands.FileDeleteCommand(change.path[0].encode("utf-8")))
        return file_cmds, modifies, renamed

    def _adjust_path_for_renames(self, path, renamed, revision_id):
        # If a previous rename is found, we should adjust the path
        for old, new in renamed:
            if path == old:
                self.note("Changing path %s given rename to %s in revision %s"
                          % (path, new, revision_id))
                path = new
            elif path.startswith(old + '/'):
                self.note(
                    "Adjusting path %s given rename of %s to %s in revision %s"
                    % (path, old, new, revision_id))
                path = path.replace(old + "/", new + "/")
        return path

    def emit_tags(self):
        for tag, revid in self.branch.tags.get_tag_dict().items():
            try:
                mark = self.revid_to_mark[revid]
            except KeyError:
                self.warning('not creating tag %r pointing to non-existent '
                             'revision %s' % (tag, revid))
            else:
                git_ref = b'refs/tags/%s' % tag.encode("utf-8")
                if self.plain_format and not check_ref_format(git_ref):
                    if self.rewrite_tags:
                        new_ref = sanitize_ref_name_for_git(git_ref)
                        self.warning('tag %r is exported as %r to be valid in git.',
                                     git_ref, new_ref)
                        git_ref = new_ref
                    else:
                        self.warning('not creating tag %r as its name would not be '
                                     'valid in git.', git_ref)
                        continue
                self.print_cmd(commands.ResetCommand(git_ref, b":%s" % mark))
