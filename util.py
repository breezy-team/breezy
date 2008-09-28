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

from bzrlib.plugins.builddeb.errors import (MissingChangelogError,
                AddChangelogError,
                )


def recursive_copy(fromdir, todir):
  """Copy the contents of fromdir to todir. Like shutil.copytree, but the 
  destination directory must already exist with this method, rather than 
  not exists for shutil."""
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
            raise MissingChangelogError("debian/changelog or changelog")
        else:
          raise MissingChangelogError("debian/changelog")
      else:
        if merge and t.has_filename('changelog'):
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
  """Return the name of the .orig.tar.gz for the given package and version."""

  return "%s_%s.orig.tar.gz" % (package, str(version))

def get_snapshot_revision(upstream_version):
  """Return the upstream revision specifier if specified in the upstream version or None. """
  match = re.search("(?:~|\\+)bzr([0-9]+)$", upstream_version)
  if match is not None:
    return match.groups()[0]
  match = re.search("(?:~|\\+)svn([0-9]+)$", upstream_version)
  if match is not None:
    return "svn:%s" % match.groups()[0]
  return None


def lookup_distribution(target_dist):
  debian_releases = ('woody', 'sarge', 'etch', 'lenny', 'squeeze', 'stable',
          'testing', 'unstable', 'experimental', 'frozen')
  debian_targets = ('', '-security', '-proposed-updates', '-backports')
  ubuntu_releases = ('warty', 'hoary', 'breezy', 'dapper', 'edgy',
          'feisty', 'gutsy', 'hardy', 'intrepid', 'jaunty')
  ubuntu_targets = ('', '-proposed', '-updates', '-security', '-backports')
  all_debian = [r + t for r in debian_releases for t in debian_targets]
  all_ubuntu = [r + t for r in ubuntu_releases for t in ubuntu_targets]
  if target_dist in all_debian:
    return "debian"
  if target_dist in all_ubuntu:
    return "ubuntu"
  return None


# vim: ts=2 sts=2 sw=2
