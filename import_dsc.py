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
import select
import shutil
import stat
from subprocess import Popen, PIPE
from StringIO import StringIO
import tarfile
import tempfile

from debian_bundle import deb822
from debian_bundle.changelog import Version, Changelog

from bzrlib import (bzrdir,
                    generate_ids,
                    osutils,
                    urlutils,
                    )
from bzrlib.config import ConfigObj
from bzrlib.errors import (FileExists,
        BzrError,
        UncommittedChanges,
        )
from bzrlib.osutils import file_iterator, isdir, basename, splitpath
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import warning, info, mutter
from bzrlib.transform import TreeTransform, cook_conflicts, resolve_conflicts
from bzrlib.transport import get_transport
from bzrlib.workingtree import WorkingTree

from bzrlib.plugins.bzrtools.upstream_import import (
                                                     names_of_files,
                                                     add_implied_parents,
                                                     )

from bzrlib.plugins.builddeb.errors import (ImportError,
                OnlyImportSingleDsc,
                UnknownType,
                )
from bzrlib.plugins.builddeb.merge_upstream import (make_upstream_tag,
                upstream_tag_to_version,
                )


files_to_ignore = set(['.cvsignore', '.arch-inventory', '.bzrignore',
    '.gitignore', 'CVS', 'RCS', '.deps', '{arch}', '.arch-ids', '.svn',
    '.hg', '_darcs', '.git', '.shelf', '.bzr', '.bzr.backup', '.bzrtags',
    '.bzr-builddeb'])

exclude_as_files = ['*/' + x for x in files_to_ignore]
exclude_as_dirs = ['*/' + x + '/*' for x in files_to_ignore]
exclude = exclude_as_files + exclude_as_dirs
underscore_x = ['-x'] * len(exclude)
ignore_arguments = []
map(ignore_arguments.extend, zip(underscore_x, exclude))
ignore_arguments = ignore_arguments + ['-x', '*,v']


def import_tar(tree, tar_input, file_ids_from=None):
    """Replace the contents of a working directory with tarfile contents.
    The tarfile may be a gzipped stream.  File ids will be updated.
    """
    tar_file = tarfile.open('lala', 'r', tar_input)
    import_archive(tree, tar_file, file_ids_from=file_ids_from)


class DirWrapper(object):
    def __init__(self, fileobj, mode='r'):
        assert mode == 'r', mode
        self.root = os.path.realpath(fileobj.read())

    def __repr__(self):
        return 'DirWrapper(%r)' % self.root

    def getmembers(self, subdir=None):
        if subdir is not None:
            mydir = os.path.join(self.root, subdir)
        else:
            mydir = self.root
        for child in os.listdir(mydir):
            if subdir is not None:
                child = os.path.join(subdir, child)
            fi = FileInfo(self.root, child)
            yield fi
            if fi.isdir():
                for v in self.getmembers(child):
                    yield v

    def extractfile(self, member):
        return open(member.fullpath)


class FileInfo(object):

    def __init__(self, root, filepath):
        self.fullpath = os.path.join(root, filepath)
        self.root = root
        if filepath != '':
            self.name = os.path.join(basename(root), filepath)
        else:
            self.name = basename(root)
        self.type = None
        stat = os.lstat(self.fullpath)
        self.mode = stat.st_mode
        if self.isdir():
            self.name += '/'

    def __repr__(self):
        return 'FileInfo(%r)' % self.name

    def isreg(self):
        return stat.S_ISREG(self.mode)

    def isdir(self):
        return stat.S_ISDIR(self.mode)

    def issym(self):
        if stat.S_ISLNK(self.mode):
            self.linkname = os.readlink(self.fullpath)
            return True
        else:
            return False

    def islnk(self):
        # This could be accurate, but the use below seems like
        # it wouldn't really care
        return False


def import_dir(tree, dir, file_ids_from=None):
    dir_input = StringIO(dir)
    dir_file = DirWrapper(dir_input)
    import_archive(tree, dir_file, file_ids_from=file_ids_from)


def do_directory(tt, trans_id, tree, relative_path, path):
    if isdir(path) and tree.path2id(relative_path) is not None:
        tt.cancel_deletion(trans_id)
    else:
        tt.create_directory(trans_id)


def should_ignore(relative_path):
  parts = splitpath(relative_path)
  if not parts:
    return False
  for part in parts:
    if part in files_to_ignore:
      return True
    if part.endswith(',v'):
      return True


def top_directory(path):
    """Return the top directory given in a path."""
    parts = osutils.splitpath(osutils.normpath(path))
    if len(parts) > 0:
      return parts[0]
    return ''


def common_directory(names):
    """Determine a single directory prefix from a list of names"""
    prefixes = set()
    prefixes.update(map(top_directory, names))
    if '' in prefixes:
      prefixes.remove('')
    if len(prefixes) != 1:
      return None
    prefix = prefixes.pop()
    if prefix == '':
      return None
    return prefix


