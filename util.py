#    util.py -- Utility functions
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
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

import shutil
import os
import re

from bzrlib.trace import info, mutter

from debian_bundle.changelog import Changelog

from bzrlib.plugins.builddeb.errors import (
                MissingChangelogError,
                AddChangelogError,
                )


def recursive_copy(fromdir, todir):
    """Copy the contents of fromdir to todir.

    Like shutil.copytree, but the destination directory must already exist
    with this method, rather than not exists for shutil.
    """
    mutter("Copying %s to %s", fromdir, todir)
    for entry in os.listdir(fromdir):
        path = os.path.join(fromdir, entry)
        if os.path.isdir(path):
            tosubdir = os.path.join(todir, entry)
            if not os.path.exists(tosubdir):
                os.mkdir(tosubdir)
            recursive_copy(path, tosubdir)
        else:
            shutil.copy(path, todir)


def find_changelog(t, merge):
    """Find the changelog in the given tree.

    First looks for 'debian/changelog'. If "merge" is true will also
    look for 'changelog'.

    The returned changelog is created with 'max_blocks=1' and
    'allow_empty_author=True'. The first to try and prevent old broken
    changelog entries from causing the command to fail, and the
    second as some people do this but still want to build.

    "larstiq" is a subset of "merge" mode. It indicates that the
    '.bzr' dir is at the same level as 'changelog' etc., rather
    than being at the same level as 'debian/'.

    :param t: the Tree to look in.
    :param merge: whether this is a "merge" package.
    :return: (changelog, larstiq) where changelog is the Changelog,
        and larstiq is a boolean indicating whether the file is at
        'changelog' if merge was given, False otherwise.
    """
    changelog_file = 'debian/changelog'
    larstiq = False
    t.lock_read()
    try:
        if not t.has_filename(changelog_file):
            if merge:
                #Assume LarstiQ's layout (.bzr in debian/)
                changelog_file = 'changelog'
                larstiq = True
                if not t.has_filename(changelog_file):
                    raise MissingChangelogError('"debian/changelog" or '
                            '"changelog"')
            else:
                raise MissingChangelogError('"debian/changelog"')
        elif merge and t.has_filename('changelog'):
            # If it is a "larstiq" pacakge and debian is a symlink to
            # "." then it will have found debian/changelog. Try and detect
            # this.
            if (t.kind(t.path2id('debian')) == 'symlink' and 
                t.get_symlink_target(t.path2id('debian')) == '.'):
                changelog_file = 'changelog'
                larstiq = True
        mutter("Using '%s' to get package information", changelog_file)
        changelog_id = t.path2id(changelog_file)
        if changelog_id is None:
            raise AddChangelogError(changelog_file)
        contents = t.get_file_text(changelog_id)
    finally:
       t.unlock()
    changelog = Changelog()
    changelog.parse_changelog(contents, max_blocks=1, allow_empty_author=True)
    return changelog, larstiq


def strip_changelog_message(changes):
    """Strip a changelog message like debcommit does.

    Takes a list of changes from a changelog entry and applies a transformation
    so the message is well formatted for a commit message.

    :param changes: a list of lines from the changelog entry
    :return: another list of lines with blank lines stripped from the start
        and the spaces the start of the lines split if there is only one logical
        entry.
    """
    while changes[-1] == '':
        changes.pop()
    while changes[0] == '':
        changes.pop(0)

    whitespace_column_re = re.compile(r'  |\t')
    changes = map(lambda line: whitespace_column_re.sub('', line, 1), changes)

    leader_re = re.compile(r'[ \t]*[*+-] ')
    count = len(filter(leader_re.match, changes))
    if count == 1:
        return map(lambda line: leader_re.sub('', line, 1).lstrip(), changes)
    else:
        return changes


def tarball_name(package, version):
    """Return the name of the .orig.tar.gz for the given package and version.

    :param package: the name of the source package.
    :param version: the upstream version of the package.
    :return: a string that is the name of the upstream tarball to use.
    """
    return "%s_%s.orig.tar.gz" % (package, str(version))


def get_snapshot_revision(upstream_version):
    """Return the upstream revision specifier if specified in the upstream version.

    When packaging an upstream snapshot some people use +vcsnn or ~vcsnn to indicate
    what revision number of the upstream VCS was taken for the snapshot. This given
    an upstream version number this function will return an identifier of the
    upstream revision if it appears to be a snapshot. The identifier is a string
    containing a bzr revision spec, so it can be transformed in to a revision.

    :param upstream_version: a string containing the upstream version number.
    :return: a string containing a revision specifier for the revision of the
        upstream branch that the snapshot was taken from, or None if it doesn't
        appear to be a snapshot.
    """
    match = re.search("(?:~|\\+)bzr([0-9]+)$", upstream_version)
    if match is not None:
        return match.groups()[0]
    match = re.search("(?:~|\\+)svn([0-9]+)$", upstream_version)
    if match is not None:
        return "svn:%s" % match.groups()[0]
    return None


def suite_to_distribution(suite):
    """Infer the distribution from a suite.

    When passed the name of a suite (anything in the distributions field of
    a changelog) it will infer the distribution from that (i.e. Debian or
    Ubuntu).

    :param suite: the string containing the suite
    :return: "debian", "ubuntu", or None if the distribution couldn't be inferred.
    """
    debian_releases = ('woody', 'sarge', 'etch', 'lenny', 'squeeze', 'stable',
            'testing', 'unstable', 'experimental', 'frozen')
    debian_targets = ('', '-security', '-proposed-updates', '-backports')
    ubuntu_releases = ('warty', 'hoary', 'breezy', 'dapper', 'edgy',
            'feisty', 'gutsy', 'hardy', 'intrepid', 'jaunty')
    ubuntu_targets = ('', '-proposed', '-updates', '-security', '-backports')
    all_debian = [r + t for r in debian_releases for t in debian_targets]
    all_ubuntu = [r + t for r in ubuntu_releases for t in ubuntu_targets]
    if suite in all_debian:
        return "debian"
    if suite in all_ubuntu:
        return "ubuntu"
    return None


def lookup_distribution(distribution_or_suite):
    """Get the distribution name based on a distribtion or suite name.

    :param distribution_or_suite: a string that is either the name of
        a distribution or a suite.
    :return: a string with a distribution name or None.
    """
    if distribution_or_suite.lower() in ("debian", "ubuntu"):
        return distribution_or_suite.lower()
    return suite_to_distribution(distribution_or_suite)
