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

import contextlib
import tempfile

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
import patiencediff

from breezy import (
    debug,
    graph as _mod_graph,
    textfile,
    ui,
    )
from breezy.bzr import (
    generate_ids,
    )
from breezy.i18n import gettext
""",
)
from . import decorators, errors, hooks, osutils, registry, trace, transform
from . import revision as _mod_revision
from . import transport as _mod_transport
from . import tree as _mod_tree

# TODO: Report back as changes are merged in


class CantReprocessAndShowBase(errors.BzrError):
    _fmt = (
        "Can't reprocess and show base, because reprocessing obscures "
        "the relationship of conflicting lines to the base"
    )


def transform_tree(from_tree, to_tree, interesting_files=None):
    with from_tree.lock_tree_write():
        merge_inner(
            from_tree.branch,
            to_tree,
            from_tree,
            ignore_zero=True,
            this_tree=from_tree,
            interesting_files=interesting_files,
        )


class MergeHooks(hooks.Hooks):
    def __init__(self):
        hooks.Hooks.__init__(self, "breezy.merge", "Merger.hooks")
        self.add_hook(
            "merge_file_content",
            "Called with a breezy.merge.Merger object to create a per file "
            "merge object when starting a merge. "
            "Should return either None or a subclass of "
            "``breezy.merge.AbstractPerFileMerger``. "
            "Such objects will then be called per file "
            "that needs to be merged (including when one "
            "side has deleted the file and the other has changed it). "
            "See the AbstractPerFileMerger API docs for details on how it is "
            "used by merge.",
            (2, 1),
        )
        self.add_hook(
            "pre_merge",
            "Called before a merge. Receives a Merger object as the single argument.",
            (2, 5),
        )
        self.add_hook(
            "post_merge",
            "Called after a merge. "
            "Receives a Merger object as the single argument. "
            "The return value is ignored.",
            (2, 5),
        )


class AbstractPerFileMerger:
    """PerFileMerger objects are used by plugins extending merge for breezy.

    See ``breezy.plugins.news_merge.news_merge`` for an example concrete class.

    :ivar merger: The Merge3Merger performing the merge.
    """

    def __init__(self, merger):
        """Create a PerFileMerger for use with merger."""
        self.merger = merger

    def merge_contents(self, merge_params):
        """Attempt to merge the contents of a single file.

        :param merge_params: A breezy.merge.MergeFileHookParams
        :return: A tuple of (status, chunks), where status is one of
            'not_applicable', 'success', 'conflicted', or 'delete'.  If status
            is 'success' or 'conflicted', then chunks should be an iterable of
            strings for the new file contents.
        """
        return ("not applicable", None)


class PerFileMerger(AbstractPerFileMerger):
    """Merge individual files when self.file_matches returns True.

    This class is intended to be subclassed.  The file_matches and
    merge_matching methods should be overridden with concrete implementations.
    """

    def file_matches(self, params):
        """Return True if merge_matching should be called on this file.

        Only called with merges of plain files with no clear winner.

        Subclasses must override this.
        """
        raise NotImplementedError(self.file_matches)

    def merge_contents(self, params):
        """Merge the contents of a single file."""
        # Check whether this custom merge logic should be used.
        if (
            # OTHER is a straight winner, rely on default merge.
            params.winner == "other"
            or
            # THIS and OTHER aren't both files.
            not params.is_file_merge()
            or
            # The filename doesn't match
            not self.file_matches(params)
        ):
            return "not_applicable", None
        return self.merge_matching(params)

    def merge_matching(self, params):
        """Merge the contents of a single file that has matched the criteria
        in PerFileMerger.merge_contents (is a conflict, is a file,
        self.file_matches is True).

        Subclasses must override this.
        """
        raise NotImplementedError(self.merge_matching)


class ConfigurableFileMerger(PerFileMerger):
    """Merge individual files when configured via a .conf file.

    This is a base class for concrete custom file merging logic. Concrete
    classes should implement ``merge_text``.

    See ``breezy.plugins.news_merge.news_merge`` for an example concrete class.

    :ivar affected_files: The configured file paths to merge.

    :cvar name_prefix: The prefix to use when looking up configuration
        details. <name_prefix>_merge_files describes the files targeted by the
        hook for example.

    :cvar default_files: The default file paths to merge when no configuration
        is present.
    """

    name_prefix: str
    default_files = None

    def __init__(self, merger):
        super().__init__(merger)
        self.affected_files = None
        self.default_files = self.__class__.default_files or []
        self.name_prefix = self.__class__.name_prefix
        if self.name_prefix is None:
            raise ValueError("name_prefix must be set.")

    def file_matches(self, params):
        """Check whether the file should call the merge hook.

        <name_prefix>_merge_files configuration variable is a list of files
        that should use the hook.
        """
        affected_files = self.affected_files
        if affected_files is None:
            config = self.merger.this_branch.get_config()
            # Until bzr provides a better policy for caching the config, we
            # just add the part we're interested in to the params to avoid
            # reading the config files repeatedly (breezy.conf, location.conf,
            # branch.conf).
            config_key = self.name_prefix + "_merge_files"
            affected_files = config.get_user_option_as_list(config_key)
            if affected_files is None:
                # If nothing was specified in the config, use the default.
                affected_files = self.default_files
            self.affected_files = affected_files
        if affected_files:
            filepath = params.this_path
            if filepath in affected_files:
                return True
        return False

    def merge_matching(self, params):
        return self.merge_text(params)

    def merge_text(self, params):
        """Merge the byte contents of a single file.

        This is called after checking that the merge should be performed in
        merge_contents, and it should behave as per
        ``breezy.merge.AbstractPerFileMerger.merge_contents``.
        """
        raise NotImplementedError(self.merge_text)


class MergeFileHookParams:
    """Object holding parameters passed to merge_file_content hooks.

    There are some fields hooks can access:

    :ivar base_path: Path in base tree
    :ivar other_path: Path in other tree
    :ivar this_path: Path in this tree
    :ivar trans_id: the transform ID for the merge of this file
    :ivar this_kind: kind of file in 'this' tree
    :ivar other_kind: kind of file in 'other' tree
    :ivar winner: one of 'this', 'other', 'conflict'
    """

    def __init__(self, merger, paths, trans_id, this_kind, other_kind, winner):
        self._merger = merger
        self.paths = paths
        self.base_path, self.other_path, self.this_path = paths
        self.trans_id = trans_id
        self.this_kind = this_kind
        self.other_kind = other_kind
        self.winner = winner

    def is_file_merge(self):
        """True if this_kind and other_kind are both 'file'."""
        return self.this_kind == "file" and self.other_kind == "file"

    @decorators.cachedproperty
    def base_lines(self):
        """The lines of the 'base' version of the file."""
        return self._merger.get_lines(self._merger.base_tree, self.base_path)

    @decorators.cachedproperty
    def this_lines(self):
        """The lines of the 'this' version of the file."""
        return self._merger.get_lines(self._merger.this_tree, self.this_path)

    @decorators.cachedproperty
    def other_lines(self):
        """The lines of the 'other' version of the file."""
        return self._merger.get_lines(self._merger.other_tree, self.other_path)


class Merger:
    hooks = MergeHooks()

    # TODO(jelmer): There should probably be a merger base type
    merge_type: object

    def __init__(
        self,
        this_branch,
        other_tree=None,
        base_tree=None,
        this_tree=None,
        change_reporter=None,
        recurse="down",
        revision_graph=None,
    ):
        object.__init__(self)
        self.this_branch = this_branch
        self.this_basis = this_branch.last_revision()
        self.this_rev_id = None
        self.this_tree = this_tree
        self.this_revision_tree = None
        self.this_basis_tree = None
        self.other_tree = other_tree
        self.other_branch = None
        self.base_tree = base_tree
        self.ignore_zero = False
        self.backup_files = False
        self.interesting_files = None
        self.show_base = False
        self.reprocess = False
        self.pp = None
        self.recurse = recurse
        self.change_reporter = change_reporter
        self._cached_trees = {}
        self._revision_graph = revision_graph
        self._base_is_ancestor = None
        self._base_is_other_ancestor = None
        self._is_criss_cross = None
        self._lca_trees = None

    def cache_trees_with_revision_ids(self, trees):
        """Cache any tree in trees if it has a revision_id."""
        for maybe_tree in trees:
            if maybe_tree is None:
                continue
            try:
                rev_id = maybe_tree.get_revision_id()
            except AttributeError:
                continue
            self._cached_trees[rev_id] = maybe_tree

    @property
    def revision_graph(self):
        if self._revision_graph is None:
            self._revision_graph = self.this_branch.repository.get_graph()
        return self._revision_graph

    def _set_base_is_ancestor(self, value):
        self._base_is_ancestor = value

    def _get_base_is_ancestor(self):
        if self._base_is_ancestor is None:
            self._base_is_ancestor = self.revision_graph.is_ancestor(
                self.base_rev_id, self.this_basis
            )
        return self._base_is_ancestor

    base_is_ancestor = property(_get_base_is_ancestor, _set_base_is_ancestor)

    def _set_base_is_other_ancestor(self, value):
        self._base_is_other_ancestor = value

    def _get_base_is_other_ancestor(self):
        if self._base_is_other_ancestor is None:
            if self.other_basis is None:
                return True
            self._base_is_other_ancestor = self.revision_graph.is_ancestor(
                self.base_rev_id, self.other_basis
            )
        return self._base_is_other_ancestor

    base_is_other_ancestor = property(
        _get_base_is_other_ancestor, _set_base_is_other_ancestor
    )

    @staticmethod
    def from_uncommitted(tree, other_tree, base_tree=None):
        """Return a Merger for uncommitted changes in other_tree.

        :param tree: The tree to merge into
        :param other_tree: The tree to get uncommitted changes from
        :param base_tree: The basis to use for the merge.  If unspecified,
            other_tree.basis_tree() will be used.
        """
        if base_tree is None:
            base_tree = other_tree.basis_tree()
        merger = Merger(tree.branch, other_tree, base_tree, tree)
        merger.base_rev_id = merger.base_tree.get_revision_id()
        merger.other_rev_id = None
        merger.other_basis = merger.base_rev_id
        return merger

    @classmethod
    def from_mergeable(klass, tree, mergeable):
        """Return a Merger for a bundle or merge directive.

        :param tree: The tree to merge changes into
        :param mergeable: A merge directive or bundle
        """
        mergeable.install_revisions(tree.branch.repository)
        base_revision_id, other_revision_id, verified = mergeable.get_merge_request(
            tree.branch.repository
        )
        revision_graph = tree.branch.repository.get_graph()
        if base_revision_id is not None:
            if (
                base_revision_id != _mod_revision.NULL_REVISION
                and revision_graph.is_ancestor(
                    base_revision_id, tree.branch.last_revision()
                )
            ):
                base_revision_id = None
            else:
                trace.warning("Performing cherrypick")
        merger = klass.from_revision_ids(
            tree, other_revision_id, base_revision_id, revision_graph=revision_graph
        )
        return merger, verified

    @staticmethod
    def from_revision_ids(
        tree,
        other,
        base=None,
        other_branch=None,
        base_branch=None,
        revision_graph=None,
        tree_branch=None,
    ):
        """Return a Merger for revision-ids.

        :param tree: The tree to merge changes into
        :param other: The revision-id to use as OTHER
        :param base: The revision-id to use as BASE.  If not specified, will
            be auto-selected.
        :param other_branch: A branch containing the other revision-id.  If
            not supplied, tree.branch is used.
        :param base_branch: A branch containing the base revision-id.  If
            not supplied, other_branch or tree.branch will be used.
        :param revision_graph: If you have a revision_graph precomputed, pass
            it in, otherwise it will be created for you.
        :param tree_branch: The branch associated with tree.  If not supplied,
            tree.branch will be used.
        """
        if tree_branch is None:
            tree_branch = tree.branch
        merger = Merger(tree_branch, this_tree=tree, revision_graph=revision_graph)
        if other_branch is None:
            other_branch = tree.branch
        merger.set_other_revision(other, other_branch)
        if base is None:
            merger.find_base()
        else:
            if base_branch is None:
                base_branch = other_branch
            merger.set_base_revision(base, base_branch)
        return merger

    def revision_tree(self, revision_id, branch=None):
        if revision_id not in self._cached_trees:
            if branch is None:
                branch = self.this_branch
            try:
                tree = self.this_tree.revision_tree(revision_id)
            except errors.NoSuchRevisionInTree:
                tree = branch.repository.revision_tree(revision_id)
            self._cached_trees[revision_id] = tree
        return self._cached_trees[revision_id]

    def _get_tree(self, treespec, possible_transports=None):
        location, revno = treespec
        if revno is None:
            from .workingtree import WorkingTree

            tree = WorkingTree.open_containing(location)[0]
            return tree.branch, tree
        from .branch import Branch

        branch = Branch.open_containing(location, possible_transports)[0]
        if revno == -1:
            revision_id = branch.last_revision()
        else:
            revision_id = branch.get_rev_id(revno)
        return branch, self.revision_tree(revision_id, branch)

    def set_interesting_files(self, file_list):
        self.interesting_files = file_list

    def set_pending(self):
        if (
            not self.base_is_ancestor
            or not self.base_is_other_ancestor
            or self.other_rev_id is None
        ):
            return
        self._add_parent()

    def _add_parent(self):
        new_parents = self.this_tree.get_parent_ids() + [self.other_rev_id]
        new_parent_trees = []
        with contextlib.ExitStack() as stack:
            for revision_id in new_parents:
                try:
                    tree = self.revision_tree(revision_id)
                except errors.NoSuchRevision:
                    tree = None
                else:
                    stack.enter_context(tree.lock_read())
                new_parent_trees.append((revision_id, tree))
            self.this_tree.set_parent_trees(
                new_parent_trees, allow_leftmost_as_ghost=True
            )

    def set_other(self, other_revision, possible_transports=None):
        """Set the revision and tree to merge from.

        This sets the other_tree, other_rev_id, other_basis attributes.

        :param other_revision: The [path, revision] list to merge from.
        """
        self.other_branch, self.other_tree = self._get_tree(
            other_revision, possible_transports
        )
        if other_revision[1] == -1:
            self.other_rev_id = self.other_branch.last_revision()
            if _mod_revision.is_null(self.other_rev_id):
                raise errors.NoCommits(self.other_branch)
            self.other_basis = self.other_rev_id
        elif other_revision[1] is not None:
            self.other_rev_id = self.other_branch.get_rev_id(other_revision[1])
            self.other_basis = self.other_rev_id
        else:
            self.other_rev_id = None
            self.other_basis = self.other_branch.last_revision()
            if self.other_basis is None:
                raise errors.NoCommits(self.other_branch)
        if self.other_rev_id is not None:
            self._cached_trees[self.other_rev_id] = self.other_tree
        self._maybe_fetch(self.other_branch, self.this_branch, self.other_basis)

    def set_other_revision(self, revision_id, other_branch):
        """Set 'other' based on a branch and revision id.

        :param revision_id: The revision to use for a tree
        :param other_branch: The branch containing this tree
        """
        self.other_rev_id = revision_id
        self.other_branch = other_branch
        self._maybe_fetch(other_branch, self.this_branch, self.other_rev_id)
        self.other_tree = self.revision_tree(revision_id)
        self.other_basis = revision_id

    def set_base_revision(self, revision_id, branch):
        """Set 'base' based on a branch and revision id.

        :param revision_id: The revision to use for a tree
        :param branch: The branch containing this tree
        """
        self.base_rev_id = revision_id
        self.base_branch = branch
        self._maybe_fetch(branch, self.this_branch, revision_id)
        self.base_tree = self.revision_tree(revision_id)

    def _maybe_fetch(self, source, target, revision_id):
        if not source.repository.has_same_location(target.repository):
            target.fetch(source, revision_id)

    def find_base(self):
        revisions = [self.this_basis, self.other_basis]
        if _mod_revision.NULL_REVISION in revisions:
            self.base_rev_id = _mod_revision.NULL_REVISION
            self.base_tree = self.revision_tree(self.base_rev_id)
            self._is_criss_cross = False
        else:
            lcas = self.revision_graph.find_lca(revisions[0], revisions[1])
            self._is_criss_cross = False
            if len(lcas) == 0:
                self.base_rev_id = _mod_revision.NULL_REVISION
            elif len(lcas) == 1:
                self.base_rev_id = list(lcas)[0]
            else:  # len(lcas) > 1
                self._is_criss_cross = True
                if len(lcas) > 2:
                    # find_unique_lca can only handle 2 nodes, so we have to
                    # start back at the beginning. It is a shame to traverse
                    # the graph again, but better than re-implementing
                    # find_unique_lca.
                    self.base_rev_id = self.revision_graph.find_unique_lca(
                        revisions[0], revisions[1]
                    )
                else:
                    self.base_rev_id = self.revision_graph.find_unique_lca(*lcas)
                sorted_lca_keys = self.revision_graph.find_merge_order(
                    revisions[0], lcas
                )
                if self.base_rev_id == _mod_revision.NULL_REVISION:
                    self.base_rev_id = sorted_lca_keys[0]

            if self.base_rev_id == _mod_revision.NULL_REVISION:
                raise errors.UnrelatedBranches()
            if self._is_criss_cross:
                trace.warning(
                    "Warning: criss-cross merge encountered.  See bzr help criss-cross."
                )
                trace.mutter("Criss-cross lcas: {!r}".format(lcas))
                if self.base_rev_id in lcas:
                    trace.mutter(
                        "Unable to find unique lca. "
                        "Fallback {!r} as best option.".format(self.base_rev_id)
                    )
                interesting_revision_ids = set(lcas)
                interesting_revision_ids.add(self.base_rev_id)
                interesting_trees = {
                    t.get_revision_id(): t
                    for t in self.this_branch.repository.revision_trees(
                        interesting_revision_ids
                    )
                }
                self._cached_trees.update(interesting_trees)
                if self.base_rev_id in lcas:
                    self.base_tree = interesting_trees[self.base_rev_id]
                else:
                    self.base_tree = interesting_trees.pop(self.base_rev_id)
                self._lca_trees = [interesting_trees[key] for key in sorted_lca_keys]
            else:
                self.base_tree = self.revision_tree(self.base_rev_id)
        self.base_is_ancestor = True
        self.base_is_other_ancestor = True
        trace.mutter("Base revid: {!r}".format(self.base_rev_id))

    def set_base(self, base_revision):
        """Set the base revision to use for the merge.

        :param base_revision: A 2-list containing a path and revision number.
        """
        trace.mutter("doing merge() with no base_revision specified")
        if base_revision == [None, None]:
            self.find_base()
        else:
            base_branch, self.base_tree = self._get_tree(base_revision)
            if base_revision[1] == -1:
                self.base_rev_id = base_branch.last_revision()
            elif base_revision[1] is None:
                self.base_rev_id = _mod_revision.NULL_REVISION
            else:
                self.base_rev_id = base_branch.get_rev_id(base_revision[1])
            self._maybe_fetch(base_branch, self.this_branch, self.base_rev_id)

    def make_merger(self):
        kwargs = {
            "working_tree": self.this_tree,
            "this_tree": self.this_tree,
            "other_tree": self.other_tree,
            "interesting_files": self.interesting_files,
            "this_branch": self.this_branch,
            "other_branch": self.other_branch,
            "do_merge": False,
        }
        if self.merge_type.requires_base:
            kwargs["base_tree"] = self.base_tree
        if self.merge_type.supports_reprocess:
            kwargs["reprocess"] = self.reprocess
        elif self.reprocess:
            raise errors.BzrError(
                "Conflict reduction is not supported for merge type {}.".format(
                    self.merge_type
                )
            )
        if self.merge_type.supports_show_base:
            kwargs["show_base"] = self.show_base
        elif self.show_base:
            raise errors.BzrError(
                "Showing base is not supported for this merge type. {}".format(
                    self.merge_type
                )
            )
        if (
            not getattr(self.merge_type, "supports_reverse_cherrypick", True)
            and not self.base_is_other_ancestor
        ):
            raise errors.CannotReverseCherrypick()
        if self.merge_type.supports_cherrypick:
            kwargs["cherrypick"] = (
                not self.base_is_ancestor or not self.base_is_other_ancestor
            )
        if self._is_criss_cross and getattr(
            self.merge_type, "supports_lca_trees", False
        ):
            kwargs["lca_trees"] = self._lca_trees
        return self.merge_type(change_reporter=self.change_reporter, **kwargs)

    def _do_merge_to(self):
        merge = self.make_merger()
        if self.other_branch is not None:
            self.other_branch.update_references(self.this_branch)
        for hook in Merger.hooks["pre_merge"]:
            hook(merge)
        merge.do_merge()
        for hook in Merger.hooks["post_merge"]:
            hook(merge)
        if self.recurse == "down":
            for relpath in self.this_tree.iter_references():
                sub_tree = self.this_tree.get_nested_tree(relpath)
                other_revision = self.other_tree.get_reference_revision(relpath)
                if other_revision == sub_tree.last_revision():
                    continue
                other_branch = self.other_tree.reference_parent(relpath)
                graph = self.this_tree.branch.repository.get_graph(
                    other_branch.repository
                )
                if graph.is_ancestor(sub_tree.last_revision(), other_revision):
                    sub_tree.pull(other_branch, stop_revision=other_revision)
                else:
                    sub_merge = Merger(sub_tree.branch, this_tree=sub_tree)
                    sub_merge.merge_type = self.merge_type
                    sub_merge.set_other_revision(other_revision, other_branch)
                    base_tree_path = _mod_tree.find_previous_path(
                        self.this_tree, self.base_tree, relpath
                    )
                    if base_tree_path is None:
                        raise NotImplementedError
                    base_revision = self.base_tree.get_reference_revision(
                        base_tree_path
                    )
                    sub_merge.base_tree = sub_tree.branch.repository.revision_tree(
                        base_revision
                    )
                    sub_merge.base_rev_id = base_revision
                    sub_merge.do_merge()
        return merge

    def do_merge(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.this_tree.lock_tree_write())
            if self.base_tree is not None:
                stack.enter_context(self.base_tree.lock_read())
            if self.other_tree is not None:
                stack.enter_context(self.other_tree.lock_read())
            merge = self._do_merge_to()
        if len(merge.cooked_conflicts) == 0:
            if not self.ignore_zero and not trace.is_quiet():
                trace.note(gettext("All changes applied successfully."))
        else:
            trace.note(
                gettext("%d conflicts encountered.") % len(merge.cooked_conflicts)
            )

        return merge.cooked_conflicts


class _InventoryNoneEntry:
    """This represents an inventory entry which *isn't there*.

    It simplifies the merging logic if we always have an InventoryEntry, even
    if it isn't actually present
    """

    executable = None
    kind = None
    name = None
    parent_id = None
    revision = None
    symlink_target = None
    text_sha1 = None

    def is_unmodified(self, other):
        return other is self


_none_entry = _InventoryNoneEntry()


class Merge3Merger:
    """Three-way merger that uses the merge3 text merger."""

    requires_base = True
    supports_reprocess = True
    supports_show_base = True
    history_based = False
    supports_cherrypick = True
    supports_reverse_cherrypick = True
    winner_idx = {"this": 2, "other": 1, "conflict": 1}
    supports_lca_trees = True
    requires_file_merge_plan = False

    def __init__(
        self,
        working_tree,
        this_tree,
        base_tree,
        other_tree,
        reprocess=False,
        show_base=False,
        change_reporter=None,
        interesting_files=None,
        do_merge=True,
        cherrypick=False,
        lca_trees=None,
        this_branch=None,
        other_branch=None,
    ):
        """Initialize the merger object and perform the merge.

        :param working_tree: The working tree to apply the merge to
        :param this_tree: The local tree in the merge operation
        :param base_tree: The common tree in the merge operation
        :param other_tree: The other tree to merge changes from
        :param this_branch: The branch associated with this_tree.  Defaults to
            this_tree.branch if not supplied.
        :param other_branch: The branch associated with other_tree, if any.
        :param: reprocess If True, perform conflict-reduction processing.
        :param show_base: If True, show the base revision in text conflicts.
            (incompatible with reprocess)
        :param change_reporter: An object that should report changes made
        :param interesting_files: The tree-relative paths of files that should
            participate in the merge.  If these paths refer to directories,
            the contents of those directories will also be included.  If not
            specified, all files may participate in the
            merge.
        :param lca_trees: Can be set to a dictionary of {revision_id:rev_tree}
            if the ancestry was found to include a criss-cross merge.
            Otherwise should be None.
        """
        object.__init__(self)
        if this_branch is None:
            this_branch = this_tree.branch
        self.interesting_files = interesting_files
        self.working_tree = working_tree
        self.this_tree = this_tree
        self.base_tree = base_tree
        self.other_tree = other_tree
        self.this_branch = this_branch
        self.other_branch = other_branch
        self._raw_conflicts = []
        self.cooked_conflicts = []
        self.reprocess = reprocess
        self.show_base = show_base
        self._lca_trees = lca_trees
        # Uncommenting this will change the default algorithm to always use
        # _entries_lca. This can be useful for running the test suite and
        # making sure we haven't missed any corner cases.
        # if lca_trees is None:
        #     self._lca_trees = [self.base_tree]
        self.change_reporter = change_reporter
        self.cherrypick = cherrypick
        if do_merge:
            self.do_merge()

    def do_merge(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.working_tree.lock_tree_write())
            stack.enter_context(self.this_tree.lock_read())
            stack.enter_context(self.base_tree.lock_read())
            stack.enter_context(self.other_tree.lock_read())
            self.tt = self.working_tree.transform()
            stack.enter_context(self.tt)
            self._compute_transform()
            results = self.tt.apply(no_conflicts=True)
            self.write_modified(results)
            try:
                self.working_tree.add_conflicts(self.cooked_conflicts)
            except errors.UnsupportedOperation:
                pass

    def make_preview_transform(self):
        with self.base_tree.lock_read(), self.other_tree.lock_read():
            self.tt = self.working_tree.preview_transform()
            self._compute_transform()
            return self.tt

    def _compute_transform(self):
        if self._lca_trees is None:
            entries = list(self._entries3())
            resolver = self._three_way
        else:
            entries = list(self._entries_lca())
            resolver = self._lca_multi_way
        # Prepare merge hooks
        factories = Merger.hooks["merge_file_content"]
        # One hook for each registered one plus our default merger
        hooks = [factory(self) for factory in factories] + [self]
        self.active_hooks = [hook for hook in hooks if hook is not None]
        with ui.ui_factory.nested_progress_bar() as child_pb:
            for num, (
                file_id,
                changed,
                paths3,
                parents3,
                names3,
                executable3,
                copied,
            ) in enumerate(entries):
                if copied:
                    # Treat copies as simple adds for now
                    paths3 = (None, paths3[1], None)
                    parents3 = (None, parents3[1], None)
                    names3 = (None, names3[1], None)
                    executable3 = (None, executable3[1], None)
                    changed = True
                    copied = False
                trans_id = self.tt.trans_id_file_id(file_id)
                # Try merging each entry
                child_pb.update(gettext("Preparing file merge"), num, len(entries))
                self._merge_names(
                    trans_id, file_id, paths3, parents3, names3, resolver=resolver
                )
                if changed:
                    file_status = self._do_merge_contents(paths3, trans_id, file_id)
                else:
                    file_status = "unmodified"
                self._merge_executable(
                    paths3, trans_id, executable3, file_status, resolver=resolver
                )
        self.tt.fixup_new_roots()
        self._finish_computing_transform()

    def _finish_computing_transform(self):
        """Finalize the transform and report the changes.

        This is the second half of _compute_transform.
        """
        with ui.ui_factory.nested_progress_bar() as child_pb:
            fs_conflicts = transform.resolve_conflicts(
                self.tt,
                child_pb,
                lambda t, c: transform.conflict_pass(t, c, self.other_tree),
            )
        if self.change_reporter is not None:
            from breezy import delta

            delta.report_changes(self.tt.iter_changes(), self.change_reporter)
        self.cook_conflicts(fs_conflicts)
        for conflict in self.cooked_conflicts:
            trace.warning("%s", conflict.describe())

    def _entries3(self):
        """Gather data about files modified between three trees.

        Return a list of tuples of file_id, changed, parents3, names3,
        executable3.  changed is a boolean indicating whether the file contents
        or kind were changed.  parents3 is a tuple of parent ids for base,
        other and this.  names3 is a tuple of names for base, other and this.
        executable3 is a tuple of execute-bit values for base, other and this.
        """
        iterator = self.other_tree.iter_changes(
            self.base_tree,
            specific_files=self.interesting_files,
            extra_trees=[self.this_tree],
        )
        this_interesting_files = self.this_tree.find_related_paths_across_trees(
            self.interesting_files, trees=[self.other_tree]
        )
        this_entries = dict(
            self.this_tree.iter_entries_by_dir(specific_files=this_interesting_files)
        )
        for change in iterator:
            if change.path[0] is not None:
                this_path = _mod_tree.find_previous_path(
                    self.base_tree, self.this_tree, change.path[0]
                )
            else:
                this_path = _mod_tree.find_previous_path(
                    self.other_tree, self.this_tree, change.path[1]
                )
            this_entry = this_entries.get(this_path)
            if this_entry is not None:
                this_name = this_entry.name
                this_parent = this_entry.parent_id
                this_executable = this_entry.executable
            else:
                this_name = None
                this_parent = None
                this_executable = None
            parents3 = change.parent_id + (this_parent,)
            names3 = change.name + (this_name,)
            paths3 = change.path + (this_path,)
            executable3 = change.executable + (this_executable,)
            yield (
                (
                    change.file_id,
                    change.changed_content,
                    paths3,
                    parents3,
                    names3,
                    executable3,
                    change.copied,
                )
            )

    def _entries_lca(self):
        """Gather data about files modified between multiple trees.

        This compares OTHER versus all LCA trees, and for interesting entries,
        it then compares with THIS and BASE.

        For the multi-valued entries, the format will be (BASE, [lca1, lca2])

        :return: [(file_id, changed, paths, parents, names, executable, copied)], where:

            * file_id: Simple file_id of the entry
            * changed: Boolean, True if the kind or contents changed else False
            * paths: ((base, [path, in, lcas]), path_other, path_this)
            * parents: ((base, [parent_id, in, lcas]), parent_id_other,
                        parent_id_this)
            * names:   ((base, [name, in, lcas]), name_in_other, name_in_this)
            * executable: ((base, [exec, in, lcas]), exec_in_other,
                        exec_in_this)
        """
        if self.interesting_files is not None:
            lookup_trees = [self.this_tree, self.base_tree]
            lookup_trees.extend(self._lca_trees)
            # I think we should include the lca trees as well
            interesting_files = self.other_tree.find_related_paths_across_trees(
                self.interesting_files, lookup_trees
            )
        else:
            interesting_files = None
        from .multiwalker import MultiWalker

        walker = MultiWalker(self.other_tree, self._lca_trees)

        for other_path, file_id, other_ie, lca_values in walker.iter_all():
            # Is this modified at all from any of the other trees?
            if other_ie is None:
                other_ie = _none_entry
                other_path = None
            if interesting_files is not None and other_path not in interesting_files:
                continue

            # If other_revision is found in any of the lcas, that means this
            # node is uninteresting. This is because when merging, if there are
            # multiple heads(), we have to create a new node. So if we didn't,
            # we know that the ancestry is linear, and that OTHER did not
            # modify anything
            # See doc/developers/lca_merge_resolution.txt for details
            # We can't use this shortcut when other_revision is None,
            # because it may be None because things are WorkingTrees, and
            # not because it is *actually* None.
            is_unmodified = False
            for lca_path, ie in lca_values:
                if ie is not None and other_ie.is_unmodified(ie):
                    is_unmodified = True
                    break
            if is_unmodified:
                continue

            lca_entries = []
            lca_paths = []
            for lca_path, lca_ie in lca_values:
                if lca_ie is None:
                    lca_entries.append(_none_entry)
                    lca_paths.append(None)
                else:
                    lca_entries.append(lca_ie)
                    lca_paths.append(lca_path)

            try:
                base_path = self.base_tree.id2path(file_id)
            except errors.NoSuchId:
                base_path = None
                base_ie = _none_entry
            else:
                base_ie = next(
                    self.base_tree.iter_entries_by_dir(specific_files=[base_path])
                )[1]

            try:
                this_path = self.this_tree.id2path(file_id)
            except errors.NoSuchId:
                this_ie = _none_entry
                this_path = None
            else:
                this_ie = next(
                    self.this_tree.iter_entries_by_dir(specific_files=[this_path])
                )[1]

            lca_kinds = []
            lca_parent_ids = []
            lca_names = []
            lca_executable = []
            for lca_ie in lca_entries:
                lca_kinds.append(lca_ie.kind)
                lca_parent_ids.append(lca_ie.parent_id)
                lca_names.append(lca_ie.name)
                lca_executable.append(lca_ie.executable)

            kind_winner = self._lca_multi_way(
                (base_ie.kind, lca_kinds), other_ie.kind, this_ie.kind
            )
            parent_id_winner = self._lca_multi_way(
                (base_ie.parent_id, lca_parent_ids),
                other_ie.parent_id,
                this_ie.parent_id,
            )
            name_winner = self._lca_multi_way(
                (base_ie.name, lca_names), other_ie.name, this_ie.name
            )

            content_changed = True
            if kind_winner == "this":
                # No kind change in OTHER, see if there are *any* changes
                if other_ie.kind == "directory":
                    if parent_id_winner == "this" and name_winner == "this":
                        # No change for this directory in OTHER, skip
                        continue
                    content_changed = False
                elif other_ie.kind is None or other_ie.kind == "file":

                    def get_sha1(tree, path):
                        if path is None:
                            return None
                        try:
                            return tree.get_file_sha1(path)
                        except _mod_transport.NoSuchFile:
                            return None

                    base_sha1 = get_sha1(self.base_tree, base_path)
                    lca_sha1s = [
                        get_sha1(tree, lca_path)
                        for tree, lca_path in zip(self._lca_trees, lca_paths)
                    ]
                    this_sha1 = get_sha1(self.this_tree, this_path)
                    other_sha1 = get_sha1(self.other_tree, other_path)
                    sha1_winner = self._lca_multi_way(
                        (base_sha1, lca_sha1s),
                        other_sha1,
                        this_sha1,
                        allow_overriding_lca=False,
                    )
                    exec_winner = self._lca_multi_way(
                        (base_ie.executable, lca_executable),
                        other_ie.executable,
                        this_ie.executable,
                    )
                    if (
                        parent_id_winner == "this"
                        and name_winner == "this"
                        and sha1_winner == "this"
                        and exec_winner == "this"
                    ):
                        # No kind, parent, name, exec, or content change for
                        # OTHER, so this node is not considered interesting
                        continue
                    if sha1_winner == "this":
                        content_changed = False
                elif other_ie.kind == "symlink":

                    def get_target(ie, tree, path):
                        if ie.kind != "symlink":
                            return None
                        return tree.get_symlink_target(path)

                    base_target = get_target(base_ie, self.base_tree, base_path)
                    lca_targets = [
                        get_target(ie, tree, lca_path)
                        for ie, tree, lca_path in zip(
                            lca_entries, self._lca_trees, lca_paths
                        )
                    ]
                    this_target = get_target(this_ie, self.this_tree, this_path)
                    other_target = get_target(other_ie, self.other_tree, other_path)
                    target_winner = self._lca_multi_way(
                        (base_target, lca_targets), other_target, this_target
                    )
                    if (
                        parent_id_winner == "this"
                        and name_winner == "this"
                        and target_winner == "this"
                    ):
                        # No kind, parent, name, or symlink target change
                        # not interesting
                        continue
                    if target_winner == "this":
                        content_changed = False
                elif other_ie.kind == "tree-reference":
                    # The 'changed' information seems to be handled at a higher
                    # level. At least, _entries3 returns False for content
                    # changed, even when at a new revision_id.
                    content_changed = False
                    if parent_id_winner == "this" and name_winner == "this":
                        # Nothing interesting
                        continue
                else:
                    raise AssertionError("unhandled kind: {}".format(other_ie.kind))

            # If we have gotten this far, that means something has changed
            yield (
                file_id,
                content_changed,
                ((base_path, lca_paths), other_path, this_path),
                (
                    (base_ie.parent_id, lca_parent_ids),
                    other_ie.parent_id,
                    this_ie.parent_id,
                ),
                ((base_ie.name, lca_names), other_ie.name, this_ie.name),
                (
                    (base_ie.executable, lca_executable),
                    other_ie.executable,
                    this_ie.executable,
                ),
                # Copy detection is not yet supported, so nothing is
                # a copy:
                False,
            )

    def write_modified(self, results):
        if not self.working_tree.supports_merge_modified():
            return
        modified_hashes = {}
        for path in results.modified_paths:
            wt_relpath = self.working_tree.relpath(path)
            if not self.working_tree.is_versioned(wt_relpath):
                continue
            hash = self.working_tree.get_file_sha1(wt_relpath)
            if hash is None:
                continue
            modified_hashes[wt_relpath] = hash
        self.working_tree.set_merge_modified(modified_hashes)

    @staticmethod
    def parent(entry):
        """Determine the parent for a file_id (used as a key method)."""
        if entry is None:
            return None
        return entry.parent_id

    @staticmethod
    def name(entry):
        """Determine the name for a file_id (used as a key method)."""
        if entry is None:
            return None
        return entry.name

    @staticmethod
    def contents_sha1(tree, path):
        """Determine the sha1 of the file contents (used as a key method)."""
        try:
            return tree.get_file_sha1(path)
        except _mod_transport.NoSuchFile:
            return None

    @staticmethod
    def executable(tree, path):
        """Determine the executability of a file-id (used as a key method)."""
        try:
            if tree.kind(path) != "file":
                return False
        except _mod_transport.NoSuchFile:
            return None
        return tree.is_executable(path)

    @staticmethod
    def kind(tree, path):
        """Determine the kind of a file-id (used as a key method)."""
        try:
            return tree.kind(path)
        except _mod_transport.NoSuchFile:
            return None

    @staticmethod
    def _three_way(base, other, this):
        if base == other:
            # if 'base == other', either they all agree, or only 'this' has
            # changed.
            return "this"
        elif this not in (base, other):
            # 'this' is neither 'base' nor 'other', so both sides changed
            return "conflict"
        elif this == other:
            # "Ambiguous clean merge" -- both sides have made the same change.
            return "this"
        else:
            # this == base: only other has changed.
            return "other"

    @staticmethod
    def _lca_multi_way(bases, other, this, allow_overriding_lca=True):
        """Consider LCAs when determining whether a change has occurred.

        If LCAS are all identical, this is the same as a _three_way comparison.

        :param bases: value in (BASE, [LCAS])
        :param other: value in OTHER
        :param this: value in THIS
        :param allow_overriding_lca: If there is more than one unique lca
            value, allow OTHER to override THIS if it has a new value, and
            THIS only has an lca value, or vice versa. This is appropriate for
            truly scalar values, not as much for non-scalars.
        :return: 'this', 'other', or 'conflict' depending on whether an entry
            changed or not.
        """
        # See doc/developers/lca_tree_merging.txt for details about this
        # algorithm.
        if other == this:
            # Either Ambiguously clean, or nothing was actually changed. We
            # don't really care
            return "this"
        base_val, lca_vals = bases
        # Remove 'base_val' from the lca_vals, because it is not interesting
        filtered_lca_vals = [lca_val for lca_val in lca_vals if lca_val != base_val]
        if len(filtered_lca_vals) == 0:
            return Merge3Merger._three_way(base_val, other, this)

        unique_lca_vals = set(filtered_lca_vals)
        if len(unique_lca_vals) == 1:
            return Merge3Merger._three_way(unique_lca_vals.pop(), other, this)

        if allow_overriding_lca:
            if other in unique_lca_vals:
                if this in unique_lca_vals:
                    # Each side picked a different lca, conflict
                    return "conflict"
                else:
                    # This has a value which supersedes both lca values, and
                    # other only has an lca value
                    return "this"
            elif this in unique_lca_vals:
                # OTHER has a value which supersedes both lca values, and this
                # only has an lca value
                return "other"

        # At this point, the lcas disagree, and the tip disagree
        return "conflict"

    def _merge_names(self, trans_id, file_id, paths, parents, names, resolver):
        """Perform a merge on file names and parents."""
        base_name, other_name, this_name = names
        base_parent, other_parent, this_parent = parents
        unused_base_path, other_path, this_path = paths

        name_winner = resolver(*names)

        parent_id_winner = resolver(*parents)
        if this_name is None:
            if name_winner == "this":
                name_winner = "other"
            if parent_id_winner == "this":
                parent_id_winner = "other"
        if name_winner == "this" and parent_id_winner == "this":
            return
        if name_winner == "conflict" or parent_id_winner == "conflict":
            # Creating helpers (.OTHER or .THIS) here cause problems down the
            # road if a ContentConflict needs to be created so we should not do
            # that
            self._raw_conflicts.append(
                (
                    "path conflict",
                    trans_id,
                    file_id,
                    this_parent,
                    this_name,
                    other_parent,
                    other_name,
                )
            )
        if other_path is None:
            # it doesn't matter whether the result was 'other' or
            # 'conflict'-- if it has no file id, we leave it alone.
            return
        parent_id = parents[self.winner_idx[parent_id_winner]]
        name = names[self.winner_idx[name_winner]]
        if parent_id is not None or name is not None:
            # if we get here, name_winner and parent_winner are set to safe
            # values.
            if parent_id is None and name is not None:
                # if parent_id is None and name is non-None, current file is
                # the tree root.
                if names[self.winner_idx[parent_id_winner]] != "":
                    raise AssertionError(
                        "File looks like a root, but named {}".format(
                            names[self.winner_idx[parent_id_winner]]
                        )
                    )
                parent_trans_id = transform.ROOT_PARENT
            else:
                parent_trans_id = self.tt.trans_id_file_id(parent_id)
            self.tt.adjust_path(name, parent_trans_id, trans_id)

    def _do_merge_contents(self, paths, trans_id, file_id):
        """Performs a merge on file_id contents."""

        def contents_pair(tree, path):
            if path is None:
                return (None, None)
            try:
                kind = tree.kind(path)
            except _mod_transport.NoSuchFile:
                return (None, None)
            if kind == "file":
                contents = tree.get_file_sha1(path)
            elif kind == "symlink":
                contents = tree.get_symlink_target(path)
            else:
                contents = None
            return kind, contents

        base_path, other_path, this_path = paths
        # See SPOT run.  run, SPOT, run.
        # So we're not QUITE repeating ourselves; we do tricky things with
        # file kind...
        other_pair = contents_pair(self.other_tree, other_path)
        this_pair = contents_pair(self.this_tree, this_path)
        if self._lca_trees:
            (base_path, lca_paths) = base_path
            base_pair = contents_pair(self.base_tree, base_path)
            lca_pairs = [
                contents_pair(tree, path)
                for tree, path in zip(self._lca_trees, lca_paths)
            ]
            winner = self._lca_multi_way(
                (base_pair, lca_pairs),
                other_pair,
                this_pair,
                allow_overriding_lca=False,
            )
        else:
            base_pair = contents_pair(self.base_tree, base_path)
            if base_pair == other_pair:
                winner = "this"
            else:
                # We delayed evaluating this_pair as long as we can to avoid
                # unnecessary sha1 calculation
                this_pair = contents_pair(self.this_tree, this_path)
                winner = self._three_way(base_pair, other_pair, this_pair)
        if winner == "this":
            # No interesting changes introduced by OTHER
            return "unmodified"
        # We have a hypothetical conflict, but if we have files, then we
        # can try to merge the content
        params = MergeFileHookParams(
            self,
            (base_path, other_path, this_path),
            trans_id,
            this_pair[0],
            other_pair[0],
            winner,
        )
        hooks = self.active_hooks
        hook_status = "not_applicable"
        for hook in hooks:
            hook_status, lines = hook.merge_contents(params)
            if hook_status != "not_applicable":
                # Don't try any more hooks, this one applies.
                break
        # If the merge ends up replacing the content of the file, we get rid of
        # it at the end of this method (this variable is used to track the
        # exceptions to this rule).
        keep_this = False
        result = "modified"
        if hook_status == "not_applicable":
            # No merge hook was able to resolve the situation. Two cases exist:
            # a content conflict or a duplicate one.
            result = None
            name = self.tt.final_name(trans_id)
            parent_id = self.tt.final_parent(trans_id)
            inhibit_content_conflict = False
            if params.this_kind is None:  # file_id is not in THIS
                # Is the name used for a different file_id ?
                if self.this_tree.is_versioned(other_path):
                    # Two entries for the same path
                    keep_this = True
                    # versioning the merged file will trigger a duplicate
                    # conflict
                    self.tt.version_file(trans_id, file_id=file_id)
                    transform.create_from_tree(
                        self.tt,
                        trans_id,
                        self.other_tree,
                        other_path,
                        filter_tree_path=self._get_filter_tree_path(other_path),
                    )
                    inhibit_content_conflict = True
            elif params.other_kind is None:  # file_id is not in OTHER
                # Is the name used for a different file_id ?
                if self.other_tree.is_versioned(this_path):
                    # Two entries for the same path again, but here, the other
                    # entry will also be merged.  We simply inhibit the
                    # 'content' conflict creation because we know OTHER will
                    # create (or has already created depending on ordering) an
                    # entry at the same path. This will trigger a 'duplicate'
                    # conflict later.
                    keep_this = True
                    inhibit_content_conflict = True
            if not inhibit_content_conflict:
                if params.this_kind is not None:
                    self.tt.unversion_file(trans_id)
                # This is a contents conflict, because none of the available
                # functions could merge it.
                file_group = self._dump_conflicts(
                    name, (base_path, other_path, this_path), parent_id
                )
                for tid in file_group:
                    self.tt.version_file(tid, file_id=file_id)
                    break
                self._raw_conflicts.append(("contents conflict", file_group))
        elif hook_status == "success":
            self.tt.create_file(lines, trans_id)
        elif hook_status == "conflicted":
            # XXX: perhaps the hook should be able to provide
            # the BASE/THIS/OTHER files?
            self.tt.create_file(lines, trans_id)
            self._raw_conflicts.append(("text conflict", trans_id))
            name = self.tt.final_name(trans_id)
            parent_id = self.tt.final_parent(trans_id)
            self._dump_conflicts(name, (base_path, other_path, this_path), parent_id)
        elif hook_status == "delete":
            self.tt.unversion_file(trans_id)
            result = "deleted"
        elif hook_status == "done":
            # The hook function did whatever it needs to do directly, no
            # further action needed here.
            pass
        else:
            raise AssertionError("unknown hook_status: {!r}".format(hook_status))
        if not this_path and result == "modified":
            self.tt.version_file(trans_id, file_id=file_id)
        if not keep_this:
            # The merge has been performed and produced a new content, so the
            # old contents should not be retained.
            self.tt.delete_contents(trans_id)
        return result

    def _default_other_winner_merge(self, merge_hook_params):
        """Replace this contents with other."""
        trans_id = merge_hook_params.trans_id
        if merge_hook_params.other_path is not None:
            # OTHER changed the file
            transform.create_from_tree(
                self.tt,
                trans_id,
                self.other_tree,
                merge_hook_params.other_path,
                filter_tree_path=self._get_filter_tree_path(
                    merge_hook_params.other_path
                ),
            )
            return "done", None
        elif merge_hook_params.this_path is not None:
            # OTHER deleted the file
            return "delete", None
        else:
            raise AssertionError(
                "winner is OTHER, but file {!r} not in THIS or OTHER tree".format(
                    merge_hook_params.base_path
                )
            )

    def merge_contents(self, merge_hook_params):
        """Fallback merge logic after user installed hooks."""
        # This function is used in merge hooks as the fallback instance.
        # Perhaps making this function and the functions it calls be a
        # a separate class would be better.
        if merge_hook_params.winner == "other":
            # OTHER is a straight winner, so replace this contents with other
            return self._default_other_winner_merge(merge_hook_params)
        elif merge_hook_params.is_file_merge():
            # THIS and OTHER are both files, so text merge.  Either
            # BASE is a file, or both converted to files, so at least we
            # have agreement that output should be a file.
            try:
                self.text_merge(merge_hook_params.trans_id, merge_hook_params.paths)
            except errors.BinaryFile:
                return "not_applicable", None
            return "done", None
        else:
            return "not_applicable", None

    def get_lines(self, tree, path):
        """Return the lines in a file, or an empty list."""
        if path is None:
            return []
        try:
            kind = tree.kind(path)
        except _mod_transport.NoSuchFile:
            return []
        else:
            if kind != "file":
                return []
            return tree.get_file_lines(path)

    def text_merge(self, trans_id, paths):
        """Perform a three-way text merge on a file."""
        from merge3 import Merge3

        # it's possible that we got here with base as a different type.
        # if so, we just want two-way text conflicts.
        base_path, other_path, this_path = paths
        base_lines = self.get_lines(self.base_tree, base_path)
        other_lines = self.get_lines(self.other_tree, other_path)
        this_lines = self.get_lines(self.this_tree, this_path)
        textfile.check_text_lines(base_lines)
        textfile.check_text_lines(other_lines)
        textfile.check_text_lines(this_lines)
        m3 = Merge3(
            base_lines,
            this_lines,
            other_lines,
            is_cherrypick=self.cherrypick,
            sequence_matcher=patiencediff.PatienceSequenceMatcher,
        )
        start_marker = b"!START OF MERGE CONFLICT!" + b"I HOPE THIS IS UNIQUE"
        if self.show_base is True:
            base_marker = b"|" * 7
        else:
            base_marker = None

        def iter_merge3(retval):
            retval["text_conflicts"] = False
            if base_marker and self.reprocess:
                raise CantReprocessAndShowBase()
            lines = list(
                m3.merge_lines(
                    name_a=b"TREE",
                    name_b=b"MERGE-SOURCE",
                    name_base=b"BASE-REVISION",
                    start_marker=start_marker,
                    base_marker=base_marker,
                    reprocess=self.reprocess,
                )
            )
            for line in lines:
                if line.startswith(start_marker):
                    retval["text_conflicts"] = True
                    yield line.replace(start_marker, b"<" * 7)
                else:
                    yield line

        retval = {}
        merge3_iterator = iter_merge3(retval)
        self.tt.create_file(merge3_iterator, trans_id)
        if retval["text_conflicts"] is True:
            self._raw_conflicts.append(("text conflict", trans_id))
            name = self.tt.final_name(trans_id)
            parent_id = self.tt.final_parent(trans_id)
            file_group = self._dump_conflicts(
                name, paths, parent_id, lines=(base_lines, other_lines, this_lines)
            )
            file_group.append(trans_id)

    def _get_filter_tree_path(self, path):
        if self.this_tree.supports_content_filtering():
            # We get the path from the working tree if it exists.
            # That fails though when OTHER is adding a file, so
            # we fall back to the other tree to find the path if
            # it doesn't exist locally.
            filter_path = _mod_tree.find_previous_path(
                self.other_tree, self.working_tree, path
            )
            if filter_path is None:
                filter_path = path
            return filter_path
        # Skip the lookup for older formats
        return None

    def _dump_conflicts(self, name, paths, parent_id, lines=None, no_base=False):
        """Emit conflict files.
        If this_lines, base_lines, or other_lines are omitted, they will be
        determined automatically.  If set_version is true, the .OTHER, .THIS
        or .BASE (in that order) will be created as versioned files.
        """
        base_path, other_path, this_path = paths
        if lines:
            base_lines, other_lines, this_lines = lines
        else:
            base_lines = other_lines = this_lines = None
        data = [
            ("OTHER", self.other_tree, other_path, other_lines),
            ("THIS", self.this_tree, this_path, this_lines),
        ]
        if not no_base:
            data.append(("BASE", self.base_tree, base_path, base_lines))

        # We need to use the actual path in the working tree of the file here,
        if self.this_tree.supports_content_filtering():
            filter_tree_path = this_path
        else:
            filter_tree_path = None

        file_group = []
        for suffix, tree, path, lines in data:
            if path is not None:
                trans_id = self._conflict_file(
                    name, parent_id, path, tree, suffix, lines, filter_tree_path
                )
                file_group.append(trans_id)
        return file_group

    def _conflict_file(
        self, name, parent_id, path, tree, suffix, lines=None, filter_tree_path=None
    ):
        """Emit a single conflict file."""
        name = name + "." + suffix
        trans_id = self.tt.create_path(name, parent_id)
        transform.create_from_tree(
            self.tt,
            trans_id,
            tree,
            path,
            chunks=lines,
            filter_tree_path=filter_tree_path,
        )
        return trans_id

    def _merge_executable(self, paths, trans_id, executable, file_status, resolver):
        """Perform a merge on the execute bit."""
        base_executable, other_executable, this_executable = executable
        base_path, other_path, this_path = paths
        if file_status == "deleted":
            return
        winner = resolver(*executable)
        if winner == "conflict":
            # There must be a None in here, if we have a conflict, but we
            # need executability since file status was not deleted.
            if other_path is None:
                winner = "this"
            else:
                winner = "other"
        if winner == "this" and file_status != "modified":
            return
        if self.tt.final_kind(trans_id) != "file":
            return
        if winner == "this":
            executability = this_executable
        else:
            if other_path is not None:
                executability = other_executable
            elif this_path is not None:
                executability = this_executable
            elif base_path is not None:
                executability = base_executable
        if executability is not None:
            self.tt.set_executability(executability, trans_id)

    def cook_conflicts(self, fs_conflicts):
        """Convert all conflicts into a form that doesn't depend on trans_id."""
        self.cooked_conflicts = list(
            self.tt.cook_conflicts(list(fs_conflicts) + self._raw_conflicts)
        )


