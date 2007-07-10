#    merge_upstream.py -- Merge new upstream versions of packages.
#    Copyright (C) 2007 Reinhard Tartler <siretart@tauware.de>
#                  2007 James Westby <jw+debian@jameswestby.net>
#
#    Code is also taken from bzrtools, which is
#             (C) 2005, 2006, 2007 Aaron Bentley <aaron.bentley@utoronto.ca>
#             (C) 2005, 2006 Canonical Limited.
#             (C) 2006 Michael Ellerman.
#    and distributed under the GPL, version 2 or later.
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

from debian_bundle.changelog import Changelog

from bzrlib.errors import (BzrCommandError,
                           NoSuchFile,
                           NoSuchTag,
                           TagAlreadyExists,
                           )
from bzrlib.plugins.bzrtools.upstream_import import (import_tar,
                                                     import_dir,
                                                     import_zip,
                                                     )

from errors import AddChangelogError

# TODO: way of working out new version number.
# TODO: support using an explicit standalone upstream branch.

def make_upstream_tag(version):
  """Make the name of the tag corresponding to the given version."""
  return "upstream-%s" % str(version)


def lookup_tag(tree):
   """Look up the last upstream tag in the branch.

   The upstream version of the last entry in debian/changelog in the tree
   is used in the name of the tag, format 'upstream-<version>'. This tag is
   then looked up in the branch. The return will be the revision_id that the
   tag corresponds to.

   :param tree: The tree to read debian/changelog from, and to have it's
                branch used for the tag lookup.
   :type tree: WorkingTree
   :returns: The revision_id corresponding to the tag.
   :rtype: string
   :throws: NoSuchTag if the tag is not present.
   """
   cl_id = tree.path2id('debian/changelog')
   if cl_id is None:
     raise AddChangelogError('debian/changelog')
   cl = Changelog(tree.get_file_text(cl_id))
   upstream_version = cl.upstream_version
   tag = make_upstream_tag(upstream_version)
   return tree.branch.tags.lookup_tag(tag)


def merge_upstream(tree, source, version_number):
    """Merge a new upstream release.

    A new upstream release will be extracted and imported in to the branch,
    and then the packaging specific changes merged in to this.

    The debian/changelog will be opened in the tree for the last upstream
    version. Then a tag named 'upstream-<version>' will be looked up in the
    branch and that revision will be used as the last import of upstream. The
    new version will then be imported on top of this and a new tag will be
    created using the specified version number. The merge will then be done
    in to this, and the tree will be left with pending merges, and possibly
    any conflicts to fix up.

    The tree must have no uncommited changes.

    If the found tag is the tip of the tree's branch then a fastforward is
    done, and will be committed.

    :param tree: The tree upon which to operate.
    :type tree: WorkingTree
    :param source: The filename tarball to import from.
    :type source: string
    :param version_number: The version number of the new upstream.
    :type version_number: string
    :return: None
    :throws NoSuchTag: if the tag for the last upstream version is not found.
    """
    if tree.changes_from(tree.basis_tree()).has_changed():
      raise BzrCommandError("Working tree has uncommitted changes.")
    if not os.path.exists(source):
      raise NoSuchFile(source)
    empty_branch = len(tree.branch.revision_history()) == 0
    if not empty_branch:
      try:
        tree.branch.tags.lookup_tag(make_upstream_tag(version_number))
        raise TagAlreadyExists(make_upstream_tag(version_number))
      except NoSuchTag:
        pass
      current_revision = tree.last_revision()
      rev_id = lookup_tag(tree)
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
          elif source.endswith('.zip'):
              import_zip(tree, open(source, 'rb'))
        tree.set_parent_ids([rev_id])
        tree.branch.set_last_revision_info(
                       tree.branch.revision_id_to_revno(rev_id), rev_id)
        tree.commit('import upstream from %s' % os.path.basename(source))
        tree.branch.tags.set_tag(make_upstream_tag(version_number),
                                 tree.branch.last_revision())
        tree.merge_from_branch(tree.branch, to_revision=current_revision)
        return
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
      elif source.endswith('.zip'):
          import_zip(tree, open(source, 'rb'))
    tree.commit('import upstream from %s' % os.path.basename(source))
    tree.branch.tags.set_tag(make_upstream_tag(version_number),
                             tree.branch.last_revision())

