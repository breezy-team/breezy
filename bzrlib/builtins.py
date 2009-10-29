# Copyright (C) 2004, 2005, 2006, 2007, 2008, 2009 Canonical Ltd
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

"""builtin bzr commands"""

import os

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import codecs
import cStringIO
import sys
import time

import bzrlib
from bzrlib import (
    bugtracker,
    bundle,
    btree_index,
    bzrdir,
    delta,
    config,
    errors,
    globbing,
    hooks,
    log,
    merge as _mod_merge,
    merge_directive,
    osutils,
    reconfigure,
    rename_map,
    revision as _mod_revision,
    symbol_versioning,
    transport,
    ui,
    urlutils,
    views,
    )
from bzrlib.branch import Branch
from bzrlib.conflicts import ConflictList
from bzrlib.revisionspec import RevisionSpec, RevisionInfo
from bzrlib.smtp_connection import SMTPConnection
from bzrlib.workingtree import WorkingTree
""")

from bzrlib.commands import Command, display_command
from bzrlib.option import (
    ListOption,
    Option,
    RegistryOption,
    custom_help,
    _parse_revision_str,
    )
from bzrlib.trace import mutter, note, warning, is_quiet, get_verbosity_level


def tree_files(file_list, default_branch=u'.', canonicalize=True,
    apply_view=True):
    try:
        return internal_tree_files(file_list, default_branch, canonicalize,
            apply_view)
    except errors.FileInWrongBranch, e:
        raise errors.BzrCommandError("%s is not in the same branch as %s" %
                                     (e.path, file_list[0]))


def tree_files_for_add(file_list):
    """
    Return a tree and list of absolute paths from a file list.

    Similar to tree_files, but add handles files a bit differently, so it a
    custom implementation.  In particular, MutableTreeTree.smart_add expects
    absolute paths, which it immediately converts to relative paths.
    """
    # FIXME Would be nice to just return the relative paths like
    # internal_tree_files does, but there are a large number of unit tests
    # that assume the current interface to mutabletree.smart_add
    if file_list:
        tree, relpath = WorkingTree.open_containing(file_list[0])
        if tree.supports_views():
            view_files = tree.views.lookup_view()
            if view_files:
                for filename in file_list:
                    if not osutils.is_inside_any(view_files, filename):
                        raise errors.FileOutsideView(filename, view_files)
        file_list = file_list[:]
        file_list[0] = tree.abspath(relpath)
    else:
        tree = WorkingTree.open_containing(u'.')[0]
        if tree.supports_views():
            view_files = tree.views.lookup_view()
            if view_files:
                file_list = view_files
                view_str = views.view_display_str(view_files)
                note("Ignoring files outside view. View is %s" % view_str)
    return tree, file_list


def _get_one_revision(command_name, revisions):
    if revisions is None:
        return None
    if len(revisions) != 1:
        raise errors.BzrCommandError(
            'bzr %s --revision takes exactly one revision identifier' % (
                command_name,))
    return revisions[0]


def _get_one_revision_tree(command_name, revisions, branch=None, tree=None):
    """Get a revision tree. Not suitable for commands that change the tree.
    
    Specifically, the basis tree in dirstate trees is coupled to the dirstate
    and doing a commit/uncommit/pull will at best fail due to changing the
    basis revision data.

    If tree is passed in, it should be already locked, for lifetime management
    of the trees internal cached state.
    """
    if branch is None:
        branch = tree.branch
    if revisions is None:
        if tree is not None:
            rev_tree = tree.basis_tree()
        else:
            rev_tree = branch.basis_tree()
    else:
        revision = _get_one_revision(command_name, revisions)
        rev_tree = revision.as_tree(branch)
    return rev_tree


# XXX: Bad function name; should possibly also be a class method of
# WorkingTree rather than a function.
def internal_tree_files(file_list, default_branch=u'.', canonicalize=True,
    apply_view=True):
    """Convert command-line paths to a WorkingTree and relative paths.

    This is typically used for command-line processors that take one or
    more filenames, and infer the workingtree that contains them.

    The filenames given are not required to exist.

    :param file_list: Filenames to convert.

    :param default_branch: Fallback tree path to use if file_list is empty or
        None.

    :param apply_view: if True and a view is set, apply it or check that
        specified files are within it

    :return: workingtree, [relative_paths]
    """
    if file_list is None or len(file_list) == 0:
        tree = WorkingTree.open_containing(default_branch)[0]
        if tree.supports_views() and apply_view:
            view_files = tree.views.lookup_view()
            if view_files:
                file_list = view_files
                view_str = views.view_display_str(view_files)
                note("Ignoring files outside view. View is %s" % view_str)
        return tree, file_list
    tree = WorkingTree.open_containing(osutils.realpath(file_list[0]))[0]
    return tree, safe_relpath_files(tree, file_list, canonicalize,
        apply_view=apply_view)


def safe_relpath_files(tree, file_list, canonicalize=True, apply_view=True):
    """Convert file_list into a list of relpaths in tree.

    :param tree: A tree to operate on.
    :param file_list: A list of user provided paths or None.
    :param apply_view: if True and a view is set, apply it or check that
        specified files are within it
    :return: A list of relative paths.
    :raises errors.PathNotChild: When a provided path is in a different tree
        than tree.
    """
    if file_list is None:
        return None
    if tree.supports_views() and apply_view:
        view_files = tree.views.lookup_view()
    else:
        view_files = []
    new_list = []
    # tree.relpath exists as a "thunk" to osutils, but canonical_relpath
    # doesn't - fix that up here before we enter the loop.
    if canonicalize:
        fixer = lambda p: osutils.canonical_relpath(tree.basedir, p)
    else:
        fixer = tree.relpath
    for filename in file_list:
        try:
            relpath = fixer(osutils.dereference_path(filename))
            if  view_files and not osutils.is_inside_any(view_files, relpath):
                raise errors.FileOutsideView(filename, view_files)
            new_list.append(relpath)
        except errors.PathNotChild:
            raise errors.FileInWrongBranch(tree.branch, filename)
    return new_list


def _get_view_info_for_change_reporter(tree):
    """Get the view information from a tree for change reporting."""
    view_info = None
    try:
        current_view = tree.views.get_view_info()[0]
        if current_view is not None:
            view_info = (current_view, tree.views.lookup_view())
    except errors.ViewsNotSupported:
        pass
    return view_info


# TODO: Make sure no commands unconditionally use the working directory as a
# branch.  If a filename argument is used, the first of them should be used to
# specify the branch.  (Perhaps this can be factored out into some kind of
# Argument class, representing a file in a branch, where the first occurrence
# opens the branch?)

class cmd_status(Command):
    """Display status summary.

    This reports on versioned and unknown files, reporting them
    grouped by state.  Possible states are:

    added
        Versioned in the working copy but not in the previous revision.

    removed
        Versioned in the previous revision but removed or deleted
        in the working copy.

    renamed
        Path of this file changed from the previous revision;
        the text may also have changed.  This includes files whose
        parent directory was renamed.

    modified
        Text has changed since the previous revision.

    kind changed
        File kind has been changed (e.g. from file to directory).

    unknown
        Not versioned and not matching an ignore pattern.

    To see ignored files use 'bzr ignored'.  For details on the
    changes to file texts, use 'bzr diff'.

    Note that --short or -S gives status flags for each item, similar
    to Subversion's status command. To get output similar to svn -q,
    use bzr status -SV.

    If no arguments are specified, the status of the entire working
    directory is shown.  Otherwise, only the status of the specified
    files or directories is reported.  If a directory is given, status
    is reported for everything inside that directory.

    Before merges are committed, the pending merge tip revisions are
    shown. To see all pending merge revisions, use the -v option.
    To skip the display of pending merge information altogether, use
    the no-pending option or specify a file/directory.

    If a revision argument is given, the status is calculated against
    that revision, or between two revisions if two are provided.
    """

    # TODO: --no-recurse, --recurse options

    takes_args = ['file*']
    takes_options = ['show-ids', 'revision', 'change', 'verbose',
                     Option('short', help='Use short status indicators.',
                            short_name='S'),
                     Option('versioned', help='Only show versioned files.',
                            short_name='V'),
                     Option('no-pending', help='Don\'t show pending merges.',
                           ),
                     ]
    aliases = ['st', 'stat']

    encoding_type = 'replace'
    _see_also = ['diff', 'revert', 'status-flags']

    @display_command
    def run(self, show_ids=False, file_list=None, revision=None, short=False,
            versioned=False, no_pending=False, verbose=False):
        from bzrlib.status import show_tree_status

        if revision and len(revision) > 2:
            raise errors.BzrCommandError('bzr status --revision takes exactly'
                                         ' one or two revision specifiers')

        tree, relfile_list = tree_files(file_list)
        # Avoid asking for specific files when that is not needed.
        if relfile_list == ['']:
            relfile_list = None
            # Don't disable pending merges for full trees other than '.'.
            if file_list == ['.']:
                no_pending = True
        # A specific path within a tree was given.
        elif relfile_list is not None:
            no_pending = True
        show_tree_status(tree, show_ids=show_ids,
                         specific_files=relfile_list, revision=revision,
                         to_file=self.outf, short=short, versioned=versioned,
                         show_pending=(not no_pending), verbose=verbose)


class cmd_cat_revision(Command):
    """Write out metadata for a revision.

    The revision to print can either be specified by a specific
    revision identifier, or you can use --revision.
    """

    hidden = True
    takes_args = ['revision_id?']
    takes_options = ['revision']
    # cat-revision is more for frontends so should be exact
    encoding = 'strict'

    @display_command
    def run(self, revision_id=None, revision=None):
        if revision_id is not None and revision is not None:
            raise errors.BzrCommandError('You can only supply one of'
                                         ' revision_id or --revision')
        if revision_id is None and revision is None:
            raise errors.BzrCommandError('You must supply either'
                                         ' --revision or a revision_id')
        b = WorkingTree.open_containing(u'.')[0].branch

        # TODO: jam 20060112 should cat-revision always output utf-8?
        if revision_id is not None:
            revision_id = osutils.safe_revision_id(revision_id, warn=False)
            try:
                self.outf.write(b.repository.get_revision_xml(revision_id).decode('utf-8'))
            except errors.NoSuchRevision:
                msg = "The repository %s contains no revision %s." % (b.repository.base,
                    revision_id)
                raise errors.BzrCommandError(msg)
        elif revision is not None:
            for rev in revision:
                if rev is None:
                    raise errors.BzrCommandError('You cannot specify a NULL'
                                                 ' revision.')
                rev_id = rev.as_revision_id(b)
                self.outf.write(b.repository.get_revision_xml(rev_id).decode('utf-8'))


class cmd_dump_btree(Command):
    """Dump the contents of a btree index file to stdout.

    PATH is a btree index file, it can be any URL. This includes things like
    .bzr/repository/pack-names, or .bzr/repository/indices/a34b3a...ca4a4.iix

    By default, the tuples stored in the index file will be displayed. With
    --raw, we will uncompress the pages, but otherwise display the raw bytes
    stored in the index.
    """

    # TODO: Do we want to dump the internal nodes as well?
    # TODO: It would be nice to be able to dump the un-parsed information,
    #       rather than only going through iter_all_entries. However, this is
    #       good enough for a start
    hidden = True
    encoding_type = 'exact'
    takes_args = ['path']
    takes_options = [Option('raw', help='Write the uncompressed bytes out,'
                                        ' rather than the parsed tuples.'),
                    ]

    def run(self, path, raw=False):
        dirname, basename = osutils.split(path)
        t = transport.get_transport(dirname)
        if raw:
            self._dump_raw_bytes(t, basename)
        else:
            self._dump_entries(t, basename)

    def _get_index_and_bytes(self, trans, basename):
        """Create a BTreeGraphIndex and raw bytes."""
        bt = btree_index.BTreeGraphIndex(trans, basename, None)
        bytes = trans.get_bytes(basename)
        bt._file = cStringIO.StringIO(bytes)
        bt._size = len(bytes)
        return bt, bytes

    def _dump_raw_bytes(self, trans, basename):
        import zlib

        # We need to parse at least the root node.
        # This is because the first page of every row starts with an
        # uncompressed header.
        bt, bytes = self._get_index_and_bytes(trans, basename)
        for page_idx, page_start in enumerate(xrange(0, len(bytes),
                                                     btree_index._PAGE_SIZE)):
            page_end = min(page_start + btree_index._PAGE_SIZE, len(bytes))
            page_bytes = bytes[page_start:page_end]
            if page_idx == 0:
                self.outf.write('Root node:\n')
                header_end, data = bt._parse_header_from_bytes(page_bytes)
                self.outf.write(page_bytes[:header_end])
                page_bytes = data
            self.outf.write('\nPage %d\n' % (page_idx,))
            decomp_bytes = zlib.decompress(page_bytes)
            self.outf.write(decomp_bytes)
            self.outf.write('\n')

    def _dump_entries(self, trans, basename):
        try:
            st = trans.stat(basename)
        except errors.TransportNotPossible:
            # We can't stat, so we'll fake it because we have to do the 'get()'
            # anyway.
            bt, _ = self._get_index_and_bytes(trans, basename)
        else:
            bt = btree_index.BTreeGraphIndex(trans, basename, st.st_size)
        for node in bt.iter_all_entries():
            # Node is made up of:
            # (index, key, value, [references])
            self.outf.write('%s\n' % (node[1:],))


class cmd_remove_tree(Command):
    """Remove the working tree from a given branch/checkout.

    Since a lightweight checkout is little more than a working tree
    this will refuse to run against one.

    To re-create the working tree, use "bzr checkout".
    """
    _see_also = ['checkout', 'working-trees']
    takes_args = ['location?']
    takes_options = [
        Option('force',
               help='Remove the working tree even if it has '
                    'uncommitted changes.'),
        ]

    def run(self, location='.', force=False):
        d = bzrdir.BzrDir.open(location)

        try:
            working = d.open_workingtree()
        except errors.NoWorkingTree:
            raise errors.BzrCommandError("No working tree to remove")
        except errors.NotLocalUrl:
            raise errors.BzrCommandError("You cannot remove the working tree"
                                         " of a remote path")
        if not force:
            # XXX: What about pending merges ? -- vila 20090629
            if working.has_changes(working.basis_tree()):
                raise errors.UncommittedChanges(working)

        working_path = working.bzrdir.root_transport.base
        branch_path = working.branch.bzrdir.root_transport.base
        if working_path != branch_path:
            raise errors.BzrCommandError("You cannot remove the working tree"
                                         " from a lightweight checkout")

        d.destroy_workingtree()


class cmd_revno(Command):
    """Show current revision number.

    This is equal to the number of revisions on this branch.
    """

    _see_also = ['info']
    takes_args = ['location?']
    takes_options = [
        Option('tree', help='Show revno of working tree'),
        ]

    @display_command
    def run(self, tree=False, location=u'.'):
        if tree:
            try:
                wt = WorkingTree.open_containing(location)[0]
                wt.lock_read()
            except (errors.NoWorkingTree, errors.NotLocalUrl):
                raise errors.NoWorkingTree(location)
            try:
                revid = wt.last_revision()
                try:
                    revno_t = wt.branch.revision_id_to_dotted_revno(revid)
                except errors.NoSuchRevision:
                    revno_t = ('???',)
                revno = ".".join(str(n) for n in revno_t)
            finally:
                wt.unlock()
        else:
            b = Branch.open_containing(location)[0]
            b.lock_read()
            try:
                revno = b.revno()
            finally:
                b.unlock()

        self.outf.write(str(revno) + '\n')


class cmd_revision_info(Command):
    """Show revision number and revision id for a given revision identifier.
    """
    hidden = True
    takes_args = ['revision_info*']
    takes_options = [
        'revision',
        Option('directory',
            help='Branch to examine, '
                 'rather than the one containing the working directory.',
            short_name='d',
            type=unicode,
            ),
        Option('tree', help='Show revno of working tree'),
        ]

    @display_command
    def run(self, revision=None, directory=u'.', tree=False,
            revision_info_list=[]):

        try:
            wt = WorkingTree.open_containing(directory)[0]
            b = wt.branch
            wt.lock_read()
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            wt = None
            b = Branch.open_containing(directory)[0]
            b.lock_read()
        try:
            revision_ids = []
            if revision is not None:
                revision_ids.extend(rev.as_revision_id(b) for rev in revision)
            if revision_info_list is not None:
                for rev_str in revision_info_list:
                    rev_spec = RevisionSpec.from_string(rev_str)
                    revision_ids.append(rev_spec.as_revision_id(b))
            # No arguments supplied, default to the last revision
            if len(revision_ids) == 0:
                if tree:
                    if wt is None:
                        raise errors.NoWorkingTree(directory)
                    revision_ids.append(wt.last_revision())
                else:
                    revision_ids.append(b.last_revision())

            revinfos = []
            maxlen = 0
            for revision_id in revision_ids:
                try:
                    dotted_revno = b.revision_id_to_dotted_revno(revision_id)
                    revno = '.'.join(str(i) for i in dotted_revno)
                except errors.NoSuchRevision:
                    revno = '???'
                maxlen = max(maxlen, len(revno))
                revinfos.append([revno, revision_id])
        finally:
            if wt is None:
                b.unlock()
            else:
                wt.unlock()

        for ri in revinfos:
            self.outf.write('%*s %s\n' % (maxlen, ri[0], ri[1]))


class cmd_add(Command):
    """Add specified files or directories.

    In non-recursive mode, all the named items are added, regardless
    of whether they were previously ignored.  A warning is given if
    any of the named files are already versioned.

    In recursive mode (the default), files are treated the same way
    but the behaviour for directories is different.  Directories that
    are already versioned do not give a warning.  All directories,
    whether already versioned or not, are searched for files or
    subdirectories that are neither versioned or ignored, and these
    are added.  This search proceeds recursively into versioned
    directories.  If no names are given '.' is assumed.

    Therefore simply saying 'bzr add' will version all files that
    are currently unknown.

    Adding a file whose parent directory is not versioned will
    implicitly add the parent, and so on up to the root. This means
    you should never need to explicitly add a directory, they'll just
    get added when you add a file in the directory.

    --dry-run will show which files would be added, but not actually
    add them.

    --file-ids-from will try to use the file ids from the supplied path.
    It looks up ids trying to find a matching parent directory with the
    same filename, and then by pure path. This option is rarely needed
    but can be useful when adding the same logical file into two
    branches that will be merged later (without showing the two different
    adds as a conflict). It is also useful when merging another project
    into a subdirectory of this one.
    
    Any files matching patterns in the ignore list will not be added
    unless they are explicitly mentioned.
    """
    takes_args = ['file*']
    takes_options = [
        Option('no-recurse',
               help="Don't recursively add the contents of directories."),
        Option('dry-run',
               help="Show what would be done, but don't actually do anything."),
        'verbose',
        Option('file-ids-from',
               type=unicode,
               help='Lookup file ids from this tree.'),
        ]
    encoding_type = 'replace'
    _see_also = ['remove', 'ignore']

    def run(self, file_list, no_recurse=False, dry_run=False, verbose=False,
            file_ids_from=None):
        import bzrlib.add

        base_tree = None
        if file_ids_from is not None:
            try:
                base_tree, base_path = WorkingTree.open_containing(
                                            file_ids_from)
            except errors.NoWorkingTree:
                base_branch, base_path = Branch.open_containing(
                                            file_ids_from)
                base_tree = base_branch.basis_tree()

            action = bzrlib.add.AddFromBaseAction(base_tree, base_path,
                          to_file=self.outf, should_print=(not is_quiet()))
        else:
            action = bzrlib.add.AddAction(to_file=self.outf,
                should_print=(not is_quiet()))

        if base_tree:
            base_tree.lock_read()
        try:
            file_list = self._maybe_expand_globs(file_list)
            tree, file_list = tree_files_for_add(file_list)
            added, ignored = tree.smart_add(file_list, not
                no_recurse, action=action, save=not dry_run)
        finally:
            if base_tree is not None:
                base_tree.unlock()
        if len(ignored) > 0:
            if verbose:
                for glob in sorted(ignored.keys()):
                    for path in ignored[glob]:
                        self.outf.write("ignored %s matching \"%s\"\n"
                                        % (path, glob))


class cmd_mkdir(Command):
    """Create a new versioned directory.

    This is equivalent to creating the directory and then adding it.
    """

    takes_args = ['dir+']
    encoding_type = 'replace'

    def run(self, dir_list):
        for d in dir_list:
            os.mkdir(d)
            wt, dd = WorkingTree.open_containing(d)
            wt.add([dd])
            self.outf.write('added %s\n' % d)


class cmd_relpath(Command):
    """Show path of a file relative to root"""

    takes_args = ['filename']
    hidden = True

    @display_command
    def run(self, filename):
        # TODO: jam 20050106 Can relpath return a munged path if
        #       sys.stdout encoding cannot represent it?
        tree, relpath = WorkingTree.open_containing(filename)
        self.outf.write(relpath)
        self.outf.write('\n')


class cmd_inventory(Command):
    """Show inventory of the current working copy or a revision.

    It is possible to limit the output to a particular entry
    type using the --kind option.  For example: --kind file.

    It is also possible to restrict the list of files to a specific
    set. For example: bzr inventory --show-ids this/file
    """

    hidden = True
    _see_also = ['ls']
    takes_options = [
        'revision',
        'show-ids',
        Option('kind',
               help='List entries of a particular kind: file, directory, symlink.',
               type=unicode),
        ]
    takes_args = ['file*']

    @display_command
    def run(self, revision=None, show_ids=False, kind=None, file_list=None):
        if kind and kind not in ['file', 'directory', 'symlink']:
            raise errors.BzrCommandError('invalid kind %r specified' % (kind,))

        revision = _get_one_revision('inventory', revision)
        work_tree, file_list = tree_files(file_list)
        work_tree.lock_read()
        try:
            if revision is not None:
                tree = revision.as_tree(work_tree.branch)

                extra_trees = [work_tree]
                tree.lock_read()
            else:
                tree = work_tree
                extra_trees = []

            if file_list is not None:
                file_ids = tree.paths2ids(file_list, trees=extra_trees,
                                          require_versioned=True)
                # find_ids_across_trees may include some paths that don't
                # exist in 'tree'.
                entries = sorted((tree.id2path(file_id), tree.inventory[file_id])
                                 for file_id in file_ids if file_id in tree)
            else:
                entries = tree.inventory.entries()
        finally:
            tree.unlock()
            if tree is not work_tree:
                work_tree.unlock()

        for path, entry in entries:
            if kind and kind != entry.kind:
                continue
            if show_ids:
                self.outf.write('%-50s %s\n' % (path, entry.file_id))
            else:
                self.outf.write(path)
                self.outf.write('\n')


class cmd_mv(Command):
    """Move or rename a file.

    :Usage:
        bzr mv OLDNAME NEWNAME

        bzr mv SOURCE... DESTINATION

    If the last argument is a versioned directory, all the other names
    are moved into it.  Otherwise, there must be exactly two arguments
    and the file is changed to a new name.

    If OLDNAME does not exist on the filesystem but is versioned and
    NEWNAME does exist on the filesystem but is not versioned, mv
    assumes that the file has been manually moved and only updates
    its internal inventory to reflect that change.
    The same is valid when moving many SOURCE files to a DESTINATION.

    Files cannot be moved between branches.
    """

    takes_args = ['names*']
    takes_options = [Option("after", help="Move only the bzr identifier"
        " of the file, because the file has already been moved."),
        Option('auto', help='Automatically guess renames.'),
        Option('dry-run', help='Avoid making changes when guessing renames.'),
        ]
    aliases = ['move', 'rename']
    encoding_type = 'replace'

    def run(self, names_list, after=False, auto=False, dry_run=False):
        if auto:
            return self.run_auto(names_list, after, dry_run)
        elif dry_run:
            raise errors.BzrCommandError('--dry-run requires --auto.')
        if names_list is None:
            names_list = []
        if len(names_list) < 2:
            raise errors.BzrCommandError("missing file argument")
        tree, rel_names = tree_files(names_list, canonicalize=False)
        tree.lock_tree_write()
        try:
            self._run(tree, names_list, rel_names, after)
        finally:
            tree.unlock()

    def run_auto(self, names_list, after, dry_run):
        if names_list is not None and len(names_list) > 1:
            raise errors.BzrCommandError('Only one path may be specified to'
                                         ' --auto.')
        if after:
            raise errors.BzrCommandError('--after cannot be specified with'
                                         ' --auto.')
        work_tree, file_list = tree_files(names_list, default_branch='.')
        work_tree.lock_tree_write()
        try:
            rename_map.RenameMap.guess_renames(work_tree, dry_run)
        finally:
            work_tree.unlock()

    def _run(self, tree, names_list, rel_names, after):
        into_existing = osutils.isdir(names_list[-1])
        if into_existing and len(names_list) == 2:
            # special cases:
            # a. case-insensitive filesystem and change case of dir
            # b. move directory after the fact (if the source used to be
            #    a directory, but now doesn't exist in the working tree
            #    and the target is an existing directory, just rename it)
            if (not tree.case_sensitive
                and rel_names[0].lower() == rel_names[1].lower()):
                into_existing = False
            else:
                inv = tree.inventory
                # 'fix' the case of a potential 'from'
                from_id = tree.path2id(
                            tree.get_canonical_inventory_path(rel_names[0]))
                if (not osutils.lexists(names_list[0]) and
                    from_id and inv.get_file_kind(from_id) == "directory"):
                    into_existing = False
        # move/rename
        if into_existing:
            # move into existing directory
            # All entries reference existing inventory items, so fix them up
            # for cicp file-systems.
            rel_names = tree.get_canonical_inventory_paths(rel_names)
            for pair in tree.move(rel_names[:-1], rel_names[-1], after=after):
                self.outf.write("%s => %s\n" % pair)
        else:
            if len(names_list) != 2:
                raise errors.BzrCommandError('to mv multiple files the'
                                             ' destination must be a versioned'
                                             ' directory')

            # for cicp file-systems: the src references an existing inventory
            # item:
            src = tree.get_canonical_inventory_path(rel_names[0])
            # Find the canonical version of the destination:  In all cases, the
            # parent of the target must be in the inventory, so we fetch the
            # canonical version from there (we do not always *use* the
            # canonicalized tail portion - we may be attempting to rename the
            # case of the tail)
            canon_dest = tree.get_canonical_inventory_path(rel_names[1])
            dest_parent = osutils.dirname(canon_dest)
            spec_tail = osutils.basename(rel_names[1])
            # For a CICP file-system, we need to avoid creating 2 inventory
            # entries that differ only by case.  So regardless of the case
            # we *want* to use (ie, specified by the user or the file-system),
            # we must always choose to use the case of any existing inventory
            # items.  The only exception to this is when we are attempting a
            # case-only rename (ie, canonical versions of src and dest are
            # the same)
            dest_id = tree.path2id(canon_dest)
            if dest_id is None or tree.path2id(src) == dest_id:
                # No existing item we care about, so work out what case we
                # are actually going to use.
                if after:
                    # If 'after' is specified, the tail must refer to a file on disk.
                    if dest_parent:
                        dest_parent_fq = osutils.pathjoin(tree.basedir, dest_parent)
                    else:
                        # pathjoin with an empty tail adds a slash, which breaks
                        # relpath :(
                        dest_parent_fq = tree.basedir

                    dest_tail = osutils.canonical_relpath(
                                    dest_parent_fq,
                                    osutils.pathjoin(dest_parent_fq, spec_tail))
                else:
                    # not 'after', so case as specified is used
                    dest_tail = spec_tail
            else:
                # Use the existing item so 'mv' fails with AlreadyVersioned.
                dest_tail = os.path.basename(canon_dest)
            dest = osutils.pathjoin(dest_parent, dest_tail)
            mutter("attempting to move %s => %s", src, dest)
            tree.rename_one(src, dest, after=after)
            self.outf.write("%s => %s\n" % (src, dest))


class cmd_pull(Command):
    """Turn this branch into a mirror of another branch.

    This command only works on branches that have not diverged.  Branches are
    considered diverged if the destination branch's most recent commit is one
    that has not been merged (directly or indirectly) into the parent.

    If branches have diverged, you can use 'bzr merge' to integrate the changes
    from one into the other.  Once one branch has merged, the other should
    be able to pull it again.

    If you want to forget your local changes and just update your branch to
    match the remote one, use pull --overwrite.

    If there is no default location set, the first pull will set it.  After
    that, you can omit the location to use the default.  To change the
    default, use --remember. The value will only be saved if the remote
    location can be accessed.

    Note: The location can be specified either in the form of a branch,
    or in the form of a path to a file containing a merge directive generated
    with bzr send.
    """

    _see_also = ['push', 'update', 'status-flags', 'send']
    takes_options = ['remember', 'overwrite', 'revision',
        custom_help('verbose',
            help='Show logs of pulled revisions.'),
        Option('directory',
            help='Branch to pull into, '
                 'rather than the one containing the working directory.',
            short_name='d',
            type=unicode,
            ),
        Option('local',
            help="Perform a local pull in a bound "
                 "branch.  Local pulls are not applied to "
                 "the master branch."
            ),
        ]
    takes_args = ['location?']
    encoding_type = 'replace'

    def run(self, location=None, remember=False, overwrite=False,
            revision=None, verbose=False,
            directory=None, local=False):
        # FIXME: too much stuff is in the command class
        revision_id = None
        mergeable = None
        if directory is None:
            directory = u'.'
        try:
            tree_to = WorkingTree.open_containing(directory)[0]
            branch_to = tree_to.branch
        except errors.NoWorkingTree:
            tree_to = None
            branch_to = Branch.open_containing(directory)[0]
        
        if local and not branch_to.get_bound_location():
            raise errors.LocalRequiresBoundBranch()

        possible_transports = []
        if location is not None:
            try:
                mergeable = bundle.read_mergeable_from_url(location,
                    possible_transports=possible_transports)
            except errors.NotABundle:
                mergeable = None

        stored_loc = branch_to.get_parent()
        if location is None:
            if stored_loc is None:
                raise errors.BzrCommandError("No pull location known or"
                                             " specified.")
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                if not is_quiet():
                    self.outf.write("Using saved parent location: %s\n" % display_url)
                location = stored_loc

        revision = _get_one_revision('pull', revision)
        if mergeable is not None:
            if revision is not None:
                raise errors.BzrCommandError(
                    'Cannot use -r with merge directives or bundles')
            mergeable.install_revisions(branch_to.repository)
            base_revision_id, revision_id, verified = \
                mergeable.get_merge_request(branch_to.repository)
            branch_from = branch_to
        else:
            branch_from = Branch.open(location,
                possible_transports=possible_transports)

            if branch_to.get_parent() is None or remember:
                branch_to.set_parent(branch_from.base)

        if branch_from is not branch_to:
            branch_from.lock_read()
        try:
            if revision is not None:
                revision_id = revision.as_revision_id(branch_from)

            branch_to.lock_write()
            try:
                if tree_to is not None:
                    view_info = _get_view_info_for_change_reporter(tree_to)
                    change_reporter = delta._ChangeReporter(
                        unversioned_filter=tree_to.is_ignored,
                        view_info=view_info)
                    result = tree_to.pull(
                        branch_from, overwrite, revision_id, change_reporter,
                        possible_transports=possible_transports, local=local)
                else:
                    result = branch_to.pull(
                        branch_from, overwrite, revision_id, local=local)

                result.report(self.outf)
                if verbose and result.old_revid != result.new_revid:
                    log.show_branch_change(
                        branch_to, self.outf, result.old_revno,
                        result.old_revid)
            finally:
                branch_to.unlock()
        finally:
            if branch_from is not branch_to:
                branch_from.unlock()


class cmd_push(Command):
    """Update a mirror of this branch.

    The target branch will not have its working tree populated because this
    is both expensive, and is not supported on remote file systems.

    Some smart servers or protocols *may* put the working tree in place in
    the future.

    This command only works on branches that have not diverged.  Branches are
    considered diverged if the destination branch's most recent commit is one
    that has not been merged (directly or indirectly) by the source branch.

    If branches have diverged, you can use 'bzr push --overwrite' to replace
    the other branch completely, discarding its unmerged changes.

    If you want to ensure you have the different changes in the other branch,
    do a merge (see bzr help merge) from the other branch, and commit that.
    After that you will be able to do a push without '--overwrite'.

    If there is no default push location set, the first push will set it.
    After that, you can omit the location to use the default.  To change the
    default, use --remember. The value will only be saved if the remote
    location can be accessed.
    """

    _see_also = ['pull', 'update', 'working-trees']
    takes_options = ['remember', 'overwrite', 'verbose', 'revision',
        Option('create-prefix',
               help='Create the path leading up to the branch '
                    'if it does not already exist.'),
        Option('directory',
            help='Branch to push from, '
                 'rather than the one containing the working directory.',
            short_name='d',
            type=unicode,
            ),
        Option('use-existing-dir',
               help='By default push will fail if the target'
                    ' directory exists, but does not already'
                    ' have a control directory.  This flag will'
                    ' allow push to proceed.'),
        Option('stacked',
            help='Create a stacked branch that references the public location '
                'of the parent branch.'),
        Option('stacked-on',
            help='Create a stacked branch that refers to another branch '
                'for the commit history. Only the work not present in the '
                'referenced branch is included in the branch created.',
            type=unicode),
        Option('strict',
               help='Refuse to push if there are uncommitted changes in'
               ' the working tree, --no-strict disables the check.'),
        ]
    takes_args = ['location?']
    encoding_type = 'replace'

    def run(self, location=None, remember=False, overwrite=False,
        create_prefix=False, verbose=False, revision=None,
        use_existing_dir=False, directory=None, stacked_on=None,
        stacked=False, strict=None):
        from bzrlib.push import _show_push_branch

        if directory is None:
            directory = '.'
        # Get the source branch
        (tree, br_from,
         _unused) = bzrdir.BzrDir.open_containing_tree_or_branch(directory)
        if strict is None:
            strict = br_from.get_config().get_user_option_as_bool('push_strict')
        if strict is None: strict = True # default value
        # Get the tip's revision_id
        revision = _get_one_revision('push', revision)
        if revision is not None:
            revision_id = revision.in_history(br_from).rev_id
        else:
            revision_id = None
        if strict and tree is not None and revision_id is None:
            if (tree.has_changes(tree.basis_tree())
                or len(tree.get_parent_ids()) > 1):
                raise errors.UncommittedChanges(
                    tree, more='Use --no-strict to force the push.')
            if tree.last_revision() != tree.branch.last_revision():
                # The tree has lost sync with its branch, there is little
                # chance that the user is aware of it but he can still force
                # the push with --no-strict
                raise errors.OutOfDateTree(
                    tree, more='Use --no-strict to force the push.')

        # Get the stacked_on branch, if any
        if stacked_on is not None:
            stacked_on = urlutils.normalize_url(stacked_on)
        elif stacked:
            parent_url = br_from.get_parent()
            if parent_url:
                parent = Branch.open(parent_url)
                stacked_on = parent.get_public_branch()
                if not stacked_on:
                    # I considered excluding non-http url's here, thus forcing
                    # 'public' branches only, but that only works for some
                    # users, so it's best to just depend on the user spotting an
                    # error by the feedback given to them. RBC 20080227.
                    stacked_on = parent_url
            if not stacked_on:
                raise errors.BzrCommandError(
                    "Could not determine branch to refer to.")

        # Get the destination location
        if location is None:
            stored_loc = br_from.get_push_location()
            if stored_loc is None:
                raise errors.BzrCommandError(
                    "No push location known or specified.")
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved push location: %s\n" % display_url)
                location = stored_loc

        _show_push_branch(br_from, revision_id, location, self.outf,
            verbose=verbose, overwrite=overwrite, remember=remember,
            stacked_on=stacked_on, create_prefix=create_prefix,
            use_existing_dir=use_existing_dir)


class cmd_branch(Command):
    """Create a new branch that is a copy of an existing branch.

    If the TO_LOCATION is omitted, the last component of the FROM_LOCATION will
    be used.  In other words, "branch ../foo/bar" will attempt to create ./bar.
    If the FROM_LOCATION has no / or path separator embedded, the TO_LOCATION
    is derived from the FROM_LOCATION by stripping a leading scheme or drive
    identifier, if any. For example, "branch lp:foo-bar" will attempt to
    create ./foo-bar.

    To retrieve the branch as of a particular revision, supply the --revision
    parameter, as in "branch foo/bar -r 5".
    """

    _see_also = ['checkout']
    takes_args = ['from_location', 'to_location?']
    takes_options = ['revision', Option('hardlink',
        help='Hard-link working tree files where possible.'),
        Option('no-tree',
            help="Create a branch without a working-tree."),
        Option('switch',
            help="Switch the checkout in the current directory "
                 "to the new branch."),
        Option('stacked',
            help='Create a stacked branch referring to the source branch. '
                'The new branch will depend on the availability of the source '
                'branch for all operations.'),
        Option('standalone',
               help='Do not use a shared repository, even if available.'),
        Option('use-existing-dir',
               help='By default branch will fail if the target'
                    ' directory exists, but does not already'
                    ' have a control directory.  This flag will'
                    ' allow branch to proceed.'),
        ]
    aliases = ['get', 'clone']

    def run(self, from_location, to_location=None, revision=None,
            hardlink=False, stacked=False, standalone=False, no_tree=False,
            use_existing_dir=False, switch=False):
        from bzrlib import switch as _mod_switch
        from bzrlib.tag import _merge_tags_if_possible
        accelerator_tree, br_from = bzrdir.BzrDir.open_tree_or_branch(
            from_location)
        if (accelerator_tree is not None and
            accelerator_tree.supports_content_filtering()):
            accelerator_tree = None
        revision = _get_one_revision('branch', revision)
        br_from.lock_read()
        try:
            if revision is not None:
                revision_id = revision.as_revision_id(br_from)
            else:
                # FIXME - wt.last_revision, fallback to branch, fall back to
                # None or perhaps NULL_REVISION to mean copy nothing
                # RBC 20060209
                revision_id = br_from.last_revision()
            if to_location is None:
                to_location = urlutils.derive_to_location(from_location)
            to_transport = transport.get_transport(to_location)
            try:
                to_transport.mkdir('.')
            except errors.FileExists:
                if not use_existing_dir:
                    raise errors.BzrCommandError('Target directory "%s" '
                        'already exists.' % to_location)
                else:
                    try:
                        bzrdir.BzrDir.open_from_transport(to_transport)
                    except errors.NotBranchError:
                        pass
                    else:
                        raise errors.AlreadyBranchError(to_location)
            except errors.NoSuchFile:
                raise errors.BzrCommandError('Parent of "%s" does not exist.'
                                             % to_location)
            try:
                # preserve whatever source format we have.
                dir = br_from.bzrdir.sprout(to_transport.base, revision_id,
                                            possible_transports=[to_transport],
                                            accelerator_tree=accelerator_tree,
                                            hardlink=hardlink, stacked=stacked,
                                            force_new_repo=standalone,
                                            create_tree_if_local=not no_tree,
                                            source_branch=br_from)
                branch = dir.open_branch()
            except errors.NoSuchRevision:
                to_transport.delete_tree('.')
                msg = "The branch %s has no revision %s." % (from_location,
                    revision)
                raise errors.BzrCommandError(msg)
            _merge_tags_if_possible(br_from, branch)
            # If the source branch is stacked, the new branch may
            # be stacked whether we asked for that explicitly or not.
            # We therefore need a try/except here and not just 'if stacked:'
            try:
                note('Created new stacked branch referring to %s.' %
                    branch.get_stacked_on_url())
            except (errors.NotStacked, errors.UnstackableBranchFormat,
                errors.UnstackableRepositoryFormat), e:
                note('Branched %d revision(s).' % branch.revno())
            if switch:
                # Switch to the new branch
                wt, _ = WorkingTree.open_containing('.')
                _mod_switch.switch(wt.bzrdir, branch)
                note('Switched to branch: %s',
                    urlutils.unescape_for_display(branch.base, 'utf-8'))
        finally:
            br_from.unlock()


class cmd_checkout(Command):
    """Create a new checkout of an existing branch.

    If BRANCH_LOCATION is omitted, checkout will reconstitute a working tree for
    the branch found in '.'. This is useful if you have removed the working tree
    or if it was never created - i.e. if you pushed the branch to its current
    location using SFTP.

    If the TO_LOCATION is omitted, the last component of the BRANCH_LOCATION will
    be used.  In other words, "checkout ../foo/bar" will attempt to create ./bar.
    If the BRANCH_LOCATION has no / or path separator embedded, the TO_LOCATION
    is derived from the BRANCH_LOCATION by stripping a leading scheme or drive
    identifier, if any. For example, "checkout lp:foo-bar" will attempt to
    create ./foo-bar.

    To retrieve the branch as of a particular revision, supply the --revision
    parameter, as in "checkout foo/bar -r 5". Note that this will be immediately
    out of date [so you cannot commit] but it may be useful (i.e. to examine old
    code.)
    """

    _see_also = ['checkouts', 'branch']
    takes_args = ['branch_location?', 'to_location?']
    takes_options = ['revision',
                     Option('lightweight',
                            help="Perform a lightweight checkout.  Lightweight "
                                 "checkouts depend on access to the branch for "
                                 "every operation.  Normal checkouts can perform "
                                 "common operations like diff and status without "
                                 "such access, and also support local commits."
                            ),
                     Option('files-from', type=str,
                            help="Get file contents from this tree."),
                     Option('hardlink',
                            help='Hard-link working tree files where possible.'
                            ),
                     ]
    aliases = ['co']

    def run(self, branch_location=None, to_location=None, revision=None,
            lightweight=False, files_from=None, hardlink=False):
        if branch_location is None:
            branch_location = osutils.getcwd()
            to_location = branch_location
        accelerator_tree, source = bzrdir.BzrDir.open_tree_or_branch(
            branch_location)
        revision = _get_one_revision('checkout', revision)
        if files_from is not None:
            accelerator_tree = WorkingTree.open(files_from)
        if revision is not None:
            revision_id = revision.as_revision_id(source)
        else:
            revision_id = None
        if to_location is None:
            to_location = urlutils.derive_to_location(branch_location)
        # if the source and to_location are the same,
        # and there is no working tree,
        # then reconstitute a branch
        if (osutils.abspath(to_location) ==
            osutils.abspath(branch_location)):
            try:
                source.bzrdir.open_workingtree()
            except errors.NoWorkingTree:
                source.bzrdir.create_workingtree(revision_id)
                return
        source.create_checkout(to_location, revision_id, lightweight,
                               accelerator_tree, hardlink)


class cmd_renames(Command):
    """Show list of renamed files.
    """
    # TODO: Option to show renames between two historical versions.

    # TODO: Only show renames under dir, rather than in the whole branch.
    _see_also = ['status']
    takes_args = ['dir?']

    @display_command
    def run(self, dir=u'.'):
        tree = WorkingTree.open_containing(dir)[0]
        tree.lock_read()
        try:
            new_inv = tree.inventory
            old_tree = tree.basis_tree()
            old_tree.lock_read()
            try:
                old_inv = old_tree.inventory
                renames = []
                iterator = tree.iter_changes(old_tree, include_unchanged=True)
                for f, paths, c, v, p, n, k, e in iterator:
                    if paths[0] == paths[1]:
                        continue
                    if None in (paths):
                        continue
                    renames.append(paths)
                renames.sort()
                for old_name, new_name in renames:
                    self.outf.write("%s => %s\n" % (old_name, new_name))
            finally:
                old_tree.unlock()
        finally:
            tree.unlock()


class cmd_update(Command):
    """Update a tree to have the latest code committed to its branch.

    This will perform a merge into the working tree, and may generate
    conflicts. If you have any local changes, you will still
    need to commit them after the update for the update to be complete.

    If you want to discard your local changes, you can just do a
    'bzr revert' instead of 'bzr commit' after the update.
    """

    _see_also = ['pull', 'working-trees', 'status-flags']
    takes_args = ['dir?']
    aliases = ['up']

    def run(self, dir='.'):
        tree = WorkingTree.open_containing(dir)[0]
        possible_transports = []
        master = tree.branch.get_master_branch(
            possible_transports=possible_transports)
        if master is not None:
            tree.lock_write()
        else:
            tree.lock_tree_write()
        try:
            existing_pending_merges = tree.get_parent_ids()[1:]
            last_rev = _mod_revision.ensure_null(tree.last_revision())
            if last_rev == _mod_revision.ensure_null(
                tree.branch.last_revision()):
                # may be up to date, check master too.
                if master is None or last_rev == _mod_revision.ensure_null(
                    master.last_revision()):
                    revno = tree.branch.revision_id_to_revno(last_rev)
                    note("Tree is up to date at revision %d." % (revno,))
                    return 0
            view_info = _get_view_info_for_change_reporter(tree)
            conflicts = tree.update(
                delta._ChangeReporter(unversioned_filter=tree.is_ignored,
                view_info=view_info), possible_transports=possible_transports)
            revno = tree.branch.revision_id_to_revno(
                _mod_revision.ensure_null(tree.last_revision()))
            note('Updated to revision %d.' % (revno,))
            if tree.get_parent_ids()[1:] != existing_pending_merges:
                note('Your local commits will now show as pending merges with '
                     "'bzr status', and can be committed with 'bzr commit'.")
            if conflicts != 0:
                return 1
            else:
                return 0
        finally:
            tree.unlock()


class cmd_info(Command):
    """Show information about a working tree, branch or repository.

    This command will show all known locations and formats associated to the
    tree, branch or repository.

    In verbose mode, statistical information is included with each report.
    To see extended statistic information, use a verbosity level of 2 or
    higher by specifying the verbose option multiple times, e.g. -vv.

    Branches and working trees will also report any missing revisions.

    :Examples:

      Display information on the format and related locations:

        bzr info

      Display the above together with extended format information and
      basic statistics (like the number of files in the working tree and
      number of revisions in the branch and repository):

        bzr info -v

      Display the above together with number of committers to the branch:

        bzr info -vv
    """
    _see_also = ['revno', 'working-trees', 'repositories']
    takes_args = ['location?']
    takes_options = ['verbose']
    encoding_type = 'replace'

    @display_command
    def run(self, location=None, verbose=False):
        if verbose:
            noise_level = get_verbosity_level()
        else:
            noise_level = 0
        from bzrlib.info import show_bzrdir_info
        show_bzrdir_info(bzrdir.BzrDir.open_containing(location)[0],
                         verbose=noise_level, outfile=self.outf)


class cmd_remove(Command):
    """Remove files or directories.

    This makes bzr stop tracking changes to the specified files. bzr will delete
    them if they can easily be recovered using revert. If no options or
    parameters are given bzr will scan for files that are being tracked by bzr
    but missing in your tree and stop tracking them for you.
    """
    takes_args = ['file*']
    takes_options = ['verbose',
        Option('new', help='Only remove files that have never been committed.'),
        RegistryOption.from_kwargs('file-deletion-strategy',
            'The file deletion mode to be used.',
            title='Deletion Strategy', value_switches=True, enum_switch=False,
            safe='Only delete files if they can be'
                 ' safely recovered (default).',
            keep='Delete from bzr but leave the working copy.',
            force='Delete all the specified files, even if they can not be '
                'recovered and even if they are non-empty directories.')]
    aliases = ['rm', 'del']
    encoding_type = 'replace'

    def run(self, file_list, verbose=False, new=False,
        file_deletion_strategy='safe'):
        tree, file_list = tree_files(file_list)

        if file_list is not None:
            file_list = [f for f in file_list]

        tree.lock_write()
        try:
            # Heuristics should probably all move into tree.remove_smart or
            # some such?
            if new:
                added = tree.changes_from(tree.basis_tree(),
                    specific_files=file_list).added
                file_list = sorted([f[0] for f in added], reverse=True)
                if len(file_list) == 0:
                    raise errors.BzrCommandError('No matching files.')
            elif file_list is None:
                # missing files show up in iter_changes(basis) as
                # versioned-with-no-kind.
                missing = []
                for change in tree.iter_changes(tree.basis_tree()):
                    # Find paths in the working tree that have no kind:
                    if change[1][1] is not None and change[6][1] is None:
                        missing.append(change[1][1])
                file_list = sorted(missing, reverse=True)
                file_deletion_strategy = 'keep'
            tree.remove(file_list, verbose=verbose, to_file=self.outf,
                keep_files=file_deletion_strategy=='keep',
                force=file_deletion_strategy=='force')
        finally:
            tree.unlock()


class cmd_file_id(Command):
    """Print file_id of a particular file or directory.

    The file_id is assigned when the file is first added and remains the
    same through all revisions where the file exists, even when it is
    moved or renamed.
    """

    hidden = True
    _see_also = ['inventory', 'ls']
    takes_args = ['filename']

    @display_command
    def run(self, filename):
        tree, relpath = WorkingTree.open_containing(filename)
        i = tree.path2id(relpath)
        if i is None:
            raise errors.NotVersionedError(filename)
        else:
            self.outf.write(i + '\n')


class cmd_file_path(Command):
    """Print path of file_ids to a file or directory.

    This prints one line for each directory down to the target,
    starting at the branch root.
    """

    hidden = True
    takes_args = ['filename']

    @display_command
    def run(self, filename):
        tree, relpath = WorkingTree.open_containing(filename)
        fid = tree.path2id(relpath)
        if fid is None:
            raise errors.NotVersionedError(filename)
        segments = osutils.splitpath(relpath)
        for pos in range(1, len(segments) + 1):
            path = osutils.joinpath(segments[:pos])
            self.outf.write("%s\n" % tree.path2id(path))


class cmd_reconcile(Command):
    """Reconcile bzr metadata in a branch.

    This can correct data mismatches that may have been caused by
    previous ghost operations or bzr upgrades. You should only
    need to run this command if 'bzr check' or a bzr developer
    advises you to run it.

    If a second branch is provided, cross-branch reconciliation is
    also attempted, which will check that data like the tree root
    id which was not present in very early bzr versions is represented
    correctly in both branches.

    At the same time it is run it may recompress data resulting in
    a potential saving in disk space or performance gain.

    The branch *MUST* be on a listable system such as local disk or sftp.
    """

    _see_also = ['check']
    takes_args = ['branch?']

    def run(self, branch="."):
        from bzrlib.reconcile import reconcile
        dir = bzrdir.BzrDir.open(branch)
        reconcile(dir)


class cmd_revision_history(Command):
    """Display the list of revision ids on a branch."""

    _see_also = ['log']
    takes_args = ['location?']

    hidden = True

    @display_command
    def run(self, location="."):
        branch = Branch.open_containing(location)[0]
        for revid in branch.revision_history():
            self.outf.write(revid)
            self.outf.write('\n')


class cmd_ancestry(Command):
    """List all revisions merged into this branch."""

    _see_also = ['log', 'revision-history']
    takes_args = ['location?']

    hidden = True

    @display_command
    def run(self, location="."):
        try:
            wt = WorkingTree.open_containing(location)[0]
        except errors.NoWorkingTree:
            b = Branch.open(location)
            last_revision = b.last_revision()
        else:
            b = wt.branch
            last_revision = wt.last_revision()

        revision_ids = b.repository.get_ancestry(last_revision)
        revision_ids.pop(0)
        for revision_id in revision_ids:
            self.outf.write(revision_id + '\n')


class cmd_init(Command):
    """Make a directory into a versioned branch.

    Use this to create an empty branch, or before importing an
    existing project.

    If there is a repository in a parent directory of the location, then
    the history of the branch will be stored in the repository.  Otherwise
    init creates a standalone branch which carries its own history
    in the .bzr directory.

    If there is already a branch at the location but it has no working tree,
    the tree can be populated with 'bzr checkout'.

    Recipe for importing a tree of files::

        cd ~/project
        bzr init
        bzr add .
        bzr status
        bzr commit -m "imported project"
    """

    _see_also = ['init-repository', 'branch', 'checkout']
    takes_args = ['location?']
    takes_options = [
        Option('create-prefix',
               help='Create the path leading up to the branch '
                    'if it does not already exist.'),
         RegistryOption('format',
                help='Specify a format for this branch. '
                'See "help formats".',
                lazy_registry=('bzrlib.bzrdir', 'format_registry'),
                converter=lambda name: bzrdir.format_registry.make_bzrdir(name),
                value_switches=True,
                title="Branch format",
                ),
         Option('append-revisions-only',
                help='Never change revnos or the existing log.'
                '  Append revisions to it only.')
         ]
    def run(self, location=None, format=None, append_revisions_only=False,
            create_prefix=False):
        if format is None:
            format = bzrdir.format_registry.make_bzrdir('default')
        if location is None:
            location = u'.'

        to_transport = transport.get_transport(location)

        # The path has to exist to initialize a
        # branch inside of it.
        # Just using os.mkdir, since I don't
        # believe that we want to create a bunch of
        # locations if the user supplies an extended path
        try:
            to_transport.ensure_base()
        except errors.NoSuchFile:
            if not create_prefix:
                raise errors.BzrCommandError("Parent directory of %s"
                    " does not exist."
                    "\nYou may supply --create-prefix to create all"
                    " leading parent directories."
                    % location)
            to_transport.create_prefix()

        try:
            a_bzrdir = bzrdir.BzrDir.open_from_transport(to_transport)
        except errors.NotBranchError:
            # really a NotBzrDir error...
            create_branch = bzrdir.BzrDir.create_branch_convenience
            branch = create_branch(to_transport.base, format=format,
                                   possible_transports=[to_transport])
            a_bzrdir = branch.bzrdir
        else:
            from bzrlib.transport.local import LocalTransport
            if a_bzrdir.has_branch():
                if (isinstance(to_transport, LocalTransport)
                    and not a_bzrdir.has_workingtree()):
                        raise errors.BranchExistsWithoutWorkingTree(location)
                raise errors.AlreadyBranchError(location)
            branch = a_bzrdir.create_branch()
            a_bzrdir.create_workingtree()
        if append_revisions_only:
            try:
                branch.set_append_revisions_only(True)
            except errors.UpgradeRequired:
                raise errors.BzrCommandError('This branch format cannot be set'
                    ' to append-revisions-only.  Try --default.')
        if not is_quiet():
            from bzrlib.info import describe_layout, describe_format
            try:
                tree = a_bzrdir.open_workingtree(recommend_upgrade=False)
            except (errors.NoWorkingTree, errors.NotLocalUrl):
                tree = None
            repository = branch.repository
            layout = describe_layout(repository, branch, tree).lower()
            format = describe_format(a_bzrdir, repository, branch, tree)
            self.outf.write("Created a %s (format: %s)\n" % (layout, format))
            if repository.is_shared():
                #XXX: maybe this can be refactored into transport.path_or_url()
                url = repository.bzrdir.root_transport.external_url()
                try:
                    url = urlutils.local_path_from_url(url)
                except errors.InvalidURL:
                    pass
                self.outf.write("Using shared repository: %s\n" % url)


class cmd_init_repository(Command):
    """Create a shared repository to hold branches.

    New branches created under the repository directory will store their
    revisions in the repository, not in the branch directory.

    If the --no-trees option is used then the branches in the repository
    will not have working trees by default.

    :Examples:
        Create a shared repositories holding just branches::

            bzr init-repo --no-trees repo
            bzr init repo/trunk

        Make a lightweight checkout elsewhere::

            bzr checkout --lightweight repo/trunk trunk-checkout
            cd trunk-checkout
            (add files here)
    """

    _see_also = ['init', 'branch', 'checkout', 'repositories']
    takes_args = ["location"]
    takes_options = [RegistryOption('format',
                            help='Specify a format for this repository. See'
                                 ' "bzr help formats" for details.',
                            lazy_registry=('bzrlib.bzrdir', 'format_registry'),
                            converter=lambda name: bzrdir.format_registry.make_bzrdir(name),
                            value_switches=True, title='Repository format'),
                     Option('no-trees',
                             help='Branches in the repository will default to'
                                  ' not having a working tree.'),
                    ]
    aliases = ["init-repo"]

    def run(self, location, format=None, no_trees=False):
        if format is None:
            format = bzrdir.format_registry.make_bzrdir('default')

        if location is None:
            location = '.'

        to_transport = transport.get_transport(location)
        to_transport.ensure_base()

        newdir = format.initialize_on_transport(to_transport)
        repo = newdir.create_repository(shared=True)
        repo.set_make_working_trees(not no_trees)
        if not is_quiet():
            from bzrlib.info import show_bzrdir_info
            show_bzrdir_info(repo.bzrdir, verbose=0, outfile=self.outf)


class cmd_diff(Command):
    """Show differences in the working tree, between revisions or branches.

    If no arguments are given, all changes for the current tree are listed.
    If files are given, only the changes in those files are listed.
    Remote and multiple branches can be compared by using the --old and
    --new options. If not provided, the default for both is derived from
    the first argument, if any, or the current tree if no arguments are
    given.

    "bzr diff -p1" is equivalent to "bzr diff --prefix old/:new/", and
    produces patches suitable for "patch -p1".

    :Exit values:
        1 - changed
        2 - unrepresentable changes
        3 - error
        0 - no change

    :Examples:
        Shows the difference in the working tree versus the last commit::

            bzr diff

        Difference between the working tree and revision 1::

            bzr diff -r1

        Difference between revision 2 and revision 1::

            bzr diff -r1..2

        Difference between revision 2 and revision 1 for branch xxx::

            bzr diff -r1..2 xxx

        Show just the differences for file NEWS::

            bzr diff NEWS

        Show the differences in working tree xxx for file NEWS::

            bzr diff xxx/NEWS

        Show the differences from branch xxx to this working tree:

            bzr diff --old xxx

        Show the differences between two branches for file NEWS::

            bzr diff --old xxx --new yyy NEWS

        Same as 'bzr diff' but prefix paths with old/ and new/::

            bzr diff --prefix old/:new/
    """
    _see_also = ['status']
    takes_args = ['file*']
    takes_options = [
        Option('diff-options', type=str,
               help='Pass these options to the external diff program.'),
        Option('prefix', type=str,
               short_name='p',
               help='Set prefixes added to old and new filenames, as '
                    'two values separated by a colon. (eg "old/:new/").'),
        Option('old',
            help='Branch/tree to compare from.',
            type=unicode,
            ),
        Option('new',
            help='Branch/tree to compare to.',
            type=unicode,
            ),
        'revision',
        'change',
        Option('using',
            help='Use this command to compare files.',
            type=unicode,
            ),
        ]
    aliases = ['di', 'dif']
    encoding_type = 'exact'

    @display_command
    def run(self, revision=None, file_list=None, diff_options=None,
            prefix=None, old=None, new=None, using=None):
        from bzrlib.diff import _get_trees_to_diff, show_diff_trees

        if (prefix is None) or (prefix == '0'):
            # diff -p0 format
            old_label = ''
            new_label = ''
        elif prefix == '1':
            old_label = 'old/'
            new_label = 'new/'
        elif ':' in prefix:
            old_label, new_label = prefix.split(":")
        else:
            raise errors.BzrCommandError(
                '--prefix expects two values separated by a colon'
                ' (eg "old/:new/")')

        if revision and len(revision) > 2:
            raise errors.BzrCommandError('bzr diff --revision takes exactly'
                                         ' one or two revision specifiers')

        old_tree, new_tree, specific_files, extra_trees = \
                _get_trees_to_diff(file_list, revision, old, new,
                apply_view=True)
        return show_diff_trees(old_tree, new_tree, sys.stdout,
                               specific_files=specific_files,
                               external_diff_options=diff_options,
                               old_label=old_label, new_label=new_label,
                               extra_trees=extra_trees, using=using)


class cmd_deleted(Command):
    """List files deleted in the working tree.
    """
    # TODO: Show files deleted since a previous revision, or
    # between two revisions.
    # TODO: Much more efficient way to do this: read in new
    # directories with readdir, rather than stating each one.  Same
    # level of effort but possibly much less IO.  (Or possibly not,
    # if the directories are very large...)
    _see_also = ['status', 'ls']
    takes_options = ['show-ids']

    @display_command
    def run(self, show_ids=False):
        tree = WorkingTree.open_containing(u'.')[0]
        tree.lock_read()
        try:
            old = tree.basis_tree()
            old.lock_read()
            try:
                for path, ie in old.inventory.iter_entries():
                    if not tree.has_id(ie.file_id):
                        self.outf.write(path)
                        if show_ids:
                            self.outf.write(' ')
                            self.outf.write(ie.file_id)
                        self.outf.write('\n')
            finally:
                old.unlock()
        finally:
            tree.unlock()


class cmd_modified(Command):
    """List files modified in working tree.
    """

    hidden = True
    _see_also = ['status', 'ls']
    takes_options = [
            Option('null',
                   help='Write an ascii NUL (\\0) separator '
                   'between files rather than a newline.')
            ]

    @display_command
    def run(self, null=False):
        tree = WorkingTree.open_containing(u'.')[0]
        td = tree.changes_from(tree.basis_tree())
        for path, id, kind, text_modified, meta_modified in td.modified:
            if null:
                self.outf.write(path + '\0')
            else:
                self.outf.write(osutils.quotefn(path) + '\n')


class cmd_added(Command):
    """List files added in working tree.
    """

    hidden = True
    _see_also = ['status', 'ls']
    takes_options = [
            Option('null',
                   help='Write an ascii NUL (\\0) separator '
                   'between files rather than a newline.')
            ]

    @display_command
    def run(self, null=False):
        wt = WorkingTree.open_containing(u'.')[0]
        wt.lock_read()
        try:
            basis = wt.basis_tree()
            basis.lock_read()
            try:
                basis_inv = basis.inventory
                inv = wt.inventory
                for file_id in inv:
                    if file_id in basis_inv:
                        continue
                    if inv.is_root(file_id) and len(basis_inv) == 0:
                        continue
                    path = inv.id2path(file_id)
                    if not os.access(osutils.abspath(path), os.F_OK):
                        continue
                    if null:
                        self.outf.write(path + '\0')
                    else:
                        self.outf.write(osutils.quotefn(path) + '\n')
            finally:
                basis.unlock()
        finally:
            wt.unlock()


class cmd_root(Command):
    """Show the tree root directory.

    The root is the nearest enclosing directory with a .bzr control
    directory."""

    takes_args = ['filename?']
    @display_command
    def run(self, filename=None):
        """Print the branch root."""
        tree = WorkingTree.open_containing(filename)[0]
        self.outf.write(tree.basedir + '\n')


def _parse_limit(limitstring):
    try:
        return int(limitstring)
    except ValueError:
        msg = "The limit argument must be an integer."
        raise errors.BzrCommandError(msg)


def _parse_levels(s):
    try:
        return int(s)
    except ValueError:
        msg = "The levels argument must be an integer."
        raise errors.BzrCommandError(msg)


class cmd_log(Command):
    """Show historical log for a branch or subset of a branch.

    log is bzr's default tool for exploring the history of a branch.
    The branch to use is taken from the first parameter. If no parameters
    are given, the branch containing the working directory is logged.
    Here are some simple examples::

      bzr log                       log the current branch
      bzr log foo.py                log a file in its branch
      bzr log http://server/branch  log a branch on a server

    The filtering, ordering and information shown for each revision can
    be controlled as explained below. By default, all revisions are
    shown sorted (topologically) so that newer revisions appear before
    older ones and descendants always appear before ancestors. If displayed,
    merged revisions are shown indented under the revision in which they
    were merged.

    :Output control:

      The log format controls how information about each revision is
      displayed. The standard log formats are called ``long``, ``short``
      and ``line``. The default is long. See ``bzr help log-formats``
      for more details on log formats.

      The following options can be used to control what information is
      displayed::

        -l N        display a maximum of N revisions
        -n N        display N levels of revisions (0 for all, 1 for collapsed)
        -v          display a status summary (delta) for each revision
        -p          display a diff (patch) for each revision
        --show-ids  display revision-ids (and file-ids), not just revnos

      Note that the default number of levels to display is a function of the
      log format. If the -n option is not used, the standard log formats show
      just the top level (mainline).

      Status summaries are shown using status flags like A, M, etc. To see
      the changes explained using words like ``added`` and ``modified``
      instead, use the -vv option.

    :Ordering control:

      To display revisions from oldest to newest, use the --forward option.
      In most cases, using this option will have little impact on the total
      time taken to produce a log, though --forward does not incrementally
      display revisions like --reverse does when it can.

    :Revision filtering:

      The -r option can be used to specify what revision or range of revisions
      to filter against. The various forms are shown below::

        -rX      display revision X
        -rX..    display revision X and later
        -r..Y    display up to and including revision Y
        -rX..Y   display from X to Y inclusive

      See ``bzr help revisionspec`` for details on how to specify X and Y.
      Some common examples are given below::

        -r-1                show just the tip
        -r-10..             show the last 10 mainline revisions
        -rsubmit:..         show what's new on this branch
        -rancestor:path..   show changes since the common ancestor of this
                            branch and the one at location path
        -rdate:yesterday..  show changes since yesterday

      When logging a range of revisions using -rX..Y, log starts at
      revision Y and searches back in history through the primary
      ("left-hand") parents until it finds X. When logging just the
      top level (using -n1), an error is reported if X is not found
      along the way. If multi-level logging is used (-n0), X may be
      a nested merge revision and the log will be truncated accordingly.

    :Path filtering:

      If parameters are given and the first one is not a branch, the log
      will be filtered to show only those revisions that changed the
      nominated files or directories.

      Filenames are interpreted within their historical context. To log a
      deleted file, specify a revision range so that the file existed at
      the end or start of the range.

      Historical context is also important when interpreting pathnames of
      renamed files/directories. Consider the following example:

      * revision 1: add tutorial.txt
      * revision 2: modify tutorial.txt
      * revision 3: rename tutorial.txt to guide.txt; add tutorial.txt

      In this case:

      * ``bzr log guide.txt`` will log the file added in revision 1

      * ``bzr log tutorial.txt`` will log the new file added in revision 3

      * ``bzr log -r2 -p tutorial.txt`` will show the changes made to
        the original file in revision 2.

      * ``bzr log -r2 -p guide.txt`` will display an error message as there
        was no file called guide.txt in revision 2.

      Renames are always followed by log. By design, there is no need to
      explicitly ask for this (and no way to stop logging a file back
      until it was last renamed).

    :Other filtering:

      The --message option can be used for finding revisions that match a
      regular expression in a commit message.

    :Tips & tricks:

      GUI tools and IDEs are often better at exploring history than command
      line tools. You may prefer qlog or glog from the QBzr and Bzr-Gtk packages
      respectively for example. (TortoiseBzr uses qlog for displaying logs.) See
      http://bazaar-vcs.org/BzrPlugins and http://bazaar-vcs.org/IDEIntegration.

      Web interfaces are often better at exploring history than command line
      tools, particularly for branches on servers. You may prefer Loggerhead
      or one of its alternatives. See http://bazaar-vcs.org/WebInterface.

      You may find it useful to add the aliases below to ``bazaar.conf``::

        [ALIASES]
        tip = log -r-1
        top = log -l10 --line
        show = log -v -p

      ``bzr tip`` will then show the latest revision while ``bzr top``
      will show the last 10 mainline revisions. To see the details of a
      particular revision X,  ``bzr show -rX``.

      If you are interested in looking deeper into a particular merge X,
      use ``bzr log -n0 -rX``.

      ``bzr log -v`` on a branch with lots of history is currently
      very slow. A fix for this issue is currently under development.
      With or without that fix, it is recommended that a revision range
      be given when using the -v option.

      bzr has a generic full-text matching plugin, bzr-search, that can be
      used to find revisions matching user names, commit messages, etc.
      Among other features, this plugin can find all revisions containing
      a list of words but not others.

      When exploring non-mainline history on large projects with deep
      history, the performance of log can be greatly improved by installing
      the historycache plugin. This plugin buffers historical information
      trading disk space for faster speed.
    """
    takes_args = ['file*']
    _see_also = ['log-formats', 'revisionspec']
    takes_options = [
            Option('forward',
                   help='Show from oldest to newest.'),
            'timezone',
            custom_help('verbose',
                   help='Show files changed in each revision.'),
            'show-ids',
            'revision',
            Option('change',
                   type=bzrlib.option._parse_revision_str,
                   short_name='c',
                   help='Show just the specified revision.'
                   ' See also "help revisionspec".'),
            'log-format',
            Option('levels',
                   short_name='n',
                   help='Number of levels to display - 0 for all, 1 for flat.',
                   argname='N',
                   type=_parse_levels),
            Option('message',
                   short_name='m',
                   help='Show revisions whose message matches this '
                        'regular expression.',
                   type=str),
            Option('limit',
                   short_name='l',
                   help='Limit the output to the first N revisions.',
                   argname='N',
                   type=_parse_limit),
            Option('show-diff',
                   short_name='p',
                   help='Show changes made in each revision as a patch.'),
            Option('include-merges',
                   help='Show merged revisions like --levels 0 does.'),
            ]
    encoding_type = 'replace'

    @display_command
    def run(self, file_list=None, timezone='original',
            verbose=False,
            show_ids=False,
            forward=False,
            revision=None,
            change=None,
            log_format=None,
            levels=None,
            message=None,
            limit=None,
            show_diff=False,
            include_merges=False):
        from bzrlib.log import (
            Logger,
            make_log_request_dict,
            _get_info_for_log_files,
            )
        direction = (forward and 'forward') or 'reverse'
        if include_merges:
            if levels is None:
                levels = 0
            else:
                raise errors.BzrCommandError(
                    '--levels and --include-merges are mutually exclusive')

        if change is not None:
            if len(change) > 1:
                raise errors.RangeInChangeOption()
            if revision is not None:
                raise errors.BzrCommandError(
                    '--revision and --change are mutually exclusive')
            else:
                revision = change

        file_ids = []
        filter_by_dir = False
        b = None
        try:
            if file_list:
                # find the file ids to log and check for directory filtering
                b, file_info_list, rev1, rev2 = _get_info_for_log_files(
                    revision, file_list)
                for relpath, file_id, kind in file_info_list:
                    if file_id is None:
                        raise errors.BzrCommandError(
                            "Path unknown at end or start of revision range: %s" %
                            relpath)
                    # If the relpath is the top of the tree, we log everything
                    if relpath == '':
                        file_ids = []
                        break
                    else:
                        file_ids.append(file_id)
                    filter_by_dir = filter_by_dir or (
                        kind in ['directory', 'tree-reference'])
            else:
                # log everything
                # FIXME ? log the current subdir only RBC 20060203
                if revision is not None \
                        and len(revision) > 0 and revision[0].get_branch():
                    location = revision[0].get_branch()
                else:
                    location = '.'
                dir, relpath = bzrdir.BzrDir.open_containing(location)
                b = dir.open_branch()
                b.lock_read()
                rev1, rev2 = _get_revision_range(revision, b, self.name())

            # Decide on the type of delta & diff filtering to use
            # TODO: add an --all-files option to make this configurable & consistent
            if not verbose:
                delta_type = None
            else:
                delta_type = 'full'
            if not show_diff:
                diff_type = None
            elif file_ids:
                diff_type = 'partial'
            else:
                diff_type = 'full'

            # Build the log formatter
            if log_format is None:
                log_format = log.log_formatter_registry.get_default(b)
            lf = log_format(show_ids=show_ids, to_file=self.outf,
                            show_timezone=timezone,
                            delta_format=get_verbosity_level(),
                            levels=levels,
                            show_advice=levels is None)

            # Choose the algorithm for doing the logging. It's annoying
            # having multiple code paths like this but necessary until
            # the underlying repository format is faster at generating
            # deltas or can provide everything we need from the indices.
            # The default algorithm - match-using-deltas - works for
            # multiple files and directories and is faster for small
            # amounts of history (200 revisions say). However, it's too
            # slow for logging a single file in a repository with deep
            # history, i.e. > 10K revisions. In the spirit of "do no
            # evil when adding features", we continue to use the
            # original algorithm - per-file-graph - for the "single
            # file that isn't a directory without showing a delta" case.
            partial_history = revision and b.repository._format.supports_chks
            match_using_deltas = (len(file_ids) != 1 or filter_by_dir
                or delta_type or partial_history)

            # Build the LogRequest and execute it
            if len(file_ids) == 0:
                file_ids = None
            rqst = make_log_request_dict(
                direction=direction, specific_fileids=file_ids,
                start_revision=rev1, end_revision=rev2, limit=limit,
                message_search=message, delta_type=delta_type,
                diff_type=diff_type, _match_using_deltas=match_using_deltas)
            Logger(b, rqst).show(lf)
        finally:
            if b is not None:
                b.unlock()


def _get_revision_range(revisionspec_list, branch, command_name):
    """Take the input of a revision option and turn it into a revision range.

    It returns RevisionInfo objects which can be used to obtain the rev_id's
    of the desired revisions. It does some user input validations.
    """
    if revisionspec_list is None:
        rev1 = None
        rev2 = None
    elif len(revisionspec_list) == 1:
        rev1 = rev2 = revisionspec_list[0].in_history(branch)
    elif len(revisionspec_list) == 2:
        start_spec = revisionspec_list[0]
        end_spec = revisionspec_list[1]
        if end_spec.get_branch() != start_spec.get_branch():
            # b is taken from revision[0].get_branch(), and
            # show_log will use its revision_history. Having
            # different branches will lead to weird behaviors.
            raise errors.BzrCommandError(
                "bzr %s doesn't accept two revisions in different"
                " branches." % command_name)
        rev1 = start_spec.in_history(branch)
        # Avoid loading all of history when we know a missing
        # end of range means the last revision ...
        if end_spec.spec is None:
            last_revno, last_revision_id = branch.last_revision_info()
            rev2 = RevisionInfo(branch, last_revno, last_revision_id)
        else:
            rev2 = end_spec.in_history(branch)
    else:
        raise errors.BzrCommandError(
            'bzr %s --revision takes one or two values.' % command_name)
    return rev1, rev2


def _revision_range_to_revid_range(revision_range):
    rev_id1 = None
    rev_id2 = None
    if revision_range[0] is not None:
        rev_id1 = revision_range[0].rev_id
    if revision_range[1] is not None:
        rev_id2 = revision_range[1].rev_id
    return rev_id1, rev_id2

def get_log_format(long=False, short=False, line=False, default='long'):
    log_format = default
    if long:
        log_format = 'long'
    if short:
        log_format = 'short'
    if line:
        log_format = 'line'
    return log_format


class cmd_touching_revisions(Command):
    """Return revision-ids which affected a particular file.

    A more user-friendly interface is "bzr log FILE".
    """

    hidden = True
    takes_args = ["filename"]

    @display_command
    def run(self, filename):
        tree, relpath = WorkingTree.open_containing(filename)
        file_id = tree.path2id(relpath)
        b = tree.branch
        b.lock_read()
        try:
            touching_revs = log.find_touching_revisions(b, file_id)
            for revno, revision_id, what in touching_revs:
                self.outf.write("%6d %s\n" % (revno, what))
        finally:
            b.unlock()


class cmd_ls(Command):
    """List files in a tree.
    """

    _see_also = ['status', 'cat']
    takes_args = ['path?']
    takes_options = [
            'verbose',
            'revision',
            Option('recursive', short_name='R',
                   help='Recurse into subdirectories.'),
            Option('from-root',
                   help='Print paths relative to the root of the branch.'),
            Option('unknown', help='Print unknown files.'),
            Option('versioned', help='Print versioned files.',
                   short_name='V'),
            Option('ignored', help='Print ignored files.'),
            Option('null',
                   help='Write an ascii NUL (\\0) separator '
                   'between files rather than a newline.'),
            Option('kind',
                   help='List entries of a particular kind: file, directory, symlink.',
                   type=unicode),
            'show-ids',
            ]
    @display_command
    def run(self, revision=None, verbose=False,
            recursive=False, from_root=False,
            unknown=False, versioned=False, ignored=False,
            null=False, kind=None, show_ids=False, path=None):

        if kind and kind not in ('file', 'directory', 'symlink'):
            raise errors.BzrCommandError('invalid kind specified')

        if verbose and null:
            raise errors.BzrCommandError('Cannot set both --verbose and --null')
        all = not (unknown or versioned or ignored)

        selection = {'I':ignored, '?':unknown, 'V':versioned}

        if path is None:
            fs_path = '.'
        else:
            if from_root:
                raise errors.BzrCommandError('cannot specify both --from-root'
                                             ' and PATH')
            fs_path = path
        tree, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch(
            fs_path)

        # Calculate the prefix to use
        prefix = None
        if from_root:
            if relpath:
                prefix = relpath + '/'
        elif fs_path != '.':
            prefix = fs_path + '/'

        if revision is not None or tree is None:
            tree = _get_one_revision_tree('ls', revision, branch=branch)

        apply_view = False
        if isinstance(tree, WorkingTree) and tree.supports_views():
            view_files = tree.views.lookup_view()
            if view_files:
                apply_view = True
                view_str = views.view_display_str(view_files)
                note("Ignoring files outside view. View is %s" % view_str)

        tree.lock_read()
        try:
            for fp, fc, fkind, fid, entry in tree.list_files(include_root=False,
                from_dir=relpath, recursive=recursive):
                # Apply additional masking
                if not all and not selection[fc]:
                    continue
                if kind is not None and fkind != kind:
                    continue
                if apply_view:
                    try:
                        if relpath:
                            fullpath = osutils.pathjoin(relpath, fp)
                        else:
                            fullpath = fp
                        views.check_path_in_view(tree, fullpath)
                    except errors.FileOutsideView:
                        continue

                # Output the entry
                if prefix:
                    fp = osutils.pathjoin(prefix, fp)
                kindch = entry.kind_character()
                outstring = fp + kindch
                ui.ui_factory.clear_term()
                if verbose:
                    outstring = '%-8s %s' % (fc, outstring)
                    if show_ids and fid is not None:
                        outstring = "%-50s %s" % (outstring, fid)
                    self.outf.write(outstring + '\n')
                elif null:
                    self.outf.write(fp + '\0')
                    if show_ids:
                        if fid is not None:
                            self.outf.write(fid)
                        self.outf.write('\0')
                    self.outf.flush()
                else:
                    if show_ids:
                        if fid is not None:
                            my_id = fid
                        else:
                            my_id = ''
                        self.outf.write('%-50s %s\n' % (outstring, my_id))
                    else:
                        self.outf.write(outstring + '\n')
        finally:
            tree.unlock()


class cmd_unknowns(Command):
    """List unknown files.
    """

    hidden = True
    _see_also = ['ls']

    @display_command
    def run(self):
        for f in WorkingTree.open_containing(u'.')[0].unknowns():
            self.outf.write(osutils.quotefn(f) + '\n')


class cmd_ignore(Command):
    """Ignore specified files or patterns.

    See ``bzr help patterns`` for details on the syntax of patterns.

    To remove patterns from the ignore list, edit the .bzrignore file.
    After adding, editing or deleting that file either indirectly by
    using this command or directly by using an editor, be sure to commit
    it.

    Note: ignore patterns containing shell wildcards must be quoted from
    the shell on Unix.

    :Examples:
        Ignore the top level Makefile::

            bzr ignore ./Makefile

        Ignore class files in all directories::

            bzr ignore "*.class"

        Ignore .o files under the lib directory::

            bzr ignore "lib/**/*.o"

        Ignore .o files under the lib directory::

            bzr ignore "RE:lib/.*\.o"

        Ignore everything but the "debian" toplevel directory::

            bzr ignore "RE:(?!debian/).*"
    """

    _see_also = ['status', 'ignored', 'patterns']
    takes_args = ['name_pattern*']
    takes_options = [
        Option('old-default-rules',
               help='Write out the ignore rules bzr < 0.9 always used.')
        ]

    def run(self, name_pattern_list=None, old_default_rules=None):
        from bzrlib import ignores
        if old_default_rules is not None:
            # dump the rules and exit
            for pattern in ignores.OLD_DEFAULTS:
                print pattern
            return
        if not name_pattern_list:
            raise errors.BzrCommandError("ignore requires at least one "
                                  "NAME_PATTERN or --old-default-rules")
        name_pattern_list = [globbing.normalize_pattern(p)
                             for p in name_pattern_list]
        for name_pattern in name_pattern_list:
            if (name_pattern[0] == '/' or
                (len(name_pattern) > 1 and name_pattern[1] == ':')):
                raise errors.BzrCommandError(
                    "NAME_PATTERN should not be an absolute path")
        tree, relpath = WorkingTree.open_containing(u'.')
        ignores.tree_ignores_add_patterns(tree, name_pattern_list)
        ignored = globbing.Globster(name_pattern_list)
        matches = []
        tree.lock_read()
        for entry in tree.list_files():
            id = entry[3]
            if id is not None:
                filename = entry[0]
                if ignored.match(filename):
                    matches.append(filename.encode('utf-8'))
        tree.unlock()
        if len(matches) > 0:
            print "Warning: the following files are version controlled and" \
                  " match your ignore pattern:\n%s" \
                  "\nThese files will continue to be version controlled" \
                  " unless you 'bzr remove' them." % ("\n".join(matches),)


class cmd_ignored(Command):
    """List ignored files and the patterns that matched them.

    List all the ignored files and the ignore pattern that caused the file to
    be ignored.

    Alternatively, to list just the files::

        bzr ls --ignored
    """

    encoding_type = 'replace'
    _see_also = ['ignore', 'ls']

    @display_command
    def run(self):
        tree = WorkingTree.open_containing(u'.')[0]
        tree.lock_read()
        try:
            for path, file_class, kind, file_id, entry in tree.list_files():
                if file_class != 'I':
                    continue
                ## XXX: Slightly inefficient since this was already calculated
                pat = tree.is_ignored(path)
                self.outf.write('%-50s %s\n' % (path, pat))
        finally:
            tree.unlock()


class cmd_lookup_revision(Command):
    """Lookup the revision-id from a revision-number

    :Examples:
        bzr lookup-revision 33
    """
    hidden = True
    takes_args = ['revno']

    @display_command
    def run(self, revno):
        try:
            revno = int(revno)
        except ValueError:
            raise errors.BzrCommandError("not a valid revision-number: %r" % revno)

        print WorkingTree.open_containing(u'.')[0].branch.get_rev_id(revno)


class cmd_export(Command):
    """Export current or past revision to a destination directory or archive.

    If no revision is specified this exports the last committed revision.

    Format may be an "exporter" name, such as tar, tgz, tbz2.  If none is
    given, try to find the format with the extension. If no extension
    is found exports to a directory (equivalent to --format=dir).

    If root is supplied, it will be used as the root directory inside
    container formats (tar, zip, etc). If it is not supplied it will default
    to the exported filename. The root option has no effect for 'dir' format.

    If branch is omitted then the branch containing the current working
    directory will be used.

    Note: Export of tree with non-ASCII filenames to zip is not supported.

      =================       =========================
      Supported formats       Autodetected by extension
      =================       =========================
         dir                         (none)
         tar                          .tar
         tbz2                    .tar.bz2, .tbz2
         tgz                      .tar.gz, .tgz
         zip                          .zip
      =================       =========================
    """
    takes_args = ['dest', 'branch_or_subdir?']
    takes_options = [
        Option('format',
               help="Type of file to export to.",
               type=unicode),
        'revision',
        Option('filters', help='Apply content filters to export the '
                'convenient form.'),
        Option('root',
               type=str,
               help="Name of the root directory inside the exported file."),
        ]
    def run(self, dest, branch_or_subdir=None, revision=None, format=None,
        root=None, filters=False):
        from bzrlib.export import export

        if branch_or_subdir is None:
            tree = WorkingTree.open_containing(u'.')[0]
            b = tree.branch
            subdir = None
        else:
            b, subdir = Branch.open_containing(branch_or_subdir)
            tree = None

        rev_tree = _get_one_revision_tree('export', revision, branch=b, tree=tree)
        try:
            export(rev_tree, dest, format, root, subdir, filtered=filters)
        except errors.NoSuchExportFormat, e:
            raise errors.BzrCommandError('Unsupported export format: %s' % e.format)


class cmd_cat(Command):
    """Write the contents of a file as of a given revision to standard output.

    If no revision is nominated, the last revision is used.

    Note: Take care to redirect standard output when using this command on a
    binary file.
    """

    _see_also = ['ls']
    takes_options = [
        Option('name-from-revision', help='The path name in the old tree.'),
        Option('filters', help='Apply content filters to display the '
                'convenience form.'),
        'revision',
        ]
    takes_args = ['filename']
    encoding_type = 'exact'

    @display_command
    def run(self, filename, revision=None, name_from_revision=False,
            filters=False):
        if revision is not None and len(revision) != 1:
            raise errors.BzrCommandError("bzr cat --revision takes exactly"
                                         " one revision specifier")
        tree, branch, relpath = \
            bzrdir.BzrDir.open_containing_tree_or_branch(filename)
        branch.lock_read()
        try:
            return self._run(tree, branch, relpath, filename, revision,
                             name_from_revision, filters)
        finally:
            branch.unlock()

    def _run(self, tree, b, relpath, filename, revision, name_from_revision,
        filtered):
        if tree is None:
            tree = b.basis_tree()
        rev_tree = _get_one_revision_tree('cat', revision, branch=b)

        old_file_id = rev_tree.path2id(relpath)

        if name_from_revision:
            # Try in revision if requested
            if old_file_id is None:
                raise errors.BzrCommandError(
                    "%r is not present in revision %s" % (
                        filename, rev_tree.get_revision_id()))
            else:
                content = rev_tree.get_file_text(old_file_id)
        else:
            cur_file_id = tree.path2id(relpath)
            found = False
            if cur_file_id is not None:
                # Then try with the actual file id
                try:
                    content = rev_tree.get_file_text(cur_file_id)
                    found = True
                except errors.NoSuchId:
                    # The actual file id didn't exist at that time
                    pass
            if not found and old_file_id is not None:
                # Finally try with the old file id
                content = rev_tree.get_file_text(old_file_id)
                found = True
            if not found:
                # Can't be found anywhere
                raise errors.BzrCommandError(
                    "%r is not present in revision %s" % (
                        filename, rev_tree.get_revision_id()))
        if filtered:
            from bzrlib.filters import (
                ContentFilterContext,
                filtered_output_bytes,
                )
            filters = rev_tree._content_filter_stack(relpath)
            chunks = content.splitlines(True)
            content = filtered_output_bytes(chunks, filters,
                ContentFilterContext(relpath, rev_tree))
            self.outf.writelines(content)
        else:
            self.outf.write(content)


class cmd_local_time_offset(Command):
    """Show the offset in seconds from GMT to local time."""
    hidden = True
    @display_command
    def run(self):
        print osutils.local_time_offset()



class cmd_commit(Command):
    """Commit changes into a new revision.

    An explanatory message needs to be given for each commit. This is
    often done by using the --message option (getting the message from the
    command line) or by using the --file option (getting the message from
    a file). If neither of these options is given, an editor is opened for
    the user to enter the message. To see the changed files in the
    boilerplate text loaded into the editor, use the --show-diff option.

    By default, the entire tree is committed and the person doing the
    commit is assumed to be the author. These defaults can be overridden
    as explained below.

    :Selective commits:

      If selected files are specified, only changes to those files are
      committed.  If a directory is specified then the directory and
      everything within it is committed.
  
      When excludes are given, they take precedence over selected files.
      For example, to commit only changes within foo, but not changes
      within foo/bar::
  
        bzr commit foo -x foo/bar
  
      A selective commit after a merge is not yet supported.

    :Custom authors:

      If the author of the change is not the same person as the committer,
      you can specify the author's name using the --author option. The
      name should be in the same format as a committer-id, e.g.
      "John Doe <jdoe@example.com>". If there is more than one author of
      the change you can specify the option multiple times, once for each
      author.
  
    :Checks:

      A common mistake is to forget to add a new file or directory before
      running the commit command. The --strict option checks for unknown
      files and aborts the commit if any are found. More advanced pre-commit
      checks can be implemented by defining hooks. See ``bzr help hooks``
      for details.

    :Things to note:

      If you accidentially commit the wrong changes or make a spelling
      mistake in the commit message say, you can use the uncommit command
      to undo it. See ``bzr help uncommit`` for details.

      Hooks can also be configured to run after a commit. This allows you
      to trigger updates to external systems like bug trackers. The --fixes
      option can be used to record the association between a revision and
      one or more bugs. See ``bzr help bugs`` for details.

      A selective commit may fail in some cases where the committed
      tree would be invalid. Consider::
  
        bzr init foo
        mkdir foo/bar
        bzr add foo/bar
        bzr commit foo -m "committing foo"
        bzr mv foo/bar foo/baz
        mkdir foo/bar
        bzr add foo/bar
        bzr commit foo/bar -m "committing bar but not baz"
  
      In the example above, the last commit will fail by design. This gives
      the user the opportunity to decide whether they want to commit the
      rename at the same time, separately first, or not at all. (As a general
      rule, when in doubt, Bazaar has a policy of Doing the Safe Thing.)
    """
    # TODO: Run hooks on tree to-be-committed, and after commit.

    # TODO: Strict commit that fails if there are deleted files.
    #       (what does "deleted files" mean ??)

    # TODO: Give better message for -s, --summary, used by tla people

    # XXX: verbose currently does nothing

    _see_also = ['add', 'bugs', 'hooks', 'uncommit']
    takes_args = ['selected*']
    takes_options = [
            ListOption('exclude', type=str, short_name='x',
                help="Do not consider changes made to a given path."),
            Option('message', type=unicode,
                   short_name='m',
                   help="Description of the new revision."),
            'verbose',
             Option('unchanged',
                    help='Commit even if nothing has changed.'),
             Option('file', type=str,
                    short_name='F',
                    argname='msgfile',
                    help='Take commit message from this file.'),
             Option('strict',
                    help="Refuse to commit if there are unknown "
                    "files in the working tree."),
             ListOption('fixes', type=str,
                    help="Mark a bug as being fixed by this revision "
                         "(see \"bzr help bugs\")."),
             ListOption('author', type=unicode,
                    help="Set the author's name, if it's different "
                         "from the committer."),
             Option('local',
                    help="Perform a local commit in a bound "
                         "branch.  Local commits are not pushed to "
                         "the master branch until a normal commit "
                         "is performed."
                    ),
              Option('show-diff',
                     help='When no message is supplied, show the diff along'
                     ' with the status summary in the message editor.'),
             ]
    aliases = ['ci', 'checkin']

    def _iter_bug_fix_urls(self, fixes, branch):
        # Configure the properties for bug fixing attributes.
        for fixed_bug in fixes:
            tokens = fixed_bug.split(':')
            if len(tokens) != 2:
                raise errors.BzrCommandError(
                    "Invalid bug %s. Must be in the form of 'tracker:id'. "
                    "See \"bzr help bugs\" for more information on this "
                    "feature.\nCommit refused." % fixed_bug)
            tag, bug_id = tokens
            try:
                yield bugtracker.get_bug_url(tag, branch, bug_id)
            except errors.UnknownBugTrackerAbbreviation:
                raise errors.BzrCommandError(
                    'Unrecognized bug %s. Commit refused.' % fixed_bug)
            except errors.MalformedBugIdentifier, e:
                raise errors.BzrCommandError(
                    "%s\nCommit refused." % (str(e),))

    def run(self, message=None, file=None, verbose=False, selected_list=None,
            unchanged=False, strict=False, local=False, fixes=None,
            author=None, show_diff=False, exclude=None):
        from bzrlib.errors import (
            PointlessCommit,
            ConflictsInTree,
            StrictCommitFailed
        )
        from bzrlib.msgeditor import (
            edit_commit_message_encoded,
            generate_commit_message_template,
            make_commit_message_template_encoded
        )

        # TODO: Need a blackbox test for invoking the external editor; may be
        # slightly problematic to run this cross-platform.

        # TODO: do more checks that the commit will succeed before
        # spending the user's valuable time typing a commit message.

        properties = {}

        tree, selected_list = tree_files(selected_list)
        if selected_list == ['']:
            # workaround - commit of root of tree should be exactly the same
            # as just default commit in that tree, and succeed even though
            # selected-file merge commit is not done yet
            selected_list = []

        if fixes is None:
            fixes = []
        bug_property = bugtracker.encode_fixes_bug_urls(
            self._iter_bug_fix_urls(fixes, tree.branch))
        if bug_property:
            properties['bugs'] = bug_property

        if local and not tree.branch.get_bound_location():
            raise errors.LocalRequiresBoundBranch()

        def get_message(commit_obj):
            """Callback to get commit message"""
            my_message = message
            if my_message is None and not file:
                t = make_commit_message_template_encoded(tree,
                        selected_list, diff=show_diff,
                        output_encoding=osutils.get_user_encoding())
                start_message = generate_commit_message_template(commit_obj)
                my_message = edit_commit_message_encoded(t,
                    start_message=start_message)
                if my_message is None:
                    raise errors.BzrCommandError("please specify a commit"
                        " message with either --message or --file")
            elif my_message and file:
                raise errors.BzrCommandError(
                    "please specify either --message or --file")
            if file:
                my_message = codecs.open(file, 'rt',
                                         osutils.get_user_encoding()).read()
            if my_message == "":
                raise errors.BzrCommandError("empty commit message specified")
            return my_message

        # The API permits a commit with a filter of [] to mean 'select nothing'
        # but the command line should not do that.
        if not selected_list:
            selected_list = None
        try:
            tree.commit(message_callback=get_message,
                        specific_files=selected_list,
                        allow_pointless=unchanged, strict=strict, local=local,
                        reporter=None, verbose=verbose, revprops=properties,
                        authors=author,
                        exclude=safe_relpath_files(tree, exclude))
        except PointlessCommit:
            # FIXME: This should really happen before the file is read in;
            # perhaps prepare the commit; get the message; then actually commit
            raise errors.BzrCommandError("No changes to commit."
                              " Use --unchanged to commit anyhow.")
        except ConflictsInTree:
            raise errors.BzrCommandError('Conflicts detected in working '
                'tree.  Use "bzr conflicts" to list, "bzr resolve FILE" to'
                ' resolve.')
        except StrictCommitFailed:
            raise errors.BzrCommandError("Commit refused because there are"
                              " unknown files in the working tree.")
        except errors.BoundBranchOutOfDate, e:
            raise errors.BzrCommandError(str(e) + "\n"
            'To commit to master branch, run update and then commit.\n'
            'You can also pass --local to commit to continue working '
            'disconnected.')


class cmd_check(Command):
    """Validate working tree structure, branch consistency and repository history.

    This command checks various invariants about branch and repository storage
    to detect data corruption or bzr bugs.

    The working tree and branch checks will only give output if a problem is
    detected. The output fields of the repository check are:

    revisions
        This is just the number of revisions checked.  It doesn't
        indicate a problem.

    versionedfiles
        This is just the number of versionedfiles checked.  It
        doesn't indicate a problem.

    unreferenced ancestors
        Texts that are ancestors of other texts, but
        are not properly referenced by the revision ancestry.  This is a
        subtle problem that Bazaar can work around.

    unique file texts
        This is the total number of unique file contents
        seen in the checked revisions.  It does not indicate a problem.

    repeated file texts
        This is the total number of repeated texts seen
        in the checked revisions.  Texts can be repeated when their file
        entries are modified, but the file contents are not.  It does not
        indicate a problem.

    If no restrictions are specified, all Bazaar data that is found at the given
    location will be checked.

    :Examples:

        Check the tree and branch at 'foo'::

            bzr check --tree --branch foo

        Check only the repository at 'bar'::

            bzr check --repo bar

        Check everything at 'baz'::

            bzr check baz
    """

    _see_also = ['reconcile']
    takes_args = ['path?']
    takes_options = ['verbose',
                     Option('branch', help="Check the branch related to the"
                                           " current directory."),
                     Option('repo', help="Check the repository related to the"
                                         " current directory."),
                     Option('tree', help="Check the working tree related to"
                                         " the current directory.")]

    def run(self, path=None, verbose=False, branch=False, repo=False,
            tree=False):
        from bzrlib.check import check_dwim
        if path is None:
            path = '.'
        if not branch and not repo and not tree:
            branch = repo = tree = True
        check_dwim(path, verbose, do_branch=branch, do_repo=repo, do_tree=tree)


class cmd_upgrade(Command):
    """Upgrade branch storage to current format.

    The check command or bzr developers may sometimes advise you to run
    this command. When the default format has changed you may also be warned
    during other operations to upgrade.
    """

    _see_also = ['check']
    takes_args = ['url?']
    takes_options = [
                    RegistryOption('format',
                        help='Upgrade to a specific format.  See "bzr help'
                             ' formats" for details.',
                        lazy_registry=('bzrlib.bzrdir', 'format_registry'),
                        converter=lambda name: bzrdir.format_registry.make_bzrdir(name),
                        value_switches=True, title='Branch format'),
                    ]

    def run(self, url='.', format=None):
        from bzrlib.upgrade import upgrade
        upgrade(url, format)


class cmd_whoami(Command):
    """Show or set bzr user id.

    :Examples:
        Show the email of the current user::

            bzr whoami --email

        Set the current user::

            bzr whoami "Frank Chu <fchu@example.com>"
    """
    takes_options = [ Option('email',
                             help='Display email address only.'),
                      Option('branch',
                             help='Set identity for the current branch instead of '
                                  'globally.'),
                    ]
    takes_args = ['name?']
    encoding_type = 'replace'

    @display_command
    def run(self, email=False, branch=False, name=None):
        if name is None:
            # use branch if we're inside one; otherwise global config
            try:
                c = Branch.open_containing('.')[0].get_config()
            except errors.NotBranchError:
                c = config.GlobalConfig()
            if email:
                self.outf.write(c.user_email() + '\n')
            else:
                self.outf.write(c.username() + '\n')
            return

        # display a warning if an email address isn't included in the given name.
        try:
            config.extract_email_address(name)
        except errors.NoEmailInUsername, e:
            warning('"%s" does not seem to contain an email address.  '
                    'This is allowed, but not recommended.', name)

        # use global config unless --branch given
        if branch:
            c = Branch.open_containing('.')[0].get_config()
        else:
            c = config.GlobalConfig()
        c.set_user_option('email', name)


class cmd_nick(Command):
    """Print or set the branch nickname.

    If unset, the tree root directory name is used as the nickname.
    To print the current nickname, execute with no argument.

    Bound branches use the nickname of its master branch unless it is set
    locally.
    """

    _see_also = ['info']
    takes_args = ['nickname?']
    def run(self, nickname=None):
        branch = Branch.open_containing(u'.')[0]
        if nickname is None:
            self.printme(branch)
        else:
            branch.nick = nickname

    @display_command
    def printme(self, branch):
        print branch.nick


class cmd_alias(Command):
    """Set/unset and display aliases.

    :Examples:
        Show the current aliases::

            bzr alias

        Show the alias specified for 'll'::

            bzr alias ll

        Set an alias for 'll'::

            bzr alias ll="log --line -r-10..-1"

        To remove an alias for 'll'::

            bzr alias --remove ll

    """
    takes_args = ['name?']
    takes_options = [
        Option('remove', help='Remove the alias.'),
        ]

    def run(self, name=None, remove=False):
        if remove:
            self.remove_alias(name)
        elif name is None:
            self.print_aliases()
        else:
            equal_pos = name.find('=')
            if equal_pos == -1:
                self.print_alias(name)
            else:
                self.set_alias(name[:equal_pos], name[equal_pos+1:])

    def remove_alias(self, alias_name):
        if alias_name is None:
            raise errors.BzrCommandError(
                'bzr alias --remove expects an alias to remove.')
        # If alias is not found, print something like:
        # unalias: foo: not found
        c = config.GlobalConfig()
        c.unset_alias(alias_name)

    @display_command
    def print_aliases(self):
        """Print out the defined aliases in a similar format to bash."""
        aliases = config.GlobalConfig().get_aliases()
        for key, value in sorted(aliases.iteritems()):
            self.outf.write('bzr alias %s="%s"\n' % (key, value))

    @display_command
    def print_alias(self, alias_name):
        from bzrlib.commands import get_alias
        alias = get_alias(alias_name)
        if alias is None:
            self.outf.write("bzr alias: %s: not found\n" % alias_name)
        else:
            self.outf.write(
                'bzr alias %s="%s"\n' % (alias_name, ' '.join(alias)))

    def set_alias(self, alias_name, alias_command):
        """Save the alias in the global config."""
        c = config.GlobalConfig()
        c.set_alias(alias_name, alias_command)


class cmd_selftest(Command):
    """Run internal test suite.

    If arguments are given, they are regular expressions that say which tests
    should run.  Tests matching any expression are run, and other tests are
    not run.

    Alternatively if --first is given, matching tests are run first and then
    all other tests are run.  This is useful if you have been working in a
    particular area, but want to make sure nothing else was broken.

    If --exclude is given, tests that match that regular expression are
    excluded, regardless of whether they match --first or not.

    To help catch accidential dependencies between tests, the --randomize
    option is useful. In most cases, the argument used is the word 'now'.
    Note that the seed used for the random number generator is displayed
    when this option is used. The seed can be explicitly passed as the
    argument to this option if required. This enables reproduction of the
    actual ordering used if and when an order sensitive problem is encountered.

    If --list-only is given, the tests that would be run are listed. This is
    useful when combined with --first, --exclude and/or --randomize to
    understand their impact. The test harness reports "Listed nn tests in ..."
    instead of "Ran nn tests in ..." when list mode is enabled.

    If the global option '--no-plugins' is given, plugins are not loaded
    before running the selftests.  This has two effects: features provided or
    modified by plugins will not be tested, and tests provided by plugins will
    not be run.

    Tests that need working space on disk use a common temporary directory,
    typically inside $TMPDIR or /tmp.

    :Examples:
        Run only tests relating to 'ignore'::

            bzr selftest ignore

        Disable plugins and list tests as they're run::

            bzr --no-plugins selftest -v
    """
    # NB: this is used from the class without creating an instance, which is
    # why it does not have a self parameter.
    def get_transport_type(typestring):
        """Parse and return a transport specifier."""
        if typestring == "sftp":
            from bzrlib.transport.sftp import SFTPAbsoluteServer
            return SFTPAbsoluteServer
        if typestring == "memory":
            from bzrlib.transport.memory import MemoryServer
            return MemoryServer
        if typestring == "fakenfs":
            from bzrlib.transport.fakenfs import FakeNFSServer
            return FakeNFSServer
        msg = "No known transport type %s. Supported types are: sftp\n" %\
            (typestring)
        raise errors.BzrCommandError(msg)

    hidden = True
    takes_args = ['testspecs*']
    takes_options = ['verbose',
                     Option('one',
                             help='Stop when one test fails.',
                             short_name='1',
                             ),
                     Option('transport',
                            help='Use a different transport by default '
                                 'throughout the test suite.',
                            type=get_transport_type),
                     Option('benchmark',
                            help='Run the benchmarks rather than selftests.'),
                     Option('lsprof-timed',
                            help='Generate lsprof output for benchmarked'
                                 ' sections of code.'),
                     Option('cache-dir', type=str,
                            help='Cache intermediate benchmark output in this '
                                 'directory.'),
                     Option('first',
                            help='Run all tests, but run specified tests first.',
                            short_name='f',
                            ),
                     Option('list-only',
                            help='List the tests instead of running them.'),
                     RegistryOption('parallel',
                        help="Run the test suite in parallel.",
                        lazy_registry=('bzrlib.tests', 'parallel_registry'),
                        value_switches=False,
                        ),
                     Option('randomize', type=str, argname="SEED",
                            help='Randomize the order of tests using the given'
                                 ' seed or "now" for the current time.'),
                     Option('exclude', type=str, argname="PATTERN",
                            short_name='x',
                            help='Exclude tests that match this regular'
                                 ' expression.'),
                     Option('subunit',
                        help='Output test progress via subunit.'),
                     Option('strict', help='Fail on missing dependencies or '
                            'known failures.'),
                     Option('load-list', type=str, argname='TESTLISTFILE',
                            help='Load a test id list from a text file.'),
                     ListOption('debugflag', type=str, short_name='E',
                                help='Turn on a selftest debug flag.'),
                     ListOption('starting-with', type=str, argname='TESTID',
                                param_name='starting_with', short_name='s',
                                help=
                                'Load only the tests starting with TESTID.'),
                     ]
    encoding_type = 'replace'

    def __init__(self):
        Command.__init__(self)
        self.additional_selftest_args = {}

    def run(self, testspecs_list=None, verbose=False, one=False,
            transport=None, benchmark=None,
            lsprof_timed=None, cache_dir=None,
            first=False, list_only=False,
            randomize=None, exclude=None, strict=False,
            load_list=None, debugflag=None, starting_with=None, subunit=False,
            parallel=None):
        from bzrlib.tests import selftest
        import bzrlib.benchmarks as benchmarks
        from bzrlib.benchmarks import tree_creator

        # Make deprecation warnings visible, unless -Werror is set
        symbol_versioning.activate_deprecation_warnings(override=False)

        if cache_dir is not None:
            tree_creator.TreeCreator.CACHE_ROOT = osutils.abspath(cache_dir)
        if testspecs_list is not None:
            pattern = '|'.join(testspecs_list)
        else:
            pattern = ".*"
        if subunit:
            try:
                from bzrlib.tests import SubUnitBzrRunner
            except ImportError:
                raise errors.BzrCommandError("subunit not available. subunit "
                    "needs to be installed to use --subunit.")
            self.additional_selftest_args['runner_class'] = SubUnitBzrRunner
        if parallel:
            self.additional_selftest_args.setdefault(
                'suite_decorators', []).append(parallel)
        if benchmark:
            test_suite_factory = benchmarks.test_suite
            # Unless user explicitly asks for quiet, be verbose in benchmarks
            verbose = not is_quiet()
            # TODO: should possibly lock the history file...
            benchfile = open(".perf_history", "at", buffering=1)
        else:
            test_suite_factory = None
            benchfile = None
        try:
            selftest_kwargs = {"verbose": verbose,
                              "pattern": pattern,
                              "stop_on_failure": one,
                              "transport": transport,
                              "test_suite_factory": test_suite_factory,
                              "lsprof_timed": lsprof_timed,
                              "bench_history": benchfile,
                              "matching_tests_first": first,
                              "list_only": list_only,
                              "random_seed": randomize,
                              "exclude_pattern": exclude,
                              "strict": strict,
                              "load_list": load_list,
                              "debug_flags": debugflag,
                              "starting_with": starting_with
                              }
            selftest_kwargs.update(self.additional_selftest_args)
            result = selftest(**selftest_kwargs)
        finally:
            if benchfile is not None:
                benchfile.close()
        return int(not result)


class cmd_version(Command):
    """Show version of bzr."""

    encoding_type = 'replace'
    takes_options = [
        Option("short", help="Print just the version number."),
        ]

    @display_command
    def run(self, short=False):
        from bzrlib.version import show_version
        if short:
            self.outf.write(bzrlib.version_string + '\n')
        else:
            show_version(to_file=self.outf)


class cmd_rocks(Command):
    """Statement of optimism."""

    hidden = True

    @display_command
    def run(self):
        print "It sure does!"


class cmd_find_merge_base(Command):
    """Find and print a base revision for merging two branches."""
    # TODO: Options to specify revisions on either side, as if
    #       merging only part of the history.
    takes_args = ['branch', 'other']
    hidden = True

    @display_command
    def run(self, branch, other):
        from bzrlib.revision import ensure_null

        branch1 = Branch.open_containing(branch)[0]
        branch2 = Branch.open_containing(other)[0]
        branch1.lock_read()
        try:
            branch2.lock_read()
            try:
                last1 = ensure_null(branch1.last_revision())
                last2 = ensure_null(branch2.last_revision())

                graph = branch1.repository.get_graph(branch2.repository)
                base_rev_id = graph.find_unique_lca(last1, last2)

                print 'merge base is revision %s' % base_rev_id
            finally:
                branch2.unlock()
        finally:
            branch1.unlock()


class cmd_merge(Command):
    """Perform a three-way merge.

    The source of the merge can be specified either in the form of a branch,
    or in the form of a path to a file containing a merge directive generated
    with bzr send. If neither is specified, the default is the upstream branch
    or the branch most recently merged using --remember.

    When merging a branch, by default the tip will be merged. To pick a different
    revision, pass --revision. If you specify two values, the first will be used as
    BASE and the second one as OTHER. Merging individual revisions, or a subset of
    available revisions, like this is commonly referred to as "cherrypicking".

    Revision numbers are always relative to the branch being merged.

    By default, bzr will try to merge in all new work from the other
    branch, automatically determining an appropriate base.  If this
    fails, you may need to give an explicit base.

    Merge will do its best to combine the changes in two branches, but there
    are some kinds of problems only a human can fix.  When it encounters those,
    it will mark a conflict.  A conflict means that you need to fix something,
    before you should commit.

    Use bzr resolve when you have fixed a problem.  See also bzr conflicts.

    If there is no default branch set, the first merge will set it. After
    that, you can omit the branch to use the default.  To change the
    default, use --remember. The value will only be saved if the remote
    location can be accessed.

    The results of the merge are placed into the destination working
    directory, where they can be reviewed (with bzr diff), tested, and then
    committed to record the result of the merge.

    merge refuses to run if there are any uncommitted changes, unless
    --force is given.

    To select only some changes to merge, use "merge -i", which will prompt
    you to apply each diff hunk and file change, similar to "shelve".

    :Examples:
        To merge the latest revision from bzr.dev::

            bzr merge ../bzr.dev

        To merge changes up to and including revision 82 from bzr.dev::

            bzr merge -r 82 ../bzr.dev

        To merge the changes introduced by 82, without previous changes::

            bzr merge -r 81..82 ../bzr.dev

        To apply a merge directive contained in /tmp/merge:

            bzr merge /tmp/merge
    """

    encoding_type = 'exact'
    _see_also = ['update', 'remerge', 'status-flags', 'send']
    takes_args = ['location?']
    takes_options = [
        'change',
        'revision',
        Option('force',
               help='Merge even if the destination tree has uncommitted changes.'),
        'merge-type',
        'reprocess',
        'remember',
        Option('show-base', help="Show base revision text in "
               "conflicts."),
        Option('uncommitted', help='Apply uncommitted changes'
               ' from a working copy, instead of branch changes.'),
        Option('pull', help='If the destination is already'
                ' completely merged into the source, pull from the'
                ' source rather than merging.  When this happens,'
                ' you do not need to commit the result.'),
        Option('directory',
               help='Branch to merge into, '
                    'rather than the one containing the working directory.',
               short_name='d',
               type=unicode,
               ),
        Option('preview', help='Instead of merging, show a diff of the'
               ' merge.'),
        Option('interactive', help='Select changes interactively.',
            short_name='i')
    ]

    def run(self, location=None, revision=None, force=False,
            merge_type=None, show_base=False, reprocess=None, remember=False,
            uncommitted=False, pull=False,
            directory=None,
            preview=False,
            interactive=False,
            ):
        if merge_type is None:
            merge_type = _mod_merge.Merge3Merger

        if directory is None: directory = u'.'
        possible_transports = []
        merger = None
        allow_pending = True
        verified = 'inapplicable'
        tree = WorkingTree.open_containing(directory)[0]

        # die as quickly as possible if there are uncommitted changes
        try:
            basis_tree = tree.revision_tree(tree.last_revision())
        except errors.NoSuchRevision:
            basis_tree = tree.basis_tree()
        if not force:
            if tree.has_changes(basis_tree):
                raise errors.UncommittedChanges(tree)

        view_info = _get_view_info_for_change_reporter(tree)
        change_reporter = delta._ChangeReporter(
            unversioned_filter=tree.is_ignored, view_info=view_info)
        cleanups = []
        try:
            pb = ui.ui_factory.nested_progress_bar()
            cleanups.append(pb.finished)
            tree.lock_write()
            cleanups.append(tree.unlock)
            if location is not None:
                try:
                    mergeable = bundle.read_mergeable_from_url(location,
                        possible_transports=possible_transports)
                except errors.NotABundle:
                    mergeable = None
                else:
                    if uncommitted:
                        raise errors.BzrCommandError('Cannot use --uncommitted'
                            ' with bundles or merge directives.')

                    if revision is not None:
                        raise errors.BzrCommandError(
                            'Cannot use -r with merge directives or bundles')
                    merger, verified = _mod_merge.Merger.from_mergeable(tree,
                       mergeable, pb)

            if merger is None and uncommitted:
                if revision is not None and len(revision) > 0:
                    raise errors.BzrCommandError('Cannot use --uncommitted and'
                        ' --revision at the same time.')
                merger = self.get_merger_from_uncommitted(tree, location, pb,
                                                          cleanups)
                allow_pending = False

            if merger is None:
                merger, allow_pending = self._get_merger_from_branch(tree,
                    location, revision, remember, possible_transports, pb)

            merger.merge_type = merge_type
            merger.reprocess = reprocess
            merger.show_base = show_base
            self.sanity_check_merger(merger)
            if (merger.base_rev_id == merger.other_rev_id and
                merger.other_rev_id is not None):
                note('Nothing to do.')
                return 0
            if pull:
                if merger.interesting_files is not None:
                    raise errors.BzrCommandError('Cannot pull individual files')
                if (merger.base_rev_id == tree.last_revision()):
                    result = tree.pull(merger.other_branch, False,
                                       merger.other_rev_id)
                    result.report(self.outf)
                    return 0
            merger.check_basis(False)
            if preview:
                return self._do_preview(merger, cleanups)
            elif interactive:
                return self._do_interactive(merger, cleanups)
            else:
                return self._do_merge(merger, change_reporter, allow_pending,
                                      verified)
        finally:
            for cleanup in reversed(cleanups):
                cleanup()

    def _get_preview(self, merger, cleanups):
        tree_merger = merger.make_merger()
        tt = tree_merger.make_preview_transform()
        cleanups.append(tt.finalize)
        result_tree = tt.get_preview_tree()
        return result_tree

    def _do_preview(self, merger, cleanups):
        from bzrlib.diff import show_diff_trees
        result_tree = self._get_preview(merger, cleanups)
        show_diff_trees(merger.this_tree, result_tree, self.outf,
                        old_label='', new_label='')

    def _do_merge(self, merger, change_reporter, allow_pending, verified):
        merger.change_reporter = change_reporter
        conflict_count = merger.do_merge()
        if allow_pending:
            merger.set_pending()
        if verified == 'failed':
            warning('Preview patch does not match changes')
        if conflict_count != 0:
            return 1
        else:
            return 0

    def _do_interactive(self, merger, cleanups):
        """Perform an interactive merge.

        This works by generating a preview tree of the merge, then using
        Shelver to selectively remove the differences between the working tree
        and the preview tree.
        """
        from bzrlib import shelf_ui
        result_tree = self._get_preview(merger, cleanups)
        writer = bzrlib.option.diff_writer_registry.get()
        shelver = shelf_ui.Shelver(merger.this_tree, result_tree, destroy=True,
                                   reporter=shelf_ui.ApplyReporter(),
                                   diff_writer=writer(sys.stdout))
        shelver.run()

    def sanity_check_merger(self, merger):
        if (merger.show_base and
            not merger.merge_type is _mod_merge.Merge3Merger):
            raise errors.BzrCommandError("Show-base is not supported for this"
                                         " merge type. %s" % merger.merge_type)
        if merger.reprocess is None:
            if merger.show_base:
                merger.reprocess = False
            else:
                # Use reprocess if the merger supports it
                merger.reprocess = merger.merge_type.supports_reprocess
        if merger.reprocess and not merger.merge_type.supports_reprocess:
            raise errors.BzrCommandError("Conflict reduction is not supported"
                                         " for merge type %s." %
                                         merger.merge_type)
        if merger.reprocess and merger.show_base:
            raise errors.BzrCommandError("Cannot do conflict reduction and"
                                         " show base.")

    def _get_merger_from_branch(self, tree, location, revision, remember,
                                possible_transports, pb):
        """Produce a merger from a location, assuming it refers to a branch."""
        from bzrlib.tag import _merge_tags_if_possible
        # find the branch locations
        other_loc, user_location = self._select_branch_location(tree, location,
            revision, -1)
        if revision is not None and len(revision) == 2:
            base_loc, _unused = self._select_branch_location(tree,
                location, revision, 0)
        else:
            base_loc = other_loc
        # Open the branches
        other_branch, other_path = Branch.open_containing(other_loc,
            possible_transports)
        if base_loc == other_loc:
            base_branch = other_branch
        else:
            base_branch, base_path = Branch.open_containing(base_loc,
                possible_transports)
        # Find the revision ids
        other_revision_id = None
        base_revision_id = None
        if revision is not None:
            if len(revision) >= 1:
                other_revision_id = revision[-1].as_revision_id(other_branch)
            if len(revision) == 2:
                base_revision_id = revision[0].as_revision_id(base_branch)
        if other_revision_id is None:
            other_revision_id = _mod_revision.ensure_null(
                other_branch.last_revision())
        # Remember where we merge from
        if ((remember or tree.branch.get_submit_branch() is None) and
             user_location is not None):
            tree.branch.set_submit_branch(other_branch.base)
        _merge_tags_if_possible(other_branch, tree.branch)
        merger = _mod_merge.Merger.from_revision_ids(pb, tree,
            other_revision_id, base_revision_id, other_branch, base_branch)
        if other_path != '':
            allow_pending = False
            merger.interesting_files = [other_path]
        else:
            allow_pending = True
        return merger, allow_pending

    def get_merger_from_uncommitted(self, tree, location, pb, cleanups):
        """Get a merger for uncommitted changes.

        :param tree: The tree the merger should apply to.
        :param location: The location containing uncommitted changes.
        :param pb: The progress bar to use for showing progress.
        :param cleanups: A list of operations to perform to clean up the
            temporary directories, unfinalized objects, etc.
        """
        location = self._select_branch_location(tree, location)[0]
        other_tree, other_path = WorkingTree.open_containing(location)
        merger = _mod_merge.Merger.from_uncommitted(tree, other_tree, pb)
        if other_path != '':
            merger.interesting_files = [other_path]
        return merger

    def _select_branch_location(self, tree, user_location, revision=None,
                                index=None):
        """Select a branch location, according to possible inputs.

        If provided, branches from ``revision`` are preferred.  (Both
        ``revision`` and ``index`` must be supplied.)

        Otherwise, the ``location`` parameter is used.  If it is None, then the
        ``submit`` or ``parent`` location is used, and a note is printed.

        :param tree: The working tree to select a branch for merging into
        :param location: The location entered by the user
        :param revision: The revision parameter to the command
        :param index: The index to use for the revision parameter.  Negative
            indices are permitted.
        :return: (selected_location, user_location).  The default location
            will be the user-entered location.
        """
        if (revision is not None and index is not None
            and revision[index] is not None):
            branch = revision[index].get_branch()
            if branch is not None:
                return branch, branch
        if user_location is None:
            location = self._get_remembered(tree, 'Merging from')
        else:
            location = user_location
        return location, user_location

    def _get_remembered(self, tree, verb_string):
        """Use tree.branch's parent if none was supplied.

        Report if the remembered location was used.
        """
        stored_location = tree.branch.get_submit_branch()
        stored_location_type = "submit"
        if stored_location is None:
            stored_location = tree.branch.get_parent()
            stored_location_type = "parent"
        mutter("%s", stored_location)
        if stored_location is None:
            raise errors.BzrCommandError("No location specified or remembered")
        display_url = urlutils.unescape_for_display(stored_location, 'utf-8')
        note(u"%s remembered %s location %s", verb_string,
                stored_location_type, display_url)
        return stored_location


class cmd_remerge(Command):
    """Redo a merge.

    Use this if you want to try a different merge technique while resolving
    conflicts.  Some merge techniques are better than others, and remerge
    lets you try different ones on different files.

    The options for remerge have the same meaning and defaults as the ones for
    merge.  The difference is that remerge can (only) be run when there is a
    pending merge, and it lets you specify particular files.

    :Examples:
        Re-do the merge of all conflicted files, and show the base text in
        conflict regions, in addition to the usual THIS and OTHER texts::

            bzr remerge --show-base

        Re-do the merge of "foobar", using the weave merge algorithm, with
        additional processing to reduce the size of conflict regions::

            bzr remerge --merge-type weave --reprocess foobar
    """
    takes_args = ['file*']
    takes_options = [
            'merge-type',
            'reprocess',
            Option('show-base',
                   help="Show base revision text in conflicts."),
            ]

    def run(self, file_list=None, merge_type=None, show_base=False,
            reprocess=False):
        if merge_type is None:
            merge_type = _mod_merge.Merge3Merger
        tree, file_list = tree_files(file_list)
        tree.lock_write()
        try:
            parents = tree.get_parent_ids()
            if len(parents) != 2:
                raise errors.BzrCommandError("Sorry, remerge only works after normal"
                                             " merges.  Not cherrypicking or"
                                             " multi-merges.")
            repository = tree.branch.repository
            interesting_ids = None
            new_conflicts = []
            conflicts = tree.conflicts()
            if file_list is not None:
                interesting_ids = set()
                for filename in file_list:
                    file_id = tree.path2id(filename)
                    if file_id is None:
                        raise errors.NotVersionedError(filename)
                    interesting_ids.add(file_id)
                    if tree.kind(file_id) != "directory":
                        continue

                    for name, ie in tree.inventory.iter_entries(file_id):
                        interesting_ids.add(ie.file_id)
                new_conflicts = conflicts.select_conflicts(tree, file_list)[0]
            else:
                # Remerge only supports resolving contents conflicts
                allowed_conflicts = ('text conflict', 'contents conflict')
                restore_files = [c.path for c in conflicts
                                 if c.typestring in allowed_conflicts]
            _mod_merge.transform_tree(tree, tree.basis_tree(), interesting_ids)
            tree.set_conflicts(ConflictList(new_conflicts))
            if file_list is not None:
                restore_files = file_list
            for filename in restore_files:
                try:
                    restore(tree.abspath(filename))
                except errors.NotConflicted:
                    pass
            # Disable pending merges, because the file texts we are remerging
            # have not had those merges performed.  If we use the wrong parents
            # list, we imply that the working tree text has seen and rejected
            # all the changes from the other tree, when in fact those changes
            # have not yet been seen.
            pb = ui.ui_factory.nested_progress_bar()
            tree.set_parent_ids(parents[:1])
            try:
                merger = _mod_merge.Merger.from_revision_ids(pb,
                                                             tree, parents[1])
                merger.interesting_ids = interesting_ids
                merger.merge_type = merge_type
                merger.show_base = show_base
                merger.reprocess = reprocess
                conflicts = merger.do_merge()
            finally:
                tree.set_parent_ids(parents)
                pb.finished()
        finally:
            tree.unlock()
        if conflicts > 0:
            return 1
        else:
            return 0


class cmd_revert(Command):
    """Revert files to a previous revision.

    Giving a list of files will revert only those files.  Otherwise, all files
    will be reverted.  If the revision is not specified with '--revision', the
    last committed revision is used.

    To remove only some changes, without reverting to a prior version, use
    merge instead.  For example, "merge . --revision -2..-3" will remove the
    changes introduced by -2, without affecting the changes introduced by -1.
    Or to remove certain changes on a hunk-by-hunk basis, see the Shelf plugin.

    By default, any files that have been manually changed will be backed up
    first.  (Files changed only by merge are not backed up.)  Backup files have
    '.~#~' appended to their name, where # is a number.

    When you provide files, you can use their current pathname or the pathname
    from the target revision.  So you can use revert to "undelete" a file by
    name.  If you name a directory, all the contents of that directory will be
    reverted.

    Any files that have been newly added since that revision will be deleted,
    with a backup kept if appropriate.  Directories containing unknown files
    will not be deleted.

    The working tree contains a list of pending merged revisions, which will
    be included as parents in the next commit.  Normally, revert clears that
    list as well as reverting the files.  If any files are specified, revert
    leaves the pending merge list alone and reverts only the files.  Use "bzr
    revert ." in the tree root to revert all files but keep the merge record,
    and "bzr revert --forget-merges" to clear the pending merge list without
    reverting any files.
    """

    _see_also = ['cat', 'export']
    takes_options = [
        'revision',
        Option('no-backup', "Do not save backups of reverted files."),
        Option('forget-merges',
               'Remove pending merge marker, without changing any files.'),
        ]
    takes_args = ['file*']

    def run(self, revision=None, no_backup=False, file_list=None,
            forget_merges=None):
        tree, file_list = tree_files(file_list)
        tree.lock_write()
        try:
            if forget_merges:
                tree.set_parent_ids(tree.get_parent_ids()[:1])
            else:
                self._revert_tree_to_revision(tree, revision, file_list, no_backup)
        finally:
            tree.unlock()

    @staticmethod
    def _revert_tree_to_revision(tree, revision, file_list, no_backup):
        rev_tree = _get_one_revision_tree('revert', revision, tree=tree)
        pb = ui.ui_factory.nested_progress_bar()
        try:
            tree.revert(file_list, rev_tree, not no_backup, pb,
                report_changes=True)
        finally:
            pb.finished()


class cmd_assert_fail(Command):
    """Test reporting of assertion failures"""
    # intended just for use in testing

    hidden = True

    def run(self):
        raise AssertionError("always fails")


class cmd_help(Command):
    """Show help on a command or other topic.
    """

    _see_also = ['topics']
    takes_options = [
            Option('long', 'Show help on all commands.'),
            ]
    takes_args = ['topic?']
    aliases = ['?', '--help', '-?', '-h']

    @display_command
    def run(self, topic=None, long=False):
        import bzrlib.help
        if topic is None and long:
            topic = "commands"
        bzrlib.help.help(topic)


class cmd_shell_complete(Command):
    """Show appropriate completions for context.

    For a list of all available commands, say 'bzr shell-complete'.
    """
    takes_args = ['context?']
    aliases = ['s-c']
    hidden = True

    @display_command
    def run(self, context=None):
        import shellcomplete
        shellcomplete.shellcomplete(context)


class cmd_missing(Command):
    """Show unmerged/unpulled revisions between two branches.

    OTHER_BRANCH may be local or remote.

    To filter on a range of revisions, you can use the command -r begin..end
    -r revision requests a specific revision, -r ..end or -r begin.. are
    also valid.

    :Examples:

        Determine the missing revisions between this and the branch at the
        remembered pull location::

            bzr missing

        Determine the missing revisions between this and another branch::

            bzr missing http://server/branch

        Determine the missing revisions up to a specific revision on the other
        branch::

            bzr missing -r ..-10

        Determine the missing revisions up to a specific revision on this
        branch::

            bzr missing --my-revision ..-10
    """

    _see_also = ['merge', 'pull']
    takes_args = ['other_branch?']
    takes_options = [
        Option('reverse', 'Reverse the order of revisions.'),
        Option('mine-only',
               'Display changes in the local branch only.'),
        Option('this' , 'Same as --mine-only.'),
        Option('theirs-only',
               'Display changes in the remote branch only.'),
        Option('other', 'Same as --theirs-only.'),
        'log-format',
        'show-ids',
        'verbose',
        custom_help('revision',
             help='Filter on other branch revisions (inclusive). '
                'See "help revisionspec" for details.'),
        Option('my-revision',
            type=_parse_revision_str,
            help='Filter on local branch revisions (inclusive). '
                'See "help revisionspec" for details.'),
        Option('include-merges',
               'Show all revisions in addition to the mainline ones.'),
        ]
    encoding_type = 'replace'

    @display_command
    def run(self, other_branch=None, reverse=False, mine_only=False,
            theirs_only=False,
            log_format=None, long=False, short=False, line=False,
            show_ids=False, verbose=False, this=False, other=False,
            include_merges=False, revision=None, my_revision=None):
        from bzrlib.missing import find_unmerged, iter_log_revisions
        def message(s):
            if not is_quiet():
                self.outf.write(s)

        if this:
            mine_only = this
        if other:
            theirs_only = other
        # TODO: We should probably check that we don't have mine-only and
        #       theirs-only set, but it gets complicated because we also have
        #       this and other which could be used.
        restrict = 'all'
        if mine_only:
            restrict = 'local'
        elif theirs_only:
            restrict = 'remote'

        local_branch = Branch.open_containing(u".")[0]
        parent = local_branch.get_parent()
        if other_branch is None:
            other_branch = parent
            if other_branch is None:
                raise errors.BzrCommandError("No peer location known"
                                             " or specified.")
            display_url = urlutils.unescape_for_display(parent,
                                                        self.outf.encoding)
            message("Using saved parent location: "
                    + display_url + "\n")

        remote_branch = Branch.open(other_branch)
        if remote_branch.base == local_branch.base:
            remote_branch = local_branch

        local_revid_range = _revision_range_to_revid_range(
            _get_revision_range(my_revision, local_branch,
                self.name()))

        remote_revid_range = _revision_range_to_revid_range(
            _get_revision_range(revision,
                remote_branch, self.name()))

        local_branch.lock_read()
        try:
            remote_branch.lock_read()
            try:
                local_extra, remote_extra = find_unmerged(
                    local_branch, remote_branch, restrict,
                    backward=not reverse,
                    include_merges=include_merges,
                    local_revid_range=local_revid_range,
                    remote_revid_range=remote_revid_range)

                if log_format is None:
                    registry = log.log_formatter_registry
                    log_format = registry.get_default(local_branch)
                lf = log_format(to_file=self.outf,
                                show_ids=show_ids,
                                show_timezone='original')

                status_code = 0
                if local_extra and not theirs_only:
                    message("You have %d extra revision(s):\n" %
                        len(local_extra))
                    for revision in iter_log_revisions(local_extra,
                                        local_branch.repository,
                                        verbose):
                        lf.log_revision(revision)
                    printed_local = True
                    status_code = 1
                else:
                    printed_local = False

                if remote_extra and not mine_only:
                    if printed_local is True:
                        message("\n\n\n")
                    message("You are missing %d revision(s):\n" %
                        len(remote_extra))
                    for revision in iter_log_revisions(remote_extra,
                                        remote_branch.repository,
                                        verbose):
                        lf.log_revision(revision)
                    status_code = 1

                if mine_only and not local_extra:
                    # We checked local, and found nothing extra
                    message('This branch is up to date.\n')
                elif theirs_only and not remote_extra:
                    # We checked remote, and found nothing extra
                    message('Other branch is up to date.\n')
                elif not (mine_only or theirs_only or local_extra or
                          remote_extra):
                    # We checked both branches, and neither one had extra
                    # revisions
                    message("Branches are up to date.\n")
            finally:
                remote_branch.unlock()
        finally:
            local_branch.unlock()
        if not status_code and parent is None and other_branch is not None:
            local_branch.lock_write()
            try:
                # handle race conditions - a parent might be set while we run.
                if local_branch.get_parent() is None:
                    local_branch.set_parent(remote_branch.base)
            finally:
                local_branch.unlock()
        return status_code


class cmd_pack(Command):
    """Compress the data within a repository."""

    _see_also = ['repositories']
    takes_args = ['branch_or_repo?']

    def run(self, branch_or_repo='.'):
        dir = bzrdir.BzrDir.open_containing(branch_or_repo)[0]
        try:
            branch = dir.open_branch()
            repository = branch.repository
        except errors.NotBranchError:
            repository = dir.open_repository()
        repository.pack()


class cmd_plugins(Command):
    """List the installed plugins.

    This command displays the list of installed plugins including
    version of plugin and a short description of each.

    --verbose shows the path where each plugin is located.

    A plugin is an external component for Bazaar that extends the
    revision control system, by adding or replacing code in Bazaar.
    Plugins can do a variety of things, including overriding commands,
    adding new commands, providing additional network transports and
    customizing log output.

    See the Bazaar web site, http://bazaar-vcs.org, for further
    information on plugins including where to find them and how to
    install them. Instructions are also provided there on how to
    write new plugins using the Python programming language.
    """
    takes_options = ['verbose']

    @display_command
    def run(self, verbose=False):
        import bzrlib.plugin
        from inspect import getdoc
        result = []
        for name, plugin in bzrlib.plugin.plugins().items():
            version = plugin.__version__
            if version == 'unknown':
                version = ''
            name_ver = '%s %s' % (name, version)
            d = getdoc(plugin.module)
            if d:
                doc = d.split('\n')[0]
            else:
                doc = '(no description)'
            result.append((name_ver, doc, plugin.path()))
        for name_ver, doc, path in sorted(result):
            print name_ver
            print '   ', doc
            if verbose:
                print '   ', path
            print


class cmd_testament(Command):
    """Show testament (signing-form) of a revision."""
    takes_options = [
            'revision',
            Option('long', help='Produce long-format testament.'),
            Option('strict',
                   help='Produce a strict-format testament.')]
    takes_args = ['branch?']
    @display_command
    def run(self, branch=u'.', revision=None, long=False, strict=False):
        from bzrlib.testament import Testament, StrictTestament
        if strict is True:
            testament_class = StrictTestament
        else:
            testament_class = Testament
        if branch == '.':
            b = Branch.open_containing(branch)[0]
        else:
            b = Branch.open(branch)
        b.lock_read()
        try:
            if revision is None:
                rev_id = b.last_revision()
            else:
                rev_id = revision[0].as_revision_id(b)
            t = testament_class.from_revision(b.repository, rev_id)
            if long:
                sys.stdout.writelines(t.as_text_lines())
            else:
                sys.stdout.write(t.as_short_text())
        finally:
            b.unlock()


class cmd_annotate(Command):
    """Show the origin of each line in a file.

    This prints out the given file with an annotation on the left side
    indicating which revision, author and date introduced the change.

    If the origin is the same for a run of consecutive lines, it is
    shown only at the top, unless the --all option is given.
    """
    # TODO: annotate directories; showing when each file was last changed
    # TODO: if the working copy is modified, show annotations on that
    #       with new uncommitted lines marked
    aliases = ['ann', 'blame', 'praise']
    takes_args = ['filename']
    takes_options = [Option('all', help='Show annotations on all lines.'),
                     Option('long', help='Show commit date in annotations.'),
                     'revision',
                     'show-ids',
                     ]
    encoding_type = 'exact'

    @display_command
    def run(self, filename, all=False, long=False, revision=None,
            show_ids=False):
        from bzrlib.annotate import annotate_file, annotate_file_tree
        wt, branch, relpath = \
            bzrdir.BzrDir.open_containing_tree_or_branch(filename)
        if wt is not None:
            wt.lock_read()
        else:
            branch.lock_read()
        try:
            tree = _get_one_revision_tree('annotate', revision, branch=branch)
            if wt is not None:
                file_id = wt.path2id(relpath)
            else:
                file_id = tree.path2id(relpath)
            if file_id is None:
                raise errors.NotVersionedError(filename)
            file_version = tree.inventory[file_id].revision
            if wt is not None and revision is None:
                # If there is a tree and we're not annotating historical
                # versions, annotate the working tree's content.
                annotate_file_tree(wt, file_id, self.outf, long, all,
                    show_ids=show_ids)
            else:
                annotate_file(branch, file_version, file_id, long, all, self.outf,
                              show_ids=show_ids)
        finally:
            if wt is not None:
                wt.unlock()
            else:
                branch.unlock()


class cmd_re_sign(Command):
    """Create a digital signature for an existing revision."""
    # TODO be able to replace existing ones.

    hidden = True # is this right ?
    takes_args = ['revision_id*']
    takes_options = ['revision']

    def run(self, revision_id_list=None, revision=None):
        if revision_id_list is not None and revision is not None:
            raise errors.BzrCommandError('You can only supply one of revision_id or --revision')
        if revision_id_list is None and revision is None:
            raise errors.BzrCommandError('You must supply either --revision or a revision_id')
        b = WorkingTree.open_containing(u'.')[0].branch
        b.lock_write()
        try:
            return self._run(b, revision_id_list, revision)
        finally:
            b.unlock()

    def _run(self, b, revision_id_list, revision):
        import bzrlib.gpg as gpg
        gpg_strategy = gpg.GPGStrategy(b.get_config())
        if revision_id_list is not None:
            b.repository.start_write_group()
            try:
                for revision_id in revision_id_list:
                    b.repository.sign_revision(revision_id, gpg_strategy)
            except:
                b.repository.abort_write_group()
                raise
            else:
                b.repository.commit_write_group()
        elif revision is not None:
            if len(revision) == 1:
                revno, rev_id = revision[0].in_history(b)
                b.repository.start_write_group()
                try:
                    b.repository.sign_revision(rev_id, gpg_strategy)
                except:
                    b.repository.abort_write_group()
                    raise
                else:
                    b.repository.commit_write_group()
            elif len(revision) == 2:
                # are they both on rh- if so we can walk between them
                # might be nice to have a range helper for arbitrary
                # revision paths. hmm.
                from_revno, from_revid = revision[0].in_history(b)
                to_revno, to_revid = revision[1].in_history(b)
                if to_revid is None:
                    to_revno = b.revno()
                if from_revno is None or to_revno is None:
                    raise errors.BzrCommandError('Cannot sign a range of non-revision-history revisions')
                b.repository.start_write_group()
                try:
                    for revno in range(from_revno, to_revno + 1):
                        b.repository.sign_revision(b.get_rev_id(revno),
                                                   gpg_strategy)
                except:
                    b.repository.abort_write_group()
                    raise
                else:
                    b.repository.commit_write_group()
            else:
                raise errors.BzrCommandError('Please supply either one revision, or a range.')


class cmd_bind(Command):
    """Convert the current branch into a checkout of the supplied branch.

    Once converted into a checkout, commits must succeed on the master branch
    before they will be applied to the local branch.

    Bound branches use the nickname of its master branch unless it is set
    locally, in which case binding will update the the local nickname to be
    that of the master.
    """

    _see_also = ['checkouts', 'unbind']
    takes_args = ['location?']
    takes_options = []

    def run(self, location=None):
        b, relpath = Branch.open_containing(u'.')
        if location is None:
            try:
                location = b.get_old_bound_location()
            except errors.UpgradeRequired:
                raise errors.BzrCommandError('No location supplied.  '
                    'This format does not remember old locations.')
            else:
                if location is None:
                    raise errors.BzrCommandError('No location supplied and no '
                        'previous location known')
        b_other = Branch.open(location)
        try:
            b.bind(b_other)
        except errors.DivergedBranches:
            raise errors.BzrCommandError('These branches have diverged.'
                                         ' Try merging, and then bind again.')
        if b.get_config().has_explicit_nickname():
            b.nick = b_other.nick


class cmd_unbind(Command):
    """Convert the current checkout into a regular branch.

    After unbinding, the local branch is considered independent and subsequent
    commits will be local only.
    """

    _see_also = ['checkouts', 'bind']
    takes_args = []
    takes_options = []

    def run(self):
        b, relpath = Branch.open_containing(u'.')
        if not b.unbind():
            raise errors.BzrCommandError('Local branch is not bound')


class cmd_uncommit(Command):
    """Remove the last committed revision.

    --verbose will print out what is being removed.
    --dry-run will go through all the motions, but not actually
    remove anything.

    If --revision is specified, uncommit revisions to leave the branch at the
    specified revision.  For example, "bzr uncommit -r 15" will leave the
    branch at revision 15.

    Uncommit leaves the working tree ready for a new commit.  The only change
    it may make is to restore any pending merges that were present before
    the commit.
    """

    # TODO: jam 20060108 Add an option to allow uncommit to remove
    # unreferenced information in 'branch-as-repository' branches.
    # TODO: jam 20060108 Add the ability for uncommit to remove unreferenced
    # information in shared branches as well.
    _see_also = ['commit']
    takes_options = ['verbose', 'revision',
                    Option('dry-run', help='Don\'t actually make changes.'),
                    Option('force', help='Say yes to all questions.'),
                    Option('local',
                           help="Only remove the commits from the local branch"
                                " when in a checkout."
                           ),
                    ]
    takes_args = ['location?']
    aliases = []
    encoding_type = 'replace'

    def run(self, location=None,
            dry_run=False, verbose=False,
            revision=None, force=False, local=False):
        if location is None:
            location = u'.'
        control, relpath = bzrdir.BzrDir.open_containing(location)
        try:
            tree = control.open_workingtree()
            b = tree.branch
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            tree = None
            b = control.open_branch()

        if tree is not None:
            tree.lock_write()
        else:
            b.lock_write()
        try:
            return self._run(b, tree, dry_run, verbose, revision, force,
                             local=local)
        finally:
            if tree is not None:
                tree.unlock()
            else:
                b.unlock()

    def _run(self, b, tree, dry_run, verbose, revision, force, local=False):
        from bzrlib.log import log_formatter, show_log
        from bzrlib.uncommit import uncommit

        last_revno, last_rev_id = b.last_revision_info()

        rev_id = None
        if revision is None:
            revno = last_revno
            rev_id = last_rev_id
        else:
            # 'bzr uncommit -r 10' actually means uncommit
            # so that the final tree is at revno 10.
            # but bzrlib.uncommit.uncommit() actually uncommits
            # the revisions that are supplied.
            # So we need to offset it by one
            revno = revision[0].in_history(b).revno + 1
            if revno <= last_revno:
                rev_id = b.get_rev_id(revno)

        if rev_id is None or _mod_revision.is_null(rev_id):
            self.outf.write('No revisions to uncommit.\n')
            return 1

        lf = log_formatter('short',
                           to_file=self.outf,
                           show_timezone='original')

        show_log(b,
                 lf,
                 verbose=False,
                 direction='forward',
                 start_revision=revno,
                 end_revision=last_revno)

        if dry_run:
            print 'Dry-run, pretending to remove the above revisions.'
            if not force:
                val = raw_input('Press <enter> to continue')
        else:
            print 'The above revision(s) will be removed.'
            if not force:
                val = raw_input('Are you sure [y/N]? ')
                if val.lower() not in ('y', 'yes'):
                    print 'Canceled'
                    return 0

        mutter('Uncommitting from {%s} to {%s}',
               last_rev_id, rev_id)
        uncommit(b, tree=tree, dry_run=dry_run, verbose=verbose,
                 revno=revno, local=local)
        note('You can restore the old tip by running:\n'
             '  bzr pull . -r revid:%s', last_rev_id)


class cmd_break_lock(Command):
    """Break a dead lock on a repository, branch or working directory.

    CAUTION: Locks should only be broken when you are sure that the process
    holding the lock has been stopped.

    You can get information on what locks are open via the 'bzr info' command.

    :Examples:
        bzr break-lock
    """
    takes_args = ['location?']

    def run(self, location=None, show=False):
        if location is None:
            location = u'.'
        control, relpath = bzrdir.BzrDir.open_containing(location)
        try:
            control.break_lock()
        except NotImplementedError:
            pass


class cmd_wait_until_signalled(Command):
    """Test helper for test_start_and_stop_bzr_subprocess_send_signal.

    This just prints a line to signal when it is ready, then blocks on stdin.
    """

    hidden = True

    def run(self):
        sys.stdout.write("running\n")
        sys.stdout.flush()
        sys.stdin.readline()


class cmd_serve(Command):
    """Run the bzr server."""

    aliases = ['server']

    takes_options = [
        Option('inet',
               help='Serve on stdin/out for use from inetd or sshd.'),
        RegistryOption('protocol', 
               help="Protocol to serve.", 
               lazy_registry=('bzrlib.transport', 'transport_server_registry'),
               value_switches=True),
        Option('port',
               help='Listen for connections on nominated port of the form '
                    '[hostname:]portnumber.  Passing 0 as the port number will '
                    'result in a dynamically allocated port.  The default port '
                    'depends on the protocol.',
               type=str),
        Option('directory',
               help='Serve contents of this directory.',
               type=unicode),
        Option('allow-writes',
               help='By default the server is a readonly server.  Supplying '
                    '--allow-writes enables write access to the contents of '
                    'the served directory and below.'
                ),
        ]

    def get_host_and_port(self, port):
        """Return the host and port to run the smart server on.

        If 'port' is None, None will be returned for the host and port.

        If 'port' has a colon in it, the string before the colon will be
        interpreted as the host.

        :param port: A string of the port to run the server on.
        :return: A tuple of (host, port), where 'host' is a host name or IP,
            and port is an integer TCP/IP port.
        """
        host = None
        if port is not None:
            if ':' in port:
                host, port = port.split(':')
            port = int(port)
        return host, port

    def run(self, port=None, inet=False, directory=None, allow_writes=False,
            protocol=None):
        from bzrlib.transport import get_transport, transport_server_registry
        if directory is None:
            directory = os.getcwd()
        if protocol is None:
            protocol = transport_server_registry.get()
        host, port = self.get_host_and_port(port)
        url = urlutils.local_path_to_url(directory)
        if not allow_writes:
            url = 'readonly+' + url
        transport = get_transport(url)
        protocol(transport, host, port, inet)


class cmd_join(Command):
    """Combine a tree into its containing tree.

    This command requires the target tree to be in a rich-root format.

    The TREE argument should be an independent tree, inside another tree, but
    not part of it.  (Such trees can be produced by "bzr split", but also by
    running "bzr branch" with the target inside a tree.)

    The result is a combined tree, with the subtree no longer an independant
    part.  This is marked as a merge of the subtree into the containing tree,
    and all history is preserved.
    """

    _see_also = ['split']
    takes_args = ['tree']
    takes_options = [
            Option('reference', help='Join by reference.', hidden=True),
            ]

    def run(self, tree, reference=False):
        sub_tree = WorkingTree.open(tree)
        parent_dir = osutils.dirname(sub_tree.basedir)
        containing_tree = WorkingTree.open_containing(parent_dir)[0]
        repo = containing_tree.branch.repository
        if not repo.supports_rich_root():
            raise errors.BzrCommandError(
                "Can't join trees because %s doesn't support rich root data.\n"
                "You can use bzr upgrade on the repository."
                % (repo,))
        if reference:
            try:
                containing_tree.add_reference(sub_tree)
            except errors.BadReferenceTarget, e:
                # XXX: Would be better to just raise a nicely printable
                # exception from the real origin.  Also below.  mbp 20070306
                raise errors.BzrCommandError("Cannot join %s.  %s" %
                                             (tree, e.reason))
        else:
            try:
                containing_tree.subsume(sub_tree)
            except errors.BadSubsumeSource, e:
                raise errors.BzrCommandError("Cannot join %s.  %s" %
                                             (tree, e.reason))


class cmd_split(Command):
    """Split a subdirectory of a tree into a separate tree.

    This command will produce a target tree in a format that supports
    rich roots, like 'rich-root' or 'rich-root-pack'.  These formats cannot be
    converted into earlier formats like 'dirstate-tags'.

    The TREE argument should be a subdirectory of a working tree.  That
    subdirectory will be converted into an independent tree, with its own
    branch.  Commits in the top-level tree will not apply to the new subtree.
    """

    _see_also = ['join']
    takes_args = ['tree']

    def run(self, tree):
        containing_tree, subdir = WorkingTree.open_containing(tree)
        sub_id = containing_tree.path2id(subdir)
        if sub_id is None:
            raise errors.NotVersionedError(subdir)
        try:
            containing_tree.extract(sub_id)
        except errors.RootNotRich:
            raise errors.RichRootUpgradeRequired(containing_tree.branch.base)


class cmd_merge_directive(Command):
    """Generate a merge directive for auto-merge tools.

    A directive requests a merge to be performed, and also provides all the
    information necessary to do so.  This means it must either include a
    revision bundle, or the location of a branch containing the desired
    revision.

    A submit branch (the location to merge into) must be supplied the first
    time the command is issued.  After it has been supplied once, it will
    be remembered as the default.

    A public branch is optional if a revision bundle is supplied, but required
    if --diff or --plain is specified.  It will be remembered as the default
    after the first use.
    """

    takes_args = ['submit_branch?', 'public_branch?']

    hidden = True

    _see_also = ['send']

    takes_options = [
        RegistryOption.from_kwargs('patch-type',
            'The type of patch to include in the directive.',
            title='Patch type',
            value_switches=True,
            enum_switch=False,
            bundle='Bazaar revision bundle (default).',
            diff='Normal unified diff.',
            plain='No patch, just directive.'),
        Option('sign', help='GPG-sign the directive.'), 'revision',
        Option('mail-to', type=str,
            help='Instead of printing the directive, email to this address.'),
        Option('message', type=str, short_name='m',
            help='Message to use when committing this merge.')
        ]

    encoding_type = 'exact'

    def run(self, submit_branch=None, public_branch=None, patch_type='bundle',
            sign=False, revision=None, mail_to=None, message=None):
        from bzrlib.revision import ensure_null, NULL_REVISION
        include_patch, include_bundle = {
            'plain': (False, False),
            'diff': (True, False),
            'bundle': (True, True),
            }[patch_type]
        branch = Branch.open('.')
        stored_submit_branch = branch.get_submit_branch()
        if submit_branch is None:
            submit_branch = stored_submit_branch
        else:
            if stored_submit_branch is None:
                branch.set_submit_branch(submit_branch)
        if submit_branch is None:
            submit_branch = branch.get_parent()
        if submit_branch is None:
            raise errors.BzrCommandError('No submit branch specified or known')

        stored_public_branch = branch.get_public_branch()
        if public_branch is None:
            public_branch = stored_public_branch
        elif stored_public_branch is None:
            branch.set_public_branch(public_branch)
        if not include_bundle and public_branch is None:
            raise errors.BzrCommandError('No public branch specified or'
                                         ' known')
        base_revision_id = None
        if revision is not None:
            if len(revision) > 2:
                raise errors.BzrCommandError('bzr merge-directive takes '
                    'at most two one revision identifiers')
            revision_id = revision[-1].as_revision_id(branch)
            if len(revision) == 2:
                base_revision_id = revision[0].as_revision_id(branch)
        else:
            revision_id = branch.last_revision()
        revision_id = ensure_null(revision_id)
        if revision_id == NULL_REVISION:
            raise errors.BzrCommandError('No revisions to bundle.')
        directive = merge_directive.MergeDirective2.from_objects(
            branch.repository, revision_id, time.time(),
            osutils.local_time_offset(), submit_branch,
            public_branch=public_branch, include_patch=include_patch,
            include_bundle=include_bundle, message=message,
            base_revision_id=base_revision_id)
        if mail_to is None:
            if sign:
                self.outf.write(directive.to_signed(branch))
            else:
                self.outf.writelines(directive.to_lines())
        else:
            message = directive.to_email(mail_to, branch, sign)
            s = SMTPConnection(branch.get_config())
            s.send_email(message)


class cmd_send(Command):
    """Mail or create a merge-directive for submitting changes.

    A merge directive provides many things needed for requesting merges:

    * A machine-readable description of the merge to perform

    * An optional patch that is a preview of the changes requested

    * An optional bundle of revision data, so that the changes can be applied
      directly from the merge directive, without retrieving data from a
      branch.

    If --no-bundle is specified, then public_branch is needed (and must be
    up-to-date), so that the receiver can perform the merge using the
    public_branch.  The public_branch is always included if known, so that
    people can check it later.

    The submit branch defaults to the parent, but can be overridden.  Both
    submit branch and public branch will be remembered if supplied.

    If a public_branch is known for the submit_branch, that public submit
    branch is used in the merge instructions.  This means that a local mirror
    can be used as your actual submit branch, once you have set public_branch
    for that mirror.

    Mail is sent using your preferred mail program.  This should be transparent
    on Windows (it uses MAPI).  On Linux, it requires the xdg-email utility.
    If the preferred client can't be found (or used), your editor will be used.

    To use a specific mail program, set the mail_client configuration option.
    (For Thunderbird 1.5, this works around some bugs.)  Supported values for
    specific clients are "claws", "evolution", "kmail", "mutt", and
    "thunderbird"; generic options are "default", "editor", "emacsclient",
    "mapi", and "xdg-email".  Plugins may also add supported clients.

    If mail is being sent, a to address is required.  This can be supplied
    either on the commandline, by setting the submit_to configuration
    option in the branch itself or the child_submit_to configuration option
    in the submit branch.

    Two formats are currently supported: "4" uses revision bundle format 4 and
    merge directive format 2.  It is significantly faster and smaller than
    older formats.  It is compatible with Bazaar 0.19 and later.  It is the
    default.  "0.9" uses revision bundle format 0.9 and merge directive
    format 1.  It is compatible with Bazaar 0.12 - 0.18.

    The merge directives created by bzr send may be applied using bzr merge or
    bzr pull by specifying a file containing a merge directive as the location.
    """

    encoding_type = 'exact'

    _see_also = ['merge', 'pull']

    takes_args = ['submit_branch?', 'public_branch?']

    takes_options = [
        Option('no-bundle',
               help='Do not include a bundle in the merge directive.'),
        Option('no-patch', help='Do not include a preview patch in the merge'
               ' directive.'),
        Option('remember',
               help='Remember submit and public branch.'),
        Option('from',
               help='Branch to generate the submission from, '
               'rather than the one containing the working directory.',
               short_name='f',
               type=unicode),
        Option('output', short_name='o',
               help='Write merge directive to this file; '
                    'use - for stdout.',
               type=unicode),
        Option('strict',
               help='Refuse to send if there are uncommitted changes in'
               ' the working tree, --no-strict disables the check.'),
        Option('mail-to', help='Mail the request to this address.',
               type=unicode),
        'revision',
        'message',
        Option('body', help='Body for the email.', type=unicode),
        RegistryOption('format',
                       help='Use the specified output format.',
                       lazy_registry=('bzrlib.send', 'format_registry')),
        ]

    def run(self, submit_branch=None, public_branch=None, no_bundle=False,
            no_patch=False, revision=None, remember=False, output=None,
            format=None, mail_to=None, message=None, body=None,
            strict=None, **kwargs):
        from bzrlib.send import send
        return send(submit_branch, revision, public_branch, remember,
                    format, no_bundle, no_patch, output,
                    kwargs.get('from', '.'), mail_to, message, body,
                    self.outf,
                    strict=strict)


class cmd_bundle_revisions(cmd_send):
    """Create a merge-directive for submitting changes.

    A merge directive provides many things needed for requesting merges:

    * A machine-readable description of the merge to perform

    * An optional patch that is a preview of the changes requested

    * An optional bundle of revision data, so that the changes can be applied
      directly from the merge directive, without retrieving data from a
      branch.

    If --no-bundle is specified, then public_branch is needed (and must be
    up-to-date), so that the receiver can perform the merge using the
    public_branch.  The public_branch is always included if known, so that
    people can check it later.

    The submit branch defaults to the parent, but can be overridden.  Both
    submit branch and public branch will be remembered if supplied.

    If a public_branch is known for the submit_branch, that public submit
    branch is used in the merge instructions.  This means that a local mirror
    can be used as your actual submit branch, once you have set public_branch
    for that mirror.

    Two formats are currently supported: "4" uses revision bundle format 4 and
    merge directive format 2.  It is significantly faster and smaller than
    older formats.  It is compatible with Bazaar 0.19 and later.  It is the
    default.  "0.9" uses revision bundle format 0.9 and merge directive
    format 1.  It is compatible with Bazaar 0.12 - 0.18.
    """

    takes_options = [
        Option('no-bundle',
               help='Do not include a bundle in the merge directive.'),
        Option('no-patch', help='Do not include a preview patch in the merge'
               ' directive.'),
        Option('remember',
               help='Remember submit and public branch.'),
        Option('from',
               help='Branch to generate the submission from, '
               'rather than the one containing the working directory.',
               short_name='f',
               type=unicode),
        Option('output', short_name='o', help='Write directive to this file.',
               type=unicode),
        Option('strict',
               help='Refuse to bundle revisions if there are uncommitted'
               ' changes in the working tree, --no-strict disables the check.'),
        'revision',
        RegistryOption('format',
                       help='Use the specified output format.',
                       lazy_registry=('bzrlib.send', 'format_registry')),
        ]
    aliases = ['bundle']

    _see_also = ['send', 'merge']

    hidden = True

    def run(self, submit_branch=None, public_branch=None, no_bundle=False,
            no_patch=False, revision=None, remember=False, output=None,
            format=None, strict=None, **kwargs):
        if output is None:
            output = '-'
        from bzrlib.send import send
        return send(submit_branch, revision, public_branch, remember,
                         format, no_bundle, no_patch, output,
                         kwargs.get('from', '.'), None, None, None,
                         self.outf, strict=strict)


class cmd_tag(Command):
    """Create, remove or modify a tag naming a revision.

    Tags give human-meaningful names to revisions.  Commands that take a -r
    (--revision) option can be given -rtag:X, where X is any previously
    created tag.

    Tags are stored in the branch.  Tags are copied from one branch to another
    along when you branch, push, pull or merge.

    It is an error to give a tag name that already exists unless you pass
    --force, in which case the tag is moved to point to the new revision.

    To rename a tag (change the name but keep it on the same revsion), run ``bzr
    tag new-name -r tag:old-name`` and then ``bzr tag --delete oldname``.
    """

    _see_also = ['commit', 'tags']
    takes_args = ['tag_name']
    takes_options = [
        Option('delete',
            help='Delete this tag rather than placing it.',
            ),
        Option('directory',
            help='Branch in which to place the tag.',
            short_name='d',
            type=unicode,
            ),
        Option('force',
            help='Replace existing tags.',
            ),
        'revision',
        ]

    def run(self, tag_name,
            delete=None,
            directory='.',
            force=None,
            revision=None,
            ):
        branch, relpath = Branch.open_containing(directory)
        branch.lock_write()
        try:
            if delete:
                branch.tags.delete_tag(tag_name)
                self.outf.write('Deleted tag %s.\n' % tag_name)
            else:
                if revision:
                    if len(revision) != 1:
                        raise errors.BzrCommandError(
                            "Tags can only be placed on a single revision, "
                            "not on a range")
                    revision_id = revision[0].as_revision_id(branch)
                else:
                    revision_id = branch.last_revision()
                if (not force) and branch.tags.has_tag(tag_name):
                    raise errors.TagAlreadyExists(tag_name)
                branch.tags.set_tag(tag_name, revision_id)
                self.outf.write('Created tag %s.\n' % tag_name)
        finally:
            branch.unlock()


class cmd_tags(Command):
    """List tags.

    This command shows a table of tag names and the revisions they reference.
    """

    _see_also = ['tag']
    takes_options = [
        Option('directory',
            help='Branch whose tags should be displayed.',
            short_name='d',
            type=unicode,
            ),
        RegistryOption.from_kwargs('sort',
            'Sort tags by different criteria.', title='Sorting',
            alpha='Sort tags lexicographically (default).',
            time='Sort tags chronologically.',
            ),
        'show-ids',
        'revision',
    ]

    @display_command
    def run(self,
            directory='.',
            sort='alpha',
            show_ids=False,
            revision=None,
            ):
        branch, relpath = Branch.open_containing(directory)

        tags = branch.tags.get_tag_dict().items()
        if not tags:
            return

        branch.lock_read()
        try:
            if revision:
                graph = branch.repository.get_graph()
                rev1, rev2 = _get_revision_range(revision, branch, self.name())
                revid1, revid2 = rev1.rev_id, rev2.rev_id
                # only show revisions between revid1 and revid2 (inclusive)
                tags = [(tag, revid) for tag, revid in tags if
                    graph.is_between(revid, revid1, revid2)]
            if sort == 'alpha':
                tags.sort()
            elif sort == 'time':
                timestamps = {}
                for tag, revid in tags:
                    try:
                        revobj = branch.repository.get_revision(revid)
                    except errors.NoSuchRevision:
                        timestamp = sys.maxint # place them at the end
                    else:
                        timestamp = revobj.timestamp
                    timestamps[revid] = timestamp
                tags.sort(key=lambda x: timestamps[x[1]])
            if not show_ids:
                # [ (tag, revid), ... ] -> [ (tag, dotted_revno), ... ]
                for index, (tag, revid) in enumerate(tags):
                    try:
                        revno = branch.revision_id_to_dotted_revno(revid)
                        if isinstance(revno, tuple):
                            revno = '.'.join(map(str, revno))
                    except errors.NoSuchRevision:
                        # Bad tag data/merges can lead to tagged revisions
                        # which are not in this branch. Fail gracefully ...
                        revno = '?'
                    tags[index] = (tag, revno)
        finally:
            branch.unlock()
        for tag, revspec in tags:
            self.outf.write('%-20s %s\n' % (tag, revspec))


class cmd_reconfigure(Command):
    """Reconfigure the type of a bzr directory.

    A target configuration must be specified.

    For checkouts, the bind-to location will be auto-detected if not specified.
    The order of preference is
    1. For a lightweight checkout, the current bound location.
    2. For branches that used to be checkouts, the previously-bound location.
    3. The push location.
    4. The parent location.
    If none of these is available, --bind-to must be specified.
    """

    _see_also = ['branches', 'checkouts', 'standalone-trees', 'working-trees']
    takes_args = ['location?']
    takes_options = [
        RegistryOption.from_kwargs(
            'target_type',
            title='Target type',
            help='The type to reconfigure the directory to.',
            value_switches=True, enum_switch=False,
            branch='Reconfigure to be an unbound branch with no working tree.',
            tree='Reconfigure to be an unbound branch with a working tree.',
            checkout='Reconfigure to be a bound branch with a working tree.',
            lightweight_checkout='Reconfigure to be a lightweight'
                ' checkout (with no local history).',
            standalone='Reconfigure to be a standalone branch '
                '(i.e. stop using shared repository).',
            use_shared='Reconfigure to use a shared repository.',
            with_trees='Reconfigure repository to create '
                'working trees on branches by default.',
            with_no_trees='Reconfigure repository to not create '
                'working trees on branches by default.'
            ),
        Option('bind-to', help='Branch to bind checkout to.', type=str),
        Option('force',
            help='Perform reconfiguration even if local changes'
            ' will be lost.'),
        Option('stacked-on',
            help='Reconfigure a branch to be stacked on another branch.',
            type=unicode,
            ),
        Option('unstacked',
            help='Reconfigure a branch to be unstacked.  This '
                'may require copying substantial data into it.',
            ),
        ]

    def run(self, location=None, target_type=None, bind_to=None, force=False,
            stacked_on=None,
            unstacked=None):
        directory = bzrdir.BzrDir.open(location)
        if stacked_on and unstacked:
            raise BzrCommandError("Can't use both --stacked-on and --unstacked")
        elif stacked_on is not None:
            reconfigure.ReconfigureStackedOn().apply(directory, stacked_on)
        elif unstacked:
            reconfigure.ReconfigureUnstacked().apply(directory)
        # At the moment you can use --stacked-on and a different
        # reconfiguration shape at the same time; there seems no good reason
        # to ban it.
        if target_type is None:
            if stacked_on or unstacked:
                return
            else:
                raise errors.BzrCommandError('No target configuration '
                    'specified')
        elif target_type == 'branch':
            reconfiguration = reconfigure.Reconfigure.to_branch(directory)
        elif target_type == 'tree':
            reconfiguration = reconfigure.Reconfigure.to_tree(directory)
        elif target_type == 'checkout':
            reconfiguration = reconfigure.Reconfigure.to_checkout(
                directory, bind_to)
        elif target_type == 'lightweight-checkout':
            reconfiguration = reconfigure.Reconfigure.to_lightweight_checkout(
                directory, bind_to)
        elif target_type == 'use-shared':
            reconfiguration = reconfigure.Reconfigure.to_use_shared(directory)
        elif target_type == 'standalone':
            reconfiguration = reconfigure.Reconfigure.to_standalone(directory)
        elif target_type == 'with-trees':
            reconfiguration = reconfigure.Reconfigure.set_repository_trees(
                directory, True)
        elif target_type == 'with-no-trees':
            reconfiguration = reconfigure.Reconfigure.set_repository_trees(
                directory, False)
        reconfiguration.apply(force)


class cmd_switch(Command):
    """Set the branch of a checkout and update.

    For lightweight checkouts, this changes the branch being referenced.
    For heavyweight checkouts, this checks that there are no local commits
    versus the current bound branch, then it makes the local branch a mirror
    of the new location and binds to it.

    In both cases, the working tree is updated and uncommitted changes
    are merged. The user can commit or revert these as they desire.

    Pending merges need to be committed or reverted before using switch.

    The path to the branch to switch to can be specified relative to the parent
    directory of the current branch. For example, if you are currently in a
    checkout of /path/to/branch, specifying 'newbranch' will find a branch at
    /path/to/newbranch.

    Bound branches use the nickname of its master branch unless it is set
    locally, in which case switching will update the the local nickname to be
    that of the master.
    """

    takes_args = ['to_location']
    takes_options = [Option('force',
                        help='Switch even if local commits will be lost.'),
                     Option('create-branch', short_name='b',
                        help='Create the target branch from this one before'
                             ' switching to it.'),
                     ]

    def run(self, to_location, force=False, create_branch=False):
        from bzrlib import switch
        tree_location = '.'
        control_dir = bzrdir.BzrDir.open_containing(tree_location)[0]
        try:
            branch = control_dir.open_branch()
            had_explicit_nick = branch.get_config().has_explicit_nickname()
        except errors.NotBranchError:
            branch = None
            had_explicit_nick = False
        if create_branch:
            if branch is None:
                raise errors.BzrCommandError('cannot create branch without'
                                             ' source branch')
            if '/' not in to_location and '\\' not in to_location:
                # This path is meant to be relative to the existing branch
                this_url = self._get_branch_location(control_dir)
                to_location = urlutils.join(this_url, '..', to_location)
            to_branch = branch.bzrdir.sprout(to_location,
                                 possible_transports=[branch.bzrdir.root_transport],
                                 source_branch=branch).open_branch()
            # try:
            #     from_branch = control_dir.open_branch()
            # except errors.NotBranchError:
            #     raise BzrCommandError('Cannot create a branch from this'
            #         ' location when we cannot open this branch')
            # from_branch.bzrdir.sprout(
            pass
        else:
            try:
                to_branch = Branch.open(to_location)
            except errors.NotBranchError:
                this_url = self._get_branch_location(control_dir)
                to_branch = Branch.open(
                    urlutils.join(this_url, '..', to_location))
        switch.switch(control_dir, to_branch, force)
        if had_explicit_nick:
            branch = control_dir.open_branch() #get the new branch!
            branch.nick = to_branch.nick
        note('Switched to branch: %s',
            urlutils.unescape_for_display(to_branch.base, 'utf-8'))

    def _get_branch_location(self, control_dir):
        """Return location of branch for this control dir."""
        try:
            this_branch = control_dir.open_branch()
            # This may be a heavy checkout, where we want the master branch
            master_location = this_branch.get_bound_location()
            if master_location is not None:
                return master_location
            # If not, use a local sibling
            return this_branch.base
        except errors.NotBranchError:
            format = control_dir.find_branch_format()
            if getattr(format, 'get_reference', None) is not None:
                return format.get_reference(control_dir)
            else:
                return control_dir.root_transport.base


class cmd_view(Command):
    """Manage filtered views.

    Views provide a mask over the tree so that users can focus on
    a subset of a tree when doing their work. After creating a view,
    commands that support a list of files - status, diff, commit, etc -
    effectively have that list of files implicitly given each time.
    An explicit list of files can still be given but those files
    must be within the current view.

    In most cases, a view has a short life-span: it is created to make
    a selected change and is deleted once that change is committed.
    At other times, you may wish to create one or more named views
    and switch between them.

    To disable the current view without deleting it, you can switch to
    the pseudo view called ``off``. This can be useful when you need
    to see the whole tree for an operation or two (e.g. merge) but
    want to switch back to your view after that.

    :Examples:
      To define the current view::

        bzr view file1 dir1 ...

      To list the current view::

        bzr view

      To delete the current view::

        bzr view --delete

      To disable the current view without deleting it::

        bzr view --switch off

      To define a named view and switch to it::

        bzr view --name view-name file1 dir1 ...

      To list a named view::

        bzr view --name view-name

      To delete a named view::

        bzr view --name view-name --delete

      To switch to a named view::

        bzr view --switch view-name

      To list all views defined::

        bzr view --all

      To delete all views::

        bzr view --delete --all
    """

    _see_also = []
    takes_args = ['file*']
    takes_options = [
        Option('all',
            help='Apply list or delete action to all views.',
            ),
        Option('delete',
            help='Delete the view.',
            ),
        Option('name',
            help='Name of the view to define, list or delete.',
            type=unicode,
            ),
        Option('switch',
            help='Name of the view to switch to.',
            type=unicode,
            ),
        ]

    def run(self, file_list,
            all=False,
            delete=False,
            name=None,
            switch=None,
            ):
        tree, file_list = tree_files(file_list, apply_view=False)
        current_view, view_dict = tree.views.get_view_info()
        if name is None:
            name = current_view
        if delete:
            if file_list:
                raise errors.BzrCommandError(
                    "Both --delete and a file list specified")
            elif switch:
                raise errors.BzrCommandError(
                    "Both --delete and --switch specified")
            elif all:
                tree.views.set_view_info(None, {})
                self.outf.write("Deleted all views.\n")
            elif name is None:
                raise errors.BzrCommandError("No current view to delete")
            else:
                tree.views.delete_view(name)
                self.outf.write("Deleted '%s' view.\n" % name)
        elif switch:
            if file_list:
                raise errors.BzrCommandError(
                    "Both --switch and a file list specified")
            elif all:
                raise errors.BzrCommandError(
                    "Both --switch and --all specified")
            elif switch == 'off':
                if current_view is None:
                    raise errors.BzrCommandError("No current view to disable")
                tree.views.set_view_info(None, view_dict)
                self.outf.write("Disabled '%s' view.\n" % (current_view))
            else:
                tree.views.set_view_info(switch, view_dict)
                view_str = views.view_display_str(tree.views.lookup_view())
                self.outf.write("Using '%s' view: %s\n" % (switch, view_str))
        elif all:
            if view_dict:
                self.outf.write('Views defined:\n')
                for view in sorted(view_dict):
                    if view == current_view:
                        active = "=>"
                    else:
                        active = "  "
                    view_str = views.view_display_str(view_dict[view])
                    self.outf.write('%s %-20s %s\n' % (active, view, view_str))
            else:
                self.outf.write('No views defined.\n')
        elif file_list:
            if name is None:
                # No name given and no current view set
                name = 'my'
            elif name == 'off':
                raise errors.BzrCommandError(
                    "Cannot change the 'off' pseudo view")
            tree.views.set_view(name, sorted(file_list))
            view_str = views.view_display_str(tree.views.lookup_view())
            self.outf.write("Using '%s' view: %s\n" % (name, view_str))
        else:
            # list the files
            if name is None:
                # No name given and no current view set
                self.outf.write('No current view.\n')
            else:
                view_str = views.view_display_str(tree.views.lookup_view(name))
                self.outf.write("'%s' view is: %s\n" % (name, view_str))


class cmd_hooks(Command):
    """Show hooks."""

    hidden = True

    def run(self):
        for hook_key in sorted(hooks.known_hooks.keys()):
            some_hooks = hooks.known_hooks_key_to_object(hook_key)
            self.outf.write("%s:\n" % type(some_hooks).__name__)
            for hook_name, hook_point in sorted(some_hooks.items()):
                self.outf.write("  %s:\n" % (hook_name,))
                found_hooks = list(hook_point)
                if found_hooks:
                    for hook in found_hooks:
                        self.outf.write("    %s\n" %
                                        (some_hooks.get_hook_name(hook),))
                else:
                    self.outf.write("    <no hooks installed>\n")


class cmd_shelve(Command):
    """Temporarily set aside some changes from the current tree.

    Shelve allows you to temporarily put changes you've made "on the shelf",
    ie. out of the way, until a later time when you can bring them back from
    the shelf with the 'unshelve' command.  The changes are stored alongside
    your working tree, and so they aren't propagated along with your branch nor
    will they survive its deletion.

    If shelve --list is specified, previously-shelved changes are listed.

    Shelve is intended to help separate several sets of changes that have
    been inappropriately mingled.  If you just want to get rid of all changes
    and you don't need to restore them later, use revert.  If you want to
    shelve all text changes at once, use shelve --all.

    If filenames are specified, only the changes to those files will be
    shelved. Other files will be left untouched.

    If a revision is specified, changes since that revision will be shelved.

    You can put multiple items on the shelf, and by default, 'unshelve' will
    restore the most recently shelved changes.
    """

    takes_args = ['file*']

    takes_options = [
        'revision',
        Option('all', help='Shelve all changes.'),
        'message',
        RegistryOption('writer', 'Method to use for writing diffs.',
                       bzrlib.option.diff_writer_registry,
                       value_switches=True, enum_switch=False),

        Option('list', help='List shelved changes.'),
        Option('destroy',
               help='Destroy removed changes instead of shelving them.'),
    ]
    _see_also = ['unshelve']

    def run(self, revision=None, all=False, file_list=None, message=None,
            writer=None, list=False, destroy=False):
        if list:
            return self.run_for_list()
        from bzrlib.shelf_ui import Shelver
        if writer is None:
            writer = bzrlib.option.diff_writer_registry.get()
        try:
            shelver = Shelver.from_args(writer(sys.stdout), revision, all,
                file_list, message, destroy=destroy)
            try:
                shelver.run()
            finally:
                shelver.work_tree.unlock()
        except errors.UserAbort:
            return 0

    def run_for_list(self):
        tree = WorkingTree.open_containing('.')[0]
        tree.lock_read()
        try:
            manager = tree.get_shelf_manager()
            shelves = manager.active_shelves()
            if len(shelves) == 0:
                note('No shelved changes.')
                return 0
            for shelf_id in reversed(shelves):
                message = manager.get_metadata(shelf_id).get('message')
                if message is None:
                    message = '<no message>'
                self.outf.write('%3d: %s\n' % (shelf_id, message))
            return 1
        finally:
            tree.unlock()


class cmd_unshelve(Command):
    """Restore shelved changes.

    By default, the most recently shelved changes are restored. However if you
    specify a shelf by id those changes will be restored instead.  This works
    best when the changes don't depend on each other.
    """

    takes_args = ['shelf_id?']
    takes_options = [
        RegistryOption.from_kwargs(
            'action', help="The action to perform.",
            enum_switch=False, value_switches=True,
            apply="Apply changes and remove from the shelf.",
            dry_run="Show changes, but do not apply or remove them.",
            delete_only="Delete changes without applying them."
        )
    ]
    _see_also = ['shelve']

    def run(self, shelf_id=None, action='apply'):
        from bzrlib.shelf_ui import Unshelver
        unshelver = Unshelver.from_args(shelf_id, action)
        try:
            unshelver.run()
        finally:
            unshelver.tree.unlock()


class cmd_clean_tree(Command):
    """Remove unwanted files from working tree.

    By default, only unknown files, not ignored files, are deleted.  Versioned
    files are never deleted.

    Another class is 'detritus', which includes files emitted by bzr during
    normal operations and selftests.  (The value of these files decreases with
    time.)

    If no options are specified, unknown files are deleted.  Otherwise, option
    flags are respected, and may be combined.

    To check what clean-tree will do, use --dry-run.
    """
    takes_options = [Option('ignored', help='Delete all ignored files.'),
                     Option('detritus', help='Delete conflict files, merge'
                            ' backups, and failed selftest dirs.'),
                     Option('unknown',
                            help='Delete files unknown to bzr (default).'),
                     Option('dry-run', help='Show files to delete instead of'
                            ' deleting them.'),
                     Option('force', help='Do not prompt before deleting.')]
    def run(self, unknown=False, ignored=False, detritus=False, dry_run=False,
            force=False):
        from bzrlib.clean_tree import clean_tree
        if not (unknown or ignored or detritus):
            unknown = True
        if dry_run:
            force = True
        clean_tree('.', unknown=unknown, ignored=ignored, detritus=detritus,
                   dry_run=dry_run, no_prompt=force)


class cmd_reference(Command):
    """list, view and set branch locations for nested trees.

    If no arguments are provided, lists the branch locations for nested trees.
    If one argument is provided, display the branch location for that tree.
    If two arguments are provided, set the branch location for that tree.
    """

    hidden = True

    takes_args = ['path?', 'location?']

    def run(self, path=None, location=None):
        branchdir = '.'
        if path is not None:
            branchdir = path
        tree, branch, relpath =(
            bzrdir.BzrDir.open_containing_tree_or_branch(branchdir))
        if path is not None:
            path = relpath
        if tree is None:
            tree = branch.basis_tree()
        if path is None:
            info = branch._get_all_reference_info().iteritems()
            self._display_reference_info(tree, branch, info)
        else:
            file_id = tree.path2id(path)
            if file_id is None:
                raise errors.NotVersionedError(path)
            if location is None:
                info = [(file_id, branch.get_reference_info(file_id))]
                self._display_reference_info(tree, branch, info)
            else:
                branch.set_reference_info(file_id, path, location)

    def _display_reference_info(self, tree, branch, info):
        ref_list = []
        for file_id, (path, location) in info:
            try:
                path = tree.id2path(file_id)
            except errors.NoSuchId:
                pass
            ref_list.append((path, location))
        for path, location in sorted(ref_list):
            self.outf.write('%s %s\n' % (path, location))


# these get imported and then picked up by the scan for cmd_*
# TODO: Some more consistent way to split command definitions across files;
# we do need to load at least some information about them to know of
# aliases.  ideally we would avoid loading the implementation until the
# details were needed.
from bzrlib.cmd_version_info import cmd_version_info
from bzrlib.conflicts import cmd_resolve, cmd_conflicts, restore
from bzrlib.bundle.commands import (
    cmd_bundle_info,
    )
from bzrlib.foreign import cmd_dpush
from bzrlib.sign_my_commits import cmd_sign_my_commits
from bzrlib.weave_commands import cmd_versionedfile_list, \
        cmd_weave_plan_merge, cmd_weave_merge_text
