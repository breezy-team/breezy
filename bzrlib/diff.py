# Copyright (C) 2004, 2005, 2006 Canonical Ltd.
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import difflib
import os
import re
import shutil
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import errno
import subprocess
import tempfile
import time

from bzrlib import (
    branch as _mod_branch,
    bzrdir,
    commands,
    errors,
    osutils,
    patiencediff,
    textfile,
    timestamp,
    )
""")

from bzrlib.symbol_versioning import (
        deprecated_function,
        one_three
        )
from bzrlib.trace import mutter, warning


# TODO: Rather than building a changeset object, we should probably
# invoke callbacks on an object.  That object can either accumulate a
# list, write them out directly, etc etc.


class _PrematchedMatcher(difflib.SequenceMatcher):
    """Allow SequenceMatcher operations to use predetermined blocks"""

    def __init__(self, matching_blocks):
        difflib.SequenceMatcher(self, None, None)
        self.matching_blocks = matching_blocks
        self.opcodes = None


def internal_diff(old_filename, oldlines, new_filename, newlines, to_file,
                  allow_binary=False, sequence_matcher=None,
                  path_encoding='utf8'):
    # FIXME: difflib is wrong if there is no trailing newline.
    # The syntax used by patch seems to be "\ No newline at
    # end of file" following the last diff line from that
    # file.  This is not trivial to insert into the
    # unified_diff output and it might be better to just fix
    # or replace that function.

    # In the meantime we at least make sure the patch isn't
    # mangled.


    # Special workaround for Python2.3, where difflib fails if
    # both sequences are empty.
    if not oldlines and not newlines:
        return
    
    if allow_binary is False:
        textfile.check_text_lines(oldlines)
        textfile.check_text_lines(newlines)

    if sequence_matcher is None:
        sequence_matcher = patiencediff.PatienceSequenceMatcher
    ud = patiencediff.unified_diff(oldlines, newlines,
                      fromfile=old_filename.encode(path_encoding),
                      tofile=new_filename.encode(path_encoding),
                      sequencematcher=sequence_matcher)

    ud = list(ud)
    if len(ud) == 0: # Identical contents, nothing to do
        return
    # work-around for difflib being too smart for its own good
    # if /dev/null is "1,0", patch won't recognize it as /dev/null
    if not oldlines:
        ud[2] = ud[2].replace('-1,0', '-0,0')
    elif not newlines:
        ud[2] = ud[2].replace('+1,0', '+0,0')
    # work around for difflib emitting random spaces after the label
    ud[0] = ud[0][:-2] + '\n'
    ud[1] = ud[1][:-2] + '\n'

    for line in ud:
        to_file.write(line)
        if not line.endswith('\n'):
            to_file.write("\n\\ No newline at end of file\n")
    to_file.write('\n')


def _spawn_external_diff(diffcmd, capture_errors=True):
    """Spawn the externall diff process, and return the child handle.

    :param diffcmd: The command list to spawn
    :param capture_errors: Capture stderr as well as setting LANG=C
        and LC_ALL=C. This lets us read and understand the output of diff,
        and respond to any errors.
    :return: A Popen object.
    """
    if capture_errors:
        # construct minimal environment
        env = {}
        path = os.environ.get('PATH')
        if path is not None:
            env['PATH'] = path
        env['LANGUAGE'] = 'C'   # on win32 only LANGUAGE has effect
        env['LANG'] = 'C'
        env['LC_ALL'] = 'C'
        stderr = subprocess.PIPE
    else:
        env = None
        stderr = None

    try:
        pipe = subprocess.Popen(diffcmd,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=stderr,
                                env=env)
    except OSError, e:
        if e.errno == errno.ENOENT:
            raise errors.NoDiff(str(e))
        raise

    return pipe


def external_diff(old_filename, oldlines, new_filename, newlines, to_file,
                  diff_opts):
    """Display a diff by calling out to the external diff program."""
    # make sure our own output is properly ordered before the diff
    to_file.flush()

    oldtmp_fd, old_abspath = tempfile.mkstemp(prefix='bzr-diff-old-')
    newtmp_fd, new_abspath = tempfile.mkstemp(prefix='bzr-diff-new-')
    oldtmpf = os.fdopen(oldtmp_fd, 'wb')
    newtmpf = os.fdopen(newtmp_fd, 'wb')

    try:
        # TODO: perhaps a special case for comparing to or from the empty
        # sequence; can just use /dev/null on Unix

        # TODO: if either of the files being compared already exists as a
        # regular named file (e.g. in the working directory) then we can
        # compare directly to that, rather than copying it.

        oldtmpf.writelines(oldlines)
        newtmpf.writelines(newlines)

        oldtmpf.close()
        newtmpf.close()

        if not diff_opts:
            diff_opts = []
        diffcmd = ['diff',
                   '--label', old_filename,
                   old_abspath,
                   '--label', new_filename,
                   new_abspath,
                   '--binary',
                  ]

        # diff only allows one style to be specified; they don't override.
        # note that some of these take optargs, and the optargs can be
        # directly appended to the options.
        # this is only an approximate parser; it doesn't properly understand
        # the grammar.
        for s in ['-c', '-u', '-C', '-U',
                  '-e', '--ed',
                  '-q', '--brief',
                  '--normal',
                  '-n', '--rcs',
                  '-y', '--side-by-side',
                  '-D', '--ifdef']:
            for j in diff_opts:
                if j.startswith(s):
                    break
            else:
                continue
            break
        else:
            diffcmd.append('-u')
                  
        if diff_opts:
            diffcmd.extend(diff_opts)

        pipe = _spawn_external_diff(diffcmd, capture_errors=True)
        out,err = pipe.communicate()
        rc = pipe.returncode
        
        # internal_diff() adds a trailing newline, add one here for consistency
        out += '\n'
        if rc == 2:
            # 'diff' gives retcode == 2 for all sorts of errors
            # one of those is 'Binary files differ'.
            # Bad options could also be the problem.
            # 'Binary files' is not a real error, so we suppress that error.
            lang_c_out = out

            # Since we got here, we want to make sure to give an i18n error
            pipe = _spawn_external_diff(diffcmd, capture_errors=False)
            out, err = pipe.communicate()

            # Write out the new i18n diff response
            to_file.write(out+'\n')
            if pipe.returncode != 2:
                raise errors.BzrError(
                               'external diff failed with exit code 2'
                               ' when run with LANG=C and LC_ALL=C,'
                               ' but not when run natively: %r' % (diffcmd,))

            first_line = lang_c_out.split('\n', 1)[0]
            # Starting with diffutils 2.8.4 the word "binary" was dropped.
            m = re.match('^(binary )?files.*differ$', first_line, re.I)
            if m is None:
                raise errors.BzrError('external diff failed with exit code 2;'
                                      ' command: %r' % (diffcmd,))
            else:
                # Binary files differ, just return
                return

        # If we got to here, we haven't written out the output of diff
        # do so now
        to_file.write(out)
        if rc not in (0, 1):
            # returns 1 if files differ; that's OK
            if rc < 0:
                msg = 'signal %d' % (-rc)
            else:
                msg = 'exit code %d' % rc
                
            raise errors.BzrError('external diff failed with %s; command: %r' 
                                  % (rc, diffcmd))


    finally:
        oldtmpf.close()                 # and delete
        newtmpf.close()
        # Clean up. Warn in case the files couldn't be deleted
        # (in case windows still holds the file open, but not
        # if the files have already been deleted)
        try:
            os.remove(old_abspath)
        except OSError, e:
            if e.errno not in (errno.ENOENT,):
                warning('Failed to delete temporary file: %s %s',
                        old_abspath, e)
        try:
            os.remove(new_abspath)
        except OSError:
            if e.errno not in (errno.ENOENT,):
                warning('Failed to delete temporary file: %s %s',
                        new_abspath, e)


def _get_trees_to_diff(path_list, revision_specs, old_url, new_url):
    """Get the trees and specific files to diff given a list of paths.

    This method works out the trees to be diff'ed and the files of
    interest within those trees.

    :param path_list:
        the list of arguments passed to the diff command
    :param revision_specs:
        Zero, one or two RevisionSpecs from the diff command line,
        saying what revisions to compare.
    :param old_url:
        The url of the old branch or tree. If None, the tree to use is
        taken from the first path, if any, or the current working tree.
    :param new_url:
        The url of the new branch or tree. If None, the tree to use is
        taken from the first path, if any, or the current working tree.
    :returns:
        a tuple of (old_tree, new_tree, specific_files, extra_trees) where
        extra_trees is a sequence of additional trees to search in for
        file-ids.
    """
    # Get the old and new revision specs
    old_revision_spec = None
    new_revision_spec = None
    if revision_specs is not None:
        if len(revision_specs) > 0:
            old_revision_spec = revision_specs[0]
            if old_url is None:
                old_url = old_revision_spec.get_branch()
        if len(revision_specs) > 1:
            new_revision_spec = revision_specs[1]
            if new_url is None:
                new_url = new_revision_spec.get_branch()

    other_paths = []
    make_paths_wt_relative = True
    consider_relpath = True
    if path_list is None or len(path_list) == 0:
        # If no path is given, the current working tree is used
        default_location = u'.'
        consider_relpath = False
    elif old_url is not None and new_url is not None:
        other_paths = path_list
        make_paths_wt_relative = False
    else:
        default_location = path_list[0]
        other_paths = path_list[1:]

    # Get the old location
    specific_files = []
    if old_url is None:
        old_url = default_location
    working_tree, branch, relpath = \
        bzrdir.BzrDir.open_containing_tree_or_branch(old_url)
    if consider_relpath and relpath != '':
        specific_files.append(relpath)
    old_tree = _get_tree_to_diff(old_revision_spec, working_tree, branch)

    # Get the new location
    if new_url is None:
        new_url = default_location
    if new_url != old_url:
        working_tree, branch, relpath = \
            bzrdir.BzrDir.open_containing_tree_or_branch(new_url)
        if consider_relpath and relpath != '':
            specific_files.append(relpath)
    new_tree = _get_tree_to_diff(new_revision_spec, working_tree, branch,
        basis_is_default=working_tree is None)

    # Get the specific files (all files is None, no files is [])
    if make_paths_wt_relative and working_tree is not None:
        other_paths = _relative_paths_in_tree(working_tree, other_paths)
    specific_files.extend(other_paths)
    if len(specific_files) == 0:
        specific_files = None

    # Get extra trees that ought to be searched for file-ids
    extra_trees = None
    if working_tree is not None and working_tree not in (old_tree, new_tree):
        extra_trees = (working_tree,)
    return old_tree, new_tree, specific_files, extra_trees


def _get_tree_to_diff(spec, tree=None, branch=None, basis_is_default=True):
    if branch is None and tree is not None:
        branch = tree.branch
    if spec is None or spec.spec is None:
        if basis_is_default:
            if tree is not None:
                return tree.basis_tree()
            else:
                return branch.basis_tree()
        else:
            return tree
    if not spec.needs_branch():
        branch = _mod_branch.Branch.open(spec.get_branch())
    revision_id = spec.as_revision_id(branch)
    return branch.repository.revision_tree(revision_id)


def _relative_paths_in_tree(tree, paths):
    """Get the relative paths within a working tree.

    Each path may be either an absolute path or a path relative to the
    current working directory.
    """
    result = []
    for filename in paths:
        try:
            result.append(tree.relpath(osutils.dereference_path(filename)))
        except errors.PathNotChild:
            raise errors.BzrCommandError("Files are in different branches")
    return result


def show_diff_trees(old_tree, new_tree, to_file, specific_files=None,
                    external_diff_options=None,
                    old_label='a/', new_label='b/',
                    extra_trees=None,
                    path_encoding='utf8',
                    using=None):
    """Show in text form the changes from one tree to another.

    to_file
        The output stream.

    specific_files
        Include only changes to these files - None for all changes.

    external_diff_options
        If set, use an external GNU diff and pass these options.

    extra_trees
        If set, more Trees to use for looking up file ids

    path_encoding
        If set, the path will be encoded as specified, otherwise is supposed
        to be utf8
    """
    old_tree.lock_read()
    try:
        if extra_trees is not None:
            for tree in extra_trees:
                tree.lock_read()
        new_tree.lock_read()
        try:
            differ = DiffTree.from_trees_options(old_tree, new_tree, to_file,
                                                 path_encoding,
                                                 external_diff_options,
                                                 old_label, new_label, using)
            return differ.show_diff(specific_files, extra_trees)
        finally:
            new_tree.unlock()
            if extra_trees is not None:
                for tree in extra_trees:
                    tree.unlock()
    finally:
        old_tree.unlock()


def _patch_header_date(tree, file_id, path):
    """Returns a timestamp suitable for use in a patch header."""
    mtime = tree.get_file_mtime(file_id, path)
    return timestamp.format_patch_date(mtime)


def _raise_if_nonexistent(paths, old_tree, new_tree):
    """Complain if paths are not in either inventory or tree.

    It's OK with the files exist in either tree's inventory, or 
    if they exist in the tree but are not versioned.
    
    This can be used by operations such as bzr status that can accept
    unknown or ignored files.
    """
    mutter("check paths: %r", paths)
    if not paths:
        return
    s = old_tree.filter_unversioned_files(paths)
    s = new_tree.filter_unversioned_files(s)
    s = [path for path in s if not new_tree.has_filename(path)]
    if s:
        raise errors.PathsDoNotExist(sorted(s))


@deprecated_function(one_three)
def get_prop_change(meta_modified):
    if meta_modified:
        return " (properties changed)"
    else:
        return  ""

def get_executable_change(old_is_x, new_is_x):
    descr = { True:"+x", False:"-x", None:"??" }
    if old_is_x != new_is_x:
        return ["%s to %s" % (descr[old_is_x], descr[new_is_x],)]
    else:
        return []


class DiffPath(object):
    """Base type for command object that compare files"""

    # The type or contents of the file were unsuitable for diffing
    CANNOT_DIFF = 'CANNOT_DIFF'
    # The file has changed in a semantic way
    CHANGED = 'CHANGED'
    # The file content may have changed, but there is no semantic change
    UNCHANGED = 'UNCHANGED'

    def __init__(self, old_tree, new_tree, to_file, path_encoding='utf-8'):
        """Constructor.

        :param old_tree: The tree to show as the old tree in the comparison
        :param new_tree: The tree to show as new in the comparison
        :param to_file: The file to write comparison data to
        :param path_encoding: The character encoding to write paths in
        """
        self.old_tree = old_tree
        self.new_tree = new_tree
        self.to_file = to_file
        self.path_encoding = path_encoding

    def finish(self):
        pass

    @classmethod
    def from_diff_tree(klass, diff_tree):
        return klass(diff_tree.old_tree, diff_tree.new_tree,
                     diff_tree.to_file, diff_tree.path_encoding)

    @staticmethod
    def _diff_many(differs, file_id, old_path, new_path, old_kind, new_kind):
        for file_differ in differs:
            result = file_differ.diff(file_id, old_path, new_path, old_kind,
                                      new_kind)
            if result is not DiffPath.CANNOT_DIFF:
                return result
        else:
            return DiffPath.CANNOT_DIFF


class DiffKindChange(object):
    """Special differ for file kind changes.

    Represents kind change as deletion + creation.  Uses the other differs
    to do this.
    """
    def __init__(self, differs):
        self.differs = differs

    def finish(self):
        pass

    @classmethod
    def from_diff_tree(klass, diff_tree):
        return klass(diff_tree.differs)

    def diff(self, file_id, old_path, new_path, old_kind, new_kind):
        """Perform comparison

        :param file_id: The file_id of the file to compare
        :param old_path: Path of the file in the old tree
        :param new_path: Path of the file in the new tree
        :param old_kind: Old file-kind of the file
        :param new_kind: New file-kind of the file
        """
        if None in (old_kind, new_kind):
            return DiffPath.CANNOT_DIFF
        result = DiffPath._diff_many(self.differs, file_id, old_path,
                                       new_path, old_kind, None)
        if result is DiffPath.CANNOT_DIFF:
            return result
        return DiffPath._diff_many(self.differs, file_id, old_path, new_path,
                                     None, new_kind)


class DiffDirectory(DiffPath):

    def diff(self, file_id, old_path, new_path, old_kind, new_kind):
        """Perform comparison between two directories.  (dummy)

        """
        if 'directory' not in (old_kind, new_kind):
            return self.CANNOT_DIFF
        if old_kind not in ('directory', None):
            return self.CANNOT_DIFF
        if new_kind not in ('directory', None):
            return self.CANNOT_DIFF
        return self.CHANGED


class DiffSymlink(DiffPath):

    def diff(self, file_id, old_path, new_path, old_kind, new_kind):
        """Perform comparison between two symlinks

        :param file_id: The file_id of the file to compare
        :param old_path: Path of the file in the old tree
        :param new_path: Path of the file in the new tree
        :param old_kind: Old file-kind of the file
        :param new_kind: New file-kind of the file
        """
        if 'symlink' not in (old_kind, new_kind):
            return self.CANNOT_DIFF
        if old_kind == 'symlink':
            old_target = self.old_tree.get_symlink_target(file_id)
        elif old_kind is None:
            old_target = None
        else:
            return self.CANNOT_DIFF
        if new_kind == 'symlink':
            new_target = self.new_tree.get_symlink_target(file_id)
        elif new_kind is None:
            new_target = None
        else:
            return self.CANNOT_DIFF
        return self.diff_symlink(old_target, new_target)

    def diff_symlink(self, old_target, new_target):
        if old_target is None:
            self.to_file.write('=== target is %r\n' % new_target)
        elif new_target is None:
            self.to_file.write('=== target was %r\n' % old_target)
        else:
            self.to_file.write('=== target changed %r => %r\n' %
                              (old_target, new_target))
        return self.CHANGED


class DiffText(DiffPath):

    # GNU Patch uses the epoch date to detect files that are being added
    # or removed in a diff.
    EPOCH_DATE = '1970-01-01 00:00:00 +0000'

    def __init__(self, old_tree, new_tree, to_file, path_encoding='utf-8',
                 old_label='', new_label='', text_differ=internal_diff):
        DiffPath.__init__(self, old_tree, new_tree, to_file, path_encoding)
        self.text_differ = text_differ
        self.old_label = old_label
        self.new_label = new_label
        self.path_encoding = path_encoding

    def diff(self, file_id, old_path, new_path, old_kind, new_kind):
        """Compare two files in unified diff format

        :param file_id: The file_id of the file to compare
        :param old_path: Path of the file in the old tree
        :param new_path: Path of the file in the new tree
        :param old_kind: Old file-kind of the file
        :param new_kind: New file-kind of the file
        """
        if 'file' not in (old_kind, new_kind):
            return self.CANNOT_DIFF
        from_file_id = to_file_id = file_id
        if old_kind == 'file':
            old_date = _patch_header_date(self.old_tree, file_id, old_path)
        elif old_kind is None:
            old_date = self.EPOCH_DATE
            from_file_id = None
        else:
            return self.CANNOT_DIFF
        if new_kind == 'file':
            new_date = _patch_header_date(self.new_tree, file_id, new_path)
        elif new_kind is None:
            new_date = self.EPOCH_DATE
            to_file_id = None
        else:
            return self.CANNOT_DIFF
        from_label = '%s%s\t%s' % (self.old_label, old_path, old_date)
        to_label = '%s%s\t%s' % (self.new_label, new_path, new_date)
        return self.diff_text(from_file_id, to_file_id, from_label, to_label)

    def diff_text(self, from_file_id, to_file_id, from_label, to_label):
        """Diff the content of given files in two trees

        :param from_file_id: The id of the file in the from tree.  If None,
            the file is not present in the from tree.
        :param to_file_id: The id of the file in the to tree.  This may refer
            to a different file from from_file_id.  If None,
            the file is not present in the to tree.
        """
        def _get_text(tree, file_id):
            if file_id is not None:
                return tree.get_file(file_id).readlines()
            else:
                return []
        try:
            from_text = _get_text(self.old_tree, from_file_id)
            to_text = _get_text(self.new_tree, to_file_id)
            self.text_differ(from_label, from_text, to_label, to_text,
                             self.to_file)
        except errors.BinaryFile:
            self.to_file.write(
                  ("Binary files %s and %s differ\n" %
                  (from_label, to_label)).encode(self.path_encoding))
        return self.CHANGED


class DiffFromTool(DiffPath):

    def __init__(self, command_template, old_tree, new_tree, to_file,
                 path_encoding='utf-8'):
        DiffPath.__init__(self, old_tree, new_tree, to_file, path_encoding)
        self.command_template = command_template
        self._root = tempfile.mkdtemp(prefix='bzr-diff-')

    @classmethod
    def from_string(klass, command_string, old_tree, new_tree, to_file,
                    path_encoding='utf-8'):
        command_template = commands.shlex_split_unicode(command_string)
        command_template.extend(['%(old_path)s', '%(new_path)s'])
        return klass(command_template, old_tree, new_tree, to_file,
                     path_encoding)

    @classmethod
    def make_from_diff_tree(klass, command_string):
        def from_diff_tree(diff_tree):
            return klass.from_string(command_string, diff_tree.old_tree,
                                     diff_tree.new_tree, diff_tree.to_file)
        return from_diff_tree

    def _get_command(self, old_path, new_path):
        my_map = {'old_path': old_path, 'new_path': new_path}
        return [t % my_map for t in self.command_template]

    def _execute(self, old_path, new_path):
        command = self._get_command(old_path, new_path)
        try:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                    cwd=self._root)
        except OSError, e:
            if e.errno == errno.ENOENT:
                raise errors.ExecutableMissing(command[0])
            else:
                raise
        self.to_file.write(proc.stdout.read())
        return proc.wait()

    def _try_symlink_root(self, tree, prefix):
        if (getattr(tree, 'abspath', None) is None
            or not osutils.host_os_dereferences_symlinks()):
            return False
        try:
            os.symlink(tree.abspath(''), osutils.pathjoin(self._root, prefix))
        except OSError, e:
            if e.errno != errno.EEXIST:
                raise
        return True

    def _write_file(self, file_id, tree, prefix, relpath):
        full_path = osutils.pathjoin(self._root, prefix, relpath)
        if self._try_symlink_root(tree, prefix):
            return full_path
        parent_dir = osutils.dirname(full_path)
        try:
            os.makedirs(parent_dir)
        except OSError, e:
            if e.errno != errno.EEXIST:
                raise
        source = tree.get_file(file_id, relpath)
        try:
            target = open(full_path, 'wb')
            try:
                osutils.pumpfile(source, target)
            finally:
                target.close()
        finally:
            source.close()
        osutils.make_readonly(full_path)
        mtime = tree.get_file_mtime(file_id)
        os.utime(full_path, (mtime, mtime))
        return full_path

    def _prepare_files(self, file_id, old_path, new_path):
        old_disk_path = self._write_file(file_id, self.old_tree, 'old',
                                         old_path)
        new_disk_path = self._write_file(file_id, self.new_tree, 'new',
                                         new_path)
        return old_disk_path, new_disk_path

    def finish(self):
        osutils.rmtree(self._root)

    def diff(self, file_id, old_path, new_path, old_kind, new_kind):
        if (old_kind, new_kind) != ('file', 'file'):
            return DiffPath.CANNOT_DIFF
        self._prepare_files(file_id, old_path, new_path)
        self._execute(osutils.pathjoin('old', old_path),
                      osutils.pathjoin('new', new_path))


class DiffTree(object):
    """Provides textual representations of the difference between two trees.

    A DiffTree examines two trees and where a file-id has altered
    between them, generates a textual representation of the difference.
    DiffTree uses a sequence of DiffPath objects which are each
    given the opportunity to handle a given altered fileid. The list
    of DiffPath objects can be extended globally by appending to
    DiffTree.diff_factories, or for a specific diff operation by
    supplying the extra_factories option to the appropriate method.
    """

    # list of factories that can provide instances of DiffPath objects
    # may be extended by plugins.
    diff_factories = [DiffSymlink.from_diff_tree,
                      DiffDirectory.from_diff_tree]

    def __init__(self, old_tree, new_tree, to_file, path_encoding='utf-8',
                 diff_text=None, extra_factories=None):
        """Constructor

        :param old_tree: Tree to show as old in the comparison
        :param new_tree: Tree to show as new in the comparison
        :param to_file: File to write comparision to
        :param path_encoding: Character encoding to write paths in
        :param diff_text: DiffPath-type object to use as a last resort for
            diffing text files.
        :param extra_factories: Factories of DiffPaths to try before any other
            DiffPaths"""
        if diff_text is None:
            diff_text = DiffText(old_tree, new_tree, to_file, path_encoding,
                                 '', '',  internal_diff)
        self.old_tree = old_tree
        self.new_tree = new_tree
        self.to_file = to_file
        self.path_encoding = path_encoding
        self.differs = []
        if extra_factories is not None:
            self.differs.extend(f(self) for f in extra_factories)
        self.differs.extend(f(self) for f in self.diff_factories)
        self.differs.extend([diff_text, DiffKindChange.from_diff_tree(self)])

    @classmethod
    def from_trees_options(klass, old_tree, new_tree, to_file,
                           path_encoding, external_diff_options, old_label,
                           new_label, using):
        """Factory for producing a DiffTree.

        Designed to accept options used by show_diff_trees.
        :param old_tree: The tree to show as old in the comparison
        :param new_tree: The tree to show as new in the comparison
        :param to_file: File to write comparisons to
        :param path_encoding: Character encoding to use for writing paths
        :param external_diff_options: If supplied, use the installed diff
            binary to perform file comparison, using supplied options.
        :param old_label: Prefix to use for old file labels
        :param new_label: Prefix to use for new file labels
        :param using: Commandline to use to invoke an external diff tool
        """
        if using is not None:
            extra_factories = [DiffFromTool.make_from_diff_tree(using)]
        else:
            extra_factories = []
        if external_diff_options:
            opts = external_diff_options.split()
            def diff_file(olab, olines, nlab, nlines, to_file):
                external_diff(olab, olines, nlab, nlines, to_file, opts)
        else:
            diff_file = internal_diff
        diff_text = DiffText(old_tree, new_tree, to_file, path_encoding,
                             old_label, new_label, diff_file)
        return klass(old_tree, new_tree, to_file, path_encoding, diff_text,
                     extra_factories)

    def show_diff(self, specific_files, extra_trees=None):
        """Write tree diff to self.to_file

        :param sepecific_files: the specific files to compare (recursive)
        :param extra_trees: extra trees to use for mapping paths to file_ids
        """
        try:
            return self._show_diff(specific_files, extra_trees)
        finally:
            for differ in self.differs:
                differ.finish()

    def _show_diff(self, specific_files, extra_trees):
        # TODO: Generation of pseudo-diffs for added/deleted files could
        # be usefully made into a much faster special case.
        iterator = self.new_tree.iter_changes(self.old_tree,
                                               specific_files=specific_files,
                                               extra_trees=extra_trees,
                                               require_versioned=True)
        has_changes = 0
        def changes_key(change):
            old_path, new_path = change[1]
            path = new_path
            if path is None:
                path = old_path
            return path
        def get_encoded_path(path):
            if path is not None:
                return path.encode(self.path_encoding, "replace")
        for (file_id, paths, changed_content, versioned, parent, name, kind,
             executable) in sorted(iterator, key=changes_key):
            if parent == (None, None):
                continue
            oldpath, newpath = paths
            oldpath_encoded = get_encoded_path(paths[0])
            newpath_encoded = get_encoded_path(paths[1])
            old_present = (kind[0] is not None and versioned[0])
            new_present = (kind[1] is not None and versioned[1])
            renamed = (parent[0], name[0]) != (parent[1], name[1])

            properties_changed = []
            properties_changed.extend(get_executable_change(executable[0], executable[1]))

            if properties_changed:
                prop_str = " (properties changed: %s)" % (", ".join(properties_changed),)
            else:
                prop_str = ""

            if (old_present, new_present) == (True, False):
                self.to_file.write("=== removed %s '%s'\n" %
                                   (kind[0], oldpath_encoded))
                newpath = oldpath
            elif (old_present, new_present) == (False, True):
                self.to_file.write("=== added %s '%s'\n" %
                                   (kind[1], newpath_encoded))
                oldpath = newpath
            elif renamed:
                self.to_file.write("=== renamed %s '%s' => '%s'%s\n" %
                    (kind[0], oldpath_encoded, newpath_encoded, prop_str))
            else:
                # if it was produced by iter_changes, it must be
                # modified *somehow*, either content or execute bit.
                self.to_file.write("=== modified %s '%s'%s\n" % (kind[0],
                                   newpath_encoded, prop_str))
            if changed_content:
                self.diff(file_id, oldpath, newpath)
                has_changes = 1
            if renamed:
                has_changes = 1
        return has_changes

    def diff(self, file_id, old_path, new_path):
        """Perform a diff of a single file

        :param file_id: file-id of the file
        :param old_path: The path of the file in the old tree
        :param new_path: The path of the file in the new tree
        """
        try:
            old_kind = self.old_tree.kind(file_id)
        except (errors.NoSuchId, errors.NoSuchFile):
            old_kind = None
        try:
            new_kind = self.new_tree.kind(file_id)
        except (errors.NoSuchId, errors.NoSuchFile):
            new_kind = None

        result = DiffPath._diff_many(self.differs, file_id, old_path,
                                       new_path, old_kind, new_kind)
        if result is DiffPath.CANNOT_DIFF:
            error_path = new_path
            if error_path is None:
                error_path = old_path
            raise errors.NoDiffFound(error_path)
