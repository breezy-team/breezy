# Copyright (C) 2007, 2008, 2009 Canonical Ltd
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

"""Utility for create branches with particular contents."""

from . import commit, controldir, errors, revision


class BranchBuilder:
    r"""A BranchBuilder aids creating Branches with particular shapes.

    The expected way to use BranchBuilder is to construct a
    BranchBuilder on the transport you want your branch on, and then call
    appropriate build_ methods on it to get the shape of history you want.

    This is meant as a helper for the test suite, not as a general class for
    real data.

    For instance:

    >>> from breezy.transport.memory import MemoryTransport
    >>> builder = BranchBuilder(MemoryTransport("memory:///"))
    >>> builder.start_series()
    >>> builder.build_snapshot(None, [
    ...     ('add', ('', b'root-id', 'directory', '')),
    ...     ('add', ('filename', b'f-id', 'file', b'content\n'))],
    ...     revision_id=b'rev-id')
    b'rev-id'
    >>> builder.build_snapshot([b'rev-id'],
    ...     [('modify', ('filename', b'new-content\n'))],
    ...     revision_id=b'rev2-id')
    b'rev2-id'
    >>> builder.finish_series()
    >>> branch = builder.get_branch()

    :ivar _tree: This is a private member which is not meant to be modified by
        users of this class. While a 'series' is in progress, it should hold a
        MemoryTree with the contents of the last commit (ready to be modified
        by the next build_snapshot command) with a held write lock. Outside of
        a series in progress, it should be None.
    """

    def __init__(self, transport=None, format=None, branch=None):
        """Construct a BranchBuilder on transport.

        :param transport: The transport the branch should be created on.
            If the path of the transport does not exist but its parent does
            it will be created.
        :param format: Either a BzrDirFormat, or the name of a format in the
            controldir format registry for the branch to be built.
        :param branch: An already constructed branch to use.  This param is
            mutually exclusive with the transport and format params.
        """
        if branch is not None:
            if format is not None:
                raise AssertionError("branch and format kwargs are mutually exclusive")
            if transport is not None:
                raise AssertionError(
                    "branch and transport kwargs are mutually exclusive"
                )
            self._branch = branch
        else:
            if not transport.has("."):
                transport.mkdir(".")
            if format is None:
                format = "default"
            if isinstance(format, str):
                format = controldir.format_registry.make_controldir(format)
            self._branch = controldir.ControlDir.create_branch_convenience(
                transport.base, format=format, force_new_tree=False
            )
        self._tree = None

    def build_commit(
        self, parent_ids=None, allow_leftmost_as_ghost=False, **commit_kwargs
    ):
        """Build a commit on the branch.

        This makes a commit with no real file content for when you only want
        to look at the revision graph structure.

        :param commit_kwargs: Arguments to pass through to commit, such as
             timestamp.
        """
        if parent_ids is not None:
            if len(parent_ids) == 0:
                base_id = revision.NULL_REVISION
            else:
                base_id = parent_ids[0]
            if base_id != self._branch.last_revision():
                self._move_branch_pointer(
                    base_id, allow_leftmost_as_ghost=allow_leftmost_as_ghost
                )
        tree = self._branch.create_memorytree()
        with tree.lock_write():
            if parent_ids is not None:
                tree.set_parent_ids(
                    parent_ids, allow_leftmost_as_ghost=allow_leftmost_as_ghost
                )
            tree.add("")
            return self._do_commit(tree, **commit_kwargs)

    def _do_commit(self, tree, message=None, message_callback=None, **kwargs):
        reporter = commit.NullCommitReporter()
        if message is None and message_callback is None:
            message = f"commit {self._branch.revno() + 1}"
        return tree.commit(
            message, message_callback=message_callback, reporter=reporter, **kwargs
        )

    def _move_branch_pointer(self, new_revision_id, allow_leftmost_as_ghost=False):
        """Point self._branch to a different revision id."""
        with self._branch.lock_write():
            # We don't seem to have a simple set_last_revision(), so we
            # implement it here.
            cur_revno, cur_revision_id = self._branch.last_revision_info()
            try:
                g = self._branch.repository.get_graph()
                new_revno = g.find_distance_to_null(
                    new_revision_id, [(cur_revision_id, cur_revno)]
                )
                self._branch.set_last_revision_info(new_revno, new_revision_id)
            except errors.GhostRevisionsHaveNoRevno:
                if not allow_leftmost_as_ghost:
                    raise
                new_revno = 1
        if self._tree is not None:
            # We are currently processing a series, but when switching branch
            # pointers, it is easiest to just create a new memory tree.
            # That way we are sure to have the right files-on-disk
            # We are cheating a little bit here, and locking the new tree
            # before the old tree is unlocked. But that way the branch stays
            # locked throughout.
            new_tree = self._branch.create_memorytree()
            new_tree.lock_write()
            self._tree.unlock()
            self._tree = new_tree

    def start_series(self):
        """We will be creating a series of commits.

        This allows us to hold open the locks while we are processing.

        Make sure to call 'finish_series' when you are done.
        """
        if self._tree is not None:
            raise AssertionError(
                "You cannot start a new series while a series is already going."
            )
        self._tree = self._branch.create_memorytree()
        self._tree.lock_write()

    def finish_series(self):
        """Call this after start_series to unlock the various objects."""
        self._tree.unlock()
        self._tree = None

    def build_snapshot(
        self,
        parent_ids,
        actions,
        message=None,
        timestamp=None,
        allow_leftmost_as_ghost=False,
        committer=None,
        timezone=None,
        message_callback=None,
        revision_id=None,
    ):
        """Build a commit, shaped in a specific way.

        Most of the actions are self-explanatory.  'flush' is special action to
        break a series of actions into discrete steps so that complex changes
        (such as unversioning a file-id and re-adding it with a different kind)
        can be expressed in a way that will clearly work.

        :param parent_ids: A list of parent_ids to use for the commit.
            It can be None, which indicates to use the last commit.
        :param actions: A list of actions to perform. Supported actions are:
            ('add', ('path', b'file-id', 'kind', b'content' or None))
            ('modify', ('path', b'new-content'))
            ('unversion', 'path')
            ('rename', ('orig-path', 'new-path'))
            ('flush', None)
        :param message: An optional commit message, if not supplied, a default
            commit message will be written.
        :param message_callback: A message callback to use for the commit, as
            per mutabletree.commit.
        :param timestamp: If non-None, set the timestamp of the commit to this
            value.
        :param timezone: An optional timezone for timestamp.
        :param committer: An optional username to use for commit
        :param allow_leftmost_as_ghost: True if the leftmost parent should be
            permitted to be a ghost.
        :param revision_id: The handle for the new commit, can be None
        :return: The revision_id of the new commit
        """
        if parent_ids is not None:
            if len(parent_ids) == 0:
                base_id = revision.NULL_REVISION
            else:
                base_id = parent_ids[0]
            if base_id != self._branch.last_revision():
                self._move_branch_pointer(
                    base_id, allow_leftmost_as_ghost=allow_leftmost_as_ghost
                )

        if self._tree is not None:
            tree = self._tree
        else:
            tree = self._branch.create_memorytree()
        with tree.lock_write():
            if parent_ids is not None:
                tree.set_parent_ids(
                    parent_ids, allow_leftmost_as_ghost=allow_leftmost_as_ghost
                )
            # Unfortunately, MemoryTree.add(directory) just creates an
            # inventory entry. And the only public function to create a
            # directory is MemoryTree.mkdir() which creates the directory, but
            # also always adds it. So we have to use a multi-pass setup.
            pending = _PendingActions()
            for action, info in actions:
                if action == "add":
                    path, file_id, kind, content = info
                    if kind == "directory":
                        pending.to_add_directories.append((path, file_id))
                    else:
                        pending.to_add_files.append(path)
                        pending.to_add_file_ids.append(file_id)
                        pending.to_add_kinds.append(kind)
                        if content is not None:
                            pending.new_contents[path] = content
                elif action == "modify":
                    path, content = info
                    pending.new_contents[path] = content
                elif action == "unversion":
                    pending.to_unversion_paths.add(info)
                elif action == "rename":
                    from_relpath, to_relpath = info
                    pending.to_rename.append((from_relpath, to_relpath))
                elif action == "flush":
                    self._flush_pending(tree, pending)
                    pending = _PendingActions()
                else:
                    raise ValueError('Unknown build action: "{}"'.format(action))
            self._flush_pending(tree, pending)
            return self._do_commit(
                tree,
                message=message,
                rev_id=revision_id,
                timestamp=timestamp,
                timezone=timezone,
                committer=committer,
                message_callback=message_callback,
            )

    def _flush_pending(self, tree, pending):
        """Flush the pending actions in 'pending', i.e. apply them to tree."""
        for path, file_id in pending.to_add_directories:
            if path == "":
                if tree.has_filename(path) and path in pending.to_unversion_paths:
                    # We're overwriting this path, no need to unversion
                    pending.to_unversion_paths.discard(path)
                # Special case, because the path already exists
                if file_id is not None:
                    tree.add([path], ["directory"], ids=[file_id])
                else:
                    tree.add([path], ["directory"])
            else:
                if file_id is not None:
                    tree.mkdir(path, file_id)
                else:
                    tree.mkdir(path)
        for from_relpath, to_relpath in pending.to_rename:
            tree.rename_one(from_relpath, to_relpath)
        if pending.to_unversion_paths:
            tree.unversion(pending.to_unversion_paths)
        if tree.supports_file_ids:
            tree.add(
                pending.to_add_files, pending.to_add_kinds, pending.to_add_file_ids
            )
        else:
            tree.add(pending.to_add_files, pending.to_add_kinds)
        for path, content in pending.new_contents.items():
            tree.put_file_bytes_non_atomic(path, content)

    def get_branch(self):
        """Return the branch created by the builder."""
        return self._branch


class _PendingActions:
    """Pending actions for build_snapshot to take.

    This is just a simple class to hold a bunch of the intermediate state of
    build_snapshot in single object.
    """

    def __init__(self):
        self.to_add_directories = []
        self.to_add_files = []
        self.to_add_file_ids = []
        self.to_add_kinds = []
        self.new_contents = {}
        self.to_unversion_paths = set()
        self.to_rename = []
