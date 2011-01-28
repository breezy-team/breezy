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

import subprocess

try:
    from debian.changelog import Version
except ImportError:
    # Prior to 0.1.15 the debian module was called debian_bundle
    from debian_bundle.changelog import Version

TAG_PREFIX = "upstream-"


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
