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
from subprocess import Popen, PIPE

import deb822
from debian_bundle.changelog import Version

from bzrlib import (bzrdir,
                    urlutils,
                    )
from bzrlib.errors import FileExists, BzrError
from bzrlib.trace import warning, info
from bzrlib.transport import get_transport

from bzrlib.plugins.bzrtools.upstream_import import (import_tar,
                                                     )

from errors import ImportError
from merge_upstream import make_upstream_tag

# TODO: support native packages (should be easy).
# TODO: Use a transport to retrieve the files, so that they can be got remotely

def open_file(path, transport, base_dir=None):
  """Open a file, possibly over a transport.

  Open the named path, using the transport if not None. If the transport and
  base_dir are not None, then path will be interpreted relative to base_dir.
  """
  if transport is None:
    base_dir, path = urlutils.split(path)
    transport = get_transport(base_dir)
  else:
    if base_dir is not None:
      path = urlutils.join(base_dir, path)
  return (transport.get(path), transport)


class DscCache(object):

  def __init__(self, transport=None):
    self.cache = {}
    self.transport_cache = {}
    self.transport = transport

  def get_dsc(self, name):
    if name in self.cache:
      dsc1 = self.cache[name]
    else:
      (f1, transport) = open_file(name, self.transport)
      try:
        dsc1 = deb822.Dsc(f1)
      finally:
        f1.close()
      self.cache[name] = dsc1
      self.transport_cache[name] = transport
    return dsc1

  def get_transport(self, name):
    return self.transport_cache[name]

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


class DscImporter(object):

  transport = None

  def __init__(self, dsc_files):
    self.dsc_files = dsc_files

  def import_orig(self, tree, origname, version, last_upstream=None,
                  transport=None, base_dir=None):
    f = open_file(origname, transport, base_dir=base_dir)[0]
    try:
      dangling_revid = None
      if last_upstream is not None:
        dangling_revid = tree.branch.last_revision()
        old_upstream_revid = tree.branch.tags.lookup_tag(
                                 make_upstream_tag(last_upstream))
        tree.revert([],
                    tree.branch.repository.revision_tree(old_upstream_revid))
      import_tar(tree, f)
      if last_upstream is not None:
        tree.set_parent_ids([old_upstream_revid])
        revno = tree.branch.revision_id_to_revno(old_upstream_revid)
        tree.branch.set_last_revision_info(revno, old_upstream_revid)
      tree.commit('import upstream from %s' % (os.path.basename(origname)))
      upstream_version = version.upstream_version
      tree.branch.tags.set_tag(make_upstream_tag(upstream_version),
                               tree.branch.last_revision())
    finally:
      f.close()
    return dangling_revid

  def _patch_tree(self, patch, basedir):
    cmd = ['patch', '--strip', '1', '--quiet', '--directory', basedir]
    child_proc = Popen(cmd, stdin=PIPE)
    for line in patch:
      child_proc.stdin.write(line)
    child_proc.stdin.close()
    r = child_proc.wait()
    if r != 0:
      raise BzrError('patch failed')

  def _get_touched_paths(self, patch):
    cmd = ['lsdiff', '--strip', '1']
    child_proc = Popen(cmd, stdin=PIPE, stdout=PIPE)
    for line in patch:
      child_proc.stdin.write(line)
    child_proc.stdin.close()
    r = child_proc.wait()
    if r != 0:
      raise BzrError('lsdiff failed')
    touched_paths = []
    for filename in child_proc.stdout.readlines():
      if filename.endswith('\n'):
        filename = filename[:-1]
      touched_paths.append(filename)
    return touched_paths

  def import_diff(self, tree, diffname, version, dangling_revid=None,
                  transport=None, base_dir=None):
    upstream_version = version.upstream_version
    up_revid = tree.branch.tags.lookup_tag(make_upstream_tag(upstream_version))
    up_tree = tree.branch.repository.revision_tree(up_revid)
    if dangling_revid is None:
      current_revid = tree.branch.last_revision()
    else:
      current_revid = dangling_revid
    current_tree = tree.branch.repository.revision_tree(current_revid)
    tree.revert([], tree.branch.repository.revision_tree(up_revid))
    f = open_file(diffname, transport, base_dir=base_dir)[0]
    f = gzip.GzipFile(fileobj=f)
    try:
      self._patch_tree(f, tree.basedir)
      f.seek(0)
      touched_paths = self._get_touched_paths(f)
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
      if dangling_revid is not None:
        tree.add_parent_tree_id(dangling_revid)
      tree.commit('merge packaging changes from %s' % \
                  (os.path.basename(diffname)))
    finally:
      f.close()

  def _add_to_safe(self, file, version, type, base, transport):
    found = False
    for safe_file in self.safe_files:
      if file == safe_file[0]:
        found = True
        break
    if not found:
      self.safe_files.append((file, version, type, base, transport))

  def _check_orig_exists(self, version):
    found = False
    for safe_file in self.safe_files:
      if safe_file[0].endswith("_%s.orig.tar.gz" % version.upstream_version):
        found = True
        break
    if found == False:
      raise ImportError("There is no upstream tarball corresponding to %s" % \
                          version)

  def _check_package_name(self, name):
    if self.package_name is not None and name != self.package_name:
      raise ImportError("The reported package name has changed from %s to "
                        "%s. I don't know what to do in this case. If this "
                        "case should be handled, please contact the author "
                        "with details of your case, and the expected outcome."
                        % (self.package_name, name))
    self.package_name = name

  def _decode_dsc(self, dsc, dscname):
    orig_file = None
    diff_file = None
    self._check_package_name(dsc['Source'])
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
    if self.transport is not None:
      base_dir = urlutils.split(dscname)[0]
    else:
      base_dir = None
    dsc_transport = self.cache.get_transport(dscname)
    if orig_file is not None:
      self._add_to_safe(orig_file, version, 'orig', base_dir, dsc_transport)
    self._check_orig_exists(version)
    self._add_to_safe(diff_file, version, 'diff', base_dir, dsc_transport)

  def import_dsc(self, target_dir):
    if os.path.exists(target_dir):
      raise FileExists(target_dir)
    self.cache = DscCache(transport=self.transport)
    self.dsc_files.sort(cmp=DscComp(self.cache).cmp)
    self.safe_files = []
    self.package_name = None
    for dscname in self.dsc_files:
      dsc = self.cache.get_dsc(dscname)
      self._decode_dsc(dsc, dscname)
    os.mkdir(target_dir)
    format = bzrdir.format_registry.make_bzrdir('dirstate-tags')
    branch  = bzrdir.BzrDir.create_branch_convenience(target_dir,
                                                      format=format)
    tree = branch.bzrdir.open_workingtree()
    tree.lock_write()
    try:
      last_upstream = None
      dangling_revid = None
      for (filename, version, type, base_dir, transport) in self.safe_files:
        if type == 'orig':
          dangling_revid = self.import_orig(tree, filename, version,
                                            last_upstream=last_upstream,
                                            transport=transport,
                                            base_dir=base_dir)
          info("imported %s" % filename)
          last_upstream = version.upstream_version
        elif type == 'diff':
          self.import_diff(tree, filename, version,
                           dangling_revid=dangling_revid,
                           transport=transport, base_dir=base_dir)
          info("imported %s" % filename)
          dangling_revid = None
    finally:
      tree.unlock()


