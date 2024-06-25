#    merge_package.py -- The plugin for bzr
#    Copyright (C) 2009 Canonical Ltd.
#    Copyright (C) 2022 Jelmer Vernooĳ
#
#    :Author: Muharem Hrnjadovic <muharem@ubuntu.com>
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

import json
import logging
import os
import re
import sys
import tempfile

from debian.changelog import Changelog, Version, format_date, get_maintainer
from debian.deb822 import Deb822
from debmutate.changelog import ChangelogEditor, changeblock_add_line, increment_version
from debmutate.reformatting import GeneratedFile

from breezy.errors import (
    BzrError,
    ConflictsInTree,
    DivergedBranches,
    NoSuchTag,
    UnrelatedBranches,
)
from breezy.transport import NoSuchFile
from breezy.workingtree import (
    PointlessMerge,
)

from .changelog import debcommit
from .cmds import _build_helper
from .directory import vcs_field_to_bzr_url_converters
from .errors import (
    MultipleUpstreamTarballsNotSupported,
)
from .import_dsc import DistributionBranch
from .util import (
    MissingChangelogError,
    debsign,
    dput_changes,
    find_changelog,
)


class ChangelogGeneratedFile(Exception):
    """The changelog file is generated."""

    def __init__(self, path, template_path, template_type):
        self.path = path
        self.template_path = template_path
        self.template_type = template_type


class SharedUpstreamConflictsWithTargetPackaging(BzrError):
    _fmt = (
        "The upstream branches for the merge source and target have "
        "diverged. Unfortunately, the attempt to fix this problem "
        "resulted in conflicts. Please resolve these, commit and "
        're-run the "%(cmd)s" command to finish. '
        'Alternatively, until you commit you can use "bzr revert" to '
        "restore the state of the unmerged branch."
    )

    def __init__(self, cmd):
        self.cmd = cmd


def _upstream_version_data(branch, revid):
    """Most recent upstream versions/revision IDs of the merge source/target.

    Please note: both packaging branches must have been read-locked
    beforehand.

    :param branch: The merge branch.
    :param revid: The revision in the branch to consider
    :param tree: Optional tree for the revision
    """
    db = DistributionBranch(branch, branch)
    tree = branch.repository.revision_tree(revid)
    changelog, _ignore = find_changelog(tree, "", False)
    uver = changelog.version.upstream_version
    upstream_revids = db.pristine_upstream_source.version_as_revisions(None, uver)
    if list(upstream_revids.keys()) != [None]:
        raise MultipleUpstreamTarballsNotSupported()
    upstream_revid, upstream_subpath = upstream_revids[None]
    return (Version(uver), upstream_revid, upstream_subpath)


