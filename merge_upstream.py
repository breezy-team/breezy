#    merge_upstream.py -- Merge new upstream versions of packages.
#    Copyright (C) 2007 Reinhard Tartler <siretart@tauware.de>
#                  2007 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import os

from bzrlib.errors import BzrCommandError
from bzrlib.plugins.bzrtools.upstream_import import import_tar

# TODO: handle more input sources.
# TODO: rename/repack tarball in to place.
# TODO: drop requirement for revision of last upstream, use tags or something
#       instead.
# TODO: support using an explicit standalone upstream branch.

def merge_upstream(tree, source, old_revision):
    """Merge a new upstream release.

    A new upstream release will be extracted and imported in to the branch,
    and then the packaging specific changes merged in to this.

    The revision of the last commit on the upstream "branch", upon which the
    new upstream will be created. The merge will then be done in to this,
    and the tree will be left with pending merges, and possibly any conflicts
    to fix up.

    The tree must have no uncommited changes.

    :param tree: The tree upon which to operate.
    :type tree: WorkingTree
    :param source: The filename tarball to import from.
    :type source: string
    :param old_revision: The revision of the last commit on the upstream
                         branch.
    :type old_revision: RevisionSpec
    :return: None
    """
    if tree.changes_from(tree.basis_tree()).has_changed():
      raise BzrCommandError("Working tree has uncommitted changes.")
    current_revision = tree.last_revision()
    revno, rev_id = old_revision.in_branch(tree.branch)
    tree.revert([], tree.branch.repository.revision_tree(rev_id))
    tar_input = open(source, 'rb')
    import_tar(tree, tar_input)
    tree.set_parent_ids([rev_id])
    tree.branch.set_last_revision_info(revno, rev_id)
    tree.commit('import upstream from %s' % os.path.basename(source))
    tree.merge_from_branch(tree.branch, to_revision=current_revision)

