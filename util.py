#    util.py -- Utility functions
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
#    
#    This file is part of bzr-builddeb.
#
#    bzr-builldeb is free software; you can redistribute it and/or modify
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

from bzrlib.atomicfile import AtomicFile
from bzrlib.ignores import parse_ignore_file
from bzrlib.workingtree import WorkingTree

from debian_bundle.changelog import Changelog

from errors import DebianError
from bdlogging import info, debug

def add_ignore(file):
  """Adds file to .bzrignore if it exists and not already in the file."""
  if os.path.exists(file):
    tree, relpath = WorkingTree.open_containing(u'.')
    ifn = tree.abspath('.bzrignore')
    ignored = set()
    if os.path.exists(ifn):
      f = open(ifn, 'rt')
      ignored = parse_ignore_file(f)
      f.close()
    
    if file not in ignored:
      info("Adding %s to .bzrignore", file)
      ignored.add(file)

      f = AtomicFile(ifn, 'wt')
      try:
        for ign in ignored:
          f.write(ign.encode('utf-8')+"\n")
        f.commit()
      finally:
        f.close()

    inv = tree.inventory
    if inv.path2id('.bzrignore'):
      debug('.bzrignore is already versioned')
    else:
      debug('need to make new .bzrignore file versioned')
      tree.add(['.bzrignore'])


def recursive_copy(fromdir, todir):
  """Copy the contents of fromdir to todir. Like shutil.copytree, but the 
  destination directory must already exist with this method, rather than 
  not exists for shutil."""
  debug("Copying %s to %s", fromdir, todir)
  for entry in os.listdir(fromdir):
    path = os.path.join(fromdir, entry)
    if os.path.isdir(path):
      tosubdir = os.path.join(todir, entry)
      if not os.path.exists(tosubdir):
        os.mkdir(tosubdir)
      recursive_copy(path, tosubdir)
    else:
      shutil.copy(path, todir)


def is_clean(oldtree, newtree, ignore_unknowns=False):
  """Return True if there are no uncommited changes or unknown files.
  
  If ignore_unknowns is True then unknown files do not count as changes."""

  changes = newtree.changes_from(oldtree)
  if changes.has_changed():
    return False
  if not ignore_unknowns and len(list(newtree.unknowns())) > 0:
    return False
  return True

def goto_branch(branch):
  """Changes to the specified branch dir if it is not None"""
  if branch is not None:
    info("Building using branch at %s", branch)
    os.chdir(branch)

def find_changelog(t, merge):
    changelog_file = 'debian/changelog'
    larstiq = False
    if not t.has_filename(changelog_file):
      if merge:
        #Assume LartstiQ's layout (.bzr in debian/)
        changelog_file = 'changelog'
        larstiq = True
        if not t.has_filename(changelog_file):
          raise DebianError("Could not open debian/changelog or changelog")
      else:
        raise DebianError("Could not open debian/changelog")
    debug("Using '%s' to get package information", changelog_file)
    changelog_id = t.inventory.path2id(changelog_file)
    contents = t.get_file_text(changelog_id)
    changelog = Changelog(contents)
    return changelog, larstiq 