def fix_ancestry_as_needed(tree, source, source_revid=None):
    r"""Manipulate the merge target's ancestry to avoid upstream conflicts.

    Merging J->I given the following ancestry tree is likely to result in
    upstream merge conflicts:

    debian-upstream                 ,------------------H
                       A-----------B                    \
    ubuntu-upstream     \           \`-------G           \
                         \           \        \           \
    debian-packaging      \ ,---------D--------\-----------J
                           C           \        \
    ubuntu-packaging        `----E------F--------I

    Here there was a new upstream release (G) that Ubuntu packaged (I), and
    then another one that Debian packaged, skipping G, at H and J.

    Now, the way to solve this is to introduce the missing link.

    debian-upstream                 ,------------------H------.
                       A-----------B                    \      \
    ubuntu-upstream     \           \`-------G-----------\------K
                         \           \        \           \
    debian-packaging      \ ,---------D--------\-----------J
                           C           \        \
    ubuntu-packaging        `----E------F--------I

    at K, which isn't a real merge, as we just use the tree from H, but add
    G as a parent and then we merge that in to Ubuntu.

    debian-upstream                 ,------------------H------.
                       A-----------B                    \      \
    ubuntu-upstream     \           \`-------G-----------\------K
                         \           \        \           \      \
    debian-packaging      \ ,---------D--------\-----------J      \
                           C           \        \                  \
    ubuntu-packaging        `----E------F--------I------------------L

    At this point we can merge J->L to merge the Debian and Ubuntu changes.

    :param tree: The `WorkingTree` of the merge target branch.
    :param source: The merge source (packaging) branch.
    """
    upstreams_diverged = False
    t_upstream_reverted = False
    target = tree.branch

    with source.lock_read():
        if source_revid is None:
            source_revid = source.last_revision()
        with tree.lock_write():
            # "Unpack" the upstream versions and revision ids for the merge
            # source and target branch respectively.
            (us_ver, us_revid, us_subpath) = _upstream_version_data(
                source, source_revid
            )
            (ut_ver, ut_revid, ut_subpath) = _upstream_version_data(
                target, target.last_revision()
            )

            if us_subpath or ut_subpath:
                raise Exception("subpaths not yet supported")

            # Did the upstream branches of the merge source/target diverge?
            graph = source.repository.get_graph(target.repository)
            upstreams_diverged = len(graph.heads([us_revid, ut_revid])) > 1

            # No, we're done!
            if not upstreams_diverged:
                return (upstreams_diverged, t_upstream_reverted)

            # Instantiate a `DistributionBranch` object for the merge target
            # (packaging) branch.
            db = DistributionBranch(tree.branch, tree.branch)
            with tempfile.TemporaryDirectory(
                dir=os.path.join(tree.basedir, "..")
            ) as tempdir:
                # Extract the merge target's upstream tree into a temporary
                # directory.
                db.extract_upstream_tree({None: (ut_revid, ut_subpath)}, tempdir)
                tmp_target_utree = db.pristine_upstream_tree

                # Merge upstream branch tips to obtain a shared upstream
                # parent.  This will add revision K (see graph above) to a
                # temporary merge target upstream tree.
                with tmp_target_utree.lock_write():
                    if us_ver > ut_ver:
                        # The source upstream tree is more recent and the
                        # temporary target tree needs to be reshaped to match
                        # it.
                        tmp_target_utree.revert(
                            None, source.repository.revision_tree(us_revid)
                        )
                        t_upstream_reverted = True

                    tmp_target_utree.set_parent_ids((ut_revid, us_revid))
                    new_revid = tmp_target_utree.commit(
                        "Prepared upstream tree for merging into target " "branch."
                    )

                    # Repository updates during a held lock are not visible,
                    # hence the call to refresh the data in the /target/ repo.
                    tree.branch.repository.refresh_data()

                    tree.branch.fetch(source, us_revid)
                    tree.branch.fetch(tmp_target_utree.branch, new_revid)

                    # Merge shared upstream parent into the target merge
                    # branch. This creates revison L in the digram above.
                    conflicts = tree.merge_from_branch(tmp_target_utree.branch)
                    if conflicts:
                        cmd = "bzr merge"
                        raise SharedUpstreamConflictsWithTargetPackaging(cmd)
                    else:
                        tree.commit("Merging shared upstream rev into target branch.")

    return (upstreams_diverged, t_upstream_reverted)


def report_fatal(code, description, *, hint=None):
    if os.environ.get("SVP_API") == "1":
        with open(os.environ["SVP_RESULT"], "w") as f:
            json.dump({"result_code": code, "description": description}, f)
    logging.fatal("%s", description)
    if hint:
        logging.info("%s", hint)


def find_origins(source):
    for field, value in source.items():
        m = re.match(r"XS\-(.*)\-Vcs\-(.*)", field, re.I)
        if not m:
            continue
        vcs_type = m.group(2)
        if vcs_type == "Browser":
            continue
        vcs_url = dict(vcs_field_to_bzr_url_converters)[vcs_type](value)
        origin = m.group(1)
        yield origin, vcs_type, vcs_url


def update_changelog(
    wt, subpath, target_distribution, version_fn, summary, author=None
):
    changes = []
    # TODO(jelmer): Iterate Build-Depends and verify that depends are
    # satisfied by target_distribution
    # TODO(jelmer): Update Vcs-Git/Vcs-Browser header?
    clp = wt.abspath(os.path.join(subpath, "debian/changelog"))

    if author is None:
        author = "{} <{}>".format(*get_maintainer())

    try:
        with ChangelogEditor(clp) as cl:
            # TODO(jelmer): If there was an existing backport, use that version
            cl.new_block(
                package=cl[0].package,
                distributions=target_distribution,
                urgency="low",
                author=author,
                date=format_date(),
                version=version_fn(cl[0].version),
                changes=[""],
            )
            changeblock_add_line(
                cl[0],
                [summary] + [" +" + line for line in changes],
            )
    except FileNotFoundError as e:
        raise MissingChangelogError([clp]) from e
    except GeneratedFile as e:
        raise ChangelogGeneratedFile(e.path, e.template_path, e.template_type) from e

    debcommit(wt, subpath=subpath)


def backport_suffix(release):
    from distro_info import DebianDistroInfo

    distro_info = DebianDistroInfo()
    if release in ("stable", "oldstable"):
        release = distro_info.codename(release)
    version = distro_info.version(release)
    if version is None:
        raise AssertionError("Unknown release {!r}".format(release))
    return "bpo{}".format(version)


