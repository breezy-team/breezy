#    merge_upstream.py -- Merge new upstream versions of packages.
#    Copyright (C) 2007 Reinhard Tartler <siretart@tauware.de>
#                  2007 James Westby <jw+debian@jameswestby.net>
#                  2008 Jelmer Vernooij <jelmer@samba.org>
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


TAG_PREFIX = "upstream-"


def upstream_branch_version(revhistory, reverse_tag_dict, package, 
                            previous_version, add_rev):
  """Determine the version string of an upstream branch.

  The upstream version is determined from the most recent tag
  in the upstream branch. If that tag does not point at the last revision, 
  the revision number is added to it (<version>+bzr<revno>).

  If there are no tags set on the upstream branch, the previous Debian 
  version is used and combined with the bzr revision number 
  (usually <version>+bzr<revno>).
  
  :param revhistory: Branch revision history.
  :param reverse_tag_dict: Reverse tag dictionary (revid -> list of tags)
  :param package: Name of package.
  :param previous_version: Previous upstream version in debian changelog.
  :param add_rev: Function that can add a revision suffix to a version string.
  :return: Name of the upstream revision.
  """
  # Parse previous_version
  # if it contains ~bzr:
  if "~bzr" in previous_version or "+bzr" in previous_version:
    # check if new tags appeared since previous_version's revision
    # if they didn't, update revno in ~bzr<revno>
    bzr_revno = int(previous_version[previous_version.find("bzr")+3:])
  else:
    bzr_revno = 0

  for r in reversed(revhistory[bzr_revno:]):
    if r in reverse_tag_dict:
      # If there is a newer version tagged in branch, 
      # convert to upstream version 
      # return <upstream_version>+bzr<revno>
      for tag in reverse_tag_dict[r]:
        upstream_version = upstream_tag_to_version(tag, 
                                                   package=package)
        if upstream_version is not None:
          if r != revhistory[-1]:
            upstream_version.upstream_version = add_rev(upstream_version.upstream_version, 
                                                                         revhistory[-1])
          return upstream_version

  return Version(add_rev(previous_version, revhistory[-1]))


def upstream_version_add_revision(upstream_branch, version_string, revid):
  """Update the revision in a upstream version string.

  :param branch: Branch in which the revision can be found
  :param version_string: Original version string
  :param revid: Revision id of the revision
  """
  revno = upstream_branch.revision_id_to_revno(revid)
  
  if "+bzr" in version_string:
    return "%s+bzr%d" % (version_string[:version_string.rfind("+bzr")], revno)

  if "~bzr" in version_string:
    return "%s~bzr%d" % (version_string[:version_string.rfind("~bzr")], revno)

  rev = upstream_branch.repository.get_revision(revid)
  svn_revmeta = getattr(rev, "svn_meta", None)
  if svn_revmeta is not None:
    svn_revno = svn_revmeta.revnum

    if "+svn" in version_string:
      return "%s+svn%d" % (version_string[:version_string.rfind("+svn")], svn_revno)
    if "~svn" in version_string:
      return "%s~svn%d" % (version_string[:version_string.rfind("~svn")], svn_revno)
    return "%s+svn%d" % (version_string, svn_revno)

  return "%s+bzr%d" % (version_string, revno)


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
    cl_id = tree.path2id('debian/changelog')
    if cl_id is None:
     raise AddChangelogError('debian/changelog')
    cl = Changelog(tree.get_file_text(cl_id))
    previous_version = cl.upstream_version
    revhistory = upstream_branch.revision_history()
    version = upstream_branch_version(revhistory,
                upstream_branch.tags.get_reverse_tag_dict(), package,
                previous_version, 
                lambda version, revision: upstream_version_add_revision(upstream_branch, version, revision))
  tree.merge_from_branch(upstream_branch)
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
    return Version(tag_name)

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
   cl = Changelog()
   cl.parse_changelog(tree.get_file_text(cl_id), max_blocks=1)
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
