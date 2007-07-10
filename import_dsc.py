#    import_dsc.py -- Import a series of .dsc files.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#
#    Code is also taken from bzrtools, which is
#             (C) 2005, 2006, 2007 Aaron Bentley <aaron.bentley@utoronto.ca>
#             (C) 2005, 2006 Canonical Limited.
#             (C) 2006 Michael Ellerman.
#    and distributed under the GPL, version 2 or later.
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
import tarfile

import deb822
from debian_bundle.changelog import Version

from bzrlib import (bzrdir,
                    generate_ids,
                    urlutils,
                    )
from bzrlib.config import ConfigObj
from bzrlib.errors import FileExists, BzrError
from bzrlib.osutils import file_iterator, isdir, basename
from bzrlib.trace import warning, info
from bzrlib.transform import TreeTransform, cook_conflicts, resolve_conflicts
from bzrlib.transport import get_transport

from bzrlib.plugins.bzrtools.upstream_import import (common_directory,
                                                     names_of_files,
                                                     add_implied_parents,
                                                     )

from errors import ImportError
from merge_upstream import make_upstream_tag

# TODO: support explicit upstream branch.
# TODO: support incremental importing.

def import_tar(tree, tar_input, file_ids_from=None):
    """Replace the contents of a working directory with tarfile contents.
    The tarfile may be a gzipped stream.  File ids will be updated.
    """
    tar_file = tarfile.open('lala', 'r', tar_input)
    import_archive(tree, tar_file, file_ids_from=file_ids_from)


def do_directory(tt, trans_id, tree, relative_path, path):
    if isdir(path) and tree.path2id(relative_path) is not None:
        tt.cancel_deletion(trans_id)
    else:
        tt.create_directory(trans_id)