class WeaveMerger(Merge3Merger):
    """Three-way tree merger, text weave merger."""

    supports_reprocess = True
    supports_show_base = False
    supports_reverse_cherrypick = False
    history_based = True
    requires_file_merge_plan = True

    def _generate_merge_plan(self, this_path, base):
        return self.this_tree.plan_file_merge(this_path, self.other_tree, base=base)

    def _merged_lines(self, this_path):
        """Generate the merged lines.
        There is no distinction between lines that are meant to contain <<<<<<<
        and conflicts.
        """
        from .bzr.versionedfile import PlanWeaveMerge

        if self.cherrypick:
            base = self.base_tree
        else:
            base = None
        plan = self._generate_merge_plan(this_path, base)
        if "merge" in debug.debug_flags:
            plan = list(plan)
            trans_id = self.tt.trans_id_file_id(file_id)
            name = self.tt.final_name(trans_id) + ".plan"
            contents = (b"%11s|%s" % l for l in plan)
            self.tt.new_file(name, self.tt.final_parent(trans_id), contents)
        textmerge = PlanWeaveMerge(plan, b"<<<<<<< TREE\n", b">>>>>>> MERGE-SOURCE\n")
        lines, conflicts = textmerge.merge_lines(self.reprocess)
        if conflicts:
            base_lines = textmerge.base_from_plan()
        else:
            base_lines = None
        return lines, base_lines

    def text_merge(self, trans_id, paths):
        """Perform a (weave) text merge for a given file and file-id.
        If conflicts are encountered, .THIS and .OTHER files will be emitted,
        and a conflict will be noted.
        """
        base_path, other_path, this_path = paths
        lines, base_lines = self._merged_lines(this_path)
        lines = list(lines)
        # Note we're checking whether the OUTPUT is binary in this case,
        # because we don't want to get into weave merge guts.
        textfile.check_text_lines(lines)
        self.tt.create_file(lines, trans_id)
        if base_lines is not None:
            # Conflict
            self._raw_conflicts.append(("text conflict", trans_id))
            name = self.tt.final_name(trans_id)
            parent_id = self.tt.final_parent(trans_id)
            file_group = self._dump_conflicts(
                name, paths, parent_id, (base_lines, None, None), no_base=False
            )
            file_group.append(trans_id)


