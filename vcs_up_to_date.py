#!/usr/bin/python3
# Copyright (C) 2022 Jelmer Vernooij <jelmer@jelmer.uk>
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

__all__ = [
    'PackageMissingInArchive',
    'NewArchiveVersion',
    'MissingChangelogError',
    'TreeVersionNotInArchive',
    'check_up_to_date',
]

import asyncio
import logging
import os

from debmutate.changelog import distribution_is_unreleased

from breezy.workingtree import WorkingTree
from breezy.plugins.debian.util import find_changelog, MissingChangelogError
from breezy.plugins.debian.apt_repo import (
    LocalApt,
    RemoteApt,
)


class PackageMissingInArchive(Exception):
    def __init__(self, package):
        self.package = package
        super(PackageMissingInArchive, self).__init__(
            "package %s is missing in archive" % package)


class NewArchiveVersion(Exception):
    def __init__(self, archive_version, tree_version):
        self.archive_version = archive_version
        self.tree_version = tree_version
        super(NewArchiveVersion, self).__init__(
            "archive version %s is newer than version %s in tree" % (
                archive_version, tree_version))


class TreeVersionNotInArchive(Exception):
    def __init__(self, tree_version, archive_versions):
        self.tree_version = tree_version
        self.archive_versions = archive_versions
        super(TreeVersionNotInArchive, self).__init__(
            "tree version %s does not appear in archive" %
            tree_version
        )


def check_up_to_date(tree, subpath, apt):
    released_tree_versions = []
    tree_cl, top_level = find_changelog(tree, subpath, max_blocks=None)
    for block in tree_cl:
        if distribution_is_unreleased(block.distributions):
            continue
        released_tree_versions.append(block.version)
    package = tree_cl.package

    released_tree_versions.sort()
    if not released_tree_versions:
        # Package hasn't made it into the archive yet?
        return
    last_released_tree_version = released_tree_versions[-1]

    archive_versions = []
    with apt:
        for entry in apt.iter_source_by_name(package):
            archive_versions.append(entry['Version'])

    archive_versions.sort()

    if not archive_versions:
        if last_released_tree_version is None:
            # Package has not made it into the archive yet
            return
        raise PackageMissingInArchive(package)

    last_archive_version = archive_versions[-1]

    if last_released_tree_version not in archive_versions:
        raise TreeVersionNotInArchive(
            last_released_tree_version, archive_versions)

    if last_archive_version not in released_tree_versions:
        raise NewArchiveVersion(
            last_archive_version, last_released_tree_version)


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--apt-repository', type=str,
        help='APT repository to use. Defaults to locally configured.',
        default=(
            os.environ.get('APT_REPOSITORY')
            or os.environ.get('REPOSITORIES')))
    parser.add_argument(
        '--apt-repository-key', type=str,
        help=('APT repository key to use for validation, '
              'if --apt-repository is set.'),
        default=os.environ.get('APT_REPOSITORY_KEY'))
    parser.add_argument(
        'directory', default='.', nargs='?',
        type=str, help='Path to working tree')

    import breezy.bzr  # noqa: F401
    import breezy.git  # noqa: F401

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    if args.apt_repository:
        apt = RemoteApt.from_string(
            args.apt_repository, args.apt_repository_key)
    else:
        apt = LocalApt()
    tree, subpath = WorkingTree.open_containing(args.directory)

    try:
        check_up_to_date(
            tree, subpath, apt,
            ignore_missing_changelog=args.ignore_missing_changelog)
    except TreeVersionNotInArchive as exc:
        logging.fatal(
            'Last released tree version %s not in archive',
            exc.tree_version)
        return 1
    except NewArchiveVersion as exc:
        logging.fatal(
            'New archive version %s is missing in tree',
            exc.archive_version)
        return 1
    except PackageMissingInArchive as exc:
        logging.fatal(
            '%s not found in the specified archive', exc.package)
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(asyncio.run(main()))
