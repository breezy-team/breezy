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

from errors import ImportError
from merge_upstream import make_upstream_tag
import patches

# TODO: support native packages (should be easy).
# TODO: Use a transport to retrieve the files, so that they can be got remotely

class DscCache(object):

  def __init__(self):
    self.cache = {}

  def get_dsc(self, name):
    if name in self.cache:
      dsc1 = self.cache[name]
    else:
      f1 = open(name)
      try:
        dsc1 = deb822.Dsc(f1)
      finally:
        f1.close()
      self.cache[name] = dsc1
    return dsc1

class DscComp(object):

  def __init__(self, cache):
    self.cache = cache

  def cmp(self, dscname1, dscname2):
    dsc1 = self.cache.get_dsc(dscname1)
    dsc2 = self.cache.get_dsc(dscname2)
    v1 = Version(dsc1['Version'])
    v2 = Version(dsc2['Version'])
    if v1 == v2:
      return 0
    if v1 > v2:
      return 1
    return -1


def import_orig(tree, origname, version, last_upstream=None):
  f = open(origname, 'rb')
  try:
    dangling_revid = None
    if last_upstream is not None:
      dangling_revid = tree.branch.last_revision()
      old_upstream_revid = tree.branch.tags.lookup_tag(
                               make_upstream_tag(last_upstream))
      tree.revert([], tree.branch.repository.revision_tree(old_upstream_revid))
    import_tar(tree, f)
    if last_upstream is not None:
      tree.set_parent_ids([old_upstream_revid])
      revno = tree.branch.revision_id_to_revno(old_upstream_revid)
      tree.branch.set_last_revision_info(revno, old_upstream_revid)
    tree.commit('import upstream from %s' % (os.path.basename(origname)))
    if last_upstream is not None:
      tree.merge_from_branch(tree.branch, to_revision=dangling_revid)
    upstream_version = version.upstream_version
    tree.branch.tags.set_tag(make_upstream_tag(upstream_version),
                             tree.branch.last_revision())
  finally:
    f.close()
  return dangling_revid


def import_diff(tree, diffname, version, dangling_revid=None):
  upstream_version = version.upstream_version
  up_revid = tree.branch.tags.lookup_tag(make_upstream_tag(upstream_version))
  up_tree = tree.branch.repository.revision_tree(up_revid)
  if dangling_revid is None:
    current_revid = tree.branch.last_revision()
  else:
    current_revid = dangling_revid
  current_tree = tree.branch.repository.revision_tree(current_revid)
  tree.revert(['.'], tree.branch.repository.revision_tree(up_revid))
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
    tree.commit('merge packaging changes from %s' % \
                (os.path.basename(diffname)))
  finally:
    f.close()


def import_dsc(target_dir, dsc_files):
  if os.path.exists(target_dir):
    raise FileExists(target_dir)
  cache = DscCache()
  dsc_files.sort(cmp=DscComp(cache).cmp)
  safe_files = []
  for dscname in dsc_files:
    dsc = cache.get_dsc(dscname)
    orig_file = None
    diff_file = None
    for file_details in dsc['files']:
      name = file_details['name']
      if name.endswith('.orig.tar.gz'):
        if orig_file is not None:
          raise ImportError("%s contains more than one .orig.tar.gz" % dscname)
        orig_file = name
      elif name.endswith('.diff.gz'):
        if diff_file is not None:
          raise ImportError("%s contains more than one .diff.gz" % dscname)
        diff_file = name
    if diff_file is None:
      raise ImportError("%s contains only a .orig.tar.gz, it must contain a "
                        ".diff.gz as well" % dscname)
    version = Version(dsc['Version'])
    if orig_file is not None:
      safe_files.append((orig_file, version, 'orig'))
    found = False
    for safe_file in safe_files:
      if safe_file[0].endswith("_%s.orig.tar.gz" % version.upstream_version):
        found = True
        break
    if found == False:
      raise ImportError("There is no upstream version corresponding to %s" % \
                          diff_file)
    safe_files.append((diff_file, version, 'diff'))
  os.mkdir(target_dir)
  format = bzrdir.format_registry.make_bzrdir('dirstate-tags')
  branch  = bzrdir.BzrDir.create_branch_convenience(target_dir,
                                                    format=format)
  tree = branch.bzrdir.open_workingtree()
  tree.lock_write()
  try:
    last_upstream = None
    dangling_revid = None
    for (filename, version, type) in safe_files:
      if type == 'orig':
        dangling_revid = import_orig(tree, filename, version,
                                     last_upstream=last_upstream)
        last_upstream = version.upstream_version
      elif type == 'diff':
        import_diff(tree, filename, version, dangling_revid=dangling_revid)
        dangling_revid = None
  finally:
    tree.unlock()