def import_archive(tree, archive_file, file_ids_from=None):
    prefix = common_directory(names_of_files(archive_file))
    tt = TreeTransform(tree)

    if file_ids_from is None:
        file_ids_from = []

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
        relative_path = osutils.normpath(relative_path)
        relative_path = relative_path.lstrip('/')
        if prefix is not None:
            relative_path = relative_path[len(prefix)+1:]
        if relative_path == '' or relative_path == '.':
            continue
        if should_ignore(relative_path):
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
        if member.isreg() or member.islnk():
            tt.create_file(file_iterator(archive_file.extractfile(member)),
                           trans_id)
            executable = (member.mode & 0111) != 0
            tt.set_executability(executable, trans_id)
        elif member.isdir():
            do_directory(tt, trans_id, tree, relative_path, path)
        elif member.issym():
            tt.create_symlink(member.linkname, trans_id)
        else:
            raise UnknownType(relative_path)
        if tt.tree_file_id(trans_id) is None:
            found = False
            for other_tree in file_ids_from:
                if other_tree.has_filename(relative_path):
                    file_id = other_tree.path2id(relative_path)
                    assert file_id is not None
                    tt.version_file(file_id, trans_id)
                    found = True
                    break
            if not found:
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
            found = False
            for other_tree in file_ids_from:
                if other_tree.has_filename(relative_path):
                    file_id = other_tree.path2id(relative_path)
                    assert file_id is not None
                    tt.version_file(file_id, trans_id)
                    found = True
                    break
            if not found:
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
                  transport=None, base_dir=None, dangling_tree=None):
    f = open_file(origname, transport, base_dir=base_dir)[0]
    try:
      if self.orig_target is not None:
        # Make the orig dir and copy the orig tarball in to it
        if not os.path.isdir(self.orig_target):
          os.mkdir(self.orig_target)
        new_filename = os.path.join(self.orig_target,
                                    os.path.basename(origname))
        contents = f.read()
        new_f = open(new_filename, 'wb')
        try:
          new_f.write(contents)
        finally:
          new_f.close()
        f.close()
        f = open(new_filename)
      dangling_revid = None
      if last_upstream is not None:
        dangling_revid = tree.branch.last_revision()
        dangling_tree = tree.branch.repository.revision_tree(dangling_revid)
        old_upstream_revid = tree.branch.tags.lookup_tag(
                                 make_upstream_tag(last_upstream))
        tree.revert(None,
                    tree.branch.repository.revision_tree(old_upstream_revid))
      file_ids_from = []
      if dangling_tree is not None:
        file_ids_from = [dangling_tree]
      import_tar(tree, f, file_ids_from=file_ids_from)
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
        tree.revert(None,
                    tree.branch.repository.revision_tree(old_upstream_revid))
      file_ids_from = []
      if dangling_tree is not None:
        file_ids_from = [dangling_tree]
      import_tar(tree, f, file_ids_from=file_ids_from)
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
      if os.path.isfile(os.path.join(tree.basedir, 'debian', 'rules')):
        os.chmod(os.path.join(tree.basedir, 'debian', 'rules'),
                 (stat.S_IRWXU|stat.S_IRGRP|stat.S_IXGRP|stat.S_IROTH|
                  stat.S_IXOTH))
      tree.commit('import package from %s' % (os.path.basename(origname)))
      upstream_version = version.upstream_version
      tree.branch.tags.set_tag(make_upstream_tag(upstream_version),
                               tree.branch.last_revision())
    finally:
      f.close()

  def _make_filter_proc(self):
    """Create a filterdiff subprocess."""
    filter_cmd = ['filterdiff'] + ignore_arguments
    filter_proc = Popen(filter_cmd, stdin=PIPE, stdout=PIPE)
    return filter_proc

  def _patch_tree(self, patch, basedir):
    """Patch a tree located at basedir."""
    filter_proc = self._make_filter_proc()
    patch_cmd =  ['patch', '-g', '0', '--strip', '1', '--quiet', '-f',
                  '--directory', basedir]
    patch_proc = Popen(patch_cmd, stdin=filter_proc.stdout, close_fds=True)
    for line in patch:
      filter_proc.stdin.write(line)
      filter_proc.stdin.flush()
    filter_proc.stdin.close()
    r = patch_proc.wait()
    if r != 0:
      raise BzrError('patch failed')

  def _get_touched_paths(self, patch):
    filter_proc = self._make_filter_proc()
    cmd = ['lsdiff', '--strip', '1']
    child_proc = Popen(cmd, stdin=filter_proc.stdout, stdout=PIPE,
                       close_fds=True)
    output = ''
    for line in patch:
      filter_proc.stdin.write(line)
      filter_proc.stdin.flush()
      while select.select([child_proc.stdout], [], [], 0)[0]:
          output += child_proc.stdout.read(1)
    filter_proc.stdin.close()
    output += child_proc.stdout.read()
    touched_paths = []
    for filename in output.split('\n'):
      if filename.endswith('\n'):
        filename = filename[:-1]
      if filename != "":
        touched_paths.append(filename)
    r = child_proc.wait()
    if r != 0:
      raise BzrError('lsdiff failed')
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

  def _get_upstream_tree(self, version, tree):
    upstream_version = version.upstream_version
    up_revid = tree.branch.tags.lookup_tag(make_upstream_tag(upstream_version))
    return tree.branch.repository.revision_tree(up_revid)


  def import_diff(self, tree, diffname, version, dangling_revid=None,
                  transport=None, base_dir=None, no_add_extra_parent=False):
    up_tree = self._get_upstream_tree(version, tree)
    if dangling_revid is None:
      current_revid = tree.branch.last_revision()
    else:
      current_revid = dangling_revid
    current_tree = tree.branch.repository.revision_tree(current_revid)
    tree.revert(None, up_tree)
    f = open_file(diffname, transport, base_dir=base_dir)[0]
    f = gzip.GzipFile(fileobj=f)
    try:
      self._patch_tree(f, tree.basedir)
      if os.path.isfile(os.path.join(tree.basedir, 'debian', 'rules')):
        os.chmod(os.path.join(tree.basedir, 'debian', 'rules'),
                 (stat.S_IRWXU|stat.S_IRGRP|stat.S_IXGRP|stat.S_IROTH|
                  stat.S_IXOTH))
      f.seek(0)
      touched_paths = self._get_touched_paths(f)
      self._update_path_info(tree, touched_paths, current_tree, up_tree)
      if (not no_add_extra_parent and dangling_revid is not None):
        tree.add_parent_tree_id(dangling_revid)
      message = 'merge packaging changes from %s' % \
                  (os.path.basename(diffname))
      author = None
      changelog_path = os.path.join(tree.basedir, 'debian', 'changelog')
      if os.path.exists(changelog_path):
        changelog_contents = open(changelog_path).read()
        changelog = Changelog(file=changelog_contents, max_blocks=1)
        if changelog._blocks:
          author = changelog._blocks[0].author
          changes = changelog._blocks[0].changes()
          message = ''
          sep = ''
          for change in reversed(changes):
            message = change + sep + message
            sep = "\n"
      tree.commit(message, author=author)
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

  def _decode_dsc(self, dsc, dscname, incremental=False):
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
      if not incremental:
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
    format = bzrdir.format_registry.make_bzrdir('default')
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

  def _find_last_upstream(self, tree, version):
    last_upstream = None
    previous_upstream = None
    tag_dict = tree.branch.tags.get_reverse_tag_dict()
    for rev in reversed(tree.branch.revision_history()):
      if rev in tag_dict:
        for poss_tag in tag_dict[rev]:
          poss_version = upstream_tag_to_version(poss_tag)
          if poss_version is None:
            continue
          if poss_version < version:
            return poss_version, previous_upstream
          previous_upstream = poss_version
    return None, previous_upstream

  def incremental_import_dsc(self, target, orig_target=None):
    self.orig_target = orig_target
    tree = WorkingTree.open_containing(target)[0]
    if tree.changes_from(tree.basis_tree()).has_changed():
      raise UncommittedChanges(tree)
    self.cache = DscCache(transport=self.transport)
    if len(self.dsc_files) > 1:
      raise OnlyImportSingleDsc
    self.safe_files = []
    self.package_name = None
    dsc = self.cache.get_dsc(self.dsc_files[0])
    self._decode_dsc(dsc, self.dsc_files[0], incremental=True)
    tree.lock_write()
    try:
      current_rev_id = tree.branch.last_revision()
      current_revno = tree.branch.revision_id_to_revno(current_rev_id)
      dangling_revid = None
      merge_base = None
      for (filename, version, type, base_dir, transport) in self.safe_files:
        if type == 'diff':
          self.import_diff(tree, filename, version,
                           dangling_revid=dangling_revid,
                           transport=transport, base_dir=base_dir,
                           no_add_extra_parent=True)
          info("imported %s" % filename)
          dangling_revid = tree.branch.last_revision()
          tree.pull(tree.branch, overwrite=True, stop_revision=current_rev_id)
          tree.merge_from_branch(tree.branch, to_revision=dangling_revid,
                  from_revision=merge_base)
        elif type == 'orig':
          dangling_tree = None
          last_upstream, previous_upstream = \
              self._find_last_upstream(tree, version)
          if last_upstream is None:
            dangling_revid = tree.branch.tags.lookup_tag(
                make_upstream_tag(previous_upstream))
            dangling_tree = tree.branch.repository.revision_tree(dangling_revid)
            tree.revert(None,
                tree.branch.repository.revision_tree(NULL_REVISION),
                backups=False)
            tree.set_parent_ids([])
            tree.branch.set_last_revision_info(0, NULL_REVISION)
          dangling_revid = self.import_orig(tree, filename, version,
                                            last_upstream=last_upstream,
                                            transport=transport,
                                            dangling_tree=dangling_tree,
                                            base_dir=base_dir)
          if last_upstream is None:
            merge_base = NULL_REVISION
            dangling_revid = current_rev_id
          info("imported %s" % filename)
        elif type == 'native':
          assert False, "Native packages not yet supported"
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