class LCAMerger(WeaveMerger):
    requires_file_merge_plan = True

    def _generate_merge_plan(self, this_path, base):
        return self.this_tree.plan_file_lca_merge(this_path, self.other_tree, base=base)


class Diff3Merger(Merge3Merger):
    """Three-way merger using external diff3 for text merging."""

    requires_file_merge_plan = False

    def dump_file(self, temp_dir, name, tree, path):
        out_path = osutils.pathjoin(temp_dir, name)
        with open(out_path, "wb") as out_file:
            in_file = tree.get_file(path)
            for line in in_file:
                out_file.write(line)
        return out_path

    def text_merge(self, trans_id, paths):
        """Perform a diff3 merge using a specified file-id and trans-id.
        If conflicts are encountered, .BASE, .THIS. and .OTHER conflict files
        will be dumped, and a will be conflict noted.
        """
        import breezy.patch

        base_path, other_path, this_path = paths
        with tempfile.TemporaryDirectory(prefix="bzr-") as temp_dir:
            new_file = osutils.pathjoin(temp_dir, "new")
            this = self.dump_file(temp_dir, "this", self.this_tree, this_path)
            base = self.dump_file(temp_dir, "base", self.base_tree, base_path)
            other = self.dump_file(temp_dir, "other", self.other_tree, other_path)
            status = breezy.patch.diff3(new_file, this, base, other)
            if status not in (0, 1):
                raise errors.BzrError("Unhandled diff3 exit code")
            with open(new_file, "rb") as f:
                self.tt.create_file(f, trans_id)
            if status == 1:
                name = self.tt.final_name(trans_id)
                parent_id = self.tt.final_parent(trans_id)
                self._dump_conflicts(name, paths, parent_id)
                self._raw_conflicts.append(("text conflict", trans_id))


