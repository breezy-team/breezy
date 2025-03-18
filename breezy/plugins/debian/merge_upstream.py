#    merge_upstream.py -- Merge new upstream versions of packages.
#    Copyright (C) 2007 Reinhard Tartler <siretart@tauware.de>
#                  2007 James Westby <jw+debian@jameswestby.net>
#                  2008-2019 Jelmer Vernooij <jelmer@samba.org>
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

import os
import tempfile

from debmutate.changelog import ChangelogEditor, upstream_merge_changelog_line
from debmutate.versions import new_package_version

from ... import osutils
from ...revision import NULL_REVISION
from ...trace import note
from .import_dsc import (
    DistributionBranch,
    DistributionBranchSet,
    UpstreamAlreadyImported,
)
from .repack_tarball import repack_tarball
from .util import (
    FORMAT_3_0_NATIVE,
    FORMAT_3_0_QUILT,
    component_from_orig_tarball,
    tarball_name,
    tree_get_source_format,
)

TAG_PREFIX = "upstream-"


# TODO(jelmer): Move into debmutate
def changelog_add_new_version(
    tree, subpath, upstream_version: str, distribution_name, changelog, package
):
    """Add an entry to the changelog for a new version.

    :param tree: WorkingTree in which the package lives
    :param upstream_version: Upstream version to add
    :param distribution_name: Distribution name (debian, ubuntu, ...)
    :param changelog: Changelog object
    :param package: Package name
    """
    if changelog is None:
        epoch = None
    else:
        epoch = changelog.epoch
    if not tree.has_filename(osutils.pathjoin(subpath, "debian")):
        tree.mkdir(osutils.pathjoin(subpath, "debian"))
    cl_path = osutils.pathjoin(subpath, "debian/changelog")
    create = not tree.has_filename(cl_path)
    if create:
        cl = ChangelogEditor.create(tree.abspath(cl_path))
    else:
        cl = ChangelogEditor(tree.abspath(cl_path))
    with cl:
        cl.auto_version(
            version=new_package_version(upstream_version, distribution_name, epoch),
            package=package,
        )
        cl.add_entry([upstream_merge_changelog_line(upstream_version)])
    if not tree.is_versioned(cl_path):
        tree.add([cl_path])


def do_import(
    tree,
    subpath,
    tarball_filenames,
    package,
    version,
    current_version,
    upstream_branch,
    upstream_revisions,
    merge_type=None,
    force=False,
    force_pristine_tar=False,
    committer=None,
    files_excluded=None,
):
    """Import new tarballs.

    Args:
      tree: Working tree to operate in
      tarball_filenames: List of tarball filenames as tuples with (path,
        component)
      package: Package name
      version: New upstream version to merge
      current_version: Current upstream version in tree
      upstream_branch: Optional upstream branch to merge from
      upstream_revisions: Dictionary mapping versions to upstream revisions
      merge_type: Merge type
      committer: Committer string to use
      files_excluded: Files to exclude
    Returns:
      list with (component, tag, revid, pristine_tar_imported, subpath)
      tuples
    """
    db = DistributionBranch(tree.branch, tree.branch, tree=tree)
    dbs = DistributionBranchSet()
    dbs.add_branch(db)
    tarballs = [
        (p, component_from_orig_tarball(p, package, version), None)
        for p in tarball_filenames
    ]

    with tempfile.TemporaryDirectory(
        dir=os.path.join(db.tree.basedir, "..")
    ) as tempdir:
        if current_version is not None:
            db._export_previous_upstream_tree(package, current_version, tempdir)
        else:
            db.create_empty_upstream_tree(tempdir)
        if db.pristine_upstream_source.has_version(package, version, try_hard=False):
            raise UpstreamAlreadyImported(version, tag)

        parents = {None: []}
        if db.pristine_upstream_branch.last_revision() != NULL_REVISION:
            parents = {None: [db.pristine_upstream_branch.last_revision()]}

        return db.import_upstream_tarballs(
            tarballs,
            package,
            version,
            parents,
            upstream_branch=upstream_branch,
            upstream_revisions=upstream_revisions,
            force_pristine_tar=force_pristine_tar,
            committer=committer,
            files_excluded=files_excluded,
        )


def do_merge(
    tree,
    tarball_filenames,
    package,
    version,
    current_version,
    upstream_branch,
    upstream_revisions,
    merge_type=None,
    force=False,
    force_pristine_tar=False,
    committer=None,
    files_excluded=None,
):
    """Actually execute a merge.

    Args:
      tree: Working tree to operate in
      tarball_filenames: List of tarball filenames as tuples with (path,
        component)
      package: Package name
      version: New upstream version to merge
      current_version: Current upstream version in tree
      upstream_branch: Optional upstream branch to merge from
      upstream_revisions: Dictionary mapping versions to upstream revisions
      merge_type: Merge type
      committer: Committer string to use
      files_excluded: Files to exclude
    """
    db = DistributionBranch(tree.branch, tree.branch, tree=tree)
    dbs = DistributionBranchSet()
    dbs.add_branch(db)
    tarballs = [
        (p, component_from_orig_tarball(p, package, version)) for p in tarball_filenames
    ]
    return db.merge_upstream(
        tarballs,
        package,
        version,
        current_version,
        upstream_branch=upstream_branch,
        upstream_revisions=upstream_revisions,
        merge_type=merge_type,
        force=force,
        force_pristine_tar=force_pristine_tar,
        committer=committer,
        files_excluded=files_excluded,
    )


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


def get_tarballs(orig_dir, tree, package, version, locations):
    """Retrieve upstream tarballs."""
    source_format = tree_get_source_format(tree)
    v3 = source_format in [FORMAT_3_0_QUILT, FORMAT_3_0_NATIVE]
    orig_dir = os.path.join(tree.basedir, orig_dir)
    if not os.path.exists(orig_dir):
        os.makedirs(orig_dir)
    return fetch_tarball(package, version, orig_dir, locations, v3)


def get_upstream_branch_location(tree, subpath, config, trust_package=False):
    from lintian_brush.vcs import sanitize_url as sanitize_vcs_url

    if config.upstream_branch is not None:
        note("Using upstream branch %s (from configuration)", config.upstream_branch)
        # TODO(jelmer): Make brz-debian sanitize the URL?
        upstream_branch_location = sanitize_vcs_url(config.upstream_branch)
        upstream_branch_browse = getattr(config, "upstream_branch_browse", None)
    else:
        from upstream_ontologist.guess import guess_upstream_metadata

        guessed_upstream_metadata = guess_upstream_metadata(
            tree.abspath(subpath),
            trust_package=trust_package,
            net_access=True,
            consult_external_directory=False,
        )
        upstream_branch_location = guessed_upstream_metadata.get("Repository")
        upstream_branch_browse = guessed_upstream_metadata.get("Repository-Browse")
        if upstream_branch_location:
            note("Using upstream branch %s (guessed)", upstream_branch_location)
    if upstream_branch_browse is None and upstream_branch_location is not None:
        try:
            from lintian_brush.vcs import determine_browser_url
        except ImportError:
            pass
        else:
            upstream_branch_browse = determine_browser_url(
                None, upstream_branch_location
            )
    return (upstream_branch_location, upstream_branch_browse)


def get_existing_imported_upstream_revids(
    upstream_source, package, new_upstream_version
):
    imported_revids = []
    for component, (revid, subpath) in upstream_source.version_as_revisions(
        package, new_upstream_version
    ).items():
        upstream_tag = upstream_source.tag_name(new_upstream_version, component)
        imported_revids.append((component, upstream_tag, revid, None, subpath))
    return imported_revids
