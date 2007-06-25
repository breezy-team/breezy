#    import_dsc.py -- Import a series of .dsc files.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
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

import gzip
import os
from StringIO import StringIO
from subprocess import Popen, PIPE

import deb822
from debian_bundle.changelog import Version

from bzrlib import (bzrdir,
                    generate_ids,
                    )
from bzrlib.errors import FileExists, BzrError
from bzrlib.transform import TreeTransform

from bzrlib.plugins.bzrtools.upstream_import import (import_tar,
                                                     common_directory,
                                                     )

from merge_upstream import make_upstream_tag
import patches

def _dsc_sorter(dscname1, dscname2):
  f1 = open(dscname1)
  try:
    dsc1 = deb822.Dsc(f1)
  finally:
    f1.close()
  f2 = open(dscname2)
  try:
    dsc2 = deb822.Dsc(f2)
  finally:
    f2.close()
  v1 = Version(dsc1['Version'])
  v2 = Version(dsc2['Version'])
  return v1 > v2


def import_orig(tree, origname, version):
  f = open(origname, 'rb')
  try:
    import_tar(tree, f)
    tree.commit('import upstream from %s' % (os.path.basename(origname)))
    upstream_version = version.upstream_version
    tree.branch.tags.set_tag(make_upstream_tag(upstream_version),
                             tree.branch.last_revision())
  finally:
    f.close()


def import_diff(tree, diffname, version):
  upstream_version = version.upstream_version
  up_revid = tree.branch.tags.lookup_tag(make_upstream_tag(upstream_version))
  up_tree = tree.branch.repository.revision_tree(up_revid)
  current_revid = tree.branch.last_revision()
  current_tree = tree.branch.repository.revision_tree(current_revid)
  tree.revert([], tree.branch.repository.revision_tree(up_revid))
  f = gzip.GzipFile(diffname, 'rb')
  try:
    cmd = ['patch', '--strip', '1', '--quiet', '--directory', tree.basedir]
    child_proc = Popen(cmd, stdin=PIPE)
    for line in f:
      child_proc.stdin.write(line)
    child_proc.stdin.close()
    r = child_proc.wait()
    if r != 0:
      raise BzrError('patch failed')
    f.seek(0)
    cmd = ['lsdiff', '--strip', '1']
    child_proc = Popen(cmd, stdin=PIPE, stdout=PIPE)
    for line in f:
      child_proc.stdin.write(line)
    child_proc.stdin.close()
    r = child_proc.wait()
    if r != 0:
      raise BzrError('patch failed')
    touched_paths = []
    for file in child_proc.stdout.readlines():
      if file.endswith('\n'):
        file = file[:-1]
      touched_paths.append(file)
    implied_parents = set()
    def add_implied_parents(path, file_ids_from=None):
      parent = os.path.dirname(path)
      if parent == '':
        return
      if parent in implied_parents:
        return
      implied_parents.add(parent)
      add_implied_parents(parent)
      if file_ids_from is None:
        tree.add([parent])
      else:
        file_id = file_ids_from.path2id(parent)
        if file_id is None:
          tree.add([parent])
        else:
          tree.add([parent], [file_id])
    for path in touched_paths:
      if not tree.has_filename(path):
        tree.remove([path], verbose=False)
      if not current_tree.has_filename(path):
        add_implied_parents(path)
        tree.add([path])
      if not up_tree.has_filename(path) and current_tree.has_filename(path):
        add_implied_parents(path, file_ids_from=current_tree)
        file_id = current_tree.path2id(path)
        if file_id is None:
          tree.add([path])
        else:
          tree.add([path], [file_id])
    tree.set_parent_ids([current_revid])
    tree.commit('merge packaging changes from %s' % \
                (os.path.basename(diffname)))
  finally:
    f.close()


def import_dsc(target_dir, dsc_files):
  if os.path.exists(target_dir):
    raise FileExists(target_dir)
  os.mkdir(target_dir)
  format = bzrdir.format_registry.make_bzrdir('dirstate-tags')
  branch  = bzrdir.BzrDir.create_branch_convenience(target_dir,
                                                    format=format)
  tree = branch.bzrdir.open_workingtree()
  tree.lock_write()
  try:
    dsc_files.sort(cmp=_dsc_sorter)
    for dscname in dsc_files:
      f = open(dscname)
      try:
        dsc = deb822.Dsc(f)
      finally:
        f.close()
      orig_files = []
      diff_files = []
      for file_details in dsc['files']:
        name = file_details['name']
        if name.endswith('.orig.tar.gz'):
          orig_files.append(name)
        elif name.endswith('.diff.gz'):
          diff_files.append(name)
      assert len(orig_files) < 2, "I don't know how to import a source " \
                                  "package with multiple .orig.tar.gz files."
      assert len(diff_files) == 1, "I don't know how to import a source " \
                                   "package which doesn't have a single " \
                                   ".diff.gz file."
      version = Version(dsc['Version'])
      if len(orig_files) == 1:
        import_orig(tree, orig_files[0], version)
      import_diff(tree, diff_files[0], version)
  finally:
    tree.unlock()

