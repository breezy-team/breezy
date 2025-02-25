#!/usr/bin/python3
# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import contextlib
import errno
import json
import logging
import os
import subprocess
import tempfile
from hashlib import sha1
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from debian.changelog import Changelog, Version
from debmutate.changelog import ChangelogEditor, distribution_is_unreleased
from debmutate.control import ControlEditor

import breezy.bzr
import breezy.git  # noqa: F401
from breezy import urlutils
from breezy.errors import (
    ConflictsInTree,
    NoSuchRevisionInTree,
    NoSuchTag,
    NotBranchError,
)
from breezy.revision import NULL_REVISION, RevisionID
from breezy.trace import note, warning
from breezy.transform import MalformedTransform
from breezy.transport import NoSuchFile
from breezy.workingtree import WorkingTree

from .apt_repo import (
    Apt,
    AptSourceError,
    LocalApt,
    NoAptSources,
    RemoteApt,
)
from .changelog import debcommit
from .directory import vcs_git_url_to_bzr_url
from .import_dsc import (
    DistributionBranch,
    DistributionBranchSet,
    VersionAlreadyImported,
)
from .info import versions_dict
from .upstream import PackageVersionNotPresent

BRANCH_NAME = "missing-commits"


def connect_udd_mirror():
    import psycopg2

    return psycopg2.connect(
        database="udd",
        user="udd-mirror",
        password="udd-mirror",
        host="udd-mirror.debian.net",
    )


def select_vcswatch_packages():
    conn = connect_udd_mirror()
    cursor = conn.cursor()
    args = []
    query = """\
    SELECT sources.source, vcswatch.url
    FROM vcswatch JOIN sources ON sources.source = vcswatch.source
    WHERE
     vcswatch.status IN ('OLD', 'UNREL') AND
     sources.release = 'sid'
"""
    cursor.execute(query, tuple(args))
    packages = []
    for package, _vcs_url in cursor.fetchall():
        packages.append(package)
    return packages


class SnapshotDownloadError(Exception):
    def __init__(self, url, inner, transient):
        self.url = url
        self.inner = inner
        self.transient = transient


class SnapshotMissing(Exception):
    def __init__(self, source_name, source_version):
        self.source_name = source_name
        self.source_version = source_version


class SnapshotHashMismatch(Exception):
    def __init__(self, filename, actual_hash, expected_hash):
        self.filename = filename
        self.actual_hash = actual_hash
        self.expected_hash = expected_hash


def download_snapshot(package: str, version: Version, output_dir: str) -> str:
    note("Downloading %s %s", package, version)
    srcfiles_url = (
        f"https://snapshot.debian.org/mr/package/{package}/{version}/"
        "srcfiles?fileinfo=1"
    )
    files = {}
    try:
        srcfiles = json.load(urlopen(srcfiles_url))  # noqa: S310
    except HTTPError as e:
        if e.status == 404:
            raise SnapshotMissing(package, version) from e
        assert e.status is not None  # noqa: S101
        if e.status // 100 == 5:
            transient = True
        else:
            transient = None
        raise SnapshotDownloadError(srcfiles_url, e, transient=transient) from e
    except URLError as e:
        if e.errno == errno.ENETUNREACH:
            transient = True
        else:
            transient = None
        raise SnapshotDownloadError(srcfiles_url, e, transient=transient) from e

    for hsh, entries in srcfiles["fileinfo"].items():
        for entry in entries:
            files[entry["name"]] = hsh
    for filename, hsh in files.items():
        local_path = os.path.join(output_dir, os.path.basename(filename))
        try:
            with open(local_path, "rb") as f:
                actual_hsh = sha1(f.read()).hexdigest()  # noqa: S324
            if actual_hsh != hsh:
                raise SnapshotHashMismatch(filename, actual_hsh, hsh)
        except FileNotFoundError:
            with open(local_path, "wb") as f:
                url = "https://snapshot.debian.org/file/{}".format(hsh)
                note(".. Downloading %s -> %s", url, filename)
                try:
                    with urlopen(url) as g:  # noqa: S310
                        f.write(g.read())
                except HTTPError as e:
                    assert e.status is not None  # noqa: S101
                    if e.status // 100 == 5:
                        transient = True
                    else:
                        transient = None
                    raise SnapshotDownloadError(url, e, transient=transient) from e
                except URLError as e:
                    if e.errno == errno.ENETUNREACH:
                        transient = True
                    else:
                        transient = None
                    raise SnapshotDownloadError(url, e, transient=None) from e
    file_version = Version(version)
    file_version.epoch = None
    dsc_filename = f"{package}_{file_version}.dsc"
    return os.path.join(output_dir, dsc_filename)


