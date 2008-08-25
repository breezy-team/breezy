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

from debian_bundle.changelog import Changelog, Version

from bzrlib.errors import (BzrCommandError,
                           NoSuchTag,
                           TagAlreadyExists,
                           )
from bzrlib.plugins.bzrtools.upstream_import import (import_tar,
                                                     import_dir,
                                                     import_zip,
                                                     )

from bzrlib.plugins.builddeb.errors import AddChangelogError

# TODO: way of working out new version number.
# TODO: support using an explicit standalone upstream branch.


TAG_PREFIX = "upstream-"

def upstream_branch_version(revhistory, tags, package, previous_version):
  """Determine the version string of an upstream branch.

  :param revhistory: Branch revision history.
  :param tags: Tags object.
  :param package: Name of package.
  :param previous_version: Upstream version currently in Debian package.
  """
  reverse_tag_dict = tags.get_reverse_tags_dict()
  
  # Check if upstream has a tag set on branch.last_revision()
  # Yes? Convert to upstream_version and return
  if revhistory[-1] in reverse_tag_dict:
    return upstream_tag_to_version(reverse_tag_dict[revhistory[-1]], 
                                   package=package)
  
  # Parse previous_version
  # if it contains ~bzr:
  if "~bzr" in previous_version or "+bzr" in previous_version:
    # check if new tags appeared since previous_version's revision
    # if they didn't, update revno in ~bzr<revno>
    bzr_revno = int(previous_version[previous_version.find("bzr")+3:])
    for r in reversed(revhistory[bzr_revno:]):
      if r in reverse_tag_dict:
        # If there is a newer version tagged in branch, 
        # convert to upstream version 
        # return <upstream_version>+bzr<revno>
        upstream_version = upstream_tag_to_version(reverse_tag_dict[r], 
                                                   package=package)
        return "%s+bzr%d" % (upstream_version, len(revhistory))

    return "%s%d" % (previous_version[previous_version.find("bzr")+3:],
                     len(revhistory))
  return "%s+bzr%d" % (previous_version, len(revhistory))


def merge_upstream_branch(tree, upstream_branch, package, version=None):
  """Merge an upstream release from a branch.

  :param tree: Mutable tree to merge into.
  :param upstream_branch: Upstream branch object
  :param package: Package name.
  :param version: Optional version string. If none is specified, will 
                  be determined from the branch.
  :param version: Actual version string that was used
  """
  if version is None:
    version = upstream_branch_version(upstream_branch.revision_history(),
                                      upstream_branch.tags(), package, 
                                      FIXME)
  tree.merge_from_branch(upstream_branch)
  tree.branch.tags.set_tag(make_upstream_tag(version),
                           upstream_branch.last_revision())
  tree.commit('import upstream from branch %s' % upstream_branch.base)
  return version


def make_upstream_tag(version):
  """Make the name of the tag corresponding to the given version."""
  return  TAG_PREFIX + "%s" % str(version)


def upstream_tag_to_version(tag_name, package=None):
  """Take a tag name and return the upstream version, or None."""
  if tag_name.startswith(TAG_PREFIX):
    return Version(tag_name[len(TAG_PREFIX):])
  if (package is not None and (
        tag_name.startswith("%s-" % package) or
        tag_name.startswith("%s_" % package))):
    return Version(tag_name[len(package)+1:])
  if tag_name[0] == "v" and tag_name[1].isdigit():
    return Version(tag_name[1:])
  if all([c.isdigit() or c in (".", "~") for c in tag_name]):
    return Version(tagname)

  return None


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
        tree.pull(tree.branch, stop_revision=rev_id, overwrite=True)
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

# vim: ts=2 sts=2 sw=2