class PathNotInTree(errors.BzrError):
    _fmt = """Merge-into failed because %(tree)s does not contain %(path)s."""

    def __init__(self, path, tree):
        errors.BzrError.__init__(self, path=path, tree=tree)


class MergeIntoMerger(Merger):
    """Merger that understands other_tree will be merged into a subdir.

    This also changes the Merger api so that it uses real Branch, revision_id,
    and RevisonTree objects, rather than using revision specs.
    """

    def __init__(
        self,
        this_tree,
        other_branch,
        other_tree,
        target_subdir,
        source_subpath,
        other_rev_id=None,
    ):
        """Create a new MergeIntoMerger object.

        source_subpath in other_tree will be effectively copied to
        target_subdir in this_tree.

        :param this_tree: The tree that we will be merging into.
        :param other_branch: The Branch we will be merging from.
        :param other_tree: The RevisionTree object we want to merge.
        :param target_subdir: The relative path where we want to merge
            other_tree into this_tree
        :param source_subpath: The relative path specifying the subtree of
            other_tree to merge into this_tree.
        """
        # It is assumed that we are merging a tree that is not in our current
        # ancestry, which means we are using the "EmptyTree" as our basis.
        null_ancestor_tree = this_tree.branch.repository.revision_tree(
            _mod_revision.NULL_REVISION
        )
        super().__init__(
            this_branch=this_tree.branch,
            this_tree=this_tree,
            other_tree=other_tree,
            base_tree=null_ancestor_tree,
        )
        self._target_subdir = target_subdir
        self._source_subpath = source_subpath
        self.other_branch = other_branch
        if other_rev_id is None:
            other_rev_id = other_tree.get_revision_id()
        self.other_rev_id = self.other_basis = other_rev_id
        self.base_is_ancestor = True
        self.backup_files = True
        self.merge_type = Merge3Merger
        self.show_base = False
        self.reprocess = False
        self.interesting_files = None
        self.merge_type = _MergeTypeParameterizer(
            MergeIntoMergeType,
            target_subdir=self._target_subdir,
            source_subpath=self._source_subpath,
        )
        if self._source_subpath != "":
            # If this isn't a partial merge make sure the revisions will be
            # present.
            self._maybe_fetch(self.other_branch, self.this_branch, self.other_basis)

    def set_pending(self):
        if self._source_subpath != "":
            return
        Merger.set_pending(self)


