# Copyright (C) 2005-2014 Canonical Ltd.
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from __future__ import absolute_import

import difflib
import os
import re
import string
import sys

from .lazy_import import lazy_import
lazy_import(globals(), """
import errno
import subprocess
import tempfile

from breezy import (
    cmdline,
    controldir,
    errors,
    osutils,
    patiencediff,
    textfile,
    timestamp,
    views,
    )

from breezy.workingtree import WorkingTree
from breezy.i18n import gettext
""")

from .registry import (
    Registry,
    )
from .sixish import text_type
from .trace import mutter, note, warning
from .tree import FileTimestampUnavailable


DEFAULT_CONTEXT_AMOUNT = 3


class AtTemplate(string.Template):
    """Templating class that uses @ instead of $."""

    delimiter = '@'


# TODO: Rather than building a changeset object, we should probably
# invoke callbacks on an object.  That object can either accumulate a
# list, write them out directly, etc etc.


class _PrematchedMatcher(difflib.SequenceMatcher):
    """Allow SequenceMatcher operations to use predetermined blocks"""

    def __init__(self, matching_blocks):
        difflib.SequenceMatcher(self, None, None)
        self.matching_blocks = matching_blocks
        self.opcodes = None


def internal_diff(old_label, oldlines, new_label, newlines, to_file,
                  allow_binary=False, sequence_matcher=None,
                  path_encoding='utf8', context_lines=DEFAULT_CONTEXT_AMOUNT):
    # FIXME: difflib is wrong if there is no trailing newline.
    # The syntax used by patch seems to be "\ No newline at
    # end of file" following the last diff line from that
    # file.  This is not trivial to insert into the
    # unified_diff output and it might be better to just fix
    # or replace that function.

    # In the meantime we at least make sure the patch isn't
    # mangled.

    if allow_binary is False:
        textfile.check_text_lines(oldlines)
        textfile.check_text_lines(newlines)

    if sequence_matcher is None:
        sequence_matcher = patiencediff.PatienceSequenceMatcher
    ud = patiencediff.unified_diff_bytes(oldlines, newlines,
                                         fromfile=old_label.encode(
                                             path_encoding, 'replace'),
                                         tofile=new_label.encode(
                                             path_encoding, 'replace'),
                                         n=context_lines, sequencematcher=sequence_matcher)

    ud = list(ud)
    if len(ud) == 0:  # Identical contents, nothing to do
        return
    # work-around for difflib being too smart for its own good
    # if /dev/null is "1,0", patch won't recognize it as /dev/null
    if not oldlines:
        ud[2] = ud[2].replace(b'-1,0', b'-0,0')
    elif not newlines:
        ud[2] = ud[2].replace(b'+1,0', b'+0,0')

    for line in ud:
        to_file.write(line)
        if not line.endswith(b'\n'):
            to_file.write(b"\n\\ No newline at end of file\n")
    to_file.write(b'\n')