class NoopChangesOnly(Exception):
    def __init__(self, vcs_version, archive_version):
        self.vcs_version = vcs_version
        self.archive_version = archive_version
        super().__init__(
            "No missing versions with effective changes. "
            f"Archive has {archive_version}, VCS has {vcs_version}"
        )


class NoMissingVersions(Exception):
    def __init__(self, vcs_version, archive_version):
        self.vcs_version = vcs_version
        self.archive_version = archive_version
        super().__init__(
            f"No missing versions after all. Archive has {archive_version}, VCS has {vcs_version}"
        )


class TreeVersionNotInArchiveChangelog(Exception):
    def __init__(self, tree_version):
        self.tree_version = tree_version
        super().__init__(
            "tree version {} does not appear in archive changelog".format(tree_version)
        )


class TreeVersionWithoutTag(Exception):
    def __init__(self, tree_version, tag_name):
        self.tree_version = tree_version
        super().__init__(
            "unable to find revision for version {}; no tags (e.g. {})".format(
                tree_version, tag_name
            )
        )


class TreeUpstreamVersionMissing(Exception):
    def __init__(self, upstream_version):
        self.upstream_version = upstream_version
        super().__init__("unable to find upstream version {!r}".format(upstream_version))


class UnreleasedChangesSinceTreeVersion(Exception):
    def __init__(self, tree_version):
        super().__init__("there are unreleased changes since {}".format(tree_version))


def find_missing_versions(
    archive_cl: Changelog, tree_version: Version
) -> list[Version]:
    missing_versions: list[Version] = []
    for block in archive_cl:
        if tree_version is not None and block.version == tree_version:
            break
        missing_versions.append(block.version)
    else:
        if tree_version is not None:
            raise TreeVersionNotInArchiveChangelog(tree_version)
    return missing_versions


def is_noop_upload(tree, basis_tree=None, subpath=""):
    if basis_tree is None:
        basis_tree = tree.basis_tree()
    changes = tree.iter_changes(basis_tree)
    try:
        while True:
            change = next(changes)
            if change.path[1] != "":
                break
    except StopIteration:
        return True
    cl_path = os.path.join(subpath, "debian", "changelog")
    if change.path != (cl_path, cl_path):
        return False
    # if there are any other changes, then this is not trivial:
    try:
        next(changes)
    except StopIteration:
        pass
    else:
        return False
    try:
        new_cl = Changelog(tree.get_file_text(cl_path))
    except NoSuchFile:
        return False
    try:
        old_cl = Changelog(basis_tree.get_file_text(cl_path))
    except NoSuchFile:
        return False

    del new_cl._blocks[0]
    # TODO(jelmer): Check for uploads that aren't just meant to trigger a
    # build.  i.e. closing bugs.
    return str(new_cl) == str(old_cl)