class _MergeTypeParameterizer:
    """Wrap a merge-type class to provide extra parameters.

    This is hack used by MergeIntoMerger to pass some extra parameters to its
    merge_type.  Merger.do_merge() sets up its own set of parameters to pass to
    the 'merge_type' member.  It is difficult override do_merge without
    re-writing the whole thing, so instead we create a wrapper which will pass
    the extra parameters.
    """

    def __init__(self, merge_type, **kwargs):
        self._extra_kwargs = kwargs
        self._merge_type = merge_type

    def __call__(self, *args, **kwargs):
        kwargs.update(self._extra_kwargs)
        return self._merge_type(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._merge_type, name)


class MergeIntoMergeType(Merge3Merger):
    """Merger that incorporates a tree (or part of a tree) into another."""

    def __init__(self, *args, **kwargs):
        """Initialize the merger object.

        :param args: See Merge3Merger.__init__'s args.
        :param kwargs: See Merge3Merger.__init__'s keyword args, except for
            source_subpath and target_subdir.
        :keyword source_subpath: The relative path specifying the subtree of
            other_tree to merge into this_tree.
        :keyword target_subdir: The relative path where we want to merge
            other_tree into this_tree
        """
        # All of the interesting work happens during Merge3Merger.__init__(),
        # so we have have to hack in to get our extra parameters set.
        self._source_subpath = kwargs.pop("source_subpath")
        self._target_subdir = kwargs.pop("target_subdir")
        super().__init__(*args, **kwargs)

    def _compute_transform(self):
        with ui.ui_factory.nested_progress_bar() as child_pb:
            entries = self._entries_to_incorporate()
            entries = list(entries)
            for num, (entry, parent_id, relpath) in enumerate(entries):
                child_pb.update(gettext("Preparing file merge"), num, len(entries))
                parent_trans_id = self.tt.trans_id_file_id(parent_id)
                path = osutils.pathjoin(self._source_subpath, relpath)
                transform.new_by_entry(
                    path, self.tt, entry, parent_trans_id, self.other_tree
                )
        self._finish_computing_transform()

    def _entries_to_incorporate(self):
        """Yields pairs of (inventory_entry, new_parent)."""
        subdir_id = self.other_tree.path2id(self._source_subpath)
        if subdir_id is None:
            # XXX: The error would be clearer if it gave the URL of the source
            # branch, but we don't have a reference to that here.
            raise PathNotInTree(self._source_subpath, "Source tree")
        subdir = next(
            self.other_tree.iter_entries_by_dir(specific_files=[self._source_subpath])
        )[1]
        parent_in_target = osutils.dirname(self._target_subdir)
        target_id = self.this_tree.path2id(parent_in_target)
        if target_id is None:
            raise PathNotInTree(self._target_subdir, "Target tree")
        name_in_target = osutils.basename(self._target_subdir)
        merge_into_root = subdir.copy()
        merge_into_root.name = name_in_target
        try:
            self.this_tree.id2path(merge_into_root.file_id)
        except errors.NoSuchId:
            pass
        else:
            # Give the root a new file-id.
            # This can happen fairly easily if the directory we are
            # incorporating is the root, and both trees have 'TREE_ROOT' as
            # their root_id.  Users will expect this to Just Work, so we
            # change the file-id here.
            # Non-root file-ids could potentially conflict too.  That's really
            # an edge case, so we don't do anything special for those.  We let
            # them cause conflicts.
            merge_into_root.file_id = generate_ids.gen_file_id(name_in_target)
        yield (merge_into_root, target_id, "")
        if subdir.kind != "directory":
            # No children, so we are done.
            return
        for path, entry in self.other_tree.root_inventory.iter_entries_by_dir(
            subdir_id
        ):
            parent_id = entry.parent_id
            if parent_id == subdir.file_id:
                # The root's parent ID has changed, so make sure children of
                # the root refer to the new ID.
                parent_id = merge_into_root.file_id
            yield (entry, parent_id, path)