def determine_distribution(release: str, backport=False) -> str:
    if backport:
        if release.endswith("-backports"):
            return release
        from distro_info import DebianDistroInfo

        distro_info = DebianDistroInfo()
        if release == "stable" or distro_info.codename("stable") == release:
            return f"{distro_info.codename('stable')}-backports"
        if release == "oldstable" or distro_info.codename("oldstable") == release:
            return f"{distro_info.codename('oldstable')}-backports-sloppy"
        raise Exception(f"unable to determine target suite for {release}")
    return release


def create_bpo_version(orig_version, bpo_suffix):
    m = re.fullmatch(r"(.*)\~" + bpo_suffix + r"\+([0-9]+)", str(orig_version))
    if m:
        base = m.group(1)
        buildno = int(m.group(2)) + 1
    else:
        base = str(orig_version)
        buildno = 1
    return f"{base}~{bpo_suffix}+{buildno}"


def auto_backport(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    return main(argv + ["--backport"])


def main(argv=None):
    DEFAULT_BUILDER = "sbuild --no-clean-source"
    import argparse

    import breezy.bzr
    import breezy.git  # noqa: F401
    from breezy.branch import Branch
    from breezy.workingtree import WorkingTree
    from breezy.workspace import check_clean_tree

    from .apt_repo import LocalApt, NoAptSources, RemoteApt
    from .directory import source_package_vcs_url

    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", "-d", type=str, help="Working directory")
    parser.add_argument(
        "--apt-repository", type=str, help="APT Repository to fetch from"
    )
    parser.add_argument(
        "--apt-repository-key", type=str, help="Repository key to use for verification"
    )
    parser.add_argument("--version", type=str, help="Version to use")
    parser.add_argument("--vendor", type=str, help="Name of vendor to merge from")
    parser.add_argument("--backport", action="store_true")
    parser.add_argument("--package", type=str)
    parser.add_argument("--target-release", type=str)
    parser.add_argument("--build", action="store_true")
    # TODO(jelmer): add --revision argument
    parser.add_argument(
        "--builder",
        type=str,
        help="Build command",
        default=(
            DEFAULT_BUILDER + " --source --source-only-changes "
            "--debbuildopt=-v${LAST_VERSION}"
        ),
    )

    parser.add_argument("vcs_url", type=str, nargs="?")

    args = parser.parse_args(argv)

    logging.basicConfig(format="%(message)s", level=logging.INFO)

    wt, subpath = WorkingTree.open_containing(args.directory)

    check_clean_tree(wt, subpath=subpath)

    vendor = args.vendor

    try:
        cl, _larstiq = find_changelog(wt, subpath=subpath)
    except MissingChangelogError:
        cl = None
        since_version = None
    else:
        since_version = cl[0].version
        if not args.target_release:
            args.target_release = cl[0].distributions

    if args.vcs_url:
        branch_url = args.vcs_url
        vcs_type = None
        package = None
    elif args.package:
        package = args.package
        branch_url = None
        vcs_type = None
    else:
        if cl is None:
            report_fatal(
                "missing-changelog",
                "Need either --package, vcs url or existing debian package",
            )
            return 1
        package = cl.package
        branch_url = None
        vcs_type = None

    if branch_url is None:
        try:
            with wt.get_file(os.path.join(subpath, "debian/control")) as f:
                source = Deb822(f)
                origins = list(find_origins(source))
                if not origins:
                    report_fatal(
                        "no-upstream-vcs-url",
                        "Source package not have any Xs-*-Vcs-* fields",
                    )
                    return 1
                if len(origins) > 1:
                    logging.warning("More than one origin: %r", origins)
                    origin, vcs_type, branch_url = origins[0]
                else:
                    [(vendor, vcs_type, branch_url)] = origins
        except NoSuchFile:
            if args.apt_repository is not None:
                apt = RemoteApt.from_string(
                    args.apt_repository, args.apt_repository_key
                )
                origin = apt.distribution
            else:
                apt = LocalApt()
                origin = None

            logging.info("Using apt repository %r", apt)

            with apt:
                versions = []
                try:
                    for source in apt.iter_source_by_name(package):
                        versions.append((source["Version"], source))
                except NoAptSources:
                    report_fatal(
                        "no-apt-sources",
                        "No sources configured in /etc/apt/sources.list",
                    )
                    return 1

            versions.sort()
            try:
                version, source = versions[-1]
            except IndexError:
                report_fatal(
                    "not-present-in-apt",
                    f"The APT repository {apt} does not contain {package}",
                )
                return 1

            source = next(apt.iter_source_by_name(package))
            vcs_type, branch_url = source_package_vcs_url(source)
            logging.info("Resolved apt repository to %s", branch_url)
            if not args.version:
                args.version = source["Version"]

    if branch_url is None:
        raise AssertionError("branch_url is None")

    branch = Branch.open(branch_url)

    if args.version is None:
        to_merge = branch.last_revision()
        wt.branch.repository.fetch(branch.repository, revision_id=to_merge)
        revtree = wt.branch.repository.revision_tree(to_merge)
        with revtree.get_file(os.path.join(subpath, "debian/changelog")) as f:
            cl = Changelog(f, max_blocks=1)
        package = cl.package
        version = cl.version
    else:
        to_merge = None

    version = Version(args.version)

    if cl and version == cl.version:
        report_fatal(
            "tree-version-is-newer",
            f"Local tree already contains remote version {cl.version}",
        )
        return 1

    if cl and version < cl.version:
        report_fatal(
            "nothing-to-do",
            f"Local tree contains newer version ({cl.version}) "
            f"than apt repo ({version})",
        )
        return 1

    if cl and cl.version is not None:
        logging.info("Importing version: %s (current: %s)", version, cl.version)
    else:
        logging.info("Importing version: %s", version)

    if to_merge is None:
        remote_db = DistributionBranch(branch, None)
        # Find the appropriate tag
        for tag_name in remote_db.possible_tags(version, vendor=vendor):
            try:
                to_merge = remote_db.branch.tags.lookup_tag(tag_name)
            except NoSuchTag:
                pass
            else:
                break
        else:
            report_fatal(
                "missing-remote-tag",
                f"Unable to find tag for version {version} in branch {remote_db.branch}",
            )
            return 1
        logging.info("Merging tag %s", tag_name)

    with wt.lock_write():
        try:
            wt.pull(branch, stop_revision=to_merge)
        except DivergedBranches:
            try:
                wt.merge_from_branch(branch, to_revision=to_merge)
            except ConflictsInTree as e:
                report_fatal("merged-conflicted", str(e))
                return 1
            except PointlessMerge as e:
                report_fatal("nothing-to-do", str(e))
                return 1
            except UnrelatedBranches:
                if apt:
                    logging.info(
                        "Upstream branch %r does not share history " "with this one.",
                        branch,
                    )
                    logging.info("Falling back to importing dsc.")
                    with tempfile.TemporaryDirectory() as td:
                        apt.retrieve_source(
                            cl.package, td, source_version=cl.version, tar_only=False
                        )
                        for entry in os.scandir(td):
                            if entry.name.endswith(".dsc"):
                                dsc_path = entry.path
                                break
                        else:
                            raise AssertionError(
                                f"{apt} did not actually " "download dsc file"
                            ) from None
                        local_db = DistributionBranch(wt.branch, None)
                        tag_name = local_db.import_package(dsc_path)
                        to_merge = wt.branch.tags.lookup_tag(tag_name)
                        try:
                            wt.merge_from_branch(wt.branch, to_revision=to_merge)
                        except ConflictsInTree as e:
                            report_fatal("merged-conflicted", str(e))
                            return 1
                else:
                    report_fatal(
                        "unrelated-branches",
                        f"Upstream branch {branch} does not share "
                        "history with this one, and no apt repository "
                        "specified.",
                    )
                    return 1

        target_distribution = determine_distribution(args.target_release, args.backport)
        if args.backport:
            version_suffix = backport_suffix(args.target_release)

            def version_fn(imported_version):
                return create_bpo_version(imported_version, version_suffix)

            summary = f"Backport to {args.target_release}."
        else:
            if origin is not None:
                summary = f"Merge from {origin}."
            else:
                origin = f"Merge {version}"

            version_fn = increment_version

        logging.info(
            "Using target distribution %s, version suffix %s",
            target_distribution,
            version_suffix,
        )
        update_changelog(
            wt,
            subpath,
            target_distribution=target_distribution,
            version_fn=version_fn,
            summary=summary,
        )

    if args.build:
        with tempfile.TemporaryDirectory() as td:
            builder = args.builder.replace("${LAST_VERSION}", str(since_version))
            target_changes = _build_helper(wt, subpath, wt.branch, td, builder=builder)
            debsign(target_changes["source"])

            if not args.dry_run:
                dput_changes(target_changes["source"])

    if os.environ.get("SVP_API") == "1":
        with open(os.environ["SVP_RESULT"], "w") as f:
            json.dump(
                {
                    "description": f"Merged from {origin}",
                    "value": 80,
                    "commit-message": f"Sync with {origin}",
                    "context": {
                        "vendor": vendor,
                        "origin": origin,
                        "vcs_type": vcs_type,
                        "branch_url": branch_url,
                        "version": str(version),
                        "revision_id": to_merge.decode("utf-8"),
                        "tag": tag_name,
                    },
                },
                f,
            )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
