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

from __future__ import absolute_import

import os
import subprocess

from debian.changelog import Version

from .errors import (
    DchError,
    )
from .import_dsc import (
    DistributionBranch,
    DistributionBranchSet,
    PreviousVersionTagMissing,
    )
from .repack_tarball import repack_tarball
from .util import (
    component_from_orig_tarball,
    tarball_name,
    FORMAT_3_0_QUILT,
    FORMAT_3_0_NATIVE,
    tree_get_source_format,
    )


TAG_PREFIX = "upstream-"


def package_version(upstream_version, distribution_name, epoch=None):
    """Determine the package version for a new upstream.

    :param upstream_version: Upstream version string
    :param distribution_name: Distribution the package is for
    :param epoch: Optional epoch
    """
    if distribution_name == "ubuntu":
        ret = Version("%s-0ubuntu1" % upstream_version)
    else:
        ret = Version("%s-1" % upstream_version)
    ret.epoch = epoch
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
    """
    entry_description = upstream_merge_changelog_line(upstream_version)
    if changelog is None:
        epoch = None
    else:
        epoch = changelog.epoch
    argv = ["dch", "-v",
            str(package_version(upstream_version, distribution_name, epoch)),
            "-D", "UNRELEASED", "--release-heuristic", "changelog",
            "--package", package, entry_description]
    create = (not tree.has_filename("debian/changelog"))
    if create:
        argv.append("--create")
    proc = subprocess.Popen(argv, cwd=tree.basedir, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    (stdout, stderr) = proc.communicate()
    if proc.returncode != 0:
        raise DchError("Adding changelog entry failed: %s" % stderr)
    if create:
        tree.add(["debian/changelog"])


def do_merge(tree, tarball_filenames, package, version,
        current_version, upstream_branch, upstream_revisions, merge_type,
        force):
    db = DistributionBranch(tree.branch, tree.branch, tree=tree)
    dbs = DistributionBranchSet()
    dbs.add_branch(db)
    tarballs = [(p, component_from_orig_tarball(p, package, version)) for p
            in tarball_filenames]
    conflicts = db.merge_upstream(tarballs, package, version,
            current_version, upstream_branch=upstream_branch,
            upstream_revisions=upstream_revisions,
            merge_type=merge_type, force=force)
    return conflicts


def fetch_tarball(package, version, orig_dir, locations, v3):
    ret = []
    format = None
    for location in locations:
        if v3:
            if location.endswith(".tar.bz2") or location.endswith(".tbz2"):
                format = "bz2"
            elif location.endswith(".tar.xz"):
                format = "xz"
        dest_name = tarball_name(package, version, None, format=format)
        tarball_filename = os.path.join(orig_dir, dest_name)
        repack_tarball(location, dest_name, target_dir=orig_dir)
        ret.append(tarball_filename)
    return ret


def get_tarballs(orig_dir, tree, package, version, upstream_branch,
        upstream_revision, locations):
    source_format = tree_get_source_format(tree)
    v3 = (source_format in [FORMAT_3_0_QUILT, FORMAT_3_0_NATIVE])
    orig_dir = os.path.join(tree.basedir, orig_dir)
    if not os.path.exists(orig_dir):
        os.makedirs(orig_dir)
    return fetch_tarball(package, version, orig_dir, locations, v3)
