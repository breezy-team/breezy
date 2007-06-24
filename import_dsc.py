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
from StringIO import StringIO
import os

import deb822
from debian_bundle.debian_support import Version

from bzrlib.bzrdir import BzrDir
from bzrlib.errors import FileExists
from bzrlib import generate_ids
from bzrlib.transform import TreeTransform

from bzrlib.plugins.bzrtools.upstream_import import (import_tar,
                                                     common_directory,
                                                     )

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


def import_orig(tree, dsc):
  for file_details in dsc['Files']:
    origname = file_details['name']
    if origname.endswith('.orig.tar.gz'):
      f = open(origname, 'rb')
      try:
        import_tar(tree, f)
        tree.commit('import upstream from %s' % (os.path.basename(origname)))
      finally:
        f.close()


def import_diff(tree, dsc):
  for file_details in dsc['Files']:
    diffname = file_details['name']
    if diffname.endswith('.diff.gz'):
      f = gzip.GzipFile(diffname, 'rb')
      try:
        tt = TreeTransform(tree)
        implied_parents = set()
        def add_implied_parents(path):
          parent = os.path.dirname(path)
          if parent == '':
            return
          if parent in implied_parents:
            return
          implied_parents.add(parent)
          add_implied_parents(parent)
        patch_list = patches.parse_patches(f)
        oldfiles = [patch.oldname for patch in patch_list]
        newfiles = [patch.newname for patch in patch_list]
        oldprefix = common_directory(oldfiles)
        newprefix = common_directory(newfiles)
        for patch in patch_list:
          oldfilename = patch.oldname
          newfilename = patch.newname
          if oldprefix is not None:
            oldfilename = oldfilename[len(oldprefix)+1:]
            oldfilename = oldfilename.rstrip('/')
          if oldfilename == '':
            continue
          if newprefix is not None:
            newfilename = newfilename[len(newprefix)+1:]
            newfilename = newfilename.rstrip('/')
          if newfilename == '':
            continue
          oldid = tree.path2id(oldfilename)
          if oldid is not None:
            oldtext = StringIO(tree.get_file_text(oldid))
          else:
            oldtext = []
          trans_id = tt.trans_id_tree_path(oldfilename)
          newtext = list(patches.iter_patched(oldtext, StringIO(patch)))
          if newtext == []:
            tt.delete_versioned(trans_id)
          else:
            if oldid is not None:
              tt.delete_contents(trans_id)
            tt.create_file(newtext, trans_id)
            if tt.tree_file_id(trans_id) is None:
              name = os.path.basename(newfilename.rstrip('/'))
              file_id = generate_ids.gen_file_id(name)
              tt.version_file(file_id, trans_id)
            add_implied_parents(newfilename)
        for path in implied_parents:
          trans_id = tt.trans_id_tree_path(path)
          if tree.path2id(path) is None:
            tt.create_directory(trans_id)
          if tt.tree_file_id(trans_id) is None:
            file_id = generate_ids.gen_file_id(name)
            tt.version_file(file_id, trans_id)
        tt.apply()
        tree.commit('merge packaging changes from %s' % \
                    (os.path.basename(diffname)))
      finally:
        f.close()


def import_dsc(target_dir, dsc_files):

  if os.path.exists(target_dir):
    raise FileExists(target_dir)
  os.mkdir(target_dir)
  branch  = BzrDir.create_branch_convenience(target_dir)
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
      import_orig(tree, dsc)
      import_diff(tree, dsc)
  finally:
    tree.unlock()

