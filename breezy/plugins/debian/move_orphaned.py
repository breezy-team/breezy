#!/usr/bin/python3
# Copyright (C) 2019 Jelmer Vernooij <jelmer@jelmer.uk>
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

import json
import logging
import os
import sys
from contextlib import ExitStack
from urllib.parse import urlparse

from debmutate.changelog import ChangelogEditor
from debmutate.control import ControlEditor
from debmutate.deb822 import ChangeConflict
from debmutate.reformatting import FormattingUnpreservable, GeneratedFile

import breezy.bzr
import breezy.git  # noqa: F401
from breezy import osutils
from breezy.branch import Branch
from breezy.plugins.debian.directory import vcs_git_url_to_bzr_url
from breezy.plugins.debian.info import versions_dict
from breezy.workingtree import WorkingTree

BRANCH_NAME = "orphan"
QA_MAINTAINER = "Debian QA Group <packages@qa.debian.org>"


def push_to_salsa(local_tree, orig_branch, user, name, dry_run=False):
    from silver_platter import pick_additional_colocated_branches
    from silver_platter.proposal import push_changes

    from breezy import urlutils
    from breezy.branch import Branch
    from breezy.errors import AlreadyControlDirError, PermissionDenied
    from breezy.forge import ForgeLoginRequired, UnsupportedForge, get_forge
    from breezy.plugins.gitlab.forge import GitLab

    if dry_run:
        logging.info("Creating and pushing to salsa project %s/%s", user, name)
        return

    try:
        salsa = GitLab.probe_from_url("https://salsa.debian.org/")
    except ForgeLoginRequired:
        logging.warning("No login for salsa known, not pushing branch.")
        return

    try:
        orig_forge = get_forge(orig_branch)
    except UnsupportedForge:
        logging.debug("Original branch %r not hosted on salsa.")
        from_project = None
    else:
        if orig_forge == salsa:
            from_project = urlutils.URL.from_string(
                orig_branch.controldir.user_url
            ).path
        else:
            from_project = None

    if from_project is not None:
        salsa.fork_project(from_project, owner=user)
    else:
        to_project = f"{user}/{name}"
        try:
            salsa.create_project(to_project)
        except PermissionDenied as e:
            logging.info(
                "No permission to create new project %s under %s: %s", name, user, e
            )
            return
        except AlreadyControlDirError:
            logging.info("Project %s already exists, using..", to_project)
    target_branch = Branch.open(f"git+ssh://git@salsa.debian.org/{user}/{name}.git")
    additional_colocated_branches = pick_additional_colocated_branches(
        local_tree.branch
    )
    return push_changes(
        local_tree.branch,
        target_branch,
        forge=salsa,
        additional_colocated_branches=additional_colocated_branches,
        dry_run=dry_run,
    )


class OrphanResult:
    def __init__(
        self,
        package=None,
        old_vcs_url=None,
        new_vcs_url=None,
        salsa_user=None,
        wnpp_bug=None,
    ):
        self.package = package
        self.old_vcs_url = old_vcs_url
        self.new_vcs_url = new_vcs_url
        self.pushed = False
        self.salsa_user = salsa_user
        self.wnpp_bug = wnpp_bug

    def json(self):
        return {
            "package": self.package,
            "old_vcs_url": self.old_vcs_url,
            "new_vcs_url": self.new_vcs_url,
            "pushed": self.pushed,
            "salsa_user": self.salsa_user,
            "wnpp_bug": self.wnpp_bug,
        }


def connect_udd_mirror():
    import psycopg2

    return psycopg2.connect(
        database="udd",
        user="udd-mirror",
        password="udd-mirror",
        host="udd-mirror.debian.net",
    )


def find_wnpp_bug(source):
    conn = connect_udd_mirror()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM wnpp WHERE type = 'O' AND source = %s", (source,))
    entry = cursor.fetchone()
    if entry is None:
        raise KeyError
    return entry[0]