def merge_inner(
    this_branch,
    other_tree,
    base_tree,
    ignore_zero=False,
    backup_files=False,
    merge_type=Merge3Merger,
    show_base=False,
    reprocess=False,
    other_rev_id=None,
    interesting_files=None,
    this_tree=None,
    change_reporter=None,
):
    """Primary interface for merging.

    Typical use is probably::

        merge_inner(branch, branch.get_revision_tree(other_revision),
                    branch.get_revision_tree(base_revision))
    """
    if this_tree is None:
        raise errors.BzrError("breezy.merge.merge_inner requires a this_tree parameter")
    merger = Merger(
        this_branch,
        other_tree,
        base_tree,
        this_tree=this_tree,
        change_reporter=change_reporter,
    )
    merger.backup_files = backup_files
    merger.merge_type = merge_type
    merger.ignore_zero = ignore_zero
    merger.interesting_files = interesting_files
    merger.show_base = show_base
    merger.reprocess = reprocess
    merger.other_rev_id = other_rev_id
    merger.other_basis = other_rev_id
    get_revision_id = getattr(base_tree, "get_revision_id", None)
    if get_revision_id is None:
        get_revision_id = base_tree.last_revision
    merger.cache_trees_with_revision_ids([other_tree, base_tree, this_tree])
    merger.set_base_revision(get_revision_id(), this_branch)
    return merger.do_merge()