class SourcesImporter(DscImporter):
  """For importing all the .dsc files from a Sources file."""

  def __init__(self, base, sources_path):
    """Create a SourcesImporter.

    :param base: the base URI from which all paths should be interpreted.
    :type base: string
    :param sources_path: the path to the Sources file to import the
                         packages from, relative to the base parameter.
    :type base: string
    """
    self.base = urlutils.normalize_url(base)
    if isinstance(sources_path, unicode):
      sources_path = sources_path.encode('utf-8')
    self.sources_path = sources_path
    self.transport = get_transport(self.base)
    sources_file = self.transport.get(self.sources_path)
    if self.sources_path.endswith(".gz"):
      sources_file = gzip.GzipFile(fileobj=sources_file)
    dsc_files = []
    for source in sources_file.read().split('\n\n'):
      if source == '':
        continue
      source = deb822.Sources(source)
      base_dir = source['Directory']
      if not self._check_basedir(base_dir):
        continue
      for file_info in source['files']:
        name = file_info['name']
        if name.endswith('.dsc'):
          dsc_files.append(urlutils.join(base_dir, name))
    super(SourcesImporter, self).__init__(dsc_files)

  def _check_basedir(self, base_dir):
    return True


class SnapshotImporter(SourcesImporter):
  """Import all versions of a package recorded on snapshot.debian.net."""

  def __init__(self, package_name):
    base = 'http://snapshot.debian.net/archive/'
    path = 'pool/%s/%s/source/Sources.gz' % (package_name[0], package_name)
    super(SnapshotImporter, self).__init__(base, path)
    warning("snapshot.debian.net has lost packages from before 12/03/2005, "
            "only packages from after that date will be imported.")

  def _check_basedir(self, base_dir):
    import re
    match = re.match(r'(?P<year>\d\d\d\d)/(?P<month>\d\d)/(?P<day>\d\d)',
                     base_dir)
    if match is not None:
      year = int(match.group('year'))
      if year < 2005:
        return False
      if year == 2005:
        month = int(match.group('month'))
        if month < 3:
          return False
        if month == 3:
          day = int(match.group('day'))
          if day < 13:
            return False
    return True