def _spawn_external_diff(diffcmd, capture_errors=True):
    """Spawn the external diff process, and return the child handle.

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
    except OSError as e:
        if e.errno == errno.ENOENT:
            raise errors.NoDiff(str(e))
        raise

    return pipe


# diff style options as of GNU diff v3.2
style_option_list = ['-c', '-C', '--context',
                     '-e', '--ed',
                     '-f', '--forward-ed',
                     '-q', '--brief',
                     '--normal',
                     '-n', '--rcs',
                     '-u', '-U', '--unified',
                     '-y', '--side-by-side',
                     '-D', '--ifdef']


def default_style_unified(diff_opts):
    """Default to unified diff style if alternative not specified in diff_opts.

        diff only allows one style to be specified; they don't override.
        Note that some of these take optargs, and the optargs can be
        directly appended to the options.
        This is only an approximate parser; it doesn't properly understand
        the grammar.

    :param diff_opts: List of options for external (GNU) diff.
    :return: List of options with default style=='unified'.
    """
    for s in style_option_list:
        for j in diff_opts:
            if j.startswith(s):
                break
        else:
            continue
        break
    else:
        diff_opts.append('-u')
    return diff_opts


def external_diff(old_label, oldlines, new_label, newlines, to_file,
                  diff_opts):
    """Display a diff by calling out to the external diff program."""
    # make sure our own output is properly ordered before the diff
    to_file.flush()

    oldtmp_fd, old_abspath = tempfile.mkstemp(prefix='brz-diff-old-')
    newtmp_fd, new_abspath = tempfile.mkstemp(prefix='brz-diff-new-')
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
        if sys.platform == 'win32':
            # Popen doesn't do the proper encoding for external commands
            # Since we are dealing with an ANSI api, use mbcs encoding
            old_label = old_label.encode('mbcs')
            new_label = new_label.encode('mbcs')
        diffcmd = ['diff',
                   '--label', old_label,
                   old_abspath,
                   '--label', new_label,
                   new_abspath,
                   '--binary',
                   ]

        diff_opts = default_style_unified(diff_opts)

        if diff_opts:
            diffcmd.extend(diff_opts)

        pipe = _spawn_external_diff(diffcmd, capture_errors=True)
        out, err = pipe.communicate()
        rc = pipe.returncode

        # internal_diff() adds a trailing newline, add one here for consistency
        out += b'\n'
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
            to_file.write(out + b'\n')
            if pipe.returncode != 2:
                raise errors.BzrError(
                    'external diff failed with exit code 2'
                    ' when run with LANG=C and LC_ALL=C,'
                    ' but not when run natively: %r' % (diffcmd,))

            first_line = lang_c_out.split(b'\n', 1)[0]
            # Starting with diffutils 2.8.4 the word "binary" was dropped.
            m = re.match(b'^(binary )?files.*differ$', first_line, re.I)
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
                                  % (msg, diffcmd))

    finally:
        oldtmpf.close()                 # and delete
        newtmpf.close()

        def cleanup(path):
            # Warn in case the file couldn't be deleted (in case windows still
            # holds the file open, but not if the files have already been
            # deleted)
            try:
                os.remove(path)
            except OSError as e:
                if e.errno not in (errno.ENOENT,):
                    warning('Failed to delete temporary file: %s %s', path, e)

        cleanup(old_abspath)
        cleanup(new_abspath)


def get_trees_and_branches_to_diff_locked(
        path_list, revision_specs, old_url, new_url, add_cleanup, apply_view=True):
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
    :param add_cleanup:
        a callable like Command.add_cleanup.  get_trees_and_branches_to_diff
        will register cleanups that must be run to unlock the trees, etc.
    :param apply_view:
        if True and a view is set, apply the view or check that the paths
        are within it
    :returns:
        a tuple of (old_tree, new_tree, old_branch, new_branch,
        specific_files, extra_trees) where extra_trees is a sequence of
        additional trees to search in for file-ids.  The trees and branches
        will be read-locked until the cleanups registered via the add_cleanup
        param are run.
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

    def lock_tree_or_branch(wt, br):
        if wt is not None:
            wt.lock_read()
            add_cleanup(wt.unlock)
        elif br is not None:
            br.lock_read()
            add_cleanup(br.unlock)

    # Get the old location
    specific_files = []
    if old_url is None:
        old_url = default_location
    working_tree, branch, relpath = \
        controldir.ControlDir.open_containing_tree_or_branch(old_url)
    lock_tree_or_branch(working_tree, branch)
    if consider_relpath and relpath != '':
        if working_tree is not None and apply_view:
            views.check_path_in_view(working_tree, relpath)
        specific_files.append(relpath)
    old_tree = _get_tree_to_diff(old_revision_spec, working_tree, branch)
    old_branch = branch

    # Get the new location
    if new_url is None:
        new_url = default_location
    if new_url != old_url:
        working_tree, branch, relpath = \
            controldir.ControlDir.open_containing_tree_or_branch(new_url)
        lock_tree_or_branch(working_tree, branch)
        if consider_relpath and relpath != '':
            if working_tree is not None and apply_view:
                views.check_path_in_view(working_tree, relpath)
            specific_files.append(relpath)
    new_tree = _get_tree_to_diff(new_revision_spec, working_tree, branch,
                                 basis_is_default=working_tree is None)
    new_branch = branch

    # Get the specific files (all files is None, no files is [])
    if make_paths_wt_relative and working_tree is not None:
        other_paths = working_tree.safe_relpath_files(
            other_paths,
            apply_view=apply_view)
    specific_files.extend(other_paths)
    if len(specific_files) == 0:
        specific_files = None
        if (working_tree is not None and working_tree.supports_views() and
                apply_view):
            view_files = working_tree.views.lookup_view()
            if view_files:
                specific_files = view_files
                view_str = views.view_display_str(view_files)
                note(gettext("*** Ignoring files outside view. View is %s") % view_str)

    # Get extra trees that ought to be searched for file-ids
    extra_trees = None
    if working_tree is not None and working_tree not in (old_tree, new_tree):
        extra_trees = (working_tree,)
    return (old_tree, new_tree, old_branch, new_branch,
            specific_files, extra_trees)


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
    return spec.as_tree(branch)


def show_diff_trees(old_tree, new_tree, to_file, specific_files=None,
                    external_diff_options=None,
                    old_label='a/', new_label='b/',
                    extra_trees=None,
                    path_encoding='utf8',
                    using=None,
                    format_cls=None,
                    context=DEFAULT_CONTEXT_AMOUNT):
    """Show in text form the changes from one tree to another.

    :param to_file: The output stream.
    :param specific_files: Include only changes to these files - None for all
        changes.
    :param external_diff_options: If set, use an external GNU diff and pass 
        these options.
    :param extra_trees: If set, more Trees to use for looking up file ids
    :param path_encoding: If set, the path will be encoded as specified, 
        otherwise is supposed to be utf8
    :param format_cls: Formatter class (DiffTree subclass)
    """
    if context is None:
        context = DEFAULT_CONTEXT_AMOUNT
    if format_cls is None:
        format_cls = DiffTree
    with old_tree.lock_read():
        if extra_trees is not None:
            for tree in extra_trees:
                tree.lock_read()
        new_tree.lock_read()
        try:
            differ = format_cls.from_trees_options(old_tree, new_tree, to_file,
                                                   path_encoding,
                                                   external_diff_options,
                                                   old_label, new_label, using,
                                                   context_lines=context)
            return differ.show_diff(specific_files, extra_trees)
        finally:
            new_tree.unlock()
            if extra_trees is not None:
                for tree in extra_trees:
                    tree.unlock()


def _patch_header_date(tree, file_id, path):
    """Returns a timestamp suitable for use in a patch header."""
    try:
        mtime = tree.get_file_mtime(path)
    except FileTimestampUnavailable:
        mtime = 0
    return timestamp.format_patch_date(mtime)


def get_executable_change(old_is_x, new_is_x):
    descr = {True: b"+x", False: b"-x", None: b"??"}
    if old_is_x != new_is_x:
        return [b"%s to %s" % (descr[old_is_x], descr[new_is_x],)]
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
            old_target = self.old_tree.get_symlink_target(old_path)
        elif old_kind is None:
            old_target = None
        else:
            return self.CANNOT_DIFF
        if new_kind == 'symlink':
            new_target = self.new_tree.get_symlink_target(new_path)
        elif new_kind is None:
            new_target = None
        else:
            return self.CANNOT_DIFF
        return self.diff_symlink(old_target, new_target)

    def diff_symlink(self, old_target, new_target):
        if old_target is None:
            self.to_file.write(b'=== target is \'%s\'\n' %
                               new_target.encode(self.path_encoding, 'replace'))
        elif new_target is None:
            self.to_file.write(b'=== target was \'%s\'\n' %
                               old_target.encode(self.path_encoding, 'replace'))
        else:
            self.to_file.write(b'=== target changed \'%s\' => \'%s\'\n' %
                               (old_target.encode(self.path_encoding, 'replace'),
                                new_target.encode(self.path_encoding, 'replace')))
        return self.CHANGED


class DiffText(DiffPath):

    # GNU Patch uses the epoch date to detect files that are being added
    # or removed in a diff.
    EPOCH_DATE = '1970-01-01 00:00:00 +0000'

    def __init__(self, old_tree, new_tree, to_file, path_encoding='utf-8',
                 old_label='', new_label='', text_differ=internal_diff,
                 context_lines=DEFAULT_CONTEXT_AMOUNT):
        DiffPath.__init__(self, old_tree, new_tree, to_file, path_encoding)
        self.text_differ = text_differ
        self.old_label = old_label
        self.new_label = new_label
        self.path_encoding = path_encoding
        self.context_lines = context_lines

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
        from_label = '%s%s\t%s' % (self.old_label, old_path,
                                   old_date)
        to_label = '%s%s\t%s' % (self.new_label, new_path,
                                 new_date)
        return self.diff_text(old_path, new_path, from_label, to_label,
                              from_file_id, to_file_id)

    def diff_text(self, from_path, to_path, from_label, to_label,
                  from_file_id=None, to_file_id=None):
        """Diff the content of given files in two trees

        :param from_path: The path in the from tree. If None,
            the file is not present in the from tree.
        :param to_path: The path in the to tree. This may refer
            to a different file from from_path.  If None,
            the file is not present in the to tree.
        :param from_file_id: The id of the file in the from tree or None if
            unknown.
        :param to_file_id: The id of the file in the to tree or None if
            unknown.
        """
        def _get_text(tree, file_id, path):
            if file_id is None:
                return []
            return tree.get_file_lines(path)
        try:
            from_text = _get_text(self.old_tree, from_file_id, from_path)
            to_text = _get_text(self.new_tree, to_file_id, to_path)
            self.text_differ(from_label, from_text, to_label, to_text,
                             self.to_file, path_encoding=self.path_encoding,
                             context_lines=self.context_lines)
        except errors.BinaryFile:
            self.to_file.write(
                ("Binary files %s and %s differ\n" %
                 (from_label, to_label)).encode(self.path_encoding, 'replace'))
        return self.CHANGED


class DiffFromTool(DiffPath):

    def __init__(self, command_template, old_tree, new_tree, to_file,
                 path_encoding='utf-8'):
        DiffPath.__init__(self, old_tree, new_tree, to_file, path_encoding)
        self.command_template = command_template
        self._root = osutils.mkdtemp(prefix='brz-diff-')

    @classmethod
    def from_string(klass, command_string, old_tree, new_tree, to_file,
                    path_encoding='utf-8'):
        command_template = cmdline.split(command_string)
        if '@' not in command_string:
            command_template.extend(['@old_path', '@new_path'])
        return klass(command_template, old_tree, new_tree, to_file,
                     path_encoding)

    @classmethod
    def make_from_diff_tree(klass, command_string, external_diff_options=None):
        def from_diff_tree(diff_tree):
            full_command_string = [command_string]
            if external_diff_options is not None:
                full_command_string += ' ' + external_diff_options
            return klass.from_string(full_command_string, diff_tree.old_tree,
                                     diff_tree.new_tree, diff_tree.to_file)
        return from_diff_tree

    def _get_command(self, old_path, new_path):
        my_map = {'old_path': old_path, 'new_path': new_path}
        command = [AtTemplate(t).substitute(my_map) for t in
                   self.command_template]
        if sys.platform == 'win32':  # Popen doesn't accept unicode on win32
            command_encoded = []
            for c in command:
                if isinstance(c, text_type):
                    command_encoded.append(c.encode('mbcs'))
                else:
                    command_encoded.append(c)
            return command_encoded
        else:
            return command

    def _execute(self, old_path, new_path):
        command = self._get_command(old_path, new_path)
        try:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                    cwd=self._root)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise errors.ExecutableMissing(command[0])
            else:
                raise
        self.to_file.write(proc.stdout.read())
        proc.stdout.close()
        return proc.wait()

    def _try_symlink_root(self, tree, prefix):
        if (getattr(tree, 'abspath', None) is None or
                not osutils.host_os_dereferences_symlinks()):
            return False
        try:
            os.symlink(tree.abspath(''), osutils.pathjoin(self._root, prefix))
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
        return True

    @staticmethod
    def _fenc():
        """Returns safe encoding for passing file path to diff tool"""
        if sys.platform == 'win32':
            return 'mbcs'
        else:
            # Don't fallback to 'utf-8' because subprocess may not be able to
            # handle utf-8 correctly when locale is not utf-8.
            return sys.getfilesystemencoding() or 'ascii'

    def _is_safepath(self, path):
        """Return true if `path` may be able to pass to subprocess."""
        fenc = self._fenc()
        try:
            return path == path.encode(fenc).decode(fenc)
        except UnicodeError:
            return False

    def _safe_filename(self, prefix, relpath):
        """Replace unsafe character in `relpath` then join `self._root`,
        `prefix` and `relpath`."""
        fenc = self._fenc()
        # encoded_str.replace('?', '_') may break multibyte char.
        # So we should encode, decode, then replace(u'?', u'_')
        relpath_tmp = relpath.encode(fenc, 'replace').decode(fenc, 'replace')
        relpath_tmp = relpath_tmp.replace(u'?', u'_')
        return osutils.pathjoin(self._root, prefix, relpath_tmp)

    def _write_file(self, relpath, tree, prefix, force_temp=False,
                    allow_write=False, file_id=None):
        if not force_temp and isinstance(tree, WorkingTree):
            full_path = tree.abspath(relpath)
            if self._is_safepath(full_path):
                return full_path

        full_path = self._safe_filename(prefix, relpath)
        if not force_temp and self._try_symlink_root(tree, prefix):
            return full_path
        parent_dir = osutils.dirname(full_path)
        try:
            os.makedirs(parent_dir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
        source = tree.get_file(relpath)
        try:
            with open(full_path, 'wb') as target:
                osutils.pumpfile(source, target)
        finally:
            source.close()
        try:
            mtime = tree.get_file_mtime(relpath)
        except FileTimestampUnavailable:
            pass
        else:
            os.utime(full_path, (mtime, mtime))
        if not allow_write:
            osutils.make_readonly(full_path)
        return full_path

    def _prepare_files(self, old_path, new_path, force_temp=False,
                       allow_write_new=False, file_id=None):
        old_disk_path = self._write_file(old_path, self.old_tree, 'old',
                                         force_temp, file_id=file_id)
        new_disk_path = self._write_file(new_path, self.new_tree, 'new',
                                         force_temp, file_id=file_id,
                                         allow_write=allow_write_new)
        return old_disk_path, new_disk_path

    def finish(self):
        try:
            osutils.rmtree(self._root)
        except OSError as e:
            if e.errno != errno.ENOENT:
                mutter("The temporary directory \"%s\" was not "
                       "cleanly removed: %s." % (self._root, e))

    def diff(self, file_id, old_path, new_path, old_kind, new_kind):
        if (old_kind, new_kind) != ('file', 'file'):
            return DiffPath.CANNOT_DIFF
        (old_disk_path, new_disk_path) = self._prepare_files(
            old_path, new_path, file_id=file_id)
        self._execute(old_disk_path, new_disk_path)

    def edit_file(self, old_path, new_path, file_id=None):
        """Use this tool to edit a file.

        A temporary copy will be edited, and the new contents will be
        returned.

        :param file_id: The id of the file to edit.
        :return: The new contents of the file.
        """
        old_abs_path, new_abs_path = self._prepare_files(
            old_path, new_path, allow_write_new=True, force_temp=True,
            file_id=file_id)
        command = self._get_command(old_abs_path, new_abs_path)
        subprocess.call(command, cwd=self._root)
        with open(new_abs_path, 'rb') as new_file:
            return new_file.read()


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
                                 '', '', internal_diff)
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
                           new_label, using, context_lines):
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
            extra_factories = [DiffFromTool.make_from_diff_tree(
                using, external_diff_options)]
        else:
            extra_factories = []
        if external_diff_options:
            opts = external_diff_options.split()

            def diff_file(olab, olines, nlab, nlines, to_file, path_encoding=None, context_lines=None):
                """:param path_encoding: not used but required
                        to match the signature of internal_diff.
                """
                external_diff(olab, olines, nlab, nlines, to_file, opts)
        else:
            diff_file = internal_diff
        diff_text = DiffText(old_tree, new_tree, to_file, path_encoding,
                             old_label, new_label, diff_file, context_lines=context_lines)
        return klass(old_tree, new_tree, to_file, path_encoding, diff_text,
                     extra_factories)

    def show_diff(self, specific_files, extra_trees=None):
        """Write tree diff to self.to_file

        :param specific_files: the specific files to compare (recursive)
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
            # The root does not get diffed, and items with no known kind (that
            # is, missing) in both trees are skipped as well.
            if parent == (None, None) or kind == (None, None):
                continue
            oldpath, newpath = paths
            oldpath_encoded = get_encoded_path(paths[0])
            newpath_encoded = get_encoded_path(paths[1])
            old_present = (kind[0] is not None and versioned[0])
            new_present = (kind[1] is not None and versioned[1])
            renamed = (parent[0], name[0]) != (parent[1], name[1])

            properties_changed = []
            properties_changed.extend(
                get_executable_change(executable[0], executable[1]))

            if properties_changed:
                prop_str = b" (properties changed: %s)" % (
                    b", ".join(properties_changed),)
            else:
                prop_str = b""

            if (old_present, new_present) == (True, False):
                self.to_file.write(b"=== removed %s '%s'\n" %
                                   (kind[0].encode('ascii'), oldpath_encoded))
                newpath = oldpath
            elif (old_present, new_present) == (False, True):
                self.to_file.write(b"=== added %s '%s'\n" %
                                   (kind[1].encode('ascii'), newpath_encoded))
                oldpath = newpath
            elif renamed:
                self.to_file.write(b"=== renamed %s '%s' => '%s'%s\n" %
                                   (kind[0].encode('ascii'), oldpath_encoded, newpath_encoded, prop_str))
            else:
                # if it was produced by iter_changes, it must be
                # modified *somehow*, either content or execute bit.
                self.to_file.write(b"=== modified %s '%s'%s\n" % (kind[0].encode('ascii'),
                                                                  newpath_encoded, prop_str))
            if changed_content:
                self._diff(oldpath, newpath, kind[0], kind[1], file_id=file_id)
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
        if old_path is None:
            old_kind = None
        else:
            old_kind = self.old_tree.kind(old_path)
        if new_path is None:
            new_kind = None
        else:
            new_kind = self.new_tree.kind(new_path)
        self._diff(old_path, new_path, old_kind, new_kind, file_id=file_id)

    def _diff(self, old_path, new_path, old_kind, new_kind, file_id):
        result = DiffPath._diff_many(self.differs, file_id, old_path,
                                     new_path, old_kind, new_kind)
        if result is DiffPath.CANNOT_DIFF:
            error_path = new_path
            if error_path is None:
                error_path = old_path
            raise errors.NoDiffFound(error_path)


format_registry = Registry()
format_registry.register('default', DiffTree)