def import_archive(tree, archive_file, file_ids_from=None):
    prefix = common_directory(names_of_files(archive_file))
    tt = TreeTransform(tree)

    removed = set()
    for path, entry in tree.inventory.iter_entries():
        if entry.parent_id is None:
            continue
        trans_id = tt.trans_id_tree_path(path)
        tt.delete_contents(trans_id)
        removed.add(path)

    added = set()
    implied_parents = set()
    seen = set()
    for member in archive_file.getmembers():
        if member.type == 'g':
            # type 'g' is a header
            continue
        relative_path = member.name
        if prefix is not None:
            relative_path = relative_path[len(prefix)+1:]
            relative_path = relative_path.rstrip('/')
        if relative_path == '':
            continue
        add_implied_parents(implied_parents, relative_path)
        trans_id = tt.trans_id_tree_path(relative_path)
        added.add(relative_path.rstrip('/'))
        path = tree.abspath(relative_path)
        if member.name in seen:
            if tt.final_kind(trans_id) == 'file':
                tt.set_executability(None, trans_id)
            tt.cancel_creation(trans_id)
        seen.add(member.name)
        if member.isreg():
            tt.create_file(file_iterator(archive_file.extractfile(member)),
                           trans_id)
            executable = (member.mode & 0111) != 0
            tt.set_executability(executable, trans_id)
        elif member.isdir():
            do_directory(tt, trans_id, tree, relative_path, path)
        elif member.issym():
            tt.create_symlink(member.linkname, trans_id)
        else:
            continue
        if tt.tree_file_id(trans_id) is None:
            if (file_ids_from is not None and
                file_ids_from.has_filename(relative_path)):
                file_id = file_ids_from.path2id(relative_path)
                assert file_id is not None
                tt.version_file(file_id, trans_id)
            else:
                name = basename(member.name.rstrip('/'))
                file_id = generate_ids.gen_file_id(name)
                tt.version_file(file_id, trans_id)

    for relative_path in implied_parents.difference(added):
        if relative_path == "":
            continue
        trans_id = tt.trans_id_tree_path(relative_path)
        path = tree.abspath(relative_path)
        do_directory(tt, trans_id, tree, relative_path, path)
        if tt.tree_file_id(trans_id) is None:
            if (file_ids_from is not None and
                file_ids_from.has_filename(relative_path)):
                file_id = file_ids_from.path2id(relative_path)
                assert file_id is not None
                tt.version_file(file_id, trans_id)
            else:
                tt.version_file(trans_id, trans_id)
        added.add(relative_path)

    for path in removed.difference(added):
        tt.unversion_file(tt.trans_id_tree_path(path))

    for conflict in cook_conflicts(resolve_conflicts(tt), tt):
        warning(conflict)
    tt.apply()


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
      if self.orig_target is not None:
        if not os.path.isdir(self.orig_target):
          os.mkdir(self.orig_target)
        new_filename = os.path.join(self.orig_target,
                                    os.path.basename(origname))
        new_f = open(new_filename, 'wb')
        try:
          new_f.write(f.read())
        finally:
          new_f.close()
        f.close()
        f = open(new_filename)
      dangling_revid = None
      dangling_tree = None
      if last_upstream is not None:
        dangling_revid = tree.branch.last_revision()
        dangling_tree = tree.branch.repository.revision_tree(dangling_revid)
        old_upstream_revid = tree.branch.tags.lookup_tag(
                                 make_upstream_tag(last_upstream))
        tree.revert([],
                    tree.branch.repository.revision_tree(old_upstream_revid))
      import_tar(tree, f, file_ids_from=dangling_tree)
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

  def import_native(self, tree, origname, version, last_upstream=None,
                    transport=None, base_dir=None):
    f = open_file(origname, transport, base_dir=base_dir)[0]
    try:
      dangling_revid = None
      dangling_tree = None
      old_upstream_tree = None
      if last_upstream is not None:
        old_upstream_revid = tree.branch.tags.lookup_tag(
                                 make_upstream_tag(last_upstream))
        old_upstream_tree = tree.branch.repository.revision_tree(
                                  old_upstream_revid)
        if old_upstream_revid != tree.branch.last_revision():
          dangling_revid = tree.branch.last_revision()
          dangling_tree = tree.branch.repository.revision_tree(dangling_revid)
        tree.revert([],
                    tree.branch.repository.revision_tree(old_upstream_revid))
      import_tar(tree, f, file_ids_from=dangling_tree)
      if last_upstream is not None:
        tree.set_parent_ids([old_upstream_revid])
        revno = tree.branch.revision_id_to_revno(old_upstream_revid)
        tree.branch.set_last_revision_info(revno, old_upstream_revid)
      if dangling_revid is not None:
        tree.add_parent_tree_id(dangling_revid)
      config_filename = '.bzr-builddeb/default.conf'
      to_add = False
      to_add_dir = False
      if not tree.has_filename(config_filename):
        if not tree.has_filename(os.path.dirname(config_filename)):
          os.mkdir(os.path.join(tree.basedir,
                                os.path.dirname(config_filename)))
          to_add_dir = True
        conf = open(os.path.join(tree.basedir, config_filename), 'wb')
        conf.close()
        to_add = True
      config_ = ConfigObj(os.path.join(tree.basedir, config_filename))
      try:
        config_['BUILDDEB']
      except KeyError:
        config_['BUILDDEB'] = {}
      try:
        current_value = config_['BUILDDEB']['native']
      except KeyError:
        current_value = False
      if not current_value:
        config_['BUILDDEB']['native'] = True
        config_.write()
      if to_add_dir:
        file_id = None
        parent = os.path.dirname(config_filename)
        if old_upstream_tree is not None:
          file_id = old_upstream_tree.path2id(parent)
        if file_id is not None:
          tree.add([parent], [file_id])
        else:
          tree.add([parent])
      if to_add:
        file_id = None
        if old_upstream_tree is not None:
          file_id = old_upstream_tree.path2id(config_filename)
        if file_id is not None:
          tree.add([config_filename], [file_id])
        else:
          tree.add([config_filename])
      tree.commit('import package from %s' % (os.path.basename(origname)))
      upstream_version = version.upstream_version
      tree.branch.tags.set_tag(make_upstream_tag(upstream_version),
                               tree.branch.last_revision())
    finally:
      f.close()

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

  def _add_implied_parents(self, tree, implied_parents, path,
                           file_ids_from=None):
    parent = os.path.dirname(path)
    if parent == '':
      return
    if parent in implied_parents:
      return
    implied_parents.add(parent)
    self._add_implied_parents(tree, implied_parents, parent,
                              file_ids_from=file_ids_from)
    if file_ids_from is None:
      tree.add([parent])
    else:
      file_id = file_ids_from.path2id(parent)
      if file_id is None:
        tree.add([parent])
      else:
        tree.add([parent], [file_id])

  def _update_path_info(self, tree, touched_paths, other_parent, main_parent):
    implied_parents = set()
    for path in touched_paths:
      if not tree.has_filename(path):
        tree.remove([path], verbose=False)
      elif not other_parent.has_filename(path):
        self._add_implied_parents(tree, implied_parents, path,
                                  file_ids_from=other_parent)
        tree.add([path])
      elif not (main_parent.has_filename(path) and
                other_parent.has_filename(path)):
        self._add_implied_parents(tree, implied_parents, path,
                                  file_ids_from=other_parent)
        file_id = other_parent.path2id(path)
        if file_id is None:
          tree.add([path])
        else:
          tree.add([path], [file_id])

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
      self._update_path_info(tree, touched_paths, current_tree, up_tree)
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
    native_file = None
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
      elif name.endswith('.tar.gz'):
        if native_file is not None:
          raise ImportError("%s contains more than one .tar.gz" % dscname)
        native_file = name
    version = Version(dsc['Version'])
    if self.transport is not None:
      base_dir = urlutils.split(dscname)[0]
    else:
      base_dir = None
    dsc_transport = self.cache.get_transport(dscname)
    if native_file is not None:
      if diff_file is not None or orig_file is not None:
        raise ImportError("%s contains both a native package and a normal "
                          "package." % dscname)
      self._add_to_safe(native_file, version, 'native', base_dir,
                        dsc_transport)
    else:
      if diff_file is None:
        raise ImportError("%s contains only a .orig.tar.gz, it must contain a "
                          ".diff.gz as well" % dscname)
      if orig_file is not None:
        self._add_to_safe(orig_file, version, 'orig', base_dir, dsc_transport)
      self._check_orig_exists(version)
      self._add_to_safe(diff_file, version, 'diff', base_dir, dsc_transport)

  def import_dsc(self, target_dir, orig_target=None):
    if os.path.exists(target_dir):
      raise FileExists(target_dir)
    self.orig_target = orig_target
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
      last_native = False
      for (filename, version, type, base_dir, transport) in self.safe_files:
        if type == 'orig':
          if last_native:
            last_upstream = None
          dangling_revid = self.import_orig(tree, filename, version,
                                            last_upstream=last_upstream,
                                            transport=transport,
                                            base_dir=base_dir)
          info("imported %s" % filename)
          last_upstream = version.upstream_version
          last_native = False
        elif type == 'diff':
          self.import_diff(tree, filename, version,
                           dangling_revid=dangling_revid,
                           transport=transport, base_dir=base_dir)
          info("imported %s" % filename)
          dangling_revid = None
          last_native = False
        elif type == 'native':
          self.import_native(tree, filename, version,
                             last_upstream=last_upstream,
                             transport=transport, base_dir=base_dir)
          last_upstream = version.upstream_version
          last_native = True
          info("imported %s" % filename)
    finally:
      tree.unlock()


class SourcesImporter(DscImporter):
  """For importing all the .dsc files from a Sources file."""

  def __init__(self, base, sources_path, other_sources=[]):
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
    for source in deb822.Sources.iter_paragraphs(sources_file):
      base_dir = source['Directory']
      if not self._check_basedir(base_dir):
        continue
      for file_info in source['files']:
        name = file_info['name']
        if name.endswith('.dsc'):
          dsc_files.append(urlutils.join(base_dir, name))
    dsc_files += other_sources
    super(SourcesImporter, self).__init__(dsc_files)

  def _check_basedir(self, base_dir):
    return True


class SnapshotImporter(SourcesImporter):
  """Import all versions of a package recorded on snapshot.debian.net."""

  def __init__(self, package_name, other_sources=[]):
    base = 'http://snapshot.debian.net/archive/'
    path = 'pool/%s/%s/source/Sources.gz' % (package_name[0], package_name)
    super(SnapshotImporter, self).__init__(base, path, other_sources=other_sources)
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