# vim: ts=2 sts=2 sw=2


class DistributionBranchSet(object):
    """A collection of DistributionBranches with an ordering.

    A DistributionBranchSet collects a group of DistributionBranches
    and an order, and then can provide the branches with information
    about their place in the relationship with other branches.
    """

    def __init__(self):
        """Create a DistributionBranchSet."""
        self._branch_list = []

    def add_branch(self, branch):
        """Adds a DistributionBranch to the end of the list.

        Appends the passed distribution branch to the end of the list
        that this DistributionBranchSet represents. It also provides
        the distribution branch with a way to get the branches that
        are before and after it in the list.

        It will call branch.set_get_lesser_branches_callback() and
        branch.set_get_greater_branches_callback(), passing it methods
        that the DistributionBranch can call to get the list of branches
        before it in the list and after it in the list respectively.
        The passed methods take no arguments and return a list (possibly
        empty) of the desired branches.

        :param branch: the DistributionBranch to add.
        """
        self._branch_list.append(branch)
        lesser_callback = self._make_lesser_callback(branch)
        branch.set_get_lesser_branches_callback(lesser_callback)
        greater_callback = self._make_greater_callback(branch)
        branch.set_get_greater_branches_callback(greater_callback)

    def _make_lesser_callback(self, branch):
        return lambda: self.get_lesser_branches(branch)

    def _make_greater_callback(self, branch):
        return lambda: self.get_greater_branches(branch)

    def get_lesser_branches(self, branch):
        """Return the list of branches less than the argument.

        :param branch: The branch that all branches returned must be less
            than.
        :return: a (possibly empty) list of all the branches that are
            less than the argument. The list is sorted starting with the
            least element.
        """
        index = self._branch_list.index(branch)
        return self._branch_list[:index]

    def get_greater_branches(self, branch):
        """Return the list of branches greater than the argument.

        :param branch: The branch that all branches returned must be greater
            than.
        :return: a (possibly empty) list of all the branches that are
            greater than the argument. The list is sorted starting with the
            least element.
        """
        index = self._branch_list.index(branch)
        return self._branch_list[index+1:]


