# Copyright (C) 2005-2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Code to show logs of changes.

Various flavors of log can be produced:

* for one file, or the whole tree, and (not done yet) for
  files in a given directory

* in "verbose" mode with a description of what changed from one
  version to the next

* with files and revision-ids shown

Logs are actually written out through an abstract LogFormatter
interface, which allows for different preferred formats.  Plugins can
register formats too.

Logs can be produced in either forward (oldest->newest) or reverse
(newest->oldest) order.

Logs can be filtered to show only revisions matching a particular
search string, or within a particular range of revisions.  The range
can be given as date/times, which are reduced to revisions before
calling in here.

In verbose mode we show a summary of what changed in each particular
revision.  Note that this is the delta for changes in that revision
relative to its left-most parent, not the delta relative to the last
logged revision.  So for example if you ask for a verbose log of
changes touching hello.c you will get a list of those revisions also
listing other things that were changed in the same revision, but not
all the changes since the previous revision that touched hello.c.
"""

import codecs
import itertools
import re
import sys
from io import BytesIO
from typing import Callable, Dict, List
from warnings import warn

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """

from breezy import (
    config,
    controldir,
    diff,
    foreign,
    lazy_regex,
    )
from breezy.i18n import gettext, ngettext
""",
)

from . import errors, registry, revisionspec, trace
from . import revision as _mod_revision
from . import transport as _mod_transport
from .osutils import (
    format_date,
    format_date_with_offset_in_original_timezone,
    get_diff_header_encoding,
    get_terminal_encoding,
    is_inside,
    terminal_width,
)
from .tree import InterTree


def find_touching_revisions(repository, last_revision, last_tree, last_path):
    """Yield a description of revisions which affect the file.

    Each returned element is (revno, revision_id, description)

    This is the list of revisions where the file is either added,
    modified, renamed or deleted.

    TODO: Perhaps some way to limit this to only particular revisions,
    or to traverse a non-mainline set of revisions?
    """
    last_verifier = last_tree.get_file_verifier(last_path)
    graph = repository.get_graph()
    history = list(graph.iter_lefthand_ancestry(last_revision, []))
    revno = len(history)
    for revision_id in history:
        this_tree = repository.revision_tree(revision_id)
        this_intertree = InterTree.get(this_tree, last_tree)
        this_path = this_intertree.find_source_path(last_path)

        # now we know how it was last time, and how it is in this revision.
        # are those two states effectively the same or not?
        if this_path is not None and last_path is None:
            yield revno, revision_id, "deleted " + this_path
            this_verifier = this_tree.get_file_verifier(this_path)
        elif this_path is None and last_path is not None:
            yield revno, revision_id, "added " + last_path
        elif this_path != last_path:
            yield revno, revision_id, ("renamed {} => {}".format(this_path, last_path))
            this_verifier = this_tree.get_file_verifier(this_path)
        else:
            this_verifier = this_tree.get_file_verifier(this_path)
            if this_verifier != last_verifier:
                yield revno, revision_id, "modified " + this_path

        last_verifier = this_verifier
        last_path = this_path
        last_tree = this_tree
        if last_path is None:
            return
        revno -= 1


def show_log(
    branch,
    lf,
    verbose=False,
    direction="reverse",
    start_revision=None,
    end_revision=None,
    limit=None,
    show_diff=False,
    match=None,
):
    """Write out human-readable log of commits to this branch.

    This function is being retained for backwards compatibility but
    should not be extended with new parameters. Use the new Logger class
    instead, eg. Logger(branch, rqst).show(lf), adding parameters to the
    make_log_request_dict function.

    :param lf: The LogFormatter object showing the output.

    :param verbose: If True show added/changed/deleted/renamed files.

    :param direction: 'reverse' (default) is latest to earliest; 'forward' is
        earliest to latest.

    :param start_revision: If not None, only show revisions >= start_revision

    :param end_revision: If not None, only show revisions <= end_revision

    :param limit: If set, shows only 'limit' revisions, all revisions are shown
        if None or 0.

    :param show_diff: If True, output a diff after each revision.

    :param match: Dictionary of search lists to use when matching revision
      properties.
    """
    if verbose:
        delta_type = "full"
    else:
        delta_type = None
    if show_diff:
        diff_type = "full"
    else:
        diff_type = None

    if isinstance(start_revision, int):
        try:
            start_revision = revisionspec.RevisionInfo(branch, start_revision)
        except (errors.NoSuchRevision, errors.RevnoOutOfBounds):
            raise errors.InvalidRevisionNumber(start_revision)

    if isinstance(end_revision, int):
        try:
            end_revision = revisionspec.RevisionInfo(branch, end_revision)
        except (errors.NoSuchRevision, errors.RevnoOutOfBounds):
            raise errors.InvalidRevisionNumber(end_revision)

    if end_revision is not None and end_revision.revno == 0:
        raise errors.InvalidRevisionNumber(end_revision.revno)

    # Build the request and execute it
    rqst = make_log_request_dict(
        direction=direction,
        start_revision=start_revision,
        end_revision=end_revision,
        limit=limit,
        delta_type=delta_type,
        diff_type=diff_type,
    )
    Logger(branch, rqst).show(lf)


# Note: This needs to be kept in sync with the defaults in
# make_log_request_dict() below
_DEFAULT_REQUEST_PARAMS = {
    "direction": "reverse",
    "levels": None,
    "generate_tags": True,
    "exclude_common_ancestry": False,
    "_match_using_deltas": True,
}


def make_log_request_dict(
    direction="reverse",
    specific_files=None,
    start_revision=None,
    end_revision=None,
    limit=None,
    message_search=None,
    levels=None,
    generate_tags=True,
    delta_type=None,
    diff_type=None,
    _match_using_deltas=True,
    exclude_common_ancestry=False,
    match=None,
    signature=False,
    omit_merges=False,
):
    """Convenience function for making a logging request dictionary.

        Using this function may make code slightly safer by ensuring
        parameters have the correct names. It also provides a reference
        point for documenting the supported parameters.

        :param direction: 'reverse' (default) is latest to earliest;
          'forward' is earliest to latest.

        :param specific_files: If not None, only include revisions
          affecting the specified files, rather than all revisions.

        :param start_revision: If not None, only generate
          revisions >= start_revision

        :param end_revision: If not None, only generate
          revisions <= end_revision

        :param limit: If set, generate only 'limit' revisions, all revisions
          are shown if None or 0.

        :param message_search: If not None, only include revisions with
          matching commit messages

        :param levels: the number of levels of revisions to
          generate; 1 for just the mainline; 0 for all levels, or None for
          a sensible default.

        :param generate_tags: If True, include tags for matched revisions.
    `
        :param delta_type: Either 'full', 'partial' or None.
          'full' means generate the complete delta - adds/deletes/modifies/etc;
          'partial' means filter the delta using specific_files;
          None means do not generate any delta.

        :param diff_type: Either 'full', 'partial' or None.
          'full' means generate the complete diff - adds/deletes/modifies/etc;
          'partial' means filter the diff using specific_files;
          None means do not generate any diff.

        :param _match_using_deltas: a private parameter controlling the
          algorithm used for matching specific_files. This parameter
          may be removed in the future so breezy client code should NOT
          use it.

        :param exclude_common_ancestry: Whether -rX..Y should be interpreted as a
          range operator or as a graph difference.

        :param signature: show digital signature information

        :param match: Dictionary of list of search strings to use when filtering
          revisions. Keys can be 'message', 'author', 'committer', 'bugs' or
          the empty string to match any of the preceding properties.

        :param omit_merges: If True, commits with more than one parent are
          omitted.

    """
    # Take care of old style message_search parameter
    if message_search:
        if match:
            if "message" in match:
                match["message"].append(message_search)
            else:
                match["message"] = [message_search]
        else:
            match = {"message": [message_search]}
    return {
        "direction": direction,
        "specific_files": specific_files,
        "start_revision": start_revision,
        "end_revision": end_revision,
        "limit": limit,
        "levels": levels,
        "generate_tags": generate_tags,
        "delta_type": delta_type,
        "diff_type": diff_type,
        "exclude_common_ancestry": exclude_common_ancestry,
        "signature": signature,
        "match": match,
        "omit_merges": omit_merges,
        # Add 'private' attributes for features that may be deprecated
        "_match_using_deltas": _match_using_deltas,
    }


def _apply_log_request_defaults(rqst):
    """Apply default values to a request dictionary."""
    result = _DEFAULT_REQUEST_PARAMS.copy()
    if rqst:
        result.update(rqst)
    return result


def format_signature_validity(rev_id, branch):
    """Get the signature validity

    :param rev_id: revision id to validate
    :param branch: branch of revision
    :return: human readable string to print to log
    """
    from breezy import gpg

    gpg_strategy = gpg.GPGStrategy(branch.get_config_stack())
    result = branch.repository.verify_revision_signature(rev_id, gpg_strategy)
    if result[0] == gpg.SIGNATURE_VALID:
        return f"valid signature from {result[1]}"
    if result[0] == gpg.SIGNATURE_KEY_MISSING:
        return f"unknown key {result[1]}"
    if result[0] == gpg.SIGNATURE_NOT_VALID:
        return "invalid signature!"
    if result[0] == gpg.SIGNATURE_NOT_SIGNED:
        return "no signature"


class LogGenerator:
    """A generator of log revisions."""

    def iter_log_revisions(self):
        """Iterate over LogRevision objects.

        :return: An iterator yielding LogRevision objects.
        """
        raise NotImplementedError(self.iter_log_revisions)


class Logger:
    """An object that generates, formats and displays a log."""

    def __init__(self, branch, rqst):
        """Create a Logger.

        :param branch: the branch to log
        :param rqst: A dictionary specifying the query parameters.
          See make_log_request_dict() for supported values.
        """
        self.branch = branch
        self.rqst = _apply_log_request_defaults(rqst)

    def show(self, lf):
        """Display the log.

        :param lf: The LogFormatter object to send the output to.
        """
        if not isinstance(lf, LogFormatter):
            warn("not a LogFormatter instance: %r" % lf)

        with self.branch.lock_read():
            if getattr(lf, "begin_log", None):
                lf.begin_log()
            self._show_body(lf)
            if getattr(lf, "end_log", None):
                lf.end_log()

    def _show_body(self, lf):
        """Show the main log output.

        Subclasses may wish to override this.
        """
        # Tweak the LogRequest based on what the LogFormatter can handle.
        # (There's no point generating stuff if the formatter can't display it.)
        rqst = self.rqst
        if rqst["levels"] is None or lf.get_levels() > rqst["levels"]:
            # user didn't specify levels, use whatever the LF can handle:
            rqst["levels"] = lf.get_levels()

        if not getattr(lf, "supports_tags", False):
            rqst["generate_tags"] = False
        if not getattr(lf, "supports_delta", False):
            rqst["delta_type"] = None
        if not getattr(lf, "supports_diff", False):
            rqst["diff_type"] = None
        if not getattr(lf, "supports_signatures", False):
            rqst["signature"] = False

        # Find and print the interesting revisions
        generator = self._generator_factory(self.branch, rqst)
        try:
            for lr in generator.iter_log_revisions():
                lf.log_revision(lr)
        except errors.GhostRevisionUnusableHere:
            raise errors.CommandError(gettext("Further revision history missing."))
        lf.show_advice()

    def _generator_factory(self, branch, rqst):
        """Make the LogGenerator object to use.

        Subclasses may wish to override this.
        """
        return _DefaultLogGenerator(branch, **rqst)


def _log_revision_iterator_using_per_file_graph(
    branch,
    delta_type,
    match,
    levels,
    path,
    start_rev_id,
    end_rev_id,
    direction,
    exclude_common_ancestry,
):
    # Get the base revisions, filtering by the revision range.
    # Note that we always generate the merge revisions because
    # filter_revisions_touching_path() requires them ...
    view_revisions = _calc_view_revisions(
        branch,
        start_rev_id,
        end_rev_id,
        direction,
        generate_merge_revisions=True,
        exclude_common_ancestry=exclude_common_ancestry,
    )
    if not isinstance(view_revisions, list):
        view_revisions = list(view_revisions)
    view_revisions = _filter_revisions_touching_path(
        branch, path, view_revisions, include_merges=levels != 1
    )
    return make_log_rev_iterator(branch, view_revisions, delta_type, match)


def _log_revision_iterator_using_delta_matching(
    branch,
    delta_type,
    match,
    levels,
    specific_files,
    start_rev_id,
    end_rev_id,
    direction,
    exclude_common_ancestry,
    limit,
):
    # Get the base revisions, filtering by the revision range
    generate_merge_revisions = levels != 1
    delayed_graph_generation = not specific_files and (
        limit or start_rev_id or end_rev_id
    )
    view_revisions = _calc_view_revisions(
        branch,
        start_rev_id,
        end_rev_id,
        direction,
        generate_merge_revisions=generate_merge_revisions,
        delayed_graph_generation=delayed_graph_generation,
        exclude_common_ancestry=exclude_common_ancestry,
    )

    # Apply the other filters
    return make_log_rev_iterator(
        branch,
        view_revisions,
        delta_type,
        match,
        files=specific_files,
        direction=direction,
    )


def _format_diff(branch, rev, diff_type, files=None):
    """Format a diff.

    :param branch: Branch object
    :param rev: Revision object
    :param diff_type: Type of diff to generate
    :param files: List of files to generate diff for (or None for all)
    """
    repo = branch.repository
    if len(rev.parent_ids) == 0:
        ancestor_id = _mod_revision.NULL_REVISION
    else:
        ancestor_id = rev.parent_ids[0]
    tree_1 = repo.revision_tree(ancestor_id)
    tree_2 = repo.revision_tree(rev.revision_id)
    if diff_type == "partial" and files is not None:
        specific_files = files
    else:
        specific_files = None
    s = BytesIO()
    path_encoding = get_diff_header_encoding()
    diff.show_diff_trees(
        tree_1,
        tree_2,
        s,
        specific_files,
        old_label="",
        new_label="",
        path_encoding=path_encoding,
    )
    return s.getvalue()


class _StartNotLinearAncestor(Exception):
    """Raised when a start revision is not found walking left-hand history."""


class _DefaultLogGenerator(LogGenerator):
    """The default generator of log revisions."""

    def __init__(
        self,
        branch,
        levels=None,
        limit=None,
        diff_type=None,
        delta_type=None,
        show_signature=None,
        omit_merges=None,
        generate_tags=None,
        specific_files=None,
        match=None,
        start_revision=None,
        end_revision=None,
        direction=None,
        exclude_common_ancestry=None,
        _match_using_deltas=None,
        signature=None,
    ):
        self.branch = branch
        self.levels = levels
        self.limit = limit
        self.diff_type = diff_type
        self.delta_type = delta_type
        self.show_signature = signature
        self.omit_merges = omit_merges
        self.specific_files = specific_files
        self.match = match
        self.start_revision = start_revision
        self.end_revision = end_revision
        self.direction = direction
        self.exclude_common_ancestry = exclude_common_ancestry
        self._match_using_deltas = _match_using_deltas
        if generate_tags and branch.supports_tags():
            self.rev_tag_dict = branch.tags.get_reverse_tag_dict()
        else:
            self.rev_tag_dict = {}

    def iter_log_revisions(self):
        """Iterate over LogRevision objects.

        :return: An iterator yielding LogRevision objects.
        """
        log_count = 0
        revision_iterator = self._create_log_revision_iterator()
        for revs in revision_iterator:
            for (rev_id, revno, merge_depth), rev, delta in revs:
                # 0 levels means show everything; merge_depth counts from 0
                if (
                    self.levels != 0
                    and merge_depth is not None
                    and merge_depth >= self.levels
                ):
                    continue
                if self.omit_merges and len(rev.parent_ids) > 1:
                    continue
                if rev is None:
                    raise errors.GhostRevisionUnusableHere(rev_id)
                if self.diff_type is None:
                    diff = None
                else:
                    diff = _format_diff(
                        self.branch, rev, self.diff_type, self.specific_files
                    )
                if self.show_signature:
                    signature = format_signature_validity(rev_id, self.branch)
                else:
                    signature = None
                yield LogRevision(
                    rev,
                    revno,
                    merge_depth,
                    delta,
                    self.rev_tag_dict.get(rev_id),
                    diff,
                    signature,
                )
                if self.limit:
                    log_count += 1
                    if log_count >= self.limit:
                        return

    def _create_log_revision_iterator(self):
        """Create a revision iterator for log.

        :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
            delta).
        """
        start_rev_id, end_rev_id = _get_revision_limits(
            self.branch, self.start_revision, self.end_revision
        )
        if self._match_using_deltas:
            return _log_revision_iterator_using_delta_matching(
                self.branch,
                delta_type=self.delta_type,
                match=self.match,
                levels=self.levels,
                specific_files=self.specific_files,
                start_rev_id=start_rev_id,
                end_rev_id=end_rev_id,
                direction=self.direction,
                exclude_common_ancestry=self.exclude_common_ancestry,
                limit=self.limit,
            )
        else:
            # We're using the per-file-graph algorithm. This scales really
            # well but only makes sense if there is a single file and it's
            # not a directory
            file_count = len(self.specific_files)
            if file_count != 1:
                raise errors.BzrError(
                    "illegal LogRequest: must match-using-deltas "
                    "when logging %d files" % file_count
                )
            return _log_revision_iterator_using_per_file_graph(
                self.branch,
                delta_type=self.delta_type,
                match=self.match,
                levels=self.levels,
                path=self.specific_files[0],
                start_rev_id=start_rev_id,
                end_rev_id=end_rev_id,
                direction=self.direction,
                exclude_common_ancestry=self.exclude_common_ancestry,
            )


def _calc_view_revisions(
    branch,
    start_rev_id,
    end_rev_id,
    direction,
    generate_merge_revisions,
    delayed_graph_generation=False,
    exclude_common_ancestry=False,
):
    """Calculate the revisions to view.

    :return: An iterator of (revision_id, dotted_revno, merge_depth) tuples OR
             a list of the same tuples.
    """
    if exclude_common_ancestry and start_rev_id == end_rev_id:
        raise errors.CommandError(
            gettext("--exclude-common-ancestry requires two different revisions")
        )
    if direction not in ("reverse", "forward"):
        raise ValueError(gettext("invalid direction %r") % direction)
    br_rev_id = branch.last_revision()
    if br_rev_id == _mod_revision.NULL_REVISION:
        return []

    if (
        end_rev_id
        and start_rev_id == end_rev_id
        and (not generate_merge_revisions or not _has_merges(branch, end_rev_id))
    ):
        # If a single revision is requested, check we can handle it
        return _generate_one_revision(branch, end_rev_id, br_rev_id, branch.revno())
    if not generate_merge_revisions:
        try:
            # If we only want to see linear revisions, we can iterate ...
            iter_revs = _linear_view_revisions(
                branch,
                start_rev_id,
                end_rev_id,
                exclude_common_ancestry=exclude_common_ancestry,
            )
            # If a start limit was given and it's not obviously an
            # ancestor of the end limit, check it before outputting anything
            if direction == "forward" or (
                start_rev_id
                and not _is_obvious_ancestor(branch, start_rev_id, end_rev_id)
            ):
                iter_revs = list(iter_revs)
            if direction == "forward":
                iter_revs = reversed(iter_revs)
            return iter_revs
        except _StartNotLinearAncestor:
            # Switch to the slower implementation that may be able to find a
            # non-obvious ancestor out of the left-hand history.
            pass
    iter_revs = _generate_all_revisions(
        branch,
        start_rev_id,
        end_rev_id,
        direction,
        delayed_graph_generation,
        exclude_common_ancestry,
    )
    if direction == "forward":
        iter_revs = _rebase_merge_depth(reverse_by_depth(list(iter_revs)))
    return iter_revs


def _generate_one_revision(branch, rev_id, br_rev_id, br_revno):
    if rev_id == br_rev_id:
        # It's the tip
        return [(br_rev_id, br_revno, 0)]
    else:
        revno_str = _compute_revno_str(branch, rev_id)
        return [(rev_id, revno_str, 0)]


def _generate_all_revisions(
    branch,
    start_rev_id,
    end_rev_id,
    direction,
    delayed_graph_generation,
    exclude_common_ancestry=False,
):
    # On large trees, generating the merge graph can take 30-60 seconds
    # so we delay doing it until a merge is detected, incrementally
    # returning initial (non-merge) revisions while we can.

    # The above is only true for old formats (<= 0.92), for newer formats, a
    # couple of seconds only should be needed to load the whole graph and the
    # other graph operations needed are even faster than that -- vila 100201
    initial_revisions = []
    if delayed_graph_generation:
        try:
            for rev_id, revno, depth in _linear_view_revisions(
                branch, start_rev_id, end_rev_id, exclude_common_ancestry
            ):
                if _has_merges(branch, rev_id):
                    # The end_rev_id can be nested down somewhere. We need an
                    # explicit ancestry check. There is an ambiguity here as we
                    # may not raise _StartNotLinearAncestor for a revision that
                    # is an ancestor but not a *linear* one. But since we have
                    # loaded the graph to do the check (or calculate a dotted
                    # revno), we may as well accept to show the log...  We need
                    # the check only if start_rev_id is not None as all
                    # revisions have _mod_revision.NULL_REVISION as an ancestor
                    # -- vila 20100319
                    graph = branch.repository.get_graph()
                    if start_rev_id is not None and not graph.is_ancestor(
                        start_rev_id, end_rev_id
                    ):
                        raise _StartNotLinearAncestor()
                    # Since we collected the revisions so far, we need to
                    # adjust end_rev_id.
                    end_rev_id = rev_id
                    break
                else:
                    initial_revisions.append((rev_id, revno, depth))
            else:
                # No merged revisions found
                return initial_revisions
        except _StartNotLinearAncestor:
            # A merge was never detected so the lower revision limit can't
            # be nested down somewhere
            raise errors.CommandError(
                gettext("Start revision not found in history of end revision.")
            )

    # We exit the loop above because we encounter a revision with merges, from
    # this revision, we need to switch to _graph_view_revisions.

    # A log including nested merges is required. If the direction is reverse,
    # we rebase the initial merge depths so that the development line is
    # shown naturally, i.e. just like it is for linear logging. We can easily
    # make forward the exact opposite display, but showing the merge revisions
    # indented at the end seems slightly nicer in that case.
    view_revisions = itertools.chain(
        iter(initial_revisions),
        _graph_view_revisions(
            branch,
            start_rev_id,
            end_rev_id,
            rebase_initial_depths=(direction == "reverse"),
            exclude_common_ancestry=exclude_common_ancestry,
        ),
    )
    return view_revisions


def _has_merges(branch, rev_id):
    """Does a revision have multiple parents or not?"""
    parents = branch.repository.get_parent_map([rev_id]).get(rev_id, [])
    return len(parents) > 1


def _compute_revno_str(branch, rev_id):
    """Compute the revno string from a rev_id.

    :return: The revno string, or None if the revision is not in the supplied
        branch.
    """
    try:
        revno = branch.revision_id_to_dotted_revno(rev_id)
    except errors.NoSuchRevision:
        # The revision must be outside of this branch
        return None
    else:
        return ".".join(str(n) for n in revno)


def _is_obvious_ancestor(branch, start_rev_id, end_rev_id):
    """Is start_rev_id an obvious ancestor of end_rev_id?"""
    if start_rev_id and end_rev_id:
        try:
            start_dotted = branch.revision_id_to_dotted_revno(start_rev_id)
            end_dotted = branch.revision_id_to_dotted_revno(end_rev_id)
        except errors.NoSuchRevision:
            # one or both is not in the branch; not obvious
            return False
        if len(start_dotted) == 1 and len(end_dotted) == 1:
            # both on mainline
            return start_dotted[0] <= end_dotted[0]
        elif (
            len(start_dotted) == 3
            and len(end_dotted) == 3
            and start_dotted[0:1] == end_dotted[0:1]
        ):
            # both on same development line
            return start_dotted[2] <= end_dotted[2]
        else:
            # not obvious
            return False
    # if either start or end is not specified then we use either the first or
    # the last revision and *they* are obvious ancestors.
    return True


def _linear_view_revisions(
    branch, start_rev_id, end_rev_id, exclude_common_ancestry=False
):
    """Calculate a sequence of revisions to view, newest to oldest.

    :param start_rev_id: the lower revision-id
    :param end_rev_id: the upper revision-id
    :param exclude_common_ancestry: Whether the start_rev_id should be part of
        the iterated revisions.
    :return: An iterator of (revision_id, dotted_revno, merge_depth) tuples.
        dotted_revno will be None for ghosts
    :raises _StartNotLinearAncestor: if a start_rev_id is specified but
        is not found walking the left-hand history
    """
    repo = branch.repository
    graph = repo.get_graph()
    if start_rev_id is None and end_rev_id is None:
        if branch._format.stores_revno() or config.GlobalStack().get(
            "calculate_revnos"
        ):
            try:
                br_revno, br_rev_id = branch.last_revision_info()
            except errors.GhostRevisionsHaveNoRevno:
                br_rev_id = branch.last_revision()
                cur_revno = None
            else:
                cur_revno = br_revno
        else:
            br_rev_id = branch.last_revision()
            cur_revno = None

        graph_iter = graph.iter_lefthand_ancestry(
            br_rev_id, (_mod_revision.NULL_REVISION,)
        )
        while True:
            try:
                revision_id = next(graph_iter)
            except errors.RevisionNotPresent as e:
                # Oops, a ghost.
                yield e.revision_id, None, None
                break
            except StopIteration:
                break
            else:
                yield revision_id, str(cur_revno) if cur_revno is not None else None, 0
                if cur_revno is not None:
                    cur_revno -= 1
    else:
        br_rev_id = branch.last_revision()
        if end_rev_id is None:
            end_rev_id = br_rev_id
        found_start = start_rev_id is None
        graph_iter = graph.iter_lefthand_ancestry(
            end_rev_id, (_mod_revision.NULL_REVISION,)
        )
        while True:
            try:
                revision_id = next(graph_iter)
            except StopIteration:
                break
            except errors.RevisionNotPresent as e:
                # Oops, a ghost.
                yield e.revision_id, None, None
                break
            else:
                revno_str = _compute_revno_str(branch, revision_id)
                if not found_start and revision_id == start_rev_id:
                    if not exclude_common_ancestry:
                        yield revision_id, revno_str, 0
                    found_start = True
                    break
                else:
                    yield revision_id, revno_str, 0
        if not found_start:
            raise _StartNotLinearAncestor()


def _graph_view_revisions(
    branch,
    start_rev_id,
    end_rev_id,
    rebase_initial_depths=True,
    exclude_common_ancestry=False,
):
    """Calculate revisions to view including merges, newest to oldest.

    :param branch: the branch
    :param start_rev_id: the lower revision-id
    :param end_rev_id: the upper revision-id
    :param rebase_initial_depth: should depths be rebased until a mainline
      revision is found?
    :return: An iterator of (revision_id, dotted_revno, merge_depth) tuples.
    """
    if exclude_common_ancestry:
        stop_rule = "with-merges-without-common-ancestry"
    else:
        stop_rule = "with-merges"
    view_revisions = branch.iter_merge_sorted_revisions(
        start_revision_id=end_rev_id, stop_revision_id=start_rev_id, stop_rule=stop_rule
    )
    if not rebase_initial_depths:
        for rev_id, merge_depth, revno, end_of_merge in view_revisions:
            yield rev_id, ".".join(map(str, revno)), merge_depth
    else:
        # We're following a development line starting at a merged revision.
        # We need to adjust depths down by the initial depth until we find
        # a depth less than it. Then we use that depth as the adjustment.
        # If and when we reach the mainline, depth adjustment ends.
        depth_adjustment = None
        for rev_id, merge_depth, revno, end_of_merge in view_revisions:
            if depth_adjustment is None:
                depth_adjustment = merge_depth
            if depth_adjustment:
                if merge_depth < depth_adjustment:
                    # From now on we reduce the depth adjustement, this can be
                    # surprising for users. The alternative requires two passes
                    # which breaks the fast display of the first revision
                    # though.
                    depth_adjustment = merge_depth
                merge_depth -= depth_adjustment
            yield rev_id, ".".join(map(str, revno)), merge_depth


def _rebase_merge_depth(view_revisions):
    """Adjust depths upwards so the top level is 0."""
    # If either the first or last revision have a merge_depth of 0, we're done
    if view_revisions and view_revisions[0][2] and view_revisions[-1][2]:
        min_depth = min([d for r, n, d in view_revisions])
        if min_depth != 0:
            view_revisions = [(r, n, d - min_depth) for r, n, d in view_revisions]
    return view_revisions


def make_log_rev_iterator(
    branch, view_revisions, generate_delta, search, files=None, direction="reverse"
):
    """Create a revision iterator for log.

    :param branch: The branch being logged.
    :param view_revisions: The revisions being viewed.
    :param generate_delta: Whether to generate a delta for each revision.
      Permitted values are None, 'full' and 'partial'.
    :param search: A user text search string.
    :param files: If non empty, only revisions matching one or more of
      the files are to be kept.
    :param direction: the direction in which view_revisions is sorted
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    # Convert view_revisions into (view, None, None) groups to fit with
    # the standard interface here.
    if isinstance(view_revisions, list):
        # A single batch conversion is faster than many incremental ones.
        # As we have all the data, do a batch conversion.
        nones = [None] * len(view_revisions)
        log_rev_iterator = iter([list(zip(view_revisions, nones, nones))])
    else:

        def _convert():
            for view in view_revisions:
                yield (view, None, None)

        log_rev_iterator = iter([_convert()])
    for adapter in log_adapters:
        # It would be nicer if log adapters were first class objects
        # with custom parameters. This will do for now. IGC 20090127
        if adapter == _make_delta_filter:
            log_rev_iterator = adapter(
                branch, generate_delta, search, log_rev_iterator, files, direction
            )
        else:
            log_rev_iterator = adapter(branch, generate_delta, search, log_rev_iterator)
    return log_rev_iterator


def _make_search_filter(branch, generate_delta, match, log_rev_iterator):
    """Create a filtered iterator of log_rev_iterator matching on a regex.

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
    :param match: A dictionary with properties as keys and lists of strings
        as values. To match, a revision may match any of the supplied strings
        within a single property but must match at least one string for each
        property.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    if not match:
        return log_rev_iterator
    # Use lazy_compile so mapping to InvalidPattern error occurs.
    searchRE = [
        (k, [lazy_regex.lazy_compile(x, re.IGNORECASE) for x in v])
        for k, v in match.items()
    ]
    return _filter_re(searchRE, log_rev_iterator)


def _filter_re(searchRE, log_rev_iterator):
    for revs in log_rev_iterator:
        new_revs = [rev for rev in revs if _match_filter(searchRE, rev[1])]
        if new_revs:
            yield new_revs


def _match_filter(searchRE, rev):
    strings = {
        "message": (rev.message,),
        "committer": (rev.committer,),
        "author": (rev.get_apparent_authors()),
        "bugs": list(rev.iter_bugs()),
    }
    strings[""] = [item for inner_list in strings.values() for item in inner_list]
    for k, v in searchRE:
        if k in strings and not _match_any_filter(strings[k], v):
            return False
    return True


def _match_any_filter(strings, res):
    return any(r.search(s) for r in res for s in strings)


def _make_delta_filter(
    branch, generate_delta, search, log_rev_iterator, files=None, direction="reverse"
):
    """Add revision deltas to a log iterator if needed.

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
      Permitted values are None, 'full' and 'partial'.
    :param search: A user text search string.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :param files: If non empty, only revisions matching one or more of
      the files are to be kept.
    :param direction: the direction in which view_revisions is sorted
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    if not generate_delta and not files:
        return log_rev_iterator
    return _generate_deltas(
        branch.repository, log_rev_iterator, generate_delta, files, direction
    )


def _generate_deltas(repository, log_rev_iterator, delta_type, files, direction):
    """Create deltas for each batch of revisions in log_rev_iterator.

    If we're only generating deltas for the sake of filtering against
    files, we stop generating deltas once all files reach the
    appropriate life-cycle point. If we're receiving data newest to
    oldest, then that life-cycle point is 'add', otherwise it's 'remove'.
    """
    check_files = files is not None and len(files) > 0
    if check_files:
        file_set = set(files)
        if direction == "reverse":
            stop_on = "add"
        else:
            stop_on = "remove"
    else:
        file_set = None
    for revs in log_rev_iterator:
        # If we were matching against files and we've run out,
        # there's nothing left to do
        if check_files and not file_set:
            return
        revisions = [rev[1] for rev in revs]
        new_revs = []
        if delta_type == "full" and not check_files:
            deltas = repository.get_revision_deltas(revisions)
            for rev, delta in zip(revs, deltas):
                new_revs.append((rev[0], rev[1], delta))
        else:
            deltas = repository.get_revision_deltas(revisions, specific_files=file_set)
            for rev, delta in zip(revs, deltas):
                if check_files:
                    if delta is None or not delta.has_changed():
                        continue
                    else:
                        _update_files(delta, file_set, stop_on)
                        if delta_type is None:
                            delta = None
                        elif delta_type == "full":
                            # If the file matches all the time, rebuilding
                            # a full delta like this in addition to a partial
                            # one could be slow. However, it's likely that
                            # most revisions won't get this far, making it
                            # faster to filter on the partial deltas and
                            # build the occasional full delta than always
                            # building full deltas and filtering those.
                            rev_id = rev[0][0]
                            delta = repository.get_revision_delta(rev_id)
                new_revs.append((rev[0], rev[1], delta))
        yield new_revs


def _update_files(delta, files, stop_on):
    """Update the set of files to search based on file lifecycle events.

    :param files: a set of files to update
    :param stop_on: either 'add' or 'remove' - take files out of the
      files set once their add or remove entry is detected respectively
    """
    if stop_on == "add":
        for item in delta.added:
            if item.path[1] in files:
                files.remove(item.path[1])
        for item in delta.copied + delta.renamed:
            if item.path[1] in files:
                files.remove(item.path[1])
                files.add(item.path[0])
            if item.kind[1] == "directory":
                for path in list(files):
                    if is_inside(item.path[1], path):
                        files.remove(path)
                        files.add(item.path[0] + path[len(item.path[1]) :])
    elif stop_on == "delete":
        for item in delta.removed:
            if item.path[0] in files:
                files.remove(item.path[0])
        for item in delta.copied + delta.renamed:
            if item.path[0] in files:
                files.remove(item.path[0])
                files.add(item.path[1])
            if item.kind[0] == "directory":
                for path in list(files):
                    if is_inside(item.path[0], path):
                        files.remove(path)
                        files.add(item.path[1] + path[len(item.path[0]) :])


def _make_revision_objects(branch, generate_delta, search, log_rev_iterator):
    """Extract revision objects from the repository

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    repository = branch.repository
    for revs in log_rev_iterator:
        # r = revision_id, n = revno, d = merge depth
        revision_ids = [view[0] for view, _, _ in revs]
        revisions = dict(repository.iter_revisions(revision_ids))
        yield [(rev[0], revisions[rev[0][0]], rev[2]) for rev in revs]


def _make_batch_filter(branch, generate_delta, search, log_rev_iterator):
    """Group up a single large batch into smaller ones.

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    num = 9
    for batch in log_rev_iterator:
        batch = iter(batch)
        while True:
            step = [detail for _, detail in zip(range(num), batch)]
            if len(step) == 0:
                break
            yield step
            num = min(int(num * 1.5), 200)


def _get_revision_limits(branch, start_revision, end_revision):
    """Get and check revision limits.

    :param branch: The branch containing the revisions.

    :param start_revision: The first revision to be logged, as a RevisionInfo.

    :param end_revision: The last revision to be logged, as a RevisionInfo

    :return: (start_rev_id, end_rev_id) tuple.
    """
    start_rev_id = None
    start_revno = None
    if start_revision is not None:
        if not isinstance(start_revision, revisionspec.RevisionInfo):
            raise TypeError(start_revision)
        start_rev_id = start_revision.rev_id
        start_revno = start_revision.revno
    if start_revno is None:
        start_revno = 1

    end_rev_id = None
    end_revno = None
    if end_revision is not None:
        if not isinstance(end_revision, revisionspec.RevisionInfo):
            raise TypeError(start_revision)
        end_rev_id = end_revision.rev_id
        end_revno = end_revision.revno

    if branch.last_revision() != _mod_revision.NULL_REVISION:
        if (
            start_rev_id == _mod_revision.NULL_REVISION
            or end_rev_id == _mod_revision.NULL_REVISION
        ):
            raise errors.CommandError(gettext("Logging revision 0 is invalid."))
        if end_revno is not None and start_revno > end_revno:
            raise errors.CommandError(
                gettext("Start revision must be older than the end revision.")
            )
    return (start_rev_id, end_rev_id)


def _get_mainline_revs(branch, start_revision, end_revision):
    """Get the mainline revisions from the branch.

    Generates the list of mainline revisions for the branch.

    :param  branch: The branch containing the revisions.

    :param  start_revision: The first revision to be logged.
            For backwards compatibility this may be a mainline integer revno,
            but for merge revision support a RevisionInfo is expected.

    :param  end_revision: The last revision to be logged.
            For backwards compatibility this may be a mainline integer revno,
            but for merge revision support a RevisionInfo is expected.

    :return: A (mainline_revs, rev_nos, start_rev_id, end_rev_id) tuple.
    """
    branch_revno, branch_last_revision = branch.last_revision_info()
    if branch_revno == 0:
        return None, None, None, None

    # For mainline generation, map start_revision and end_revision to
    # mainline revnos. If the revision is not on the mainline choose the
    # appropriate extreme of the mainline instead - the extra will be
    # filtered later.
    # Also map the revisions to rev_ids, to be used in the later filtering
    # stage.
    start_rev_id = None
    if start_revision is None:
        start_revno = 1
    else:
        if isinstance(start_revision, revisionspec.RevisionInfo):
            start_rev_id = start_revision.rev_id
            start_revno = start_revision.revno or 1
        else:
            branch.check_real_revno(start_revision)
            start_revno = start_revision

    end_rev_id = None
    if end_revision is None:
        end_revno = branch_revno
    else:
        if isinstance(end_revision, revisionspec.RevisionInfo):
            end_rev_id = end_revision.rev_id
            end_revno = end_revision.revno or branch_revno
        else:
            branch.check_real_revno(end_revision)
            end_revno = end_revision

    if (start_rev_id == _mod_revision.NULL_REVISION) or (
        end_rev_id == _mod_revision.NULL_REVISION
    ):
        raise errors.CommandError(gettext("Logging revision 0 is invalid."))
    if start_revno > end_revno:
        raise errors.CommandError(
            gettext("Start revision must be older than the end revision.")
        )

    if end_revno < start_revno:
        return None, None, None, None
    cur_revno = branch_revno
    rev_nos = {}
    mainline_revs = []
    graph = branch.repository.get_graph()
    for revision_id in graph.iter_lefthand_ancestry(
        branch_last_revision, (_mod_revision.NULL_REVISION,)
    ):
        if cur_revno < start_revno:
            # We have gone far enough, but we always add 1 more revision
            rev_nos[revision_id] = cur_revno
            mainline_revs.append(revision_id)
            break
        if cur_revno <= end_revno:
            rev_nos[revision_id] = cur_revno
            mainline_revs.append(revision_id)
        cur_revno -= 1
    else:
        # We walked off the edge of all revisions, so we add a 'None' marker
        mainline_revs.append(None)

    mainline_revs.reverse()

    # override the mainline to look like the revision history.
    return mainline_revs, rev_nos, start_rev_id, end_rev_id


def _filter_revisions_touching_path(branch, path, view_revisions, include_merges=True):
    r"""Return the list of revision ids which touch a given path.

    The function filters view_revisions and returns a subset.
    This includes the revisions which directly change the path,
    and the revisions which merge these changes. So if the
    revision graph is::

        A-.
        |\ \
        B C E
        |/ /
        D |
        |\|
        | F
        |/
        G

    And 'C' changes a file, then both C and D will be returned. F will not be
    returned even though it brings the changes to C into the branch starting
    with E. (Note that if we were using F as the tip instead of G, then we
    would see C, D, F.)

    This will also be restricted based on a subset of the mainline.

    :param branch: The branch where we can get text revision information.

    :param path: Filter out revisions that do not touch path.

    :param view_revisions: A list of (revision_id, dotted_revno, merge_depth)
        tuples. This is the list of revisions which will be filtered. It is
        assumed that view_revisions is in merge_sort order (i.e. newest
        revision first ).

    :param include_merges: include merge revisions in the result or not

    :return: A list of (revision_id, dotted_revno, merge_depth) tuples.
    """
    # Lookup all possible text keys to determine which ones actually modified
    # the file.
    graph = branch.repository.get_file_graph()
    start_tree = branch.repository.revision_tree(view_revisions[0][0])
    file_id = start_tree.path2id(path)
    get_parent_map = graph.get_parent_map
    text_keys = [(file_id, rev_id) for rev_id, revno, depth in view_revisions]
    next_keys = None
    # Looking up keys in batches of 1000 can cut the time in half, as well as
    # memory consumption. GraphIndex *does* like to look for a few keys in
    # parallel, it just doesn't like looking for *lots* of keys in parallel.
    # TODO: This code needs to be re-evaluated periodically as we tune the
    #       indexing layer. We might consider passing in hints as to the known
    #       access pattern (sparse/clustered, high success rate/low success
    #       rate). This particular access is clustered with a low success rate.
    modified_text_revisions = set()
    chunk_size = 1000
    for start in range(0, len(text_keys), chunk_size):
        next_keys = text_keys[start : start + chunk_size]
        # Only keep the revision_id portion of the key
        modified_text_revisions.update([k[1] for k in get_parent_map(next_keys)])
    del text_keys, next_keys

    result = []
    # Track what revisions will merge the current revision, replace entries
    # with 'None' when they have been added to result
    current_merge_stack = [None]
    for info in view_revisions:
        rev_id, revno, depth = info
        if depth == len(current_merge_stack):
            current_merge_stack.append(info)
        else:
            del current_merge_stack[depth + 1 :]
            current_merge_stack[-1] = info

        if rev_id in modified_text_revisions:
            # This needs to be logged, along with the extra revisions
            for idx in range(len(current_merge_stack)):
                node = current_merge_stack[idx]
                if node is not None:
                    if include_merges or node[2] == 0:
                        result.append(node)
                        current_merge_stack[idx] = None
    return result


def reverse_by_depth(merge_sorted_revisions, _depth=0):
    """Reverse revisions by depth.

    Revisions with a different depth are sorted as a group with the previous
    revision of that depth.  There may be no topological justification for this
    but it looks much nicer.
    """
    # Add a fake revision at start so that we can always attach sub revisions
    merge_sorted_revisions = [(None, None, _depth)] + merge_sorted_revisions
    zd_revisions = []
    for val in merge_sorted_revisions:
        if val[2] == _depth:
            # Each revision at the current depth becomes a chunk grouping all
            # higher depth revisions.
            zd_revisions.append([val])
        else:
            zd_revisions[-1].append(val)
    for revisions in zd_revisions:
        if len(revisions) > 1:
            # We have higher depth revisions, let reverse them locally
            revisions[1:] = reverse_by_depth(revisions[1:], _depth + 1)
    zd_revisions.reverse()
    result = []
    for chunk in zd_revisions:
        result.extend(chunk)
    if _depth == 0:
        # Top level call, get rid of the fake revisions that have been added
        result = [r for r in result if r[0] is not None and r[1] is not None]
    return result


class LogRevision:
    """A revision to be logged (by LogFormatter.log_revision).

    A simple wrapper for the attributes of a revision to be logged.
    The attributes may or may not be populated, as determined by the
    logging options and the log formatter capabilities.
    """

    def __init__(
        self,
        rev=None,
        revno=None,
        merge_depth=0,
        delta=None,
        tags=None,
        diff=None,
        signature=None,
    ):
        self.rev = rev
        if revno is None:
            self.revno = None
        else:
            self.revno = str(revno)
        self.merge_depth = merge_depth
        self.delta = delta
        self.tags = tags
        self.diff = diff
        self.signature = signature


class LogFormatter:
    """Abstract class to display log messages.

    At a minimum, a derived class must implement the log_revision method.

    If the LogFormatter needs to be informed of the beginning or end of
    a log it should implement the begin_log and/or end_log hook methods.

    A LogFormatter should define the following supports_XXX flags
    to indicate which LogRevision attributes it supports:

    - supports_delta must be True if this log formatter supports delta.
      Otherwise the delta attribute may not be populated.  The 'delta_format'
      attribute describes whether the 'short_status' format (1) or the long
      one (2) should be used.

    - supports_merge_revisions must be True if this log formatter supports
      merge revisions.  If not, then only mainline revisions will be passed
      to the formatter.

    - preferred_levels is the number of levels this formatter defaults to.
      The default value is zero meaning display all levels.
      This value is only relevant if supports_merge_revisions is True.

    - supports_tags must be True if this log formatter supports tags.
      Otherwise the tags attribute may not be populated.

    - supports_diff must be True if this log formatter supports diffs.
      Otherwise the diff attribute may not be populated.

    - supports_signatures must be True if this log formatter supports GPG
      signatures.

    Plugins can register functions to show custom revision properties using
    the properties_handler_registry. The registered function
    must respect the following interface description::

        def my_show_properties(properties_dict):
            # code that returns a dict {'name':'value'} of the properties
            # to be shown
    """

    preferred_levels = 0

    def __init__(
        self,
        to_file,
        show_ids=False,
        show_timezone="original",
        delta_format=None,
        levels=None,
        show_advice=False,
        to_exact_file=None,
        author_list_handler=None,
    ):
        """Create a LogFormatter.

        :param to_file: the file to output to
        :param to_exact_file: if set, gives an output stream to which
             non-Unicode diffs are written.
        :param show_ids: if True, revision-ids are to be displayed
        :param show_timezone: the timezone to use
        :param delta_format: the level of delta information to display
          or None to leave it to the formatter to decide
        :param levels: the number of levels to display; None or -1 to
          let the log formatter decide.
        :param show_advice: whether to show advice at the end of the
          log or not
        :param author_list_handler: callable generating a list of
          authors to display for a given revision
        """
        self.to_file = to_file
        # 'exact' stream used to show diff, it should print content 'as is'
        # and should not try to decode/encode it to unicode to avoid bug
        # #328007
        if to_exact_file is not None:
            self.to_exact_file = to_exact_file
        else:
            # XXX: somewhat hacky; this assumes it's a codec writer; it's
            # better for code that expects to get diffs to pass in the exact
            # file stream
            self.to_exact_file = getattr(to_file, "stream", to_file)
        self.show_ids = show_ids
        self.show_timezone = show_timezone
        if delta_format is None:
            # Ensures backward compatibility
            delta_format = 2  # long format
        self.delta_format = delta_format
        self.levels = levels
        self._show_advice = show_advice
        self._merge_count = 0
        self._author_list_handler = author_list_handler

    def get_levels(self):
        """Get the number of levels to display or 0 for all."""
        if getattr(self, "supports_merge_revisions", False):
            if self.levels is None or self.levels == -1:
                self.levels = self.preferred_levels
        else:
            self.levels = 1
        return self.levels

    def log_revision(self, revision):
        """Log a revision.

        :param  revision:   The LogRevision to be logged.
        """
        raise NotImplementedError("not implemented in abstract base")

    def show_advice(self):
        """Output user advice, if any, when the log is completed."""
        if self._show_advice and self.levels == 1 and self._merge_count > 0:
            advice_sep = self.get_advice_separator()
            if advice_sep:
                self.to_file.write(advice_sep)
            self.to_file.write("Use --include-merged or -n0 to see merged revisions.\n")

    def get_advice_separator(self):
        """Get the text separating the log from the closing advice."""
        return ""

    def short_committer(self, rev):
        name, address = config.parse_username(rev.committer)
        if name:
            return name
        return address

    def short_author(self, rev):
        return self.authors(rev, "first", short=True, sep=", ")

    def authors(self, rev, who, short=False, sep=None):
        """Generate list of authors, taking --authors option into account.

        The caller has to specify the name of a author list handler,
        as provided by the author list registry, using the ``who``
        argument.  That name only sets a default, though: when the
        user selected a different author list generation using the
        ``--authors`` command line switch, as represented by the
        ``author_list_handler`` constructor argument, that value takes
        precedence.

        :param rev: The revision for which to generate the list of authors.
        :param who: Name of the default handler.
        :param short: Whether to shorten names to either name or address.
        :param sep: What separator to use for automatic concatenation.
        """
        if self._author_list_handler is not None:
            # The user did specify --authors, which overrides the default
            author_list_handler = self._author_list_handler
        else:
            # The user didn't specify --authors, so we use the caller's default
            author_list_handler = author_list_registry.get(who)
        names = author_list_handler(rev)
        if short:
            for i in range(len(names)):
                name, address = config.parse_username(names[i])
                if name:
                    names[i] = name
                else:
                    names[i] = address
        if sep is not None:
            names = sep.join(names)
        return names

    def merge_marker(self, revision):
        """Get the merge marker to include in the output or '' if none."""
        if len(revision.rev.parent_ids) > 1:
            self._merge_count += 1
            return " [merge]"
        else:
            return ""

    def show_properties(self, revision, indent):
        """Displays the custom properties returned by each registered handler.

        If a registered handler raises an error it is propagated.
        """
        for line in self.custom_properties(revision):
            self.to_file.write("{}{}\n".format(indent, line))

    def custom_properties(self, revision):
        """Format the custom properties returned by each registered handler.

        If a registered handler raises an error it is propagated.

        :return: a list of formatted lines (excluding trailing newlines)
        """
        lines = self._foreign_info_properties(revision)
        for key, handler in properties_handler_registry.iteritems():
            try:
                lines.extend(self._format_properties(handler(revision)))
            except Exception:
                trace.log_exception_quietly()
                trace.print_exception(sys.exc_info(), self.to_file)
        return lines

    def _foreign_info_properties(self, rev):
        """Custom log displayer for foreign revision identifiers.

        :param rev: Revision object.
        """
        # Revision comes directly from a foreign repository
        if isinstance(rev, foreign.ForeignRevision):
            return self._format_properties(
                rev.mapping.vcs.show_foreign_revid(rev.foreign_revid)
            )

        # Imported foreign revision revision ids always contain :
        if b":" not in rev.revision_id:
            return []

        # Revision was once imported from a foreign repository
        try:
            foreign_revid, mapping = foreign.foreign_vcs_registry.parse_revision_id(
                rev.revision_id
            )
        except errors.InvalidRevisionId:
            return []

        return self._format_properties(mapping.vcs.show_foreign_revid(foreign_revid))

    def _format_properties(self, properties):
        lines = []
        for key, value in properties.items():
            lines.append(key + ": " + value)
        return lines

    def show_diff(self, to_file, diff, indent):
        encoding = get_terminal_encoding()
        for l in diff.rstrip().split(b"\n"):
            to_file.write(indent + l.decode(encoding, "ignore") + "\n")


# Separator between revisions in long format
_LONG_SEP = "-" * 60


class LongLogFormatter(LogFormatter):
    supports_merge_revisions = True
    preferred_levels = 1
    supports_delta = True
    supports_tags = True
    supports_diff = True
    supports_signatures = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.show_timezone == "original":
            self.date_string = self._date_string_original_timezone
        else:
            self.date_string = self._date_string_with_timezone

    def _date_string_with_timezone(self, rev):
        return format_date(rev.timestamp, rev.timezone or 0, self.show_timezone)

    def _date_string_original_timezone(self, rev):
        return format_date_with_offset_in_original_timezone(
            rev.timestamp, rev.timezone or 0
        )

    def log_revision(self, revision):
        """Log a revision, either merged or not."""
        indent = "    " * revision.merge_depth
        lines = [_LONG_SEP]
        if revision.revno is not None:
            lines.append(
                "revno: {}{}".format(revision.revno, self.merge_marker(revision))
            )
        if revision.tags:
            lines.append("tags: %s" % (", ".join(sorted(revision.tags))))
        if self.show_ids or revision.revno is None:
            lines.append(
                "revision-id: %s" % (revision.rev.revision_id.decode("utf-8"),)
            )
        if self.show_ids:
            for parent_id in revision.rev.parent_ids:
                lines.append("parent: {}".format(parent_id.decode("utf-8")))
        lines.extend(self.custom_properties(revision.rev))

        committer = revision.rev.committer
        authors = self.authors(revision.rev, "all")
        if authors != [committer]:
            lines.append("author: {}".format(", ".join(authors)))
        lines.append("committer: {}".format(committer))

        branch_nick = revision.rev.properties.get("branch-nick", None)
        if branch_nick is not None:
            lines.append("branch nick: {}".format(branch_nick))

        lines.append("timestamp: {}".format(self.date_string(revision.rev)))

        if revision.signature is not None:
            lines.append("signature: " + revision.signature)

        lines.append("message:")
        if not revision.rev.message:
            lines.append("  (no message)")
        else:
            message = revision.rev.message.rstrip("\r\n")
            for l in message.split("\n"):
                lines.append("  {}".format(l))

        # Dump the output, appending the delta and diff if requested
        to_file = self.to_file
        to_file.write("{}{}\n".format(indent, ("\n" + indent).join(lines)))
        if revision.delta is not None:
            # Use the standard status output to display changes
            from breezy.delta import report_delta

            report_delta(
                to_file,
                revision.delta,
                short_status=False,
                show_ids=self.show_ids,
                indent=indent,
            )
        if revision.diff is not None:
            to_file.write(indent + "diff:\n")
            to_file.flush()
            # Note: we explicitly don't indent the diff (relative to the
            # revision information) so that the output can be fed to patch -p0
            self.show_diff(self.to_exact_file, revision.diff, indent)
            self.to_exact_file.flush()

    def get_advice_separator(self):
        """Get the text separating the log from the closing advice."""
        return "-" * 60 + "\n"


class ShortLogFormatter(LogFormatter):
    supports_merge_revisions = True
    preferred_levels = 1
    supports_delta = True
    supports_tags = True
    supports_diff = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.revno_width_by_depth = {}

    def log_revision(self, revision):
        # We need two indents: one per depth and one for the information
        # relative to that indent. Most mainline revnos are 5 chars or
        # less while dotted revnos are typically 11 chars or less. Once
        # calculated, we need to remember the offset for a given depth
        # as we might be starting from a dotted revno in the first column
        # and we want subsequent mainline revisions to line up.
        depth = revision.merge_depth
        indent = "    " * depth
        revno_width = self.revno_width_by_depth.get(depth)
        if revno_width is None:
            if revision.revno is None or revision.revno.find(".") == -1:
                # mainline revno, e.g. 12345
                revno_width = 5
            else:
                # dotted revno, e.g. 12345.10.55
                revno_width = 11
            self.revno_width_by_depth[depth] = revno_width
        offset = " " * (revno_width + 1)

        to_file = self.to_file
        tags = ""
        if revision.tags:
            tags = " {%s}" % (", ".join(sorted(revision.tags)))
        to_file.write(
            indent
            + "%*s %s\t%s%s%s\n"
            % (
                revno_width,
                revision.revno or "",
                self.short_author(revision.rev),
                format_date(
                    revision.rev.timestamp,
                    revision.rev.timezone or 0,
                    self.show_timezone,
                    date_fmt="%Y-%m-%d",
                    show_offset=False,
                ),
                tags,
                self.merge_marker(revision),
            )
        )
        self.show_properties(revision.rev, indent + offset)
        if self.show_ids or revision.revno is None:
            to_file.write(
                indent
                + offset
                + "revision-id:%s\n" % (revision.rev.revision_id.decode("utf-8"),)
            )
        if not revision.rev.message:
            to_file.write(indent + offset + "(no message)\n")
        else:
            message = revision.rev.message.rstrip("\r\n")
            for l in message.split("\n"):
                to_file.write(indent + offset + "{}\n".format(l))

        if revision.delta is not None:
            # Use the standard status output to display changes
            from breezy.delta import report_delta

            report_delta(
                to_file,
                revision.delta,
                short_status=self.delta_format == 1,
                show_ids=self.show_ids,
                indent=indent + offset,
            )
        if revision.diff is not None:
            self.show_diff(self.to_exact_file, revision.diff, "      ")
        to_file.write("\n")


class LineLogFormatter(LogFormatter):
    supports_merge_revisions = True
    preferred_levels = 1
    supports_tags = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        width = terminal_width()
        if width is not None:
            # we need one extra space for terminals that wrap on last char
            width = width - 1
        self._max_chars = width

    def truncate(self, str, max_len):
        if max_len is None or len(str) <= max_len:
            return str
        return str[: max_len - 3] + "..."

    def date_string(self, rev):
        return format_date(
            rev.timestamp,
            rev.timezone or 0,
            self.show_timezone,
            date_fmt="%Y-%m-%d",
            show_offset=False,
        )

    def message(self, rev):
        if not rev.message:
            return "(no message)"
        else:
            return rev.message

    def log_revision(self, revision):
        indent = "  " * revision.merge_depth
        self.to_file.write(
            self.log_string(
                revision.revno, revision.rev, self._max_chars, revision.tags, indent
            )
        )
        self.to_file.write("\n")

    def log_string(self, revno, rev, max_chars, tags=None, prefix=""):
        """Format log info into one string. Truncate tail of string

        :param revno:      revision number or None.
                           Revision numbers counts from 1.
        :param rev:        revision object
        :param max_chars:  maximum length of resulting string
        :param tags:       list of tags or None
        :param prefix:     string to prefix each line
        :return:           formatted truncated string
        """
        out = []
        if revno:
            # show revno only when is not None
            out.append("%s:" % revno)
        if max_chars is not None:
            out.append(self.truncate(self.short_author(rev), (max_chars + 3) // 4))
        else:
            out.append(self.short_author(rev))
        out.append(self.date_string(rev))
        if len(rev.parent_ids) > 1:
            out.append("[merge]")
        if tags:
            tag_str = "{%s}" % (", ".join(sorted(tags)))
            out.append(tag_str)
        out.append(rev.get_summary())
        return self.truncate(prefix + " ".join(out).rstrip("\n"), max_chars)


class GnuChangelogLogFormatter(LogFormatter):
    supports_merge_revisions = True
    supports_delta = True

    def log_revision(self, revision):
        """Log a revision, either merged or not."""
        to_file = self.to_file

        date_str = format_date(
            revision.rev.timestamp,
            revision.rev.timezone or 0,
            self.show_timezone,
            date_fmt="%Y-%m-%d",
            show_offset=False,
        )
        committer_str = self.authors(revision.rev, "first", sep=", ")
        committer_str = committer_str.replace(" <", "  <")
        to_file.write("{}  {}\n\n".format(date_str, committer_str))

        if revision.delta is not None and revision.delta.has_changed():
            for c in (
                revision.delta.added + revision.delta.removed + revision.delta.modified
            ):
                if c.path[0] is None:
                    path = c.path[1]
                else:
                    path = c.path[0]
                to_file.write("\t* {}:\n".format(path))
            for c in revision.delta.renamed + revision.delta.copied:
                # For renamed files, show both the old and the new path
                to_file.write("\t* {}:\n\t* {}:\n".format(c.path[0], c.path[1]))
            to_file.write("\n")

        if not revision.rev.message:
            to_file.write("\tNo commit message\n")
        else:
            message = revision.rev.message.rstrip("\r\n")
            for l in message.split("\n"):
                to_file.write("\t{}\n".format(l.lstrip()))
            to_file.write("\n")


def line_log(rev, max_chars):
    lf = LineLogFormatter(None)
    return lf.log_string(None, rev, max_chars)


class LogFormatterRegistry(registry.Registry):
    """Registry for log formatters"""

    def make_formatter(self, name, *args, **kwargs):
        """Construct a formatter from arguments.

        :param name: Name of the formatter to construct.  'short', 'long' and
            'line' are built-in.
        """
        return self.get(name)(*args, **kwargs)

    def get_default(self, branch):
        c = branch.get_config_stack()
        return self.get(c.get("log_format"))


log_formatter_registry = LogFormatterRegistry()


log_formatter_registry.register(
    "short", ShortLogFormatter, "Moderately short log format."
)
log_formatter_registry.register("long", LongLogFormatter, "Detailed log format.")
log_formatter_registry.register(
    "line", LineLogFormatter, "Log format with one line per revision."
)
log_formatter_registry.register(
    "gnu-changelog", GnuChangelogLogFormatter, "Format used by GNU ChangeLog files."
)


def register_formatter(name, formatter):
    log_formatter_registry.register(name, formatter)


def log_formatter(name, *args, **kwargs):
    """Construct a formatter from arguments.

    name -- Name of the formatter to construct; currently 'long', 'short' and
        'line' are supported.
    """
    try:
        return log_formatter_registry.make_formatter(name, *args, **kwargs)
    except KeyError:
        raise errors.CommandError(gettext("unknown log formatter: %r") % name)


def author_list_all(rev):
    return rev.get_apparent_authors()[:]


def author_list_first(rev):
    lst = rev.get_apparent_authors()
    try:
        return [lst[0]]
    except IndexError:
        return []


def author_list_committer(rev):
    return [rev.committer]


author_list_registry = registry.Registry[
    str, Callable[[_mod_revision.Revision], List[str]]
]()

author_list_registry.register("all", author_list_all, "All authors")

author_list_registry.register("first", author_list_first, "The first author")

author_list_registry.register("committer", author_list_committer, "The committer")


def show_changed_revisions(branch, old_rh, new_rh, to_file=None, log_format="long"):
    """Show the change in revision history comparing the old revision history to the new one.

    :param branch: The branch where the revisions exist
    :param old_rh: The old revision history
    :param new_rh: The new revision history
    :param to_file: A file to write the results to. If None, stdout will be used
    """
    if to_file is None:
        to_file = codecs.getwriter(get_terminal_encoding())(
            sys.stdout, errors="replace"
        )
    lf = log_formatter(
        log_format, show_ids=False, to_file=to_file, show_timezone="original"
    )

    # This is the first index which is different between
    # old and new
    base_idx = None
    for i in range(max(len(new_rh), len(old_rh))):
        if len(new_rh) <= i or len(old_rh) <= i or new_rh[i] != old_rh[i]:
            base_idx = i
            break

    if base_idx is None:
        to_file.write("Nothing seems to have changed\n")
        return
    # TODO: It might be nice to do something like show_log
    # and show the merged entries. But since this is the
    # removed revisions, it shouldn't be as important
    if base_idx < len(old_rh):
        to_file.write("*" * 60)
        to_file.write("\nRemoved Revisions:\n")
        for i in range(base_idx, len(old_rh)):
            rev = branch.repository.get_revision(old_rh[i])
            lr = LogRevision(rev, i + 1, 0, None)
            lf.log_revision(lr)
        to_file.write("*" * 60)
        to_file.write("\n\n")
    if base_idx < len(new_rh):
        to_file.write("Added Revisions:\n")
        show_log(
            branch,
            lf,
            verbose=False,
            direction="forward",
            start_revision=base_idx + 1,
            end_revision=len(new_rh),
        )


def get_history_change(old_revision_id, new_revision_id, repository):
    """Calculate the uncommon lefthand history between two revisions.

    :param old_revision_id: The original revision id.
    :param new_revision_id: The new revision id.
    :param repository: The repository to use for the calculation.

    return old_history, new_history
    """
    old_history = []
    old_revisions = set()
    new_history = []
    new_revisions = set()
    graph = repository.get_graph()
    new_iter = graph.iter_lefthand_ancestry(new_revision_id)
    old_iter = graph.iter_lefthand_ancestry(old_revision_id)
    stop_revision = None
    do_old = True
    do_new = True
    while do_new or do_old:
        if do_new:
            try:
                new_revision = next(new_iter)
            except StopIteration:
                do_new = False
            else:
                new_history.append(new_revision)
                new_revisions.add(new_revision)
                if new_revision in old_revisions:
                    stop_revision = new_revision
                    break
        if do_old:
            try:
                old_revision = next(old_iter)
            except StopIteration:
                do_old = False
            else:
                old_history.append(old_revision)
                old_revisions.add(old_revision)
                if old_revision in new_revisions:
                    stop_revision = old_revision
                    break
    new_history.reverse()
    old_history.reverse()
    if stop_revision is not None:
        new_history = new_history[new_history.index(stop_revision) + 1 :]
        old_history = old_history[old_history.index(stop_revision) + 1 :]
    return old_history, new_history


def show_branch_change(branch, output, old_revno, old_revision_id):
    """Show the changes made to a branch.

    :param branch: The branch to show changes about.
    :param output: A file-like object to write changes to.
    :param old_revno: The revno of the old tip.
    :param old_revision_id: The revision_id of the old tip.
    """
    new_revno, new_revision_id = branch.last_revision_info()
    old_history, new_history = get_history_change(
        old_revision_id, new_revision_id, branch.repository
    )
    if old_history == [] and new_history == []:
        output.write("Nothing seems to have changed\n")
        return

    log_format = log_formatter_registry.get_default(branch)
    lf = log_format(show_ids=False, to_file=output, show_timezone="original")
    if old_history != []:
        output.write("*" * 60)
        output.write("\nRemoved Revisions:\n")
        show_flat_log(branch.repository, old_history, old_revno, lf)
        output.write("*" * 60)
        output.write("\n\n")
    if new_history != []:
        output.write("Added Revisions:\n")
        start_revno = new_revno - len(new_history) + 1
        show_log(
            branch, lf, verbose=False, direction="forward", start_revision=start_revno
        )


def show_flat_log(repository, history, last_revno, lf):
    """Show a simple log of the specified history.

    :param repository: The repository to retrieve revisions from.
    :param history: A list of revision_ids indicating the lefthand history.
    :param last_revno: The revno of the last revision_id in the history.
    :param lf: The log formatter to use.
    """
    revisions = repository.get_revisions(history)
    for i, rev in enumerate(revisions):
        lr = LogRevision(rev, i + last_revno, 0, None)
        lf.log_revision(lr)


def _get_info_for_log_files(revisionspec_list, file_list, exit_stack):
    """Find files and kinds given a list of files and a revision range.

    We search for files at the end of the range. If not found there,
    we try the start of the range.

    :param revisionspec_list: revision range as parsed on the command line
    :param file_list: the list of paths given on the command line;
      the first of these can be a branch location or a file path,
      the remainder must be file paths
    :param exit_stack: When the branch returned is read locked,
      an unlock call will be queued to the exit stack.
    :return: (branch, info_list, start_rev_info, end_rev_info) where
      info_list is a list of (relative_path, found, kind) tuples where
      kind is one of values 'directory', 'file', 'symlink', 'tree-reference'.
      branch will be read-locked.
    """
    from breezy.builtins import _get_revision_range

    tree, b, path = controldir.ControlDir.open_containing_tree_or_branch(file_list[0])
    exit_stack.enter_context(b.lock_read())
    # XXX: It's damn messy converting a list of paths to relative paths when
    # those paths might be deleted ones, they might be on a case-insensitive
    # filesystem and/or they might be in silly locations (like another branch).
    # For example, what should "log bzr://branch/dir/file1 file2" do? (Is
    # file2 implicitly in the same dir as file1 or should its directory be
    # taken from the current tree somehow?) For now, this solves the common
    # case of running log in a nested directory, assuming paths beyond the
    # first one haven't been deleted ...
    if tree:
        relpaths = [path] + tree.safe_relpath_files(file_list[1:])
    else:
        relpaths = [path] + file_list[1:]
    info_list = []
    start_rev_info, end_rev_info = _get_revision_range(revisionspec_list, b, "log")
    if relpaths in ([], [""]):
        return b, [], start_rev_info, end_rev_info
    if start_rev_info is None and end_rev_info is None:
        if tree is None:
            tree = b.basis_tree()
        tree1 = None
        for fp in relpaths:
            kind = _get_kind_for_file(tree, fp)
            if not kind:
                # go back to when time began
                if tree1 is None:
                    try:
                        rev1 = b.get_rev_id(1)
                    except errors.NoSuchRevision:
                        # No history at all
                        kind = None
                    else:
                        tree1 = b.repository.revision_tree(rev1)
                if tree1:
                    kind = _get_kind_for_file(tree1, fp)
            info_list.append((fp, kind))

    elif start_rev_info == end_rev_info:
        # One revision given - file must exist in it
        tree = b.repository.revision_tree(end_rev_info.rev_id)
        for fp in relpaths:
            kind = _get_kind_for_file(tree, fp)
            info_list.append((fp, kind))

    else:
        # Revision range given. Get the file-id from the end tree.
        # If that fails, try the start tree.
        rev_id = end_rev_info.rev_id
        if rev_id is None:
            tree = b.basis_tree()
        else:
            tree = b.repository.revision_tree(rev_id)
        tree1 = None
        for fp in relpaths:
            kind = _get_kind_for_file(tree, fp)
            if not kind:
                if tree1 is None:
                    rev_id = start_rev_info.rev_id
                    if rev_id is None:
                        rev1 = b.get_rev_id(1)
                        tree1 = b.repository.revision_tree(rev1)
                    else:
                        tree1 = b.repository.revision_tree(rev_id)
                kind = _get_kind_for_file(tree1, fp)
            info_list.append((fp, kind))
    return b, info_list, start_rev_info, end_rev_info


def _get_kind_for_file(tree, path):
    """Return the kind of a path or None if it doesn't exist."""
    with tree.lock_read():
        try:
            return tree.stored_kind(path)
        except _mod_transport.NoSuchFile:
            return None


properties_handler_registry = registry.Registry[
    str, Callable[[Dict[str, str]], Dict[str, str]]
]()

# Use the properties handlers to print out bug information if available


def _bugs_properties_handler(revision):
    fixed_bug_urls = []
    related_bug_urls = []
    for bug_url, status in revision.iter_bugs():
        if status == "fixed":
            fixed_bug_urls.append(bug_url)
        elif status == "related":
            related_bug_urls.append(bug_url)
    ret = {}
    if fixed_bug_urls:
        text = ngettext("fixes bug", "fixes bugs", len(fixed_bug_urls))
        ret[text] = " ".join(fixed_bug_urls)
    if related_bug_urls:
        text = ngettext("related bug", "related bugs", len(related_bug_urls))
        ret[text] = " ".join(related_bug_urls)
    return ret


properties_handler_registry.register(
    "bugs_properties_handler", _bugs_properties_handler
)


# adapters which revision ids to log are filtered. When log is called, the
# log_rev_iterator is adapted through each of these factory methods.
# Plugins are welcome to mutate this list in any way they like - as long
# as the overall behaviour is preserved. At this point there is no extensible
# mechanism for getting parameters to each factory method, and until there is
# this won't be considered a stable api.
log_adapters = [
    # core log logic
    _make_batch_filter,
    # read revision objects
    _make_revision_objects,
    # filter on log messages
    _make_search_filter,
    # generate deltas for things we will show
    _make_delta_filter,
]
