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

from bz2 import BZ2File
import os
from StringIO import StringIO

from bzrlib.errors import BzrCommandError
from bzrlib.plugins.bzrtools.upstream_import import (import_tar,
                                                     import_dir,
                                                     )

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

    If the specified old_revision is the tip of the tree's branch then
    a fastforward is done, and will be committed.

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
    if not os.path.exists(source):
      raise BzrCommandError("%s does not exists" % source)
    current_revision = tree.last_revision()
    revno, rev_id = old_revision.in_branch(tree.branch)
    if rev_id != tree.branch.last_revision():
      tree.revert([], tree.branch.repository.revision_tree(rev_id))
      if os.path.isdir(source):
        s = StringIO(source)
        s.seek(0)
        import_dir(tree, s)
      else:
        if (source.endswith('.tar') or source.endswith('.tar.gz') or
            source.endswith('.tar.bz2') or source.endswith('.tgz')):
          if source.endswith('.bz2'):
            tar_input = BZ2File(source, 'r')
            tar_input = StringIO(tar_input.read())
          else:
            tar_input = open(source, 'rb')
          try:
            import_tar(tree, tar_input)
          finally:
            tar_input.close()
      tree.set_parent_ids([rev_id])
      tree.branch.set_last_revision_info(revno, rev_id)
      tree.commit('import upstream from %s' % os.path.basename(source))
      tree.merge_from_branch(tree.branch, to_revision=current_revision)
    else:
      # Fast forward the merge.
      if os.path.isdir(source):
        s = StringIO(source)
        s.seek(0)
        import_dir(tree, s)
      else:
        if (source.endswith('.tar') or source.endswith('.tar.gz') or
            source.endswith('.tar.bz2') or source.endswith('.tgz')):
          if source.endswith('.bz2'):
            tar_input = BZ2File(source, 'r')
            tar_input = StringIO(tar_input.read())
          else:
            tar_input = open(source, 'rb')
          try:
            import_tar(tree, tar_input)
          finally:
            tar_input.close()
      tree.commit('import upstream from %s' % os.path.basename(source))

