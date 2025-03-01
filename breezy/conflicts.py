# Copyright (C) 2005, 2006, 2007, 2009, 2010, 2011 Canonical Ltd
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

# TODO: 'brz resolve' should accept a directory name and work from that
# point down

import errno
import os

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """

from breezy import (
    workingtree,
    )
from breezy.i18n import gettext, ngettext
""",
)
from . import commands, errors, option, osutils, registry, trace


class cmd_conflicts(commands.Command):
    __doc__ = """List files with conflicts.

    Merge will do its best to combine the changes in two branches, but there
    are some kinds of problems only a human can fix.  When it encounters those,
    it will mark a conflict.  A conflict means that you need to fix something,
    before you can commit.

    Conflicts normally are listed as short, human-readable messages.  If --text
    is supplied, the pathnames of files with text conflicts are listed,
    instead.  (This is useful for editing all files with text conflicts.)

    Use brz resolve when you have fixed a problem.
    """
    takes_options = [
        "directory",
        option.Option("text", help="List paths of files with text conflicts."),
    ]
    _see_also = ["resolve", "conflict-types"]

    def run(self, text=False, directory="."):
        wt = workingtree.WorkingTree.open_containing(directory)[0]
        for conflict in wt.conflicts():
            if text:
                if conflict.typestring != "text conflict":
                    continue
                self.outf.write(conflict.path + "\n")
            else:
                self.outf.write(str(conflict) + "\n")


resolve_action_registry = registry.Registry[str, str]()


resolve_action_registry.register(
    "auto", "auto", "Detect whether conflict has been resolved by user."
)
resolve_action_registry.register("done", "done", "Marks the conflict as resolved.")
resolve_action_registry.register(
    "take-this",
    "take_this",
    "Resolve the conflict preserving the version in the working tree.",
)
resolve_action_registry.register(
    "take-other",
    "take_other",
    "Resolve the conflict taking the merged version into account.",
)
resolve_action_registry.default_key = "done"


class ResolveActionOption(option.RegistryOption):
    def __init__(self):
        super().__init__(
            "action",
            "How to resolve the conflict.",
            value_switches=True,
            registry=resolve_action_registry,
        )


class cmd_resolve(commands.Command):
    __doc__ = """Mark a conflict as resolved.

    Merge will do its best to combine the changes in two branches, but there
    are some kinds of problems only a human can fix.  When it encounters those,
    it will mark a conflict.  A conflict means that you need to fix something,
    before you can commit.

    Once you have fixed a problem, use "brz resolve" to automatically mark
    text conflicts as fixed, "brz resolve FILE" to mark a specific conflict as
    resolved, or "brz resolve --all" to mark all conflicts as resolved.
    """
    aliases = ["resolved"]
    takes_args = ["file*"]
    takes_options = [
        "directory",
        option.Option("all", help="Resolve all conflicts in this tree."),
        ResolveActionOption(),
    ]
    _see_also = ["conflicts"]

    def run(self, file_list=None, all=False, action=None, directory=None):
        if all:
            if file_list:
                raise errors.CommandError(
                    gettext("If --all is specified, no FILE may be provided")
                )
            if directory is None:
                directory = "."
            tree = workingtree.WorkingTree.open_containing(directory)[0]
            if action is None:
                action = "done"
        else:
            tree, file_list = workingtree.WorkingTree.open_containing_paths(
                file_list, directory
            )
            if action is None:
                if file_list is None:
                    action = "auto"
                else:
                    action = "done"
        before, after = resolve(tree, file_list, action=action)
        # GZ 2012-07-27: Should unify UI below now that auto is less magical.
        if action == "auto" and file_list is None:
            if after > 0:
                trace.note(
                    ngettext(
                        "%d conflict auto-resolved.",
                        "%d conflicts auto-resolved.",
                        before - after,
                    ),
                    before - after,
                )
                trace.note(gettext("Remaining conflicts:"))
                for conflict in tree.conflicts():
                    trace.note(str(conflict))
                return 1
            else:
                trace.note(gettext("All conflicts resolved."))
                return 0
        else:
            trace.note(
                ngettext(
                    "{0} conflict resolved, {1} remaining",
                    "{0} conflicts resolved, {1} remaining",
                    before - after,
                ).format(before - after, after)
            )