class DistributionBranch(object):
    """A DistributionBranch is a representation of one line of development.

    It is a branch that is linked to a line of development, such as Debian
    unstable. It also has associated branches, some of which are "lesser"
    and some are "greater". A lesser branch is one that this branch
    derives from. A greater branch is one that derives from this. For
    instance Debian experimental would have unstable as a lesser branch,
    and vice-versa. It is assumed that a group of DistributionBranches will
    have a total ordering with respect to these relationships.
    """

    def __init__(self, name, branch, upstream_branch, tree=None,
            upstream_tree=None):
        """Create a distribution branch.

        You can only import packages on to the DistributionBranch
        if both tree and upstream_tree are provided.

        :param name: a String which is used as a descriptive name.
        :param branch: the Branch for the packaging part.
        :param upstream_branch: the Branch for the upstream part, if any.
        :param tree: an optional tree for the branch.
        :param upstream_tree: an optional upstream_tree for the
            upstream_branch.
        """
        self.name = name
        self.branch = branch
        self.upstream_branch = upstream_branch
        self.tree = tree
        self.upstream_tree = upstream_tree
        if self.tree is not None:
            assert self.upstream_tree is not None
        if self.upstream_tree is not None:
            assert self.tree is not None
        self.get_lesser_branches = None
        self.get_greater_branches = None

    def set_get_lesser_branches_callback(self, callback):
        """Set the callback to get the branches "lesser" than this.

        The function passed to this method will be used to get the
        list of branches that are "lesser" than this one. It is
        expected to require no arguments, and to return the desired
        (possibly empty) list of branches. The returned list should
        be sorted starting with the least element.

        :param callback: a function that is called to get the desired list
            of branches.
        """
        self.get_lesser_branches = callback

    def set_get_greater_branches_callback(self, callback):
        """Set the callback to get the branches "greater" than this.

        The function passed to this method will be used to get the
        list of branches that are "greater" than this one. It is
        expected to require no arguments, and to return the desired
        (possibly empty) list of branches. The returned list should
        be sorted starting with the least element.

        :param callback: a function that is called to get the desired list
            of branches.
        """
        self.get_greater_branches = callback

    def get_other_branches(self):
        """Return all the other branches in this set.

        The returned list will be ordered, and will not contain this
        branch.

        :return: a list of all the other branches in this set (if any).
        """
        return self.get_lesser_branches() + self.get_greater_branches()

    def tag_name(self, version):
        """Gets the name of the tag that is used for the version.

        :param version: the Version object that the tag should refer to.
        :return: a String with the name of the tag.
        """
        return self.name + "-" + str(version)

    def upstream_tag_name(self, version):
        """Gets the tag name for the upstream part of version.

        :param version: the Version object to extract the upstream
            part of the version number from.
        :return: a String with the name of the tag.
        """
        return "upstream-" + self.tag_name(version.upstream_version)

    def _has_version(self, branch, tag_name, md5=None):
        if branch.tags.has_tag(tag_name):
            if md5 is None:
                return True
            revid = branch.tags.lookup_tag(tag_name)
            rev = branch.repository.get_revision(revid)
            try:
                return rev.properties['deb-md5'] == md5
            except KeyError:
                warning("tag %s present in branch, but there is no "
                    "associated 'deb-md5' property" % tag_name)
                pass
        return False

    def has_version(self, version, md5=None):
        """Whether this branch contains the package version specified.

        The version must be judged present by having the appropriate tag
        in the branch. If the md5 argument is not None then the string
        passed must the the md5sum that is associated with the revision
        pointed to by the tag.

        :param version: a Version object to look for in this branch.
        :param md5: a string with the md5sum that if not None must be
            associated with the revision.
        :return: True if this branch contains the specified version of the
            package. False otherwise.
        """
        tag_name = self.tag_name(version)
        return self._has_version(self.branch, tag_name, md5=md5)

    def has_upstream_version(self, version, md5=None):
        """Whether this branch contains the upstream version specified.

        The version must be judged present by having the appropriate tag
        in the upstream branch. If the md5 argument is not None then the
        string passed must the the md5sum that is associated with the
        revision pointed to by the tag.

        :param version: a Version object from which to extract the upstream
            version number to look for in the upstream branch.
        :param md5: a string with the md5sum that if not None must be
            associated with the revision.
        :return: True if the upstream branch contains the specified upstream
            version of the package. False otherwise.
        """
        tag_name = self.upstream_tag_name(version)
        return self._has_version(self.upstream_branch, tag_name, md5=md5)

    def contained_versions(self, versions):
        """Splits a list of versions depending on presence in the branch.

        Partitions the input list of versions depending on whether they
        are present in the branch or not.

        The two output lists will be sorted in the same order as the input
        list.

        :param versions: a list of Version objects to look for in the
            branch. May be an empty list.
        :return: A tuple of two lists. The first list is the list of those
            items from the input list that are present in the branch. The
            second list is the list of those items from the input list that
            are not present in the branch. The two lists will be disjoint
            and cover the input list. Either list may be empty, or both if
            the input list is empty.
        """
        #FIXME: should probably do an ancestory check to find all
        # merged revisions. This will avoid adding an extra parent
        # when say
        # experimental 1-1~rc1
        # unstable 1-1 1-1~rc1
        # Ubuntu 1-1ubuntu1 1-1 1-1~rc1
        # where only the first in each list is actually uploaded.
        contained = []
        not_contained = []
        for version in versions:
            if self.has_version(version):
                contained.append(version)
            else:
                not_contained.append(version)
        return contained, not_contained

    def missing_versions(self, versions):
        """Returns the versions from the list that the branch does not have.

        Looks at all the versions specified and returns a list of the ones
        that are earlier in the list that the last version that is
        contained in this branch.

        :param versions: a list of Version objects to look for in the branch.
            May be an empty list.
        :return: The subset of versions from the list that are not present
            in this branch. May be an empty list.
        """
        last_contained = self.last_contained_version(versions)
        if last_contained is None:
            return versions
        index = versions.index(last_contained)
        return versions[:index]

    def last_contained_version(self, versions):
        """Returns the highest version from the list present in this branch.

        It assumes that the input list of versions is sorted with the
        highest version first.

        :param versions: a list of Version objects to look for in the branch.
            Must be sorted with the highest version first. May be an empty
            list.
        :return: the highest version that is contained in this branch, or
            None if none of the versions are contained within the branch.
        """
        for version in versions:
            if self.has_version(version):
                return version
        return None

    def revid_of_version(self, version):
        """Returns the revision id corresponding to that version.

        :param version: the Version object that you wish to retrieve the
            revision id of. The Version must be present in the branch.
        :return: the revision id corresponding to that version
        """
        return self.branch.tags.lookup_tag(self.tag_name(version))

    def revid_of_upstream_version(self, version):
        """Returns the revision id corresponding to the upstream version.

        :param version: the Version object to extract the upstream version
            from to retreive the revid of. The upstream version must be
            present in the upstream branch.
        :return: the revision id corresponding to the upstream portion
            of the version
        """
        tag_name = self.upstream_tag_name(version)
        return self.upstream_branch.tags.lookup_tag(tag_name)

    def tag_version(self, version):
        """Tags the branch's last revision with the given version.

        Sets a tag on the last revision of the branch with a tag that refers
        to the version provided.

        :param version: the Version object to derive the tag name from.
        """
        tag_name = self.tag_name(version)
        self.branch.tags.set_tag(tag_name,
                self.branch.last_revision())

    def tag_upstream_version(self, version):
        """Tags the upstream branch's last revision with an upstream version.

        Sets a tag on the last revision of the upstream branch with a tag
        that refers to the upstream part of the version provided.

        :param version: the Version object from which to extract the upstream
            part of the version number to derive the tag name from.
        """
        tag_name = self.upstream_tag_name(version)
        self.upstream_branch.tags.set_tag(tag_name,
                self.upstream_branch.last_revision())

    def is_version_native(self, version):
        """Determines whether the given version is native.

        :param version: the Version object to test. Must be present in
            the branch.
        :return: True if the version is was recorded as native when
            imported, False otherwise.
        """
        revid = self.revid_of_version(version)
        rev = self.branch.repository.get_revision(revid)
        try:
            prop = rev.properties["deb-native"]
            return prop == "True"
        except KeyError:
            return False

    def branch_to_pull_version_from(self, version, md5):
        """Checks whether this upload is a pull from a lesser branch.

        Looks in all the lesser branches for the given version/md5 pair
        in a branch that has not diverged from this.

        If it is present in a lower branch that has not diverged this
        method will return the greatest branch that it is present in,
        otherwise it will return None. If it returns a branch then it
        indicates that a pull should be done from that branch, rather
        than importing the version as a new revision in this branch.

        :param version: the Version object to look for in the lesser
            branches.
        :param md5: a String containing the md5 associateed with the
            version.
        :return: a DistributionBranch object to pull from if that is
            what should be done, otherwise None.
        """
        assert md5 is not None, \
            ("It's not a good idea to use branch_to_pull_version_from with "
             "md5 == None, as you may pull the wrong revision.")
        self.branch.lock_read()
        try:
            for branch in reversed(self.get_lesser_branches()):
                if branch.has_version(version, md5=md5):
                    # Check that they haven't diverged
                    branch.branch.lock_read()
                    try:
                        graph = branch.branch.repository.get_graph(
                                self.branch.repository)
                        if len(graph.heads([branch.branch.last_revision(),
                                    self.branch.last_revision()])) == 1:
                            return branch
                    finally:
                        branch.branch.unlock()
            return None
        finally:
            self.branch.unlock()

    def branch_to_pull_upstream_from(self, version, md5):
        """Checks whether this upstream is a pull from a lesser branch.

        Looks in all the lesser upstream branches for the given
        version/md5 pair in a branch that has not diverged from this.
        If it is present in a lower branch this method will return the
        greatest branch that it is present in that has not diverged,
        otherwise it will return None. If it returns a branch then it
        indicates that a pull should be done from that branch, rather
        than importing the upstream as a new revision in this branch.

        :param version: the Version object to use the upstream part
            of when searching in the lesser branches.
        :param md5: a String containing the md5 associateed with the
            upstream version.
        :return: a DistributionBranch object to pull the upstream from
            if that is what should be done, otherwise None.
        """
        assert md5 is not None, \
            ("It's not a good idea to use branch_to_pull_upstream_from with "
             "md5 == None, as you may pull the wrong revision.")
        up_branch = self.upstream_branch
        up_branch.lock_read()
        try:
            for branch in reversed(self.get_lesser_branches()):
                if branch.has_upstream_version(version, md5=md5):
                    # Check for divergenge.
                    other_up_branch = branch.upstream_branch
                    other_up_branch.lock_read()
                    try:
                        graph = other_up_branch.repository.get_graph(
                                up_branch.repository)
                        if len(graph.heads([other_up_branch.last_revision(),
                                    up_branch.last_revision()])) == 1:
                            return branch
                    finally:
                        other_up_branch.unlock()
            return None
        finally:
            up_branch.unlock()

    def get_parents(self, versions):
        """Return the list of parents for a specific version.

        This method returns the list of revision ids that should be parents
        for importing a specifc package version. The specific package version
        is the first element of the list of versions passed.

        The parents are determined by looking at the other versions in the
        passed list and examining which of the branches (if any) they are
        already present in.

        You should probably use get_parents_with_upstream rather than
        this method.

        :param versions: a list of Version objects, the first item of
            which is the version of the package that is currently being
            imported.
        :return: a list of tuples of (DistributionBranch, version,
            revision id). The revision ids should all be parents of the
            revision that imports the specified version of the package.
            The versions are the versions that correspond to that revision
            id. The DistributionBranch is the branch that contains that
            version.
        """
        assert len(versions) > 0, "Need a version to import"
        mutter("Getting parents of %s" % str(versions))
        missing_versions = self.missing_versions(versions)
        mutter("Versions we don't have are %s" % str(missing_versions))
        last_contained_version = self.last_contained_version(versions)
        parents = []
        if last_contained_version is not None:
            assert last_contained_version != versions[0], \
                "Reupload of a version?"
            mutter("The last versions we do have is %s" \
                    % str(last_contained_version))
            parents = [(self, last_contained_version,
                    self.revid_of_version(last_contained_version))]
        else:
            mutter("We don't have any of those versions")
        for branch in reversed(self.get_lesser_branches()):
            merged, missing_versions = \
                branch.contained_versions(missing_versions)
            if merged:
                revid = branch.revid_of_version(merged[0])
                parents.append((branch, merged[0], revid))
                mutter("Adding merge from lesser of %s for version %s from "
                    "branch %s" % (revid, str(merged[0]), branch.name))
                #FIXME: should this really be here?
                branch.branch.tags.merge_to(self.branch.tags)
                self.branch.fetch(branch.branch,
                        last_revision=revid)
        for branch in self.get_greater_branches():
            merged, missing_versions = \
                branch.contained_versions(missing_versions)
            if merged:
                revid = branch.revid_of_version(merged[0])
                parents.append((branch, merged[0], revid))
                mutter("Adding merge from greater of %s for version %s from "
                    "branch %s" % (revid, str(merged[0]), branch.name))
                #FIXME: should this really be here?
                branch.branch.tags.merge_to(self.branch.tags)
                self.branch.fetch(branch.branch,
                        last_revision=revid)
        return parents

    def pull_upstream_from_branch(self, pull_branch, version):
        """Pulls an upstream version from a branch.

        Given a DistributionBranch and a version number this method
        will pull the upstream part of the given version from the
        branch in to this. The upstream version must be present
        in the DistributionBranch, and it is assumed that the md5
        matches.

        It sets the necessary tags so that the pulled version is
        recognised as being part of this branch.

        :param pull_branch: the DistributionBranch to pull from.
        :param version: the Version to use the upstream part of.
        """
        pull_revision = pull_branch.revid_of_upstream_version(version)
        mutter("Pulling upstream part of %s from revision %s of %s" % \
                (str(version), pull_revision, pull_branch.name))
        up_pull_branch = pull_branch.upstream_branch
        assert self.upstream_tree is not None, \
            "Can't pull upstream with no tree"
        self.upstream_tree.pull(up_pull_branch,
                stop_revision=pull_revision)
        self.tag_upstream_version(version)
        self.branch.fetch(self.upstream_branch, last_revision=pull_revision)

    def pull_version_from_branch(self, pull_branch, version, native=False):
        """Pull a version from a particular branch.

        Given a DistributionBranch and a version number this method
        will pull the given version from the branch in to this. The
        version must be present in the DistributionBranch, and it
        is assumed that the md5 matches.

        It will also pull in any upstream part that is needed to
        the upstream branch. It is assumed that the md5 matches
        here as well. If the upstream version must be present in
        at least one of the upstream branches.

        It sets the necessary tags on the revisions so they are
        recongnised in this branch as well.

        :param pull_branch: the DistributionBranch to pull from.
        :param version: the Version to pull.
        :param native: whether it is a native version that is being
            imported.
        """
        pull_revision = pull_branch.revid_of_version(version)
        mutter("%s already has version %s so pulling from revision %s"
                % (pull_branch.name, str(version), pull_revision))
        assert self.tree is not None, "Can't pull branch with no tree"
        self.tree.pull(pull_branch.branch, stop_revision=pull_revision)
        self.tag_version(version)
        if not native and not self.has_upstream_version(version):
            if pull_branch.has_upstream_version(version):
                self.pull_upstream_from_branch(pull_branch, version)
            else:
                assert False, "Can't find the needed upstream part"
        elif native:
            mutter("Not checking for upstream as it is a native package")
        else:
            mutter("Not importing the upstream part as it is already "
                    "present in the upstream branch")

    def get_parents_with_upstream(self, version, versions,
            force_upstream_parent=False):
        """Get the list of parents including any upstream parents.

        Further to get_parents this method includes any upstream parents
        that are needed. An upstream parent is needed if none of
        the other parents include the upstream version. The needed
        upstream must already present in the upstream branch before
        calling this method.

        If force_upstream_parent is True then the upstream parent will
        be included, even if another parent is already using that
        upstream. This is for use in cases where the .orig.tar.gz
        is different in two ditributions.

        :param version: the Version that we are currently importing.
        :param versions: the list of Versions that are ancestors of
            version, including version itself. Sorted with the latest
            versions first, so version must be the first entry.
        :param force_upstream_parent: if True then an upstream parent
            will be added as the first parent, regardless of what the
            other parents are.
        :return: a list of revision ids that should be the parents when
            importing the specified revision.
        """
        assert version == versions[0], \
            "version is not the first entry of versions"
        parents = self.get_parents(versions)
        need_upstream_parent = True
        if not force_upstream_parent:
            for parent_pair in parents:
                if (parent_pair[1].upstream_version == \
                        version.upstream_version):
                    need_upstream_parent = False
                    break
        real_parents = [p[2] for p in parents]
        if need_upstream_parent:
            parent_revid = self.revid_of_upstream_version(version)
            if len(parents) > 0:
                real_parents.insert(1, parent_revid)
            else:
                real_parents = [parent_revid]
        return real_parents

    def import_upstream(self, upstream_part, version, md5, upstream_parents):
        """Import an upstream part on to the upstream branch.

        This imports the upstream part of the code and places it on to
        the upstream branch, setting the necessary tags.

        :param upstream_part: the path of a directory containing the
            unpacked upstream part of the source package.
        :param version: the Version of the package that is being imported.
        :param md5: the md5 of the upstream part.
        :param upstream_parents: the parents to give the upstream revision
        """
        # Should we just dump the upstream part on whatever is currently
        # there, or try and pull all of the other upstream versions
        # from lesser branches first? For now we'll just dump it on.
        # TODO: this method needs a lot of work for when we will make
        # the branches writeable by others.
        mutter("Importing upstream version %s from %s with parents %s" \
                % (version, upstream_part, str(upstream_parents)))
        assert self.upstream_tree is not None, \
            "Can't import upstream with no tree"
        if len(upstream_parents) > 0:
            parent_revid = upstream_parents[0]
        else:
            parent_revid = NULL_REVISION
        self.upstream_tree.pull(self.upstream_tree.branch, overwrite=True,
                stop_revision=parent_revid)
        other_branches = self.get_other_branches()
        def get_last_revision_tree(br):
            return br.repository.revision_tree(br.last_revision())
        upstream_trees = [get_last_revision_tree(o.upstream_branch)
            for o in other_branches]
        import_dir(self.upstream_tree, upstream_part,
                file_ids_from=upstream_trees + [self.tree])
        self.upstream_tree.set_parent_ids(upstream_parents)
        revid = self.upstream_tree.commit("Import upstream version %s" \
                % (str(version.upstream_version),),
                revprops={"deb-md5":md5})
        self.tag_upstream_version(version)
        self.branch.fetch(self.upstream_branch, last_revision=revid)

    def _get_commit_message_from_changelog(self):
        """Retrieves the messages from the last section of debian/changelog.

        Reads the last section of debian/changelog and returns the
        text of the changes in that section, it also returns the 
        uploader of that change.

        :return: a tuple (message, author), both Strings. If the
            information is not available then either can be None.
        """
        changelog_path = os.path.join(self.tree.basedir, 'debian',
            'changelog')
        author = None
        message = None
        if os.path.exists(changelog_path):
          changelog_contents = open(changelog_path).read()
          changelog = Changelog(file=changelog_contents, max_blocks=1)
          if changelog._blocks:
            author = changelog._blocks[0].author
            changes = changelog._blocks[0].changes()
            message = ''
            sep = ''
            for change in reversed(changes):
              message = change + sep + message
              sep = "\n"
        return (message, author)

    def import_debian(self, debian_part, version, parents, md5,
            native=False):
        """Import the debian part of a source package.

        :param debian_part: the path of a directory containing the unpacked
            source package.
        :param version: the Version of the source package.
        :param parents: a list of revision ids that should be the
            parents of the imported revision.
        :param md5: the md5 sum reported by the .dsc for
            the .diff.gz part of this source package.
        """
        mutter("Importing debian part for version %s from %s, with parents "
                "%s" % (str(version), debian_part, str(parents)))
        assert self.tree is not None, "Can't import with no tree"
        # First we move the branch to the first parent
        if parents:
            if self.branch.last_revision() == NULL_REVISION:
                parent_revid = parents[0]
                self.tree.pull(self.tree.branch, overwrite=True,
                        stop_revision=parent_revid)
            elif parents[0] != self.branch.last_revision():
                mutter("Adding current tip as parent: %s"
                        % self.branch.last_revision())
                parents.insert(0, self.branch.last_revision())
        elif self.branch.last_revision() != NULL_REVISION:
            # We were told to import with no parents. That's not
            # right, so import with the current parent. Should
            # perhaps be fixed in the methods to determine the parents.
            mutter("Told to import with no parents. Adding current tip "
                   "as the single parent")
            parents = [self.branch.last_revision()]
        other_branches = self.get_other_branches()
        def get_last_revision_tree(br):
            return br.repository.revision_tree(br.last_revision())
        debian_trees = [get_last_revision_tree(o.branch)
            for o in other_branches]
        parent_trees = []
        for parent in parents:
            parent_trees.append(self.branch.repository.revision_tree(
                        parent))
        import_dir(self.tree, debian_part,
                file_ids_from=parent_trees + debian_trees)
        rules_path = os.path.join(self.tree.basedir, 'debian', 'rules')
        if os.path.isfile(rules_path):
            os.chmod(rules_path,
                     (stat.S_IRWXU|stat.S_IRGRP|stat.S_IXGRP|
                      stat.S_IROTH|stat.S_IXOTH))
        self.tree.set_parent_ids(parents)
        (message, author) = self._get_commit_message_from_changelog()
        if message is None:
            message = 'Import packaging changes for version %s' % \
                        (str(version),)
        revprops={"deb-md5":md5}
        if native:
            revprops['deb-native'] = "True"
        self.tree.commit(message, author=author, revprops=revprops)
        self.tag_version(version)

    def _get_dsc_part(self, dsc, end):
        """Get the path and md5 of a file ending with end in dsc."""
        files = dsc['files']
        for file_info in files:
            name = file_info['name']
            if name.endswith(end):
                filename = name
                md5 = file_info['md5sum']
                return (filename, md5)
        return (None, None)

    def get_upstream_part(self, dsc):
        """Gets the information about the upstream part from the dsc.

        :param dsc: a deb822.Dsc object to take the information from.
        :return: a tuple (path, md5), both strings, the former being
            the path to the .orig.tar.gz, the latter being the md5
            reported for it. If there is no upstream part both will
            be None.
        """
        return self._get_dsc_part(dsc, ".orig.tar.gz")

    def get_diff_part(self, dsc):
        """Gets the information about the diff part from the dsc.

        :param dsc: a deb822.Dsc object to take the information from.
        :return: a tuple (path, md5), both strings, the former being
            the path to the .diff.gz, the latter being the md5
            reported for it. If there is no diff part both will be
            None.
        """
        return self._get_dsc_part(dsc, ".diff.gz")

    def get_native_part(self, dsc):
        """Gets the information about the native part from the dsc.

        :param dsc: a deb822.Dsc object to take the information from.
        :return: a tuple (path, md5), both strings, the former being
            the path to the .tar.gz, the latter being the md5 reported
            for it. If there is not native part both will be None.
        """
        (path, md5) = self._get_dsc_part(dsc, ".tar.gz")
        assert not path.endswith(".orig.tar.gz")
        return (path, md5)

    def upstream_parents(self, versions):
        """Get the parents for importing a new upstream.

        The upstream parents will be the last upstream version,
        except for some cases when the last version was native.

        :return: the list of revision ids to use as parents when
            importing the specified upstream version.
        """
        parents = []
        first_parent = self.upstream_branch.last_revision()
        if first_parent != NULL_REVISION:
            parents = [first_parent]
        last_contained_version = self.last_contained_version(versions)
        if last_contained_version is not None:
            # If the last version was native, and was not from the same
            # upstream as a non-native version (i.e. it wasn't a mistaken
            # native -2 version), then we want to add an extra parent.
            if (self.is_version_native(last_contained_version)
                and not self.has_upstream_version(last_contained_version)):
                revid = self.revid_of_version(last_contained_version)
                parents.append(revid)
                self.upstream_branch.fetch(self.branch,
                        last_revision=revid)
        if first_parent == NULL_REVISION:
            pull_parents = self.get_parents(versions)
            if len(pull_parents) > 0:
                pull_branch = pull_parents[0][0]
                pull_version = pull_parents[0][1]
                if not pull_branch.is_version_native(pull_version):
                    pull_revid = \
                        pull_branch.revid_of_upstream_version(pull_version)
                    mutter("Initialising upstream from %s, version %s" \
                        % (str(pull_branch), str(pull_version)))
                    parents.append(pull_revid)
                    self.upstream_branch.fetch(
                            pull_branch.upstream_branch,
                            last_revision=pull_revid)
        return parents

    def get_changelog_from_source(self, dir):
        cl_filename = os.path.join(dir, "debian", "changelog")
        cl = Changelog()
        cl.parse_changelog(open(cl_filename).read(), strict=False)
        return cl

    def extract_dsc(self, dsc_filename):
        """Extract a dsc file in to a temporary directory."""
        tempdir = tempfile.mkdtemp()
        dsc_filename = os.path.abspath(dsc_filename)
        proc = Popen("dpkg-source -su -x %s" % (dsc_filename,), shell=True,
                cwd=tempdir, stdout=PIPE, stderr=PIPE)
        ret = proc.wait()
        assert ret == 0, "dpkg-source -x failed, output:\n%s\n%s" % \
                    (proc.stdout.read(), proc.stderr.read())
        return tempdir

    def _do_import_package(self, version, versions, debian_part, md5,
            upstream_part, upstream_md5):
        pull_branch = self.branch_to_pull_version_from(version, md5)
        if pull_branch is not None:
            self.pull_version_from_branch(pull_branch, version)
        else:
            # We need to import at least the diff, possibly upstream.
            # Work out if we need the upstream part first.
            imported_upstream = False
            if not self.has_upstream_version(version):
                up_pull_branch = \
                    self.branch_to_pull_upstream_from(version, upstream_md5)
                if up_pull_branch is not None:
                    self.pull_upstream_from_branch(up_pull_branch, version)
                else:
                    imported_upstream = True
                    # Check whether we should pull first if this initialises
                    # from another branch:
                    upstream_parents = self.upstream_parents(versions)
                    self.import_upstream(upstream_part, version,
                            upstream_md5, upstream_parents)
            else:
                mutter("We already have the needed upstream part")
            parents = self.get_parents_with_upstream(version, versions,
                    force_upstream_parent=imported_upstream)
            # Now we have the list of parents we need to import the .diff.gz
            self.import_debian(debian_part, version, parents, md5)

    def get_native_parents(self, version, versions):
        last_contained_version = self.last_contained_version(versions)
        if last_contained_version is None:
            return []
        else:
            return [self.revid_of_version(last_contained_version)]

    def _import_native_package(self, version, versions, debian_part, md5):
        pull_branch = self.branch_to_pull_version_from(version, md5)
        if pull_branch is not None:
            self.pull_version_from_branch(pull_branch, version, native=True)
        else:
            parents = self.get_native_parents(version, versions)
            self.import_debian(debian_part, version, parents, md5,
                    native=True)

    def import_package(self, dsc_filename):
        """Import a source package.

        :param dsc_filename: a path to a .dsc file for the version
            to be imported.
        """
        base_path = osutils.dirname(dsc_filename)
        dsc = deb822.Dsc(open(dsc_filename).read())
        version = Version(dsc['Version'])
        name = dsc['Source']
        tempdir = self.extract_dsc(dsc_filename)
        try:
            # TODO: make more robust against strange .dsc files.
            upstream_part = os.path.join(tempdir,
                    "%s-%s.orig" % (name, str(version.upstream_version)))
            debian_part = os.path.join(tempdir,
                    "%s-%s" % (name, str(version.upstream_version)))
            native = False
            if not os.path.exists(upstream_part):
                mutter("It's a native package")
                native = True
                (_, md5) = self.get_native_part(dsc)
            else:
                (_, upstream_md5) = self.get_upstream_part(dsc)
                (_, md5) = self.get_diff_part(dsc)
            cl = self.get_changelog_from_source(debian_part)
            versions = cl.versions
            assert not self.has_version(version), \
                "Trying to import version %s again" % str(version)
            #TODO: check that the versions list is correctly ordered,
            # as some methods assume that, and it's not clear what
            # should happen if it isn't.
            if not native:
                self._do_import_package(version, versions, debian_part, md5,
                        upstream_part, upstream_md5)
            else:
                self._import_native_package(version, versions, debian_part,
                        md5)
        finally:
            shutil.rmtree(tempdir)

