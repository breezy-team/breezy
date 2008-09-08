# Copyright (C) 2007, 2008 Canonical Ltd
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

"""Utility for create branches with particular contents."""

from bzrlib import bzrdir, errors, memorytree


class BranchBuilder(object):
    """A BranchBuilder aids creating Branches with particular shapes.
    
    The expected way to use BranchBuilder is to construct a
    BranchBuilder on the transport you want your branch on, and then call
    appropriate build_ methods on it to get the shape of history you want.

    This is meant as a helper for the test suite, not as a general class for
    real data.

    For instance:
      builder = BranchBuilder(self.get_transport().clone('relpath'))
      builder.start_series()
      builder.build_snapshot('rev-id', [],
        [('add', ('filename', 'f-id', 'file', 'content\n'))])
      builder.build_snapshot('rev2-id', ['rev-id'],
        [('modify', ('f-id', 'new-content\n'))])
      builder.finish_series()
      branch = builder.get_branch()

    :ivar _tree: This is a private member which is not meant to be modified by
        users of this class. While a 'series' is in progress, it should hold a
        MemoryTree with the contents of the last commit (ready to be modified
        by the next build_snapshot command) with a held write lock. Outside of
        a series in progress, it should be None.
    """

    def __init__(self, transport, format=None):
        """Construct a BranchBuilder on transport.
        
        :param transport: The transport the branch should be created on.
            If the path of the transport does not exist but its parent does
            it will be created.
        :param format: Either a BzrDirFormat, or the name of a format in the
            bzrdir format registry for the branch to be built.
        """
        if not transport.has('.'):
            transport.mkdir('.')
        if format is None:
            format = 'default'
        if isinstance(format, str):
            format = bzrdir.format_registry.make_bzrdir(format)
        self._branch = bzrdir.BzrDir.create_branch_convenience(transport.base,
            format=format, force_new_tree=False)
        self._tree = None

    def build_commit(self):
        """Build a commit on the branch."""
        tree = memorytree.MemoryTree.create_on_branch(self._branch)
        tree.lock_write()
        try:
            tree.add('')
            return tree.commit('commit %d' % (self._branch.revno() + 1))
        finally:
            tree.unlock()

    def _move_branch_pointer(self, new_revision_id):
        """Point self._branch to a different revision id."""
        self._branch.lock_write()
        try:
            # We don't seem to have a simple set_last_revision(), so we
            # implement it here.
            cur_revno, cur_revision_id = self._branch.last_revision_info()
            g = self._branch.repository.get_graph()
            new_revno = g.find_distance_to_null(new_revision_id,
                                                [(cur_revision_id, cur_revno)])
            self._branch.set_last_revision_info(new_revno, new_revision_id)
        finally:
            self._branch.unlock()
        if self._tree is not None:
            # We are currently processing a series, but when switching branch
            # pointers, it is easiest to just create a new memory tree.
            # That way we are sure to have the right files-on-disk
            # We are cheating a little bit here, and locking the new tree
            # before the old tree is unlocked. But that way the branch stays
            # locked throughout.
            new_tree = memorytree.MemoryTree.create_on_branch(self._branch)
            new_tree.lock_write()
            self._tree.unlock()
            self._tree = new_tree

    def start_series(self):
        """We will be creating a series of commits.

        This allows us to hold open the locks while we are processing.

        Make sure to call 'finish_series' when you are done.
        """
        if self._tree is not None:
            raise AssertionError('You cannot start a new series while a'
                                 ' series is already going.')
        self._tree = memorytree.MemoryTree.create_on_branch(self._branch)
        self._tree.lock_write()

    def finish_series(self):
        """Call this after start_series to unlock the various objects."""
        self._tree.unlock()
        self._tree = None

    def build_snapshot(self, revision_id, parent_ids, actions,
                       message=None):
        """Build a commit, shaped in a specific way.

        :param revision_id: The handle for the new commit, can be None
        :param parent_ids: A list of parent_ids to use for the commit.
            It can be None, which indicates to use the last commit.
        :param actions: A list of actions to perform. Supported actions are:
            ('add', ('path', 'file-id', 'kind', 'content' or None))
            ('modify', ('file-id', 'new-content'))
            ('unversion', 'file-id')
            # not supported yet: ('rename', ('orig-path', 'new-path'))
        :param message: An optional commit message, if not supplied, a default
            commit message will be written.
        :return: The revision_id of the new commit
        """
        if parent_ids is not None:
            base_id = parent_ids[0]
            if base_id != self._branch.last_revision():
                self._move_branch_pointer(base_id)

        if self._tree is not None:
            tree = self._tree
        else:
            tree = memorytree.MemoryTree.create_on_branch(self._branch)
        tree.lock_write()
        try:
            if parent_ids is not None:
                tree.set_parent_ids(parent_ids)
            # Unfortunately, MemoryTree.add(directory) just creates an
            # inventory entry. And the only public function to create a
            # directory is MemoryTree.mkdir() which creates the directory, but
            # also always adds it. So we have to use a multi-pass setup.
            to_add_directories = []
            to_add_files = []
            to_add_file_ids = []
            to_add_kinds = []
            new_contents = {}
            to_unversion_ids = []
            # TODO: MemoryTree doesn't support rename() or
            #       apply_inventory_delta, so we'll postpone allowing renames
            #       for now
            # to_rename = []
            for action, info in actions:
                if action == 'add':
                    path, file_id, kind, content = info
                    if kind == 'directory':
                        to_add_directories.append((path, file_id))
                    else:
                        to_add_files.append(path)
                        to_add_file_ids.append(file_id)
                        to_add_kinds.append(kind)
                        if content is not None:
                            new_contents[file_id] = content
                elif action == 'modify':
                    file_id, content = info
                    new_contents[file_id] = content
                elif action == 'unversion':
                    to_unversion_ids.append(info)
                else:
                    raise ValueError('Unknown build action: "%s"' % (action,))
            if to_unversion_ids:
                tree.unversion(to_unversion_ids)
            for path, file_id in to_add_directories:
                if path == '':
                    # Special case, because the path already exists
                    tree.add([path], [file_id], ['directory'])
                else:
                    tree.mkdir(path, file_id)
            tree.add(to_add_files, to_add_file_ids, to_add_kinds)
            for file_id, content in new_contents.iteritems():
                tree.put_file_bytes_non_atomic(file_id, content)

            if message is None:
                message = u'commit %d' % (self._branch.revno() + 1,)
            return tree.commit(message, rev_id=revision_id)
        finally:
            tree.unlock()

    def get_branch(self):
        """Return the branch created by the builder."""
        return self._branch