def resolve(tree, paths=None, ignore_misses=False, recursive=False, action="done"):
    """Resolve some or all of the conflicts in a working tree.

    :param paths: If None, resolve all conflicts.  Otherwise, select only
        specified conflicts.
    :param recursive: If True, then elements of paths which are directories
        have all their children resolved, etc.  When invoked as part of
        recursive commands like revert, this should be True.  For commands
        or applications wishing finer-grained control, like the resolve
        command, this should be False.
    :param ignore_misses: If False, warnings will be printed if the supplied
        paths do not have conflicts.
    :param action: How the conflict should be resolved,
    """
    nb_conflicts_after = None
    with tree.lock_tree_write():
        tree_conflicts = tree.conflicts()
        nb_conflicts_before = len(tree_conflicts)
        if paths is None:
            new_conflicts = []
            to_process = tree_conflicts
        else:
            new_conflicts, to_process = tree_conflicts.select_conflicts(
                tree, paths, ignore_misses, recursive
            )
        for conflict in to_process:
            try:
                conflict.do(action, tree)
                conflict.cleanup(tree)
            except NotImplementedError:
                new_conflicts.append(conflict)
        try:
            nb_conflicts_after = len(new_conflicts)
            tree.set_conflicts(new_conflicts)
        except errors.UnsupportedOperation:
            pass
    if nb_conflicts_after is None:
        nb_conflicts_after = nb_conflicts_before
    return nb_conflicts_before, nb_conflicts_after


def restore(filename):
    """Restore a conflicted file to the state it was in before merging.

    Only text restoration is supported at present.
    """
    conflicted = False
    try:
        osutils.rename(filename + ".THIS", filename)
        conflicted = True
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
    try:
        os.unlink(filename + ".BASE")
        conflicted = True
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
    try:
        os.unlink(filename + ".OTHER")
        conflicted = True
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
    if not conflicted:
        raise errors.NotConflicted(filename)


class ConflictList:
    """List of conflicts.

    Typically obtained from WorkingTree.conflicts()
    """

    def __init__(self, conflicts=None):
        object.__init__(self)
        if conflicts is None:
            self.__list = []
        else:
            self.__list = conflicts

    def is_empty(self):
        return len(self.__list) == 0

    def __len__(self):
        return len(self.__list)

    def __iter__(self):
        return iter(self.__list)

    def __getitem__(self, key):
        return self.__list[key]

    def append(self, conflict):
        return self.__list.append(conflict)

    def __eq__(self, other_list):
        return list(self) == list(other_list)

    def __ne__(self, other_list):
        return not (self == other_list)

    def __repr__(self):
        return "ConflictList(%r)" % self.__list

    def to_strings(self):
        """Generate strings for the provided conflicts"""
        for conflict in self:
            yield str(conflict)

    def remove_files(self, tree):
        """Remove the THIS, BASE and OTHER files for listed conflicts"""
        for conflict in self:
            if not conflict.has_files:
                continue
            conflict.cleanup(tree)

    def select_conflicts(self, tree, paths, ignore_misses=False, recurse=False):
        """Select the conflicts associated with paths in a tree.

        :return: a pair of ConflictLists: (not_selected, selected)
        """
        path_set = set(paths)
        selected_paths = set()
        new_conflicts = ConflictList()
        selected_conflicts = ConflictList()

        for conflict in self:
            selected = False
            if conflict.path in path_set:
                selected = True
                selected_paths.add(conflict.path)
            if recurse:
                if osutils.is_inside_any(path_set, conflict.path):
                    selected = True
                    selected_paths.add(conflict.path)

            if selected:
                selected_conflicts.append(conflict)
            else:
                new_conflicts.append(conflict)
        if ignore_misses is not True:
            for path in [p for p in paths if p not in selected_paths]:
                if not os.path.exists(tree.abspath(path)):
                    print("%s does not exist" % path)
                else:
                    print("%s is not conflicted" % path)
        return new_conflicts, selected_conflicts


class Conflict:
    """Base class for conflicts."""

    typestring: str

    def __init__(self, path):
        self.path = path

    def associated_filenames(self):
        """The names of the files generated to help resolve the conflict."""
        raise NotImplementedError(self.associated_filenames)

    def cleanup(self, tree):
        for fname in self.associated_filenames():
            try:
                osutils.delete_any(tree.abspath(fname))
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise

    def do(self, action, tree):
        """Apply the specified action to the conflict.

        :param action: The method name to call.

        :param tree: The tree passed as a parameter to the method.
        """
        raise NotImplementedError(self.do)

    def describe(self):
        """Return a string description of this conflict."""
        raise NotImplementedError(self.describe)