def set_vcs_fields_to_salsa_user(control, salsa_user):
    old_vcs_url = control.source.get("Vcs-Git")
    control.source["Vcs-Git"] = "https://salsa.debian.org/{}/{}.git".format(
        salsa_user, control.source["Source"]
    )
    new_vcs_url = control.source["Vcs-Git"]
    control.source["Vcs-Browser"] = "https://salsa.debian.org/{}/{}".format(
        salsa_user, control.source["Source"]
    )
    return (old_vcs_url, new_vcs_url)


def set_maintainer_to_qa_team(control):
    if (
        control.source.get("Maintainer") == QA_MAINTAINER
        and "Uploaders" not in control.source
    ):
        return False
    control.source["Maintainer"] = QA_MAINTAINER
    try:
        del control.source["Uploaders"]
    except KeyError:
        pass
    return True


class NoWnppBug(Exception):
    """No wnpp bug exists."""

    def __init__(self, package):
        self.package = package


class AlreadyOrphaned(Exception):
    """Package is already orphaned."""


class MissingControlFile(Exception):
    """Control file can not be found."""


def orphan(
    local_tree,
    subpath,
    update_changelog,
    committer,
    update_vcs=True,
    salsa_push=True,
    salsa_user="debian",
    dry_run=False,
    check_wnpp=True,
) -> OrphanResult:
    control_path = local_tree.abspath(osutils.pathjoin(subpath, "debian/control"))
    changelog_entries = []
    with ExitStack() as es:
        try:
            control = es.enter_context(ControlEditor(path=control_path))
        except FileNotFoundError as e:
            raise MissingControlFile(e.filename) from e
        if check_wnpp:
            try:
                wnpp_bug = find_wnpp_bug(control.source["Source"])
            except KeyError as e:
                raise NoWnppBug(control.source["Source"]) from e
        else:
            wnpp_bug = None
        if set_maintainer_to_qa_team(control):
            if wnpp_bug is not None:
                changelog_entries.append("Orphan package - see bug %d." % wnpp_bug)
            else:
                changelog_entries.append("Orphan package.")
        result = OrphanResult(wnpp_bug=wnpp_bug, package=control.source["Source"])

        if update_vcs:
            (result.old_vcs_url, result.new_vcs_url) = set_vcs_fields_to_salsa_user(
                control, salsa_user
            )
            result.salsa_user = salsa_user
            if result.old_vcs_url == result.new_vcs_url:
                result.old_vcs_url = result.new_vcs_url = None
            else:
                changelog_entries.append("Update VCS URLs to point to Debian group.")
    if not changelog_entries:
        raise AlreadyOrphaned()
    if update_changelog in (True, None):
        cl_path = osutils.pathjoin(subpath, "debian/changelog")
        with ChangelogEditor(path=local_tree.abspath(cl_path)) as ce:
            ce.add_entry(changelog_entries)

    local_tree.commit(
        "Move package to QA team.", committer=committer, allow_pointless=False
    )

    result.pushed = False
    if update_vcs and salsa_push and result.new_vcs_url:
        parent_branch_url = local_tree.branch.get_parent()
        if parent_branch_url is not None:
            parent_branch = Branch.open(parent_branch_url)
        else:
            parent_branch = local_tree.branch
        push_result = push_to_salsa(
            local_tree,
            parent_branch,
            salsa_user,
            result.package,
            dry_run=dry_run,
        )
        if push_result:
            result.pushed = True
    return result


def move_instructions(package_name, salsa_user, old_vcs_url, new_vcs_url):
    yield f"Please move the repository from {old_vcs_url} to {new_vcs_url}."
    if urlparse(old_vcs_url).hostname == "salsa.debian.org":
        path = urlparse(old_vcs_url).path
        if path.endswith(".git"):
            path = path[:-4]
        yield "If you have the salsa(1) tool installed, run: "
        yield ""
        yield f"    salsa fork --group={salsa_user} {path}"
    else:
        yield "If you have the salsa(1) tool installed, run: "
        yield ""
        yield f"    git clone {old_vcs_url} {package_name}"
        yield f"    salsa --group={salsa_user} push_repo {package_name}"