merge_type_registry = registry.Registry[str, type[Merge3Merger]]()
merge_type_registry.register("diff3", Diff3Merger, "Merge using external diff3.")
merge_type_registry.register("lca", LCAMerger, "LCA-newness merge.")
merge_type_registry.register("merge3", Merge3Merger, "Native diff3-style merge.")
merge_type_registry.register("weave", WeaveMerger, "Weave-based merge.")


def get_merge_type_registry():
    """Merge type registry was previously in breezy.option.

    This method provides a backwards compatible way to retrieve it.
    """
    return merge_type_registry


def _plan_annotate_merge(annotated_a, annotated_b, ancestors_a, ancestors_b):
    def status_a(revision, text):
        if revision in ancestors_b:
            return "killed-b", text
        else:
            return "new-a", text

    def status_b(revision, text):
        if revision in ancestors_a:
            return "killed-a", text
        else:
            return "new-b", text

    plain_a = [t for (a, t) in annotated_a]
    plain_b = [t for (a, t) in annotated_b]
    matcher = patiencediff.PatienceSequenceMatcher(None, plain_a, plain_b)
    blocks = matcher.get_matching_blocks()
    a_cur = 0
    b_cur = 0
    for ai, bi, l in blocks:
        # process all mismatched sections
        # (last mismatched section is handled because blocks always
        # includes a 0-length last block)
        for revision, text in annotated_a[a_cur:ai]:
            yield status_a(revision, text)
        for revision, text in annotated_b[b_cur:bi]:
            yield status_b(revision, text)
        # and now the matched section
        a_cur = ai + l
        b_cur = bi + l
        for text_a in plain_a[ai:a_cur]:
            yield "unchanged", text_a


class _PlanMergeBase:
    def __init__(self, a_rev, b_rev, vf, key_prefix):
        """Contructor.

        :param a_rev: Revision-id of one revision to merge
        :param b_rev: Revision-id of the other revision to merge
        :param vf: A VersionedFiles containing both revisions
        :param key_prefix: A prefix for accessing keys in vf, typically
            (file_id,).
        """
        self.a_rev = a_rev
        self.b_rev = b_rev
        self.vf = vf
        self._last_lines = None
        self._last_lines_revision_id = None
        self._cached_matching_blocks = {}
        self._key_prefix = key_prefix
        self._precache_tip_lines()

    def _precache_tip_lines(self):
        lines = self.get_lines([self.a_rev, self.b_rev])
        self.lines_a = lines[self.a_rev]
        self.lines_b = lines[self.b_rev]

    def get_lines(self, revisions):
        """Get lines for revisions from the backing VersionedFiles.

        :raises RevisionNotPresent: on absent texts.
        """
        keys = [(self._key_prefix + (rev,)) for rev in revisions]
        result = {}
        for record in self.vf.get_record_stream(keys, "unordered", True):
            if record.storage_kind == "absent":
                raise errors.RevisionNotPresent(record.key, self.vf)
            result[record.key[-1]] = record.get_bytes_as("lines")
        return result

    def plan_merge(self):
        """Generate a 'plan' for merging the two revisions.

        This involves comparing their texts and determining the cause of
        differences.  If text A has a line and text B does not, then either the
        line was added to text A, or it was deleted from B.  Once the causes
        are combined, they are written out in the format described in
        VersionedFile.plan_merge
        """
        blocks = self._get_matching_blocks(self.a_rev, self.b_rev)
        unique_a, unique_b = self._unique_lines(blocks)
        new_a, killed_b = self._determine_status(self.a_rev, unique_a)
        new_b, killed_a = self._determine_status(self.b_rev, unique_b)
        return self._iter_plan(blocks, new_a, killed_b, new_b, killed_a)

    def _iter_plan(self, blocks, new_a, killed_b, new_b, killed_a):
        last_i = 0
        last_j = 0
        for i, j, n in blocks:
            for a_index in range(last_i, i):
                if a_index in new_a:
                    if a_index in killed_b:
                        yield "conflicted-a", self.lines_a[a_index]
                    else:
                        yield "new-a", self.lines_a[a_index]
                else:
                    yield "killed-b", self.lines_a[a_index]
            for b_index in range(last_j, j):
                if b_index in new_b:
                    if b_index in killed_a:
                        yield "conflicted-b", self.lines_b[b_index]
                    else:
                        yield "new-b", self.lines_b[b_index]
                else:
                    yield "killed-a", self.lines_b[b_index]
            # handle common lines
            for a_index in range(i, i + n):
                yield "unchanged", self.lines_a[a_index]
            last_i = i + n
            last_j = j + n

    def _get_matching_blocks(self, left_revision, right_revision):
        """Return a description of which sections of two revisions match.

        See SequenceMatcher.get_matching_blocks
        """
        cached = self._cached_matching_blocks.get((left_revision, right_revision))
        if cached is not None:
            return cached
        if self._last_lines_revision_id == left_revision:
            left_lines = self._last_lines
            right_lines = self.get_lines([right_revision])[right_revision]
        else:
            lines = self.get_lines([left_revision, right_revision])
            left_lines = lines[left_revision]
            right_lines = lines[right_revision]
        self._last_lines = right_lines
        self._last_lines_revision_id = right_revision
        matcher = patiencediff.PatienceSequenceMatcher(None, left_lines, right_lines)
        return matcher.get_matching_blocks()

    def _unique_lines(self, matching_blocks):
        """Analyse matching_blocks to determine which lines are unique.

        :return: a tuple of (unique_left, unique_right), where the values are
            sets of line numbers of unique lines.
        """
        last_i = 0
        last_j = 0
        unique_left = []
        unique_right = []
        for i, j, n in matching_blocks:
            unique_left.extend(range(last_i, i))
            unique_right.extend(range(last_j, j))
            last_i = i + n
            last_j = j + n
        return unique_left, unique_right

    @staticmethod
    def _subtract_plans(old_plan, new_plan):
        """Remove changes from new_plan that came from old_plan.

        It is assumed that the difference between the old_plan and new_plan
        is their choice of 'b' text.

        All lines from new_plan that differ from old_plan are emitted
        verbatim.  All lines from new_plan that match old_plan but are
        not about the 'b' revision are emitted verbatim.

        Lines that match and are about the 'b' revision are the lines we
        don't want, so we convert 'killed-b' -> 'unchanged', and 'new-b'
        is skipped entirely.
        """
        matcher = patiencediff.PatienceSequenceMatcher(None, old_plan, new_plan)
        last_j = 0
        for _i, j, n in matcher.get_matching_blocks():
            for jj in range(last_j, j):
                yield new_plan[jj]
            for jj in range(j, j + n):
                plan_line = new_plan[jj]
                if plan_line[0] == "new-b":
                    pass
                elif plan_line[0] == "killed-b":
                    yield "unchanged", plan_line[1]
                else:
                    yield plan_line
            last_j = j + n