def import_uncommitted(
    tree: WorkingTree,
    subpath: str,
    apt: Apt,
    source_name: str,
    archive_version: Optional[Version] = None,
    tree_version: Optional[Version] = None,
    merge_unreleased: bool = True,
    skip_noop: bool = True,
) -> list[tuple[str, Version, RevisionID]]:
    with contextlib.ExitStack() as es:
        es.enter_context(apt)
        archive_source = es.enter_context(tempfile.TemporaryDirectory())
        apt.retrieve_source(source_name, archive_source, source_version=archive_version)
        [dsc] = [e.name for e in os.scandir(archive_source) if e.name.endswith(".dsc")]
        note("Unpacking source %s", dsc)
        subprocess.check_output(["dpkg-source", "-x", dsc], cwd=archive_source)  # noqa: S607
        [subdir] = [e.path for e in os.scandir(archive_source) if e.is_dir()]
        with open(os.path.join(subdir, "debian", "changelog")) as f:
            archive_cl = Changelog(f)
        assert tree_version is not None  # noqa: S101
        missing_versions = find_missing_versions(archive_cl, tree_version)
        if len(missing_versions) == 0:
            raise NoMissingVersions(tree_version, archive_cl.version)
        note("Missing versions: %s", ", ".join(map(str, missing_versions)))

        ret = []
        dbs = DistributionBranchSet()
        db = DistributionBranch(tree.branch, tree.branch, tree=tree)
        dbs.add_branch(db)

        if tree_version is not None:
            try:
                tree_version_revid = db.revid_of_version(tree_version)
            except NoSuchTag as e:
                raise TreeVersionWithoutTag(tree_version, e.tag_name) from e
            if tree_version_revid != tree.last_revision():
                # There are changes since the last tree version.
                note("Commits exist on the branch since last upload to archive")
                if not merge_unreleased:
                    raise UnreleasedChangesSinceTreeVersion(tree_version)

                merge_into = tree.last_revision()
                tree.update(revision=tree_version_revid)
            else:
                merge_into = None
        else:
            merge_into = None

        applied_patches = tree.has_filename(".pc/applied-patches")
        if tree_version and tree_version.debian_revision:
            try:
                upstream_tips = db.pristine_upstream_source.version_as_revisions(
                    source_name, tree_version.upstream_version
                )
            except PackageVersionNotPresent as e:
                raise TreeUpstreamVersionMissing(tree_version.upstream_version) from e
            else:
                note("Extracting upstream version %s.", tree_version.upstream_version)
                upstream_dir = es.enter_context(tempfile.TemporaryDirectory())
                db.extract_upstream_tree(upstream_tips, upstream_dir)
        else:
            upstream_dir = es.enter_context(tempfile.TemporaryDirectory())
            db.create_empty_upstream_tree(upstream_dir)
        output_dir = es.enter_context(tempfile.TemporaryDirectory())
        last_revid = db.tree.last_revision()
        for version in reversed(missing_versions):
            try:
                dsc_path = download_snapshot(source_name, version, output_dir)
            except SnapshotMissing as e:
                warning(
                    "Missing snapshot for %s (never uploaded?), skipping.",
                    e.source_version,
                )
                continue
            note("Importing %s", version)
            try:
                tag_name = db.import_package(dsc_path, apply_patches=applied_patches)
            except VersionAlreadyImported as e:
                # Present in the repository, just not on the branch
                note(
                    "%s was already imported (tag: %s), just not on the "
                    "branch. Updating tree.",
                    e.version,  # type: ignore
                    e.tag_name,  # type: ignore
                )
                tag_name = e.tag_name  # type: ignore
                db.tree.update(revision=db.branch.tags.lookup_tag(e.tag_name))  # type: ignore
            revid = db.branch.tags.lookup_tag(tag_name)
            if skip_noop and last_revid != NULL_REVISION:
                try:
                    last_tree = db.tree.revision_tree(last_revid)
                except NoSuchRevisionInTree:
                    last_tree = db.branch.repository.revision_tree(last_revid)
                if is_noop_upload(tree, last_tree, subpath):
                    note("Skipping version %s without effective changes", version)
                    tree.update(revision=last_revid)
                    continue
            ret.append((tag_name, version, revid))
            last_revid = revid

    if not ret:
        raise NoopChangesOnly(tree_version, archive_cl.version)

    if merge_into:
        to_merge = tree.last_revision()
        tree.update(revision=merge_into)
        tree.merge_from_branch(tree.branch, to_revision=to_merge)
        revid = debcommit(
            tree,
            subpath=subpath,
            message="Merge archive versions: {}".format(", ".join([str(v) for (t, v, r) in ret])),
        )
        parent_ids = tree.branch.repository.get_revision(revid).parent_ids
        if parent_ids != [merge_into, to_merge]:
            raise AssertionError(
                f"Expected parents to be {[merge_into, to_merge]!r}, was {parent_ids!r}"
            )
    return ret


