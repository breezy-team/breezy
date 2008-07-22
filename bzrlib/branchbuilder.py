# Copyright (C) 2007 Canonical Ltd
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

    For instance:
      builder = BranchBuilder(self.get_transport().clone('relpath'))
      builder.build_commit()
      builder.build_commit()
      builder.build_commit()
      branch = builder.get_branch()
    """

    def __init__(self, transport, format=None):
        """Construct a BranchBuilder on transport.
        
        :param transport: The transport the branch should be created on.
            If the path of the transport does not exist but its parent does
            it will be created.
        :param format: The name of a format in the bzrdir format registry
            for the branch to be built.
        """
        if not transport.has('.'):
            transport.mkdir('.')
        if format is None:
            format = 'default'
        self._branch = bzrdir.BzrDir.create_branch_convenience(transport.base,
            format=bzrdir.format_registry.make_bzrdir(format))

    def build_commit(self):
        """Build a commit on the branch."""
        tree = memorytree.MemoryTree.create_on_branch(self._branch)
        tree.lock_write()
        try:
            tree.add('')
            return tree.commit('commit %d' % (self._branch.revno() + 1))
        finally:
            tree.unlock()

    def build_snapshot(self, parent_ids, revision_id, actions):
        tree = memorytree.MemoryTree.create_on_branch(self._branch)
        tree.lock_write()
        try:
            to_add_paths = []
            to_add_file_ids = []
            to_add_kinds = []
            new_contents = {}
            to_unversion_ids = []
            # to_rename = []
            for action, info in actions:
                if action == 'add':
                    path, file_id, kind, content = info
                    to_add_paths.append(path)
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
                    raise errors.UnknownBuildAction(action)
            if to_unversion_ids:
                tree.unversion(to_unversion_ids)
            tree.add(to_add_paths, to_add_file_ids, to_add_kinds)
            for file_id, content in new_contents.iteritems():
                tree.put_file_bytes_non_atomic(file_id, content)

            return tree.commit('commit %s' % (revision_id,), rev_id=revision_id)
        finally:
            tree.unlock()

    def get_branch(self):
        """Return the branch created by the builder."""
        return self._branch
