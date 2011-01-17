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

import itertools
import subprocess

try:
    from debian.changelog import Version
except ImportError:
    # Prior to 0.1.15 the debian module was called debian_bundle
    from debian_bundle.changelog import Version

from bzrlib.errors import InvalidRevisionId
from bzrlib.revisionspec import RevisionSpec

from bzrlib.plugins.builddeb.util import get_snapshot_revision


TAG_PREFIX = "upstream-"


def extract_svn_revno(rev):
    """Extract the Subversion number of a revision from a revision.

    :param rev: Revision object
    :return: Revision number, None if this was not a Subversion revision or
         if the revision number could not be determined (bzr-svn not available).
    """
    try:
        from bzrlib.plugins.svn import extract_svn_foreign_revid
    except ImportError:
        # No svn support
        return None
    else:
        try:
            (svn_uuid, branch_path, svn_revno) = extract_svn_foreign_revid(rev)
        except InvalidRevisionId:
            return None
        else:
            return svn_revno


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
    svn_revno = extract_svn_revno(rev)

    # FIXME: Raise error if +svn/~svn is present and svn_revno is not set?
    if "+svn" in version_string and svn_revno:
        return "%s+svn%d" % (version_string[:version_string.rfind("+svn")], svn_revno)
    if "~svn" in version_string and svn_revno:
        return "%s~svn%d" % (version_string[:version_string.rfind("~svn")], svn_revno)

    if svn_revno:
        return "%s+svn%d" % (version_string, svn_revno)
    else:
        return "%s+bzr%d" % (version_string, revno)


def _upstream_branch_version(revhistory, reverse_tag_dict, package, 
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
    if revhistory == []:
        # No new version to merge
        return Version(previous_version)
    for r in reversed(revhistory):
        if r in reverse_tag_dict:
            # If there is a newer version tagged in branch, 
            # convert to upstream version 
            # return <upstream_version>+bzr<revno>
            for tag in reverse_tag_dict[r]:
                upstream_version = upstream_tag_to_version(tag,
                                                   package=package)
                if upstream_version is not None:
                    if r != revhistory[-1]:
                        upstream_version.upstream_version = add_rev(
                          upstream_version.upstream_version, revhistory[-1])
                    return upstream_version
    return Version(add_rev(previous_version, revhistory[-1]))


def upstream_branch_version(upstream_branch, upstream_revision, package,
        previous_version):
    """Determine the version string for a revision in an upstream branch.

    :param upstream_branch: The upstream branch object
    :param upstream_revision: The revision id of the upstream revision
    :param package: The name of the package
    :param previous_version: The previous upstream version string
    :return: Upstream version string for `upstream_revision`.
    """
    dotted_revno = upstream_branch.revision_id_to_dotted_revno(upstream_revision)
    if len(dotted_revno) > 1:
        revno = -2
    else:
        revno = dotted_revno[0]
    revhistory = upstream_branch.revision_history()
    previous_revision = get_snapshot_revision(previous_version)
    if previous_revision is not None:
        previous_revspec = RevisionSpec.from_string(previous_revision)
        previous_revno, _ = previous_revspec.in_history(upstream_branch)
        # Trim revision history - we don't care about any revisions
        # before the revision of the previous version
    else:
        previous_revno = 0
    revhistory = revhistory[previous_revno:revno+1]
    return _upstream_branch_version(revhistory,
            upstream_branch.tags.get_reverse_tag_dict(), package,
            previous_version,
            lambda version, revision: upstream_version_add_revision(upstream_branch, version, revision))


def upstream_tag_to_version(tag_name, package=None):
    """Take a tag name and return the upstream version, or None."""
    if tag_name.startswith(TAG_PREFIX):
        return Version(tag_name[len(TAG_PREFIX):])
    if (package is not None and (
          tag_name.startswith("%s-" % package) or
          tag_name.startswith("%s_" % package))):
        return Version(tag_name[len(package)+1:])
    if tag_name.startswith("release-"):
        return Version(tag_name[len("release-"):])
    if tag_name[0] == "v" and tag_name[1].isdigit():
        return Version(tag_name[1:])
    if all([c.isdigit() or c in (".", "~") for c in tag_name]):
        return Version(tag_name)
    return None


def package_version(upstream_version, distribution_name):
    """Determine the package version for a new upstream.

    :param upstream_version: Upstream version string
    :param distribution_name: Distribution the package is for
    """
    assert isinstance(upstream_version, str), \
        "upstream_version should be a str, not %s" % str(
                type(upstream_version))
    if distribution_name == "ubuntu":
        ret = Version("%s-0ubuntu1" % upstream_version)
    else:
        ret = Version("%s-1" % upstream_version)
    return ret


def upstream_merge_changelog_line(upstream_version):
    """Describe that a new upstream revision was merged.

    This will either describe that a new upstream release or a new upstream snapshot
    was merged.

    :param upstream_version: Upstream version string
    :return: Line string for use in changelog
    """
    vcs_suffixes = ["~bzr", "+bzr", "~svn", "+svn", "~git", "+git"]
    for vcs_suffix in vcs_suffixes:
        if vcs_suffix in str(upstream_version):
            entry_description = "New upstream snapshot."
            break
    else:
        entry_description = "New upstream release."
    return entry_description


def changelog_add_new_version(tree, upstream_version, distribution_name,
        changelog, package):
    """Add an entry to the changelog for a new version.

    :param tree: WorkingTree in which the package lives
    :param upstream_version: Upstream version to add
    :param distribution_name: Distribution name (debian, ubuntu, ...)
    :param changelog: Changelog object
    :param package: Package name
    :return: Whether an entry was successfully added
    """
    assert isinstance(upstream_version, str), \
         "upstream_version should be a str, not %s" % str(
                 type(upstream_version))
    entry_description = upstream_merge_changelog_line(upstream_version)
    proc = subprocess.Popen(["dch", "-v",
            str(package_version(upstream_version, distribution_name)),
            "-D", "UNRELEASED", "--release-heuristic", "changelog", entry_description],
            cwd=tree.basedir)
    proc.wait()
    # FIXME: Raise insightful exception here rather than just checking
    # return code.
    return proc.returncode == 0