def report_fatal(code, description):
    if os.environ.get("SVP_API") == "1":
        with open(os.environ["SVP_RESULT"], "w") as f:
            json.dump(
                {
                    "versions": versions_dict(),
                    "result_code": code,
                    "description": description,
                },
                f,
            )
    logging.info("%s", description)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(prog="deb-move-orphaned")
    parser.add_argument(
        "--dry-run",
        help="Create branches but don't push or propose anything.",
        action="store_true",
        default=False,
    )
    parser.add_argument("--directory", type=str, help="Directory to open")
    parser.add_argument("--committer", help="Committer identity", type=str)
    parser.add_argument(
        "--no-update-changelog",
        action="store_false",
        default=True,
        dest="update_changelog",
        help="do not update the changelog",
    )
    parser.add_argument(
        "--update-changelog",
        action="store_true",
        dest="update_changelog",
        help="force updating of the changelog",
        default=None,
    )
    parser.add_argument(
        "--no-update-vcs",
        action="store_true",
        help="Do not move the VCS repository to the Debian team on Salsa.",
    )
    parser.add_argument(
        "--salsa-user",
        type=str,
        default="debian",
        help="Salsa user to push repository to.",
    )
    parser.add_argument(
        "--just-update-headers",
        action="store_true",
        help="Update the VCS-* headers, but don't actually " "clone the repository.",
    )
    parser.add_argument(
        "--no-check-wnpp", action="store_true", help="Do not check for WNPP bug."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(format="%(message)s", level=logging.INFO)

    update_changelog = args.update_changelog
    if os.environ.get("DEB_UPDATE_CHANGELOG") == "leave":
        update_changelog = False
    elif os.environ.get("DEB_UPDATE_CHANGELOG") == "update":
        update_changelog = True

    tree, subpath = WorkingTree.open_containing(args.directory)

    try:
        result = orphan(
            tree,
            subpath=subpath,
            update_changelog=update_changelog,
            committer=args.committer,
            update_vcs=not args.no_update_vcs,
            dry_run=args.dry_run,
            salsa_user=args.salsa_user,
            salsa_push=not args.just_update_headers,
            check_wnpp=not args.no_check_wnpp,
        )
    except AlreadyOrphaned:
        report_fatal("nothing-to-do", "Already orphaned")
        return 0
    except NoWnppBug as e:
        report_fatal(
            "nothing-to-do",
            "Package {} is purported to be orphaned, "
            "but no open wnpp bug exists.".format(e.package),
        )
        return 1
    except FormattingUnpreservable as e:
        report_fatal(
            "formatting-unpreservable",
            "unable to preserve formatting while editing {}".format(e.path),
        )
        if hasattr(e, "diff"):
            sys.stderr.writelines(e.diff())
        return 1
    except (ChangeConflict, GeneratedFile) as e:
        report_fatal("generated-file", "unable to edit generated file: {!r}".format(e))
        return 1
    except MissingControlFile as e:
        report_fatal("missing-control-file", "Missing control file: {!r}".format(e))
        return 1

    if result.new_vcs_url:
        target_branch_url = vcs_git_url_to_bzr_url(result.new_vcs_url)
    else:
        target_branch_url = None

    if os.environ.get("SVP_API") == "1":
        with open(os.environ["SVP_RESULT"], "w") as f:
            json.dump(
                {
                    "description": "Move package to QA team.",
                    "versions": versions_dict(),
                    "target-branch-url": target_branch_url,
                    "value": 60,
                    "context": result.json(),
                },
                f,
            )

    if result.new_vcs_url:
        for line in move_instructions(
            result.package,
            result.salsa_user,
            result.old_vcs_url,
            result.new_vcs_url,
        ):
            logging.info("%s", line)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