def report_fatal(code, description, *, hint=None, transient=None):
    if os.environ.get("SVP_API") == "1":
        with open(os.environ["SVP_RESULT"], "w") as f:
            json.dump(
                {
                    "versions": versions_dict(),
                    "transient": transient,
                    "result_code": code,
                    "description": description,
                },
                f,
            )
    logging.fatal("%s", description)
    if hint:
        logging.info("%s", hint)


def set_vcs_git_url(
    control, vcs_git_base: Optional[str], vcs_browser_base: Optional[str]
):
    old_vcs_url = control.source.get("Vcs-Git")
    if vcs_git_base is not None:
        control.source["Vcs-Git"] = urlutils.join(
            vcs_git_base, "{}.git".format(control.source["Source"])
        )
    new_vcs_url = control.source.get("Vcs-Git")
    if vcs_browser_base:
        control.source["Vcs-Browser"] = urlutils.join(
            vcs_browser_base, control.source["Source"]
        )
    return (old_vcs_url, new_vcs_url)


def contains_git_attributes(tree, subpath):
    for path, _versioned, _kind, _ie in tree.list_files(
        recursive=True, recurse_nested=True, from_dir=subpath
    ):
        if os.path.basename(path) == ".gitattributes":
            return True
    return False


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apt-repository",
        type=str,
        help="APT repository to use. Defaults to locally configured.",
        default=(os.environ.get("APT_REPOSITORY") or os.environ.get("REPOSITORIES")),
    )
    parser.add_argument(
        "--apt-repository-key",
        type=str,
        help=(
            "APT repository key to use for validation, " "if --apt-repository is set."
        ),
        default=os.environ.get("APT_REPOSITORY_KEY"),
    )
    parser.add_argument("--version", type=str, help="Source version to import")
    parser.add_argument("--vcs-git-base", type=str, help="Set Vcs-Git URL")
    parser.add_argument("--vcs-browser-base", type=str, help="Set Vcs-Browser URL")
    parser.add_argument(
        "--no-merge-unreleased",
        action="store_true",
        help=("Error rather than merge when there are " "unreleased changes"),
    )
    parser.add_argument(
        "--no-skip-noop",
        action="store_true",
        help="Do not skip uploads without effective changes",
    )
    parser.add_argument(
        "--package",
        type=str,
        help="Package to import",
        default=os.environ.get("PACKAGE"),
    )
    parser.add_argument(
        "--force-git-attributes",
        action="store_true",
        help="Force importing even if the tree contains git attributes",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.apt_repository:
        apt = RemoteApt.from_string(args.apt_repository, args.apt_repository_key)
    else:
        apt = LocalApt()
    try:
        local_tree, subpath = WorkingTree.open_containing(".")
    except NotBranchError:
        report_fatal(
            "not-branch-error", "Not running in a version-controlled directory"
        )
        return 1

    cl_path = os.path.join(subpath, "debian/changelog")
    try:
        with local_tree.get_file(cl_path) as f:
            tree_cl = Changelog(f)
            source_name = tree_cl.package
            for block in tree_cl:
                if distribution_is_unreleased(block.distributions):
                    continue
                tree_version = block.version
                break
            else:
                tree_version = None
    except NoSuchFile as e:
        if local_tree.last_revision() == NULL_REVISION and args.package:
            source_name = args.package
            tree_version = None
            tree_cl = None
        else:
            if local_tree.last_revision() == NULL_REVISION:
                hint = "Tree is empty. Specify --package?"
            else:
                hint = None
            report_fatal(
                "missing-changelog", "Missing changelog: {}".format(e.path), hint=hint
            )
            return 1
    else:
        if args.package and tree_cl.package != args.package:
            report_fatal(
                "inconsistent-package",
                "Inconsistent package name: {} specified, {} found".format(
                    args.package, tree_cl.package
                ),
            )
            return 1

    if not args.force_git_attributes and hasattr(local_tree.branch.repository, "_git"):
        # See https://salsa.debian.org/jelmer/janitor.debian.net/-/issues/74
        if contains_git_attributes(local_tree, subpath):
            report_fatal(
                "unsupported-git-attributes",
                "Tree contains .gitattributes which may impact imports and "
                "are unsupported",
                hint="Run with --force-git-attributes to ignore",
            )
            return 1

    try:
        ret = import_uncommitted(
            local_tree,
            subpath,
            apt,
            source_name=source_name,
            archive_version=Version(args.version) if args.version else None,
            tree_version=tree_version,
            merge_unreleased=not args.no_merge_unreleased,
            skip_noop=not args.no_skip_noop,
        )
    except AptSourceError as e:
        if isinstance(e.reason, list):
            reason = e.reason[-1]
        else:
            reason = e.reason
        report_fatal("apt-source-error", reason)
        return 1
    except NoAptSources:
        report_fatal("no-apt-sources", "No sources configured in /etc/apt/sources.list")
        return 1
    except TreeVersionWithoutTag as e:
        report_fatal("tree-version-not-found", str(e))
        return 1
    except TreeUpstreamVersionMissing as e:
        report_fatal("tree-upstream-version-missing", str(e))
        return 1
    except UnreleasedChangesSinceTreeVersion as e:
        report_fatal("unreleased-changes", str(e))
        return 1
    except TreeVersionNotInArchiveChangelog as e:
        report_fatal("tree-version-not-in-archive-changelog", str(e))
        return 1
    except NoopChangesOnly as e:
        report_fatal(
            "nothing-to-do",
            str(e),
            hint="Run with --no-skip-noop to include trivial uploads.",
        )
        return 1
    except NoMissingVersions as e:
        report_fatal("nothing-to-do", str(e))
        return 1
    except SnapshotDownloadError as e:
        report_fatal(
            "snapshot-download-failed",
            f"Downloading {e.url} failed: {e.inner}",
            transient=e.transient,
        )
        return 1
    except SnapshotHashMismatch as e:
        report_fatal(
            "snapshot-hash-mismatch",
            "Snapshot hash mismatch for {}: {} != {}".format(
                e.filename, e.expected_hash, e.actual_hash
            ),
        )
        return 1
    except MalformedTransform as e:
        report_fatal("malformed-transform", str(e))
        return 1
    except ConflictsInTree:
        report_fatal(
            "merge-conflicts",
            "Merging uncommitted changes resulted in conflicts.",
            transient=False,
        )
        return 1

    if args.vcs_git_base:
        with ControlEditor(local_tree.abspath("debian/control")) as control:
            (old_vcs_url, new_vcs_url) = set_vcs_git_url(
                control, args.vcs_git_base, args.vcs_browser_base
            )
        if old_vcs_url != new_vcs_url:
            note("Updating Vcs-Git URL to %s", new_vcs_url)
            with ChangelogEditor(local_tree.abspath("debian/changelog")) as changelog:
                changelog.add_entry(["Set Vcs-Git header."])
            debcommit(local_tree, subpath=subpath)
            target_branch_url = vcs_git_url_to_bzr_url(new_vcs_url)
        else:
            target_branch_url = None
    else:
        target_branch_url = None

    if os.environ.get("SVP_API") == "1":
        if len(ret) == 1:
            commit_message = "Import missing upload: {}".format(ret[0][1])
            description = "Import uploaded version: {}".format(ret[0][1])
        else:
            commit_message = "Import missing uploads: {}.".format(", ".join([str(v) for t, v, rs in ret]))
            description = "Import uploaded versions: %r" % (
                [str(v) for t, v, rs in ret]
            )
        with open(os.environ["SVP_RESULT"], "w") as f:
            json.dump(
                {
                    "description": description,
                    "versions": versions_dict(),
                    "value": 60 + sum([60 if "nmu" in str(e[1]) else 20 for e in ret]),
                    "commit-message": commit_message,
                    "context": {
                        "versions": [tag_name for (tag_name, version, rs) in ret],
                        "tags": [
                            (tag_name, str(version)) for (tag_name, version, rs) in ret
                        ],
                    },
                    "target-branch-url": target_branch_url,
                },
                f,
            )

    note("Imported uploads: %s.", [str(v[1]) for v in ret])


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