class _PlanMerge(_PlanMergeBase):
    """Plan an annotate merge using on-the-fly annotation."""

    def __init__(self, a_rev, b_rev, vf, key_prefix):
        super().__init__(a_rev, b_rev, vf, key_prefix)
        self.a_key = self._key_prefix + (self.a_rev,)
        self.b_key = self._key_prefix + (self.b_rev,)
        self.graph = _mod_graph.Graph(self.vf)
        heads = self.graph.heads((self.a_key, self.b_key))
        if len(heads) == 1:
            # one side dominates, so we can just return its values, yay for
            # per-file graphs
            # Ideally we would know that before we get this far
            self._head_key = heads.pop()
            if self._head_key == self.a_key:
                other = b_rev
            else:
                other = a_rev
            trace.mutter(
                "found dominating revision for %s\n%s > %s",
                self.vf,
                self._head_key[-1],
                other,
            )
            self._weave = None
        else:
            self._head_key = None
            self._build_weave()

    def _precache_tip_lines(self):
        # Turn this into a no-op, because we will do this later
        pass

    def _find_recursive_lcas(self):
        """Find all the ancestors back to a unique lca."""
        cur_ancestors = (self.a_key, self.b_key)
        # graph.find_lca(uncommon, keys) now returns plain NULL_REVISION,
        # rather than a key tuple. We will just map that directly to no common
        # ancestors.
        parent_map = {}
        while True:
            next_lcas = self.graph.find_lca(*cur_ancestors)
            # Map a plain NULL_REVISION to a simple no-ancestors
            if next_lcas == {_mod_revision.NULL_REVISION}:
                next_lcas = ()
            # Order the lca's based on when they were merged into the tip
            # While the actual merge portion of weave merge uses a set() of
            # active revisions, the order of insertion *does* effect the
            # implicit ordering of the texts.
            for rev_key in cur_ancestors:
                ordered_parents = tuple(self.graph.find_merge_order(rev_key, next_lcas))
                parent_map[rev_key] = ordered_parents
            if len(next_lcas) == 0:
                break
            elif len(next_lcas) == 1:
                parent_map[list(next_lcas)[0]] = ()
                break
            elif len(next_lcas) > 2:
                # More than 2 lca's, fall back to grabbing all nodes between
                # this and the unique lca.
                trace.mutter(
                    "More than 2 LCAs, falling back to all nodes for: %s, %s\n=> %s",
                    self.a_key,
                    self.b_key,
                    cur_ancestors,
                )
                cur_lcas = next_lcas
                while len(cur_lcas) > 1:
                    cur_lcas = self.graph.find_lca(*cur_lcas)
                if len(cur_lcas) == 0:
                    # No common base to find, use the full ancestry
                    unique_lca = None
                else:
                    unique_lca = list(cur_lcas)[0]
                    if unique_lca == _mod_revision.NULL_REVISION:
                        # find_lca will return a plain 'NULL_REVISION' rather
                        # than a key tuple when there is no common ancestor, we
                        # prefer to just use None, because it doesn't confuse
                        # _get_interesting_texts()
                        unique_lca = None
                parent_map.update(self._find_unique_parents(next_lcas, unique_lca))
                break
            cur_ancestors = next_lcas
        return parent_map

    def _find_unique_parents(self, tip_keys, base_key):
        """Find ancestors of tip that aren't ancestors of base.

        :param tip_keys: Nodes that are interesting
        :param base_key: Cull all ancestors of this node
        :return: The parent map for all revisions between tip_keys and
            base_key. base_key will be included. References to nodes outside of
            the ancestor set will also be removed.
        """
        # TODO: this would be simpler if find_unique_ancestors took a list
        #       instead of a single tip, internally it supports it, but it
        #       isn't a "backwards compatible" api change.
        if base_key is None:
            parent_map = dict(self.graph.iter_ancestry(tip_keys))
            # We remove NULL_REVISION because it isn't a proper tuple key, and
            # thus confuses things like _get_interesting_texts, and our logic
            # to add the texts into the memory weave.
            if _mod_revision.NULL_REVISION in parent_map:
                parent_map.pop(_mod_revision.NULL_REVISION)
        else:
            interesting = set()
            for tip in tip_keys:
                interesting.update(self.graph.find_unique_ancestors(tip, [base_key]))
            parent_map = self.graph.get_parent_map(interesting)
            parent_map[base_key] = ()
        culled_parent_map, child_map, tails = self._remove_external_references(
            parent_map
        )
        # Remove all the tails but base_key
        if base_key is not None:
            tails.remove(base_key)
            self._prune_tails(culled_parent_map, child_map, tails)
        # Now remove all the uninteresting 'linear' regions
        simple_map = _mod_graph.collapse_linear_regions(culled_parent_map)
        return simple_map

    @staticmethod
    def _remove_external_references(parent_map):
        """Remove references that go outside of the parent map.

        :param parent_map: Something returned from Graph.get_parent_map(keys)
        :return: (filtered_parent_map, child_map, tails)
            filtered_parent_map is parent_map without external references
            child_map is the {parent_key: [child_keys]} mapping
            tails is a list of nodes that do not have any parents in the map
        """
        # TODO: The basic effect of this function seems more generic than
        #       _PlanMerge. But the specific details of building a child_map,
        #       and computing tails seems very specific to _PlanMerge.
        #       Still, should this be in Graph land?
        filtered_parent_map = {}
        child_map = {}
        tails = []
        for key, parent_keys in parent_map.items():
            culled_parent_keys = [p for p in parent_keys if p in parent_map]
            if not culled_parent_keys:
                tails.append(key)
            for parent_key in culled_parent_keys:
                child_map.setdefault(parent_key, []).append(key)
            # TODO: Do we want to do this, it adds overhead for every node,
            #       just to say that the node has no children
            child_map.setdefault(key, [])
            filtered_parent_map[key] = culled_parent_keys
        return filtered_parent_map, child_map, tails

    @staticmethod
    def _prune_tails(parent_map, child_map, tails_to_remove):
        """Remove tails from the parent map.

        This will remove the supplied revisions until no more children have 0
        parents.

        :param parent_map: A dict of {child: [parents]}, this dictionary will
            be modified in place.
        :param tails_to_remove: A list of tips that should be removed,
            this list will be consumed
        :param child_map: The reverse dict of parent_map ({parent: [children]})
            this dict will be modified
        :return: None, parent_map will be modified in place.
        """
        while tails_to_remove:
            next = tails_to_remove.pop()
            parent_map.pop(next)
            children = child_map.pop(next)
            for child in children:
                child_parents = parent_map[child]
                child_parents.remove(next)
                if len(child_parents) == 0:
                    tails_to_remove.append(child)

    def _get_interesting_texts(self, parent_map):
        """Return a dict of texts we are interested in.

        Note that the input is in key tuples, but the output is in plain
        revision ids.

        :param parent_map: The output from _find_recursive_lcas
        :return: A dict of {'revision_id':lines} as returned by
            _PlanMergeBase.get_lines()
        """
        all_revision_keys = set(parent_map)
        all_revision_keys.add(self.a_key)
        all_revision_keys.add(self.b_key)

        # Everything else is in 'keys' but get_lines is in 'revision_ids'
        all_texts = self.get_lines([k[-1] for k in all_revision_keys])
        return all_texts

    def _build_weave(self):
        from .bzr import weave
        from .tsort import merge_sort

        self._weave = weave.Weave(weave_name="in_memory_weave", allow_reserved=True)
        parent_map = self._find_recursive_lcas()

        all_texts = self._get_interesting_texts(parent_map)

        # Note: Unfortunately, the order given by topo_sort will effect the
        # ordering resolution in the output. Specifically, if you add A then B,
        # then in the output text A lines will show up before B lines. And, of
        # course, topo_sort doesn't guarantee any real ordering.
        # So we use merge_sort, and add a fake node on the tip.
        # This ensures that left-hand parents will always be inserted into the
        # weave before right-hand parents.
        tip_key = self._key_prefix + (_mod_revision.CURRENT_REVISION,)
        parent_map[tip_key] = (self.a_key, self.b_key)

        for _seq_num, key, _depth, _eom in reversed(merge_sort(parent_map, tip_key)):
            if key == tip_key:
                continue
            # for key in tsort.topo_sort(parent_map):
            parent_keys = parent_map[key]
            revision_id = key[-1]
            parent_ids = [k[-1] for k in parent_keys]
            self._weave.add_lines(revision_id, parent_ids, all_texts[revision_id])

    def plan_merge(self):
        """Generate a 'plan' for merging the two revisions.

        This involves comparing their texts and determining the cause of
        differences.  If text A has a line and text B does not, then either the
        line was added to text A, or it was deleted from B.  Once the causes
        are combined, they are written out in the format described in
        VersionedFile.plan_merge
        """
        if self._head_key is not None:  # There was a single head
            if self._head_key == self.a_key:
                plan = "new-a"
            else:
                if self._head_key != self.b_key:
                    raise AssertionError(
                        "There was an invalid head: {} != {}".format(
                            self.b_key, self._head_key
                        )
                    )
                plan = "new-b"
            head_rev = self._head_key[-1]
            lines = self.get_lines([head_rev])[head_rev]
            return ((plan, line) for line in lines)
        return self._weave.plan_merge(self.a_rev, self.b_rev)


class _PlanLCAMerge(_PlanMergeBase):
    """Least Common Ancestor merge plan generator.

    This merge algorithm differs from _PlanMerge in that:

    1. comparisons are done against LCAs only
    2. cases where a contested line is new versus one LCA but old versus
       another are marked as conflicts, by emitting the line as conflicted-a
       or conflicted-b.

    This is faster, and hopefully produces more useful output.
    """

    def __init__(self, a_rev, b_rev, vf, key_prefix, graph):
        _PlanMergeBase.__init__(self, a_rev, b_rev, vf, key_prefix)
        lcas = graph.find_lca(key_prefix + (a_rev,), key_prefix + (b_rev,))
        self.lcas = set()
        for lca in lcas:
            if lca == _mod_revision.NULL_REVISION:
                self.lcas.add(lca)
            else:
                self.lcas.add(lca[-1])
        for lca in self.lcas:
            if _mod_revision.is_null(lca):
                lca_lines = []
            else:
                lca_lines = self.get_lines([lca])[lca]
            matcher = patiencediff.PatienceSequenceMatcher(
                None, self.lines_a, lca_lines
            )
            blocks = list(matcher.get_matching_blocks())
            self._cached_matching_blocks[(a_rev, lca)] = blocks
            matcher = patiencediff.PatienceSequenceMatcher(
                None, self.lines_b, lca_lines
            )
            blocks = list(matcher.get_matching_blocks())
            self._cached_matching_blocks[(b_rev, lca)] = blocks

    def _determine_status(self, revision_id, unique_line_numbers):
        """Determines the status unique lines versus all lcas.

        Basically, determines why the line is unique to this revision.

        A line may be determined new, killed, or both.

        If a line is determined new, that means it was not present in at least
        one LCA, and is not present in the other merge revision.

        If a line is determined killed, that means the line was present in
        at least one LCA.

        If a line is killed and new, this indicates that the two merge
        revisions contain differing conflict resolutions.

        :param revision_id: The id of the revision in which the lines are
            unique
        :param unique_line_numbers: The line numbers of unique lines.
        :return: a tuple of (new_this, killed_other)
        """
        new = set()
        killed = set()
        unique_line_numbers = set(unique_line_numbers)
        for lca in self.lcas:
            blocks = self._get_matching_blocks(revision_id, lca)
            unique_vs_lca, _ignored = self._unique_lines(blocks)
            new.update(unique_line_numbers.intersection(unique_vs_lca))
            killed.update(unique_line_numbers.difference(unique_vs_lca))
        return new, killed
