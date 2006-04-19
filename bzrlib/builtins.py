# Copyright (C) 2004, 2005, 2006 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""builtin bzr commands"""


import errno
import os
from shutil import rmtree
import sys

import bzrlib
import bzrlib.branch
from bzrlib.branch import Branch
import bzrlib.bzrdir as bzrdir
from bzrlib.commands import Command, display_command
from bzrlib.revision import common_ancestor
import bzrlib.errors as errors
from bzrlib.errors import (BzrError, BzrCheckError, BzrCommandError, 
                           NotBranchError, DivergedBranches, NotConflicted,
                           NoSuchFile, NoWorkingTree, FileInWrongBranch,
                           NotVersionedError)
from bzrlib.log import show_one_log
from bzrlib.merge import Merge3Merger
from bzrlib.option import Option
from bzrlib.progress import DummyProgress, ProgressPhase
from bzrlib.revisionspec import RevisionSpec
import bzrlib.trace
from bzrlib.trace import mutter, note, log_error, warning, is_quiet
from bzrlib.transport.local import LocalTransport
import bzrlib.ui
from bzrlib.workingtree import WorkingTree


def tree_files(file_list, default_branch=u'.'):
    try:
        return internal_tree_files(file_list, default_branch)
    except FileInWrongBranch, e:
        raise BzrCommandError("%s is not in the same branch as %s" %
                             (e.path, file_list[0]))


# XXX: Bad function name; should possibly also be a class method of
# WorkingTree rather than a function.
def internal_tree_files(file_list, default_branch=u'.'):
    """Convert command-line paths to a WorkingTree and relative paths.

    This is typically used for command-line processors that take one or
    more filenames, and infer the workingtree that contains them.

    The filenames given are not required to exist.

    :param file_list: Filenames to convert.  

    :param default_branch: Fallback tree path to use if file_list is empty or None.

    :return: workingtree, [relative_paths]
    """
    if file_list is None or len(file_list) == 0:
        return WorkingTree.open_containing(default_branch)[0], file_list
    tree = WorkingTree.open_containing(file_list[0])[0]
    new_list = []
    for filename in file_list:
        try:
            new_list.append(tree.relpath(filename))
        except errors.PathNotChild:
            raise FileInWrongBranch(tree.branch, filename)
    return tree, new_list


def get_format_type(typestring):
    """Parse and return a format specifier."""
    if typestring == "weave":
        return bzrdir.BzrDirFormat6()
    if typestring == "metadir":
        return bzrdir.BzrDirMetaFormat1()
    if typestring == "knit":
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = bzrlib.repository.RepositoryFormatKnit1()
        return format
    msg = "No known bzr-dir format %s. Supported types are: weave, metadir\n" %\
        (typestring)
    raise BzrCommandError(msg)


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

    unchanged
        Nothing about this file has changed since the previous revision.
        Only shown with --all.

    unknown
        Not versioned and not matching an ignore pattern.

    To see ignored files use 'bzr ignored'.  For details in the
    changes to file texts, use 'bzr diff'.

    If no arguments are specified, the status of the entire working
    directory is shown.  Otherwise, only the status of the specified
    files or directories is reported.  If a directory is given, status
    is reported for everything inside that directory.

    If a revision argument is given, the status is calculated against
    that revision, or between two revisions if two are provided.
    """
    
    # TODO: --no-recurse, --recurse options
    
    takes_args = ['file*']
    takes_options = ['all', 'show-ids', 'revision']
    aliases = ['st', 'stat']
    
    @display_command
    def run(self, all=False, show_ids=False, file_list=None, revision=None):
        tree, file_list = tree_files(file_list)
            
        from bzrlib.status import show_tree_status
        show_tree_status(tree, show_unchanged=all, show_ids=show_ids,
                         specific_files=file_list, revision=revision)


class cmd_cat_revision(Command):
    """Write out metadata for a revision.
    
    The revision to print can either be specified by a specific
    revision identifier, or you can use --revision.
    """

    hidden = True
    takes_args = ['revision_id?']
    takes_options = ['revision']
    
    @display_command
    def run(self, revision_id=None, revision=None):

        if revision_id is not None and revision is not None:
            raise BzrCommandError('You can only supply one of revision_id or --revision')
        if revision_id is None and revision is None:
            raise BzrCommandError('You must supply either --revision or a revision_id')
        b = WorkingTree.open_containing(u'.')[0].branch
        if revision_id is not None:
            sys.stdout.write(b.repository.get_revision_xml(revision_id))
        elif revision is not None:
            for rev in revision:
                if rev is None:
                    raise BzrCommandError('You cannot specify a NULL revision.')
                revno, rev_id = rev.in_history(b)
                sys.stdout.write(b.repository.get_revision_xml(rev_id))
    

class cmd_revno(Command):
    """Show current revision number.

    This is equal to the number of revisions on this branch."""
    takes_args = ['location?']
    @display_command
    def run(self, location=u'.'):
        print Branch.open_containing(location)[0].revno()


class cmd_revision_info(Command):
    """Show revision number and revision id for a given revision identifier.
    """
    hidden = True
    takes_args = ['revision_info*']
    takes_options = ['revision']
    @display_command
    def run(self, revision=None, revision_info_list=[]):

        revs = []
        if revision is not None:
            revs.extend(revision)
        if revision_info_list is not None:
            for rev in revision_info_list:
                revs.append(RevisionSpec(rev))
        if len(revs) == 0:
            raise BzrCommandError('You must supply a revision identifier')

        b = WorkingTree.open_containing(u'.')[0].branch

        for rev in revs:
            revinfo = rev.in_history(b)
            if revinfo.revno is None:
                print '     %s' % revinfo.rev_id
            else:
                print '%4d %s' % (revinfo.revno, revinfo.rev_id)

    
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
    you should never need to explictly add a directory, they'll just
    get added when you add a file in the directory.

    --dry-run will show which files would be added, but not actually 
    add them.
    """
    takes_args = ['file*']
    takes_options = ['no-recurse', 'dry-run', 'verbose']

    def run(self, file_list, no_recurse=False, dry_run=False, verbose=False):
        import bzrlib.add

        if dry_run:
            if is_quiet():
                # This is pointless, but I'd rather not raise an error
                action = bzrlib.add.add_action_null
            else:
                action = bzrlib.add.add_action_print
        elif is_quiet():
            action = bzrlib.add.add_action_add
        else:
            action = bzrlib.add.add_action_add_and_print

        added, ignored = bzrlib.add.smart_add(file_list, not no_recurse, 
                                              action)
        if len(ignored) > 0:
            for glob in sorted(ignored.keys()):
                match_len = len(ignored[glob])
                if verbose:
                    for path in ignored[glob]:
                        print "ignored %s matching \"%s\"" % (path, glob)
                else:
                    print "ignored %d file(s) matching \"%s\"" % (match_len,
                                                              glob)
            print "If you wish to add some of these files, please add them"\
                " by name."


class cmd_mkdir(Command):
    """Create a new versioned directory.

    This is equivalent to creating the directory and then adding it.
    """
    takes_args = ['dir+']

    def run(self, dir_list):
        for d in dir_list:
            os.mkdir(d)
            wt, dd = WorkingTree.open_containing(d)
            wt.add([dd])
            print 'added', d


class cmd_relpath(Command):
    """Show path of a file relative to root"""
    takes_args = ['filename']
    hidden = True
    
    @display_command
    def run(self, filename):
        tree, relpath = WorkingTree.open_containing(filename)
        print relpath


class cmd_inventory(Command):
    """Show inventory of the current working copy or a revision.

    It is possible to limit the output to a particular entry
    type using the --kind option.  For example; --kind file.
    """
    takes_options = ['revision', 'show-ids', 'kind']
    
    @display_command
    def run(self, revision=None, show_ids=False, kind=None):
        if kind and kind not in ['file', 'directory', 'symlink']:
            raise BzrCommandError('invalid kind specified')
        tree = WorkingTree.open_containing(u'.')[0]
        if revision is None:
            inv = tree.read_working_inventory()
        else:
            if len(revision) > 1:
                raise BzrCommandError('bzr inventory --revision takes'
                    ' exactly one revision identifier')
            inv = tree.branch.repository.get_revision_inventory(
                revision[0].in_history(tree.branch).rev_id)

        for path, entry in inv.entries():
            if kind and kind != entry.kind:
                continue
            if show_ids:
                print '%-50s %s' % (path, entry.file_id)
            else:
                print path


class cmd_mv(Command):
    """Move or rename a file.

    usage:
        bzr mv OLDNAME NEWNAME
        bzr mv SOURCE... DESTINATION

    If the last argument is a versioned directory, all the other names
    are moved into it.  Otherwise, there must be exactly two arguments
    and the file is changed to a new name, which must not already exist.

    Files cannot be moved between branches.
    """
    takes_args = ['names*']
    aliases = ['move', 'rename']

    def run(self, names_list):
        if len(names_list) < 2:
            raise BzrCommandError("missing file argument")
        tree, rel_names = tree_files(names_list)
        
        if os.path.isdir(names_list[-1]):
            # move into existing directory
            for pair in tree.move(rel_names[:-1], rel_names[-1]):
                print "%s => %s" % pair
        else:
            if len(names_list) != 2:
                raise BzrCommandError('to mv multiple files the destination '
                                      'must be a versioned directory')
            tree.rename_one(rel_names[0], rel_names[1])
            print "%s => %s" % (rel_names[0], rel_names[1])
            
    
class cmd_pull(Command):
    """Turn this branch into a mirror of another branch.

    This command only works on branches that have not diverged.  Branches are
    considered diverged if the destination branch's most recent commit is one
    that has not been merged (directly or indirectly) into the parent.

    If branches have diverged, you can use 'bzr merge' to integrate the changes
    from one into the other.  Once one branch has merged, the other should
    be able to pull it again.

    If branches have diverged, you can use 'bzr merge' to pull the text changes
    from one into the other.  Once one branch has merged, the other should
    be able to pull it again.

    If you want to forget your local changes and just update your branch to
    match the remote one, use pull --overwrite.

    If there is no default location set, the first pull will set it.  After
    that, you can omit the location to use the default.  To change the
    default, use --remember.
    """
    takes_options = ['remember', 'overwrite', 'revision', 'verbose']
    takes_args = ['location?']

    def run(self, location=None, remember=False, overwrite=False, revision=None, verbose=False):
        # FIXME: too much stuff is in the command class
        try:
            tree_to = WorkingTree.open_containing(u'.')[0]
            branch_to = tree_to.branch
        except NoWorkingTree:
            tree_to = None
            branch_to = Branch.open_containing(u'.')[0] 
        stored_loc = branch_to.get_parent()
        if location is None:
            if stored_loc is None:
                raise BzrCommandError("No pull location known or specified.")
            else:
                print "Using saved location: %s" % stored_loc
                location = stored_loc

        if branch_to.get_parent() is None or remember:
            branch_to.set_parent(location)

        branch_from = Branch.open(location)

        if revision is None:
            rev_id = None
        elif len(revision) == 1:
            rev_id = revision[0].in_history(branch_from).rev_id
        else:
            raise BzrCommandError('bzr pull --revision takes one value.')

        old_rh = branch_to.revision_history()
        if tree_to is not None:
            count = tree_to.pull(branch_from, overwrite, rev_id)
        else:
            count = branch_to.pull(branch_from, overwrite, rev_id)
        note('%d revision(s) pulled.' % (count,))

        if verbose:
            new_rh = branch_to.revision_history()
            if old_rh != new_rh:
                # Something changed
                from bzrlib.log import show_changed_revisions
                show_changed_revisions(branch_to, old_rh, new_rh)


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
    default, use --remember.
    """
    takes_options = ['remember', 'overwrite', 
                     Option('create-prefix', 
                            help='Create the path leading up to the branch '
                                 'if it does not already exist')]
    takes_args = ['location?']

    def run(self, location=None, remember=False, overwrite=False,
            create_prefix=False, verbose=False):
        # FIXME: Way too big!  Put this into a function called from the
        # command.
        from bzrlib.transport import get_transport
        
        tree_from = WorkingTree.open_containing(u'.')[0]
        br_from = tree_from.branch
        stored_loc = tree_from.branch.get_push_location()
        if location is None:
            if stored_loc is None:
                raise BzrCommandError("No push location known or specified.")
            else:
                print "Using saved location: %s" % stored_loc
                location = stored_loc
        if br_from.get_push_location() is None or remember:
            br_from.set_push_location(location)
        try:
            dir_to = bzrlib.bzrdir.BzrDir.open(location)
            br_to = dir_to.open_branch()
        except NotBranchError:
            # create a branch.
            transport = get_transport(location).clone('..')
            if not create_prefix:
                try:
                    transport.mkdir(transport.relpath(location))
                except NoSuchFile:
                    raise BzrCommandError("Parent directory of %s "
                                          "does not exist." % location)
            else:
                current = transport.base
                needed = [(transport, transport.relpath(location))]
                while needed:
                    try:
                        transport, relpath = needed[-1]
                        transport.mkdir(relpath)
                        needed.pop()
                    except NoSuchFile:
                        new_transport = transport.clone('..')
                        needed.append((new_transport,
                                       new_transport.relpath(transport.base)))
                        if new_transport.base == transport.base:
                            raise BzrCommandError("Could not create "
                                                  "path prefix.")
            dir_to = br_from.bzrdir.clone(location)
            br_to = dir_to.open_branch()
        old_rh = br_to.revision_history()
        try:
            try:
                tree_to = dir_to.open_workingtree()
            except errors.NotLocalUrl:
                # TODO: This should be updated for branches which don't have a
                # working tree, as opposed to ones where we just couldn't 
                # update the tree.
                warning('This transport does not update the working '
                        'tree of: %s' % (br_to.base,))
                count = br_to.pull(br_from, overwrite)
            except NoWorkingTree:
                count = br_to.pull(br_from, overwrite)
            else:
                count = tree_to.pull(br_from, overwrite)
        except DivergedBranches:
            raise BzrCommandError("These branches have diverged."
                                  "  Try a merge then push with overwrite.")
        note('%d revision(s) pushed.' % (count,))

        if verbose:
            new_rh = br_to.revision_history()
            if old_rh != new_rh:
                # Something changed
                from bzrlib.log import show_changed_revisions
                show_changed_revisions(br_to, old_rh, new_rh)


class cmd_branch(Command):
    """Create a new copy of a branch.

    If the TO_LOCATION is omitted, the last component of the FROM_LOCATION will
    be used.  In other words, "branch ../foo/bar" will attempt to create ./bar.

    To retrieve the branch as of a particular revision, supply the --revision
    parameter, as in "branch foo/bar -r 5".

    --basis is to speed up branching from remote branches.  When specified, it
    copies all the file-contents, inventory and revision data from the basis
    branch before copying anything from the remote branch.
    """
    takes_args = ['from_location', 'to_location?']
    takes_options = ['revision', 'basis']
    aliases = ['get', 'clone']

    def run(self, from_location, to_location=None, revision=None, basis=None):
        if revision is None:
            revision = [None]
        elif len(revision) > 1:
            raise BzrCommandError(
                'bzr branch --revision takes exactly 1 revision value')
        try:
            br_from = Branch.open(from_location)
        except OSError, e:
            if e.errno == errno.ENOENT:
                raise BzrCommandError('Source location "%s" does not'
                                      ' exist.' % to_location)
            else:
                raise
        br_from.lock_read()
        try:
            if basis is not None:
                basis_dir = bzrdir.BzrDir.open_containing(basis)[0]
            else:
                basis_dir = None
            if len(revision) == 1 and revision[0] is not None:
                revision_id = revision[0].in_history(br_from)[1]
            else:
                # FIXME - wt.last_revision, fallback to branch, fall back to
                # None or perhaps NULL_REVISION to mean copy nothing
                # RBC 20060209
                revision_id = br_from.last_revision()
            if to_location is None:
                to_location = os.path.basename(from_location.rstrip("/\\"))
                name = None
            else:
                name = os.path.basename(to_location) + '\n'
            try:
                os.mkdir(to_location)
            except OSError, e:
                if e.errno == errno.EEXIST:
                    raise BzrCommandError('Target directory "%s" already'
                                          ' exists.' % to_location)
                if e.errno == errno.ENOENT:
                    raise BzrCommandError('Parent of "%s" does not exist.' %
                                          to_location)
                else:
                    raise
            try:
                # preserve whatever source format we have.
                dir = br_from.bzrdir.sprout(to_location, revision_id, basis_dir)
                branch = dir.open_branch()
            except bzrlib.errors.NoSuchRevision:
                rmtree(to_location)
                msg = "The branch %s has no revision %s." % (from_location, revision[0])
                raise BzrCommandError(msg)
            except bzrlib.errors.UnlistableBranch:
                rmtree(to_location)
                msg = "The branch %s cannot be used as a --basis" % (basis,)
                raise BzrCommandError(msg)
            if name:
                branch.control_files.put_utf8('branch-name', name)

            note('Branched %d revision(s).' % branch.revno())
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

    To retrieve the branch as of a particular revision, supply the --revision
    parameter, as in "checkout foo/bar -r 5". Note that this will be immediately
    out of date [so you cannot commit] but it may be useful (i.e. to examine old
    code.)

    --basis is to speed up checking out from remote branches.  When specified, it
    uses the inventory and file contents from the basis branch in preference to the
    branch being checked out. [Not implemented yet.]
    """
    takes_args = ['branch_location?', 'to_location?']
    takes_options = ['revision', # , 'basis']
                     Option('lightweight',
                            help="perform a lightweight checkout. Lightweight "
                                 "checkouts depend on access to the branch for "
                                 "every operation. Normal checkouts can perform "
                                 "common operations like diff and status without "
                                 "such access, and also support local commits."
                            ),
                     ]

    def run(self, branch_location=None, to_location=None, revision=None, basis=None,
            lightweight=False):
        if revision is None:
            revision = [None]
        elif len(revision) > 1:
            raise BzrCommandError(
                'bzr checkout --revision takes exactly 1 revision value')
        if branch_location is None:
            branch_location = bzrlib.osutils.getcwd()
            to_location = branch_location
        source = Branch.open(branch_location)
        if len(revision) == 1 and revision[0] is not None:
            revision_id = revision[0].in_history(source)[1]
        else:
            revision_id = None
        if to_location is None:
            to_location = os.path.basename(branch_location.rstrip("/\\"))
        # if the source and to_location are the same, 
        # and there is no working tree,
        # then reconstitute a branch
        if (bzrlib.osutils.abspath(to_location) == 
            bzrlib.osutils.abspath(branch_location)):
            try:
                source.bzrdir.open_workingtree()
            except errors.NoWorkingTree:
                source.bzrdir.create_workingtree()
                return
        try:
            os.mkdir(to_location)
        except OSError, e:
            if e.errno == errno.EEXIST:
                raise BzrCommandError('Target directory "%s" already'
                                      ' exists.' % to_location)
            if e.errno == errno.ENOENT:
                raise BzrCommandError('Parent of "%s" does not exist.' %
                                      to_location)
            else:
                raise
        old_format = bzrlib.bzrdir.BzrDirFormat.get_default_format()
        bzrlib.bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            if lightweight:
                checkout = bzrdir.BzrDirMetaFormat1().initialize(to_location)
                bzrlib.branch.BranchReferenceFormat().initialize(checkout, source)
            else:
                checkout_branch =  bzrlib.bzrdir.BzrDir.create_branch_convenience(
                    to_location, force_new_tree=False)
                checkout = checkout_branch.bzrdir
                checkout_branch.bind(source)
                if revision_id is not None:
                    rh = checkout_branch.revision_history()
                    checkout_branch.set_revision_history(rh[:rh.index(revision_id) + 1])
            checkout.create_workingtree(revision_id)
        finally:
            bzrlib.bzrdir.BzrDirFormat.set_default_format(old_format)


class cmd_renames(Command):
    """Show list of renamed files.
    """
    # TODO: Option to show renames between two historical versions.

    # TODO: Only show renames under dir, rather than in the whole branch.
    takes_args = ['dir?']

    @display_command
    def run(self, dir=u'.'):
        tree = WorkingTree.open_containing(dir)[0]
        old_inv = tree.basis_tree().inventory
        new_inv = tree.read_working_inventory()

        renames = list(bzrlib.tree.find_renames(old_inv, new_inv))
        renames.sort()
        for old_name, new_name in renames:
            print "%s => %s" % (old_name, new_name)        


class cmd_update(Command):
    """Update a tree to have the latest code committed to its branch.
    
    This will perform a merge into the working tree, and may generate
    conflicts. If you have any local changes, you will still 
    need to commit them after the update for the update to be complete.
    
    If you want to discard your local changes, you can just do a 
    'bzr revert' instead of 'bzr commit' after the update.
    """
    takes_args = ['dir?']

    def run(self, dir='.'):
        tree = WorkingTree.open_containing(dir)[0]
        tree.lock_write()
        try:
            if tree.last_revision() == tree.branch.last_revision():
                # may be up to date, check master too.
                master = tree.branch.get_master_branch()
                if master is None or master.last_revision == tree.last_revision():
                    note("Tree is up to date.")
                    return
            conflicts = tree.update()
            note('Updated to revision %d.' %
                 (tree.branch.revision_id_to_revno(tree.last_revision()),))
            if conflicts != 0:
                return 1
            else:
                return 0
        finally:
            tree.unlock()


class cmd_info(Command):
    """Show statistical information about a branch."""
    takes_args = ['branch?']
    takes_options = ['verbose']
    
    @display_command
    def run(self, branch=None, verbose=False):
        import bzrlib.info
        bzrlib.info.show_bzrdir_info(bzrdir.BzrDir.open_containing(branch)[0],
                                     verbose=verbose)


class cmd_remove(Command):
    """Make a file unversioned.

    This makes bzr stop tracking changes to a versioned file.  It does
    not delete the working copy.
    """
    takes_args = ['file+']
    takes_options = ['verbose']
    aliases = ['rm']
    
    def run(self, file_list, verbose=False):
        tree, file_list = tree_files(file_list)
        tree.remove(file_list, verbose=verbose)


class cmd_file_id(Command):
    """Print file_id of a particular file or directory.

    The file_id is assigned when the file is first added and remains the
    same through all revisions where the file exists, even when it is
    moved or renamed.
    """
    hidden = True
    takes_args = ['filename']
    @display_command
    def run(self, filename):
        tree, relpath = WorkingTree.open_containing(filename)
        i = tree.inventory.path2id(relpath)
        if i == None:
            raise BzrError("%r is not a versioned file" % filename)
        else:
            print i


class cmd_file_path(Command):
    """Print path of file_ids to a file or directory.

    This prints one line for each directory down to the target,
    starting at the branch root."""
    hidden = True
    takes_args = ['filename']
    @display_command
    def run(self, filename):
        tree, relpath = WorkingTree.open_containing(filename)
        inv = tree.inventory
        fid = inv.path2id(relpath)
        if fid == None:
            raise BzrError("%r is not a versioned file" % filename)
        for fip in inv.get_idpath(fid):
            print fip


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
    takes_args = ['branch?']

    def run(self, branch="."):
        from bzrlib.reconcile import reconcile
        dir = bzrlib.bzrdir.BzrDir.open(branch)
        reconcile(dir)


class cmd_revision_history(Command):
    """Display list of revision ids on this branch."""
    hidden = True
    @display_command
    def run(self):
        branch = WorkingTree.open_containing(u'.')[0].branch
        for patchid in branch.revision_history():
            print patchid


class cmd_ancestry(Command):
    """List all revisions merged into this branch."""
    hidden = True
    @display_command
    def run(self):
        tree = WorkingTree.open_containing(u'.')[0]
        b = tree.branch
        # FIXME. should be tree.last_revision
        for revision_id in b.repository.get_ancestry(b.last_revision()):
            print revision_id


class cmd_init(Command):
    """Make a directory into a versioned branch.

    Use this to create an empty branch, or before importing an
    existing project.

    Recipe for importing a tree of files:
        cd ~/project
        bzr init
        bzr add .
        bzr status
        bzr commit -m 'imported project'
    """
    takes_args = ['location?']
    takes_options = [
                     Option('format', 
                            help='Create a specific format rather than the'
                                 ' current default format. Currently this '
                                 ' option only accepts "metadir"',
                            type=get_format_type),
                     ]
    def run(self, location=None, format=None):
        from bzrlib.branch import Branch
        if location is None:
            location = u'.'
        else:
            # The path has to exist to initialize a
            # branch inside of it.
            # Just using os.mkdir, since I don't
            # believe that we want to create a bunch of
            # locations if the user supplies an extended path
            if not os.path.exists(location):
                os.mkdir(location)
        try:
            existing = bzrdir.BzrDir.open(location)
        except NotBranchError:
            bzrdir.BzrDir.create_branch_convenience(location, format=format)
        else:
            try:
                existing.open_branch()
            except NotBranchError:
                existing.create_branch()
                existing.create_workingtree()
            else:
                raise errors.AlreadyBranchError(location)


class cmd_init_repository(Command):
    """Create a shared repository to hold branches.

    New branches created under the repository directory will store their revisions
    in the repository, not in the branch directory, if the branch format supports
    shared storage.

    example:    
        bzr init-repo repo
        bzr init --format=metadir repo/trunk
        cd repo/trunk
        (add files here)
    """
    takes_args = ["location"] 
    takes_options = [Option('format', 
                            help='Use a specific format rather than the'
                            ' current default format. Currently this'
                            ' option only accepts "metadir" and "knit"'
                            ' WARNING: the knit format is currently unstable'
                            ' and only for experimental use.',
                            type=get_format_type),
                     Option('trees',
                             help='Allows branches in repository to have'
                             ' a working tree')]
    aliases = ["init-repo"]
    def run(self, location, format=None, trees=False):
        from bzrlib.bzrdir import BzrDirMetaFormat1
        from bzrlib.transport import get_transport
        if format is None:
            format = BzrDirMetaFormat1()
        transport = get_transport(location)
        if not transport.has('.'):
            transport.mkdir('')
        newdir = format.initialize_on_transport(transport)
        repo = newdir.create_repository(shared=True)
        repo.set_make_working_trees(trees)


class cmd_diff(Command):
    """Show differences in working tree.
    
    If files are listed, only the changes in those files are listed.
    Otherwise, all changes for the tree are listed.

    examples:
        bzr diff
        bzr diff -r1
        bzr diff -r1..2
    """
    # TODO: Allow diff across branches.
    # TODO: Option to use external diff command; could be GNU diff, wdiff,
    #       or a graphical diff.

    # TODO: Python difflib is not exactly the same as unidiff; should
    #       either fix it up or prefer to use an external diff.

    # TODO: If a directory is given, diff everything under that.

    # TODO: Selected-file diff is inefficient and doesn't show you
    #       deleted files.

    # TODO: This probably handles non-Unix newlines poorly.
    
    takes_args = ['file*']
    takes_options = ['revision', 'diff-options']
    aliases = ['di', 'dif']

    @display_command
    def run(self, revision=None, file_list=None, diff_options=None):
        from bzrlib.diff import diff_cmd_helper, show_diff_trees
        try:
            tree1, file_list = internal_tree_files(file_list)
            tree2 = None
            b = None
            b2 = None
        except FileInWrongBranch:
            if len(file_list) != 2:
                raise BzrCommandError("Files are in different branches")

            tree1, file1 = WorkingTree.open_containing(file_list[0])
            tree2, file2 = WorkingTree.open_containing(file_list[1])
            if file1 != "" or file2 != "":
                # FIXME diff those two files. rbc 20051123
                raise BzrCommandError("Files are in different branches")
            file_list = None
        if revision is not None:
            if tree2 is not None:
                raise BzrCommandError("Can't specify -r with two branches")
            if (len(revision) == 1) or (revision[1].spec is None):
                return diff_cmd_helper(tree1, file_list, diff_options,
                                       revision[0])
            elif len(revision) == 2:
                return diff_cmd_helper(tree1, file_list, diff_options,
                                       revision[0], revision[1])
            else:
                raise BzrCommandError('bzr diff --revision takes exactly one or two revision identifiers')
        else:
            if tree2 is not None:
                return show_diff_trees(tree1, tree2, sys.stdout, 
                                       specific_files=file_list,
                                       external_diff_options=diff_options)
            else:
                return diff_cmd_helper(tree1, file_list, diff_options)


class cmd_deleted(Command):
    """List files deleted in the working tree.
    """
    # TODO: Show files deleted since a previous revision, or
    # between two revisions.
    # TODO: Much more efficient way to do this: read in new
    # directories with readdir, rather than stating each one.  Same
    # level of effort but possibly much less IO.  (Or possibly not,
    # if the directories are very large...)
    @display_command
    def run(self, show_ids=False):
        tree = WorkingTree.open_containing(u'.')[0]
        old = tree.basis_tree()
        for path, ie in old.inventory.iter_entries():
            if not tree.has_id(ie.file_id):
                if show_ids:
                    print '%-50s %s' % (path, ie.file_id)
                else:
                    print path


class cmd_modified(Command):
    """List files modified in working tree."""
    hidden = True
    @display_command
    def run(self):
        from bzrlib.delta import compare_trees

        tree = WorkingTree.open_containing(u'.')[0]
        td = compare_trees(tree.basis_tree(), tree)

        for path, id, kind, text_modified, meta_modified in td.modified:
            print path



class cmd_added(Command):
    """List files added in working tree."""
    hidden = True
    @display_command
    def run(self):
        wt = WorkingTree.open_containing(u'.')[0]
        basis_inv = wt.basis_tree().inventory
        inv = wt.inventory
        for file_id in inv:
            if file_id in basis_inv:
                continue
            path = inv.id2path(file_id)
            if not os.access(bzrlib.osutils.abspath(path), os.F_OK):
                continue
            print path
                
        

class cmd_root(Command):
    """Show the tree root directory.

    The root is the nearest enclosing directory with a .bzr control
    directory."""
    takes_args = ['filename?']
    @display_command
    def run(self, filename=None):
        """Print the branch root."""
        tree = WorkingTree.open_containing(filename)[0]
        print tree.basedir


class cmd_log(Command):
    """Show log of a branch, file, or directory.

    By default show the log of the branch containing the working directory.

    To request a range of logs, you can use the command -r begin..end
    -r revision requests a specific revision, -r ..end or -r begin.. are
    also valid.

    examples:
        bzr log
        bzr log foo.c
        bzr log -r -10.. http://server/branch
    """

    # TODO: Make --revision support uuid: and hash: [future tag:] notation.

    takes_args = ['location?']
    takes_options = [Option('forward', 
                            help='show from oldest to newest'),
                     'timezone', 
                     Option('verbose', 
                             help='show files changed in each revision'),
                     'show-ids', 'revision',
                     'log-format',
                     'line', 'long', 
                     Option('message',
                            help='show revisions whose message matches this regexp',
                            type=str),
                     'short',
                     ]
    @display_command
    def run(self, location=None, timezone='original',
            verbose=False,
            show_ids=False,
            forward=False,
            revision=None,
            log_format=None,
            message=None,
            long=False,
            short=False,
            line=False):
        from bzrlib.log import log_formatter, show_log
        import codecs
        assert message is None or isinstance(message, basestring), \
            "invalid message argument %r" % message
        direction = (forward and 'forward') or 'reverse'
        
        # log everything
        file_id = None
        if location:
            # find the file id to log:

            dir, fp = bzrdir.BzrDir.open_containing(location)
            b = dir.open_branch()
            if fp != '':
                try:
                    # might be a tree:
                    inv = dir.open_workingtree().inventory
                except (errors.NotBranchError, errors.NotLocalUrl):
                    # either no tree, or is remote.
                    inv = b.basis_tree().inventory
                file_id = inv.path2id(fp)
        else:
            # local dir only
            # FIXME ? log the current subdir only RBC 20060203 
            dir, relpath = bzrdir.BzrDir.open_containing('.')
            b = dir.open_branch()

        if revision is None:
            rev1 = None
            rev2 = None
        elif len(revision) == 1:
            rev1 = rev2 = revision[0].in_history(b).revno
        elif len(revision) == 2:
            if revision[0].spec is None:
                # missing begin-range means first revision
                rev1 = 1
            else:
                rev1 = revision[0].in_history(b).revno

            if revision[1].spec is None:
                # missing end-range means last known revision
                rev2 = b.revno()
            else:
                rev2 = revision[1].in_history(b).revno
        else:
            raise BzrCommandError('bzr log --revision takes one or two values.')

        # By this point, the revision numbers are converted to the +ve
        # form if they were supplied in the -ve form, so we can do
        # this comparison in relative safety
        if rev1 > rev2:
            (rev2, rev1) = (rev1, rev2)

        mutter('encoding log as %r', bzrlib.user_encoding)

        # use 'replace' so that we don't abort if trying to write out
        # in e.g. the default C locale.
        outf = codecs.getwriter(bzrlib.user_encoding)(sys.stdout, errors='replace')

        if (log_format == None):
            default = bzrlib.config.BranchConfig(b).log_format()
            log_format = get_log_format(long=long, short=short, line=line, default=default)

        lf = log_formatter(log_format,
                           show_ids=show_ids,
                           to_file=outf,
                           show_timezone=timezone)

        show_log(b,
                 lf,
                 file_id,
                 verbose=verbose,
                 direction=direction,
                 start_revision=rev1,
                 end_revision=rev2,
                 search=message)


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

    A more user-friendly interface is "bzr log FILE"."""
    hidden = True
    takes_args = ["filename"]
    @display_command
    def run(self, filename):
        tree, relpath = WorkingTree.open_containing(filename)
        b = tree.branch
        inv = tree.read_working_inventory()
        file_id = inv.path2id(relpath)
        for revno, revision_id, what in bzrlib.log.find_touching_revisions(b, file_id):
            print "%6d %s" % (revno, what)


class cmd_ls(Command):
    """List files in a tree.
    """
    # TODO: Take a revision or remote path and list that tree instead.
    hidden = True
    takes_options = ['verbose', 'revision',
                     Option('non-recursive',
                            help='don\'t recurse into sub-directories'),
                     Option('from-root',
                            help='Print all paths from the root of the branch.'),
                     Option('unknown', help='Print unknown files'),
                     Option('versioned', help='Print versioned files'),
                     Option('ignored', help='Print ignored files'),

                     Option('null', help='Null separate the files'),
                    ]
    @display_command
    def run(self, revision=None, verbose=False, 
            non_recursive=False, from_root=False,
            unknown=False, versioned=False, ignored=False,
            null=False):

        if verbose and null:
            raise BzrCommandError('Cannot set both --verbose and --null')
        all = not (unknown or versioned or ignored)

        selection = {'I':ignored, '?':unknown, 'V':versioned}

        tree, relpath = WorkingTree.open_containing(u'.')
        if from_root:
            relpath = u''
        elif relpath:
            relpath += '/'
        if revision is not None:
            tree = tree.branch.repository.revision_tree(
                revision[0].in_history(tree.branch).rev_id)
        for fp, fc, kind, fid, entry in tree.list_files():
            if fp.startswith(relpath):
                fp = fp[len(relpath):]
                if non_recursive and '/' in fp:
                    continue
                if not all and not selection[fc]:
                    continue
                if verbose:
                    kindch = entry.kind_character()
                    print '%-8s %s%s' % (fc, fp, kindch)
                elif null:
                    sys.stdout.write(fp)
                    sys.stdout.write('\0')
                    sys.stdout.flush()
                else:
                    print fp


class cmd_unknowns(Command):
    """List unknown files."""
    @display_command
    def run(self):
        from bzrlib.osutils import quotefn
        for f in WorkingTree.open_containing(u'.')[0].unknowns():
            print quotefn(f)


class cmd_ignore(Command):
    """Ignore a command or pattern.

    To remove patterns from the ignore list, edit the .bzrignore file.

    If the pattern contains a slash, it is compared to the whole path
    from the branch root.  Otherwise, it is compared to only the last
    component of the path.  To match a file only in the root directory,
    prepend './'.

    Ignore patterns are case-insensitive on case-insensitive systems.

    Note: wildcards must be quoted from the shell on Unix.

    examples:
        bzr ignore ./Makefile
        bzr ignore '*.class'
    """
    # TODO: Complain if the filename is absolute
    takes_args = ['name_pattern']
    
    def run(self, name_pattern):
        from bzrlib.atomicfile import AtomicFile
        import os.path

        tree, relpath = WorkingTree.open_containing(u'.')
        ifn = tree.abspath('.bzrignore')

        if os.path.exists(ifn):
            f = open(ifn, 'rt')
            try:
                igns = f.read().decode('utf-8')
            finally:
                f.close()
        else:
            igns = ''

        # TODO: If the file already uses crlf-style termination, maybe
        # we should use that for the newly added lines?

        if igns and igns[-1] != '\n':
            igns += '\n'
        igns += name_pattern + '\n'

        try:
            f = AtomicFile(ifn, 'wt')
            f.write(igns.encode('utf-8'))
            f.commit()
        finally:
            f.close()

        inv = tree.inventory
        if inv.path2id('.bzrignore'):
            mutter('.bzrignore is already versioned')
        else:
            mutter('need to make new .bzrignore file versioned')
            tree.add(['.bzrignore'])


class cmd_ignored(Command):
    """List ignored files and the patterns that matched them.

    See also: bzr ignore"""
    @display_command
    def run(self):
        tree = WorkingTree.open_containing(u'.')[0]
        for path, file_class, kind, file_id, entry in tree.list_files():
            if file_class != 'I':
                continue
            ## XXX: Slightly inefficient since this was already calculated
            pat = tree.is_ignored(path)
            print '%-50s %s' % (path, pat)


class cmd_lookup_revision(Command):
    """Lookup the revision-id from a revision-number

    example:
        bzr lookup-revision 33
    """
    hidden = True
    takes_args = ['revno']
    
    @display_command
    def run(self, revno):
        try:
            revno = int(revno)
        except ValueError:
            raise BzrCommandError("not a valid revision-number: %r" % revno)

        print WorkingTree.open_containing(u'.')[0].branch.get_rev_id(revno)


class cmd_export(Command):
    """Export past revision to destination directory.

    If no revision is specified this exports the last committed revision.

    Format may be an "exporter" name, such as tar, tgz, tbz2.  If none is
    given, try to find the format with the extension. If no extension
    is found exports to a directory (equivalent to --format=dir).

    Root may be the top directory for tar, tgz and tbz2 formats. If none
    is given, the top directory will be the root name of the file.

    Note: export of tree with non-ascii filenames to zip is not supported.

     Supported formats       Autodetected by extension
     -----------------       -------------------------
         dir                            -
         tar                          .tar
         tbz2                    .tar.bz2, .tbz2
         tgz                      .tar.gz, .tgz
         zip                          .zip
    """
    takes_args = ['dest']
    takes_options = ['revision', 'format', 'root']
    def run(self, dest, revision=None, format=None, root=None):
        import os.path
        from bzrlib.export import export
        tree = WorkingTree.open_containing(u'.')[0]
        b = tree.branch
        if revision is None:
            # should be tree.last_revision  FIXME
            rev_id = b.last_revision()
        else:
            if len(revision) != 1:
                raise BzrError('bzr export --revision takes exactly 1 argument')
            rev_id = revision[0].in_history(b).rev_id
        t = b.repository.revision_tree(rev_id)
        try:
            export(t, dest, format, root)
        except errors.NoSuchExportFormat, e:
            raise BzrCommandError('Unsupported export format: %s' % e.format)


class cmd_cat(Command):
    """Write a file's text from a previous revision."""

    takes_options = ['revision']
    takes_args = ['filename']

    @display_command
    def run(self, filename, revision=None):
        if revision is not None and len(revision) != 1:
            raise BzrCommandError("bzr cat --revision takes exactly one number")
        tree = None
        try:
            tree, relpath = WorkingTree.open_containing(filename)
            b = tree.branch
        except NotBranchError:
            pass

        if tree is None:
            b, relpath = Branch.open_containing(filename)
        if revision is None:
            revision_id = b.last_revision()
        else:
            revision_id = revision[0].in_history(b).rev_id
        b.print_file(relpath, revision_id)


class cmd_local_time_offset(Command):
    """Show the offset in seconds from GMT to local time."""
    hidden = True    
    @display_command
    def run(self):
        print bzrlib.osutils.local_time_offset()



class cmd_commit(Command):
    """Commit changes into a new revision.
    
    If no arguments are given, the entire tree is committed.

    If selected files are specified, only changes to those files are
    committed.  If a directory is specified then the directory and everything 
    within it is committed.

    A selected-file commit may fail in some cases where the committed
    tree would be invalid, such as trying to commit a file in a
    newly-added directory that is not itself committed.
    """
    # TODO: Run hooks on tree to-be-committed, and after commit.

    # TODO: Strict commit that fails if there are deleted files.
    #       (what does "deleted files" mean ??)

    # TODO: Give better message for -s, --summary, used by tla people

    # XXX: verbose currently does nothing

    takes_args = ['selected*']
    takes_options = ['message', 'verbose', 
                     Option('unchanged',
                            help='commit even if nothing has changed'),
                     Option('file', type=str, 
                            argname='msgfile',
                            help='file containing commit message'),
                     Option('strict',
                            help="refuse to commit if there are unknown "
                            "files in the working tree."),
                     Option('local',
                            help="perform a local only commit in a bound "
                                 "branch. Such commits are not pushed to "
                                 "the master branch until a normal commit "
                                 "is performed."
                            ),
                     ]
    aliases = ['ci', 'checkin']

    def run(self, message=None, file=None, verbose=True, selected_list=None,
            unchanged=False, strict=False, local=False):
        from bzrlib.commit import (NullCommitReporter, ReportCommitToLog)
        from bzrlib.errors import (PointlessCommit, ConflictsInTree,
                StrictCommitFailed)
        from bzrlib.msgeditor import edit_commit_message, \
                make_commit_message_template
        from tempfile import TemporaryFile
        import codecs

        # TODO: Need a blackbox test for invoking the external editor; may be
        # slightly problematic to run this cross-platform.

        # TODO: do more checks that the commit will succeed before 
        # spending the user's valuable time typing a commit message.
        #
        # TODO: if the commit *does* happen to fail, then save the commit 
        # message to a temporary file where it can be recovered
        tree, selected_list = tree_files(selected_list)
        if local and not tree.branch.get_bound_location():
            raise errors.LocalRequiresBoundBranch()
        if message is None and not file:
            template = make_commit_message_template(tree, selected_list)
            message = edit_commit_message(template)
            if message is None:
                raise BzrCommandError("please specify a commit message"
                                      " with either --message or --file")
        elif message and file:
            raise BzrCommandError("please specify either --message or --file")
        
        if file:
            import codecs
            message = codecs.open(file, 'rt', bzrlib.user_encoding).read()

        if message == "":
                raise BzrCommandError("empty commit message specified")
        
        if verbose:
            reporter = ReportCommitToLog()
        else:
            reporter = NullCommitReporter()
        
        try:
            tree.commit(message, specific_files=selected_list,
                        allow_pointless=unchanged, strict=strict, local=local,
                        reporter=reporter)
        except PointlessCommit:
            # FIXME: This should really happen before the file is read in;
            # perhaps prepare the commit; get the message; then actually commit
            raise BzrCommandError("no changes to commit",
                                  ["use --unchanged to commit anyhow"])
        except ConflictsInTree:
            raise BzrCommandError("Conflicts detected in working tree.  "
                'Use "bzr conflicts" to list, "bzr resolve FILE" to resolve.')
        except StrictCommitFailed:
            raise BzrCommandError("Commit refused because there are unknown "
                                  "files in the working tree.")
        except errors.BoundBranchOutOfDate, e:
            raise BzrCommandError(str(e)
                                  + ' Either unbind, update, or'
                                    ' pass --local to commit.')


class cmd_check(Command):
    """Validate consistency of branch history.

    This command checks various invariants about the branch storage to
    detect data corruption or bzr bugs.
    """
    takes_args = ['branch?']
    takes_options = ['verbose']

    def run(self, branch=None, verbose=False):
        from bzrlib.check import check
        if branch is None:
            tree = WorkingTree.open_containing()[0]
            branch = tree.branch
        else:
            branch = Branch.open(branch)
        check(branch, verbose)


class cmd_scan_cache(Command):
    hidden = True
    def run(self):
        from bzrlib.hashcache import HashCache

        c = HashCache(u'.')
        c.read()
        c.scan()
            
        print '%6d stats' % c.stat_count
        print '%6d in hashcache' % len(c._cache)
        print '%6d files removed from cache' % c.removed_count
        print '%6d hashes updated' % c.update_count
        print '%6d files changed too recently to cache' % c.danger_count

        if c.needs_write:
            c.write()


class cmd_upgrade(Command):
    """Upgrade branch storage to current format.

    The check command or bzr developers may sometimes advise you to run
    this command. When the default format has changed you may also be warned
    during other operations to upgrade.
    """
    takes_args = ['url?']
    takes_options = [
                     Option('format', 
                            help='Upgrade to a specific format rather than the'
                                 ' current default format. Currently this'
                                 ' option only accepts "metadir" and "knit".'
                                 ' WARNING: the knit format is currently'
                                 ' unstable and only for experimental use.',
                            type=get_format_type),
                    ]


    def run(self, url='.', format=None):
        from bzrlib.upgrade import upgrade
        upgrade(url, format)


class cmd_whoami(Command):
    """Show bzr user id."""
    takes_options = ['email']
    
    @display_command
    def run(self, email=False):
        try:
            b = WorkingTree.open_containing(u'.')[0].branch
            config = bzrlib.config.BranchConfig(b)
        except NotBranchError:
            config = bzrlib.config.GlobalConfig()
        
        if email:
            print config.user_email()
        else:
            print config.username()


class cmd_nick(Command):
    """Print or set the branch nickname.  

    If unset, the tree root directory name is used as the nickname
    To print the current nickname, execute with no argument.  
    """
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


class cmd_selftest(Command):
    """Run internal test suite.
    
    This creates temporary test directories in the working directory,
    but not existing data is affected.  These directories are deleted
    if the tests pass, or left behind to help in debugging if they
    fail and --keep-output is specified.
    
    If arguments are given, they are regular expressions that say
    which tests should run.

    If the global option '--no-plugins' is given, plugins are not loaded
    before running the selftests.  This has two effects: features provided or
    modified by plugins will not be tested, and tests provided by plugins will
    not be run.

    examples:
        bzr selftest ignore
        bzr --no-plugins selftest -v
    """
    # TODO: --list should give a list of all available tests

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
        raise BzrCommandError(msg)

    hidden = True
    takes_args = ['testspecs*']
    takes_options = ['verbose',
                     Option('one', help='stop when one test fails'),
                     Option('keep-output', 
                            help='keep output directories when tests fail'),
                     Option('transport', 
                            help='Use a different transport by default '
                                 'throughout the test suite.',
                            type=get_transport_type),
                    ]

    def run(self, testspecs_list=None, verbose=False, one=False,
            keep_output=False, transport=None):
        import bzrlib.ui
        from bzrlib.tests import selftest
        # we don't want progress meters from the tests to go to the
        # real output; and we don't want log messages cluttering up
        # the real logs.
        save_ui = bzrlib.ui.ui_factory
        bzrlib.trace.info('running tests...')
        try:
            bzrlib.ui.ui_factory = bzrlib.ui.SilentUIFactory()
            if testspecs_list is not None:
                pattern = '|'.join(testspecs_list)
            else:
                pattern = ".*"
            result = selftest(verbose=verbose, 
                              pattern=pattern,
                              stop_on_failure=one, 
                              keep_output=keep_output,
                              transport=transport)
            if result:
                bzrlib.trace.info('tests passed')
            else:
                bzrlib.trace.info('tests failed')
            return int(not result)
        finally:
            bzrlib.ui.ui_factory = save_ui


def _get_bzr_branch():
    """If bzr is run from a branch, return Branch or None"""
    import bzrlib.errors
    from bzrlib.branch import Branch
    from bzrlib.osutils import abspath
    from os.path import dirname
    
    try:
        branch = Branch.open(dirname(abspath(dirname(__file__))))
        return branch
    except bzrlib.errors.BzrError:
        return None
    

def show_version():
    print "bzr (bazaar-ng) %s" % bzrlib.__version__
    # is bzrlib itself in a branch?
    branch = _get_bzr_branch()
    if branch:
        rh = branch.revision_history()
        revno = len(rh)
        print "  bzr checkout, revision %d" % (revno,)
        print "  nick: %s" % (branch.nick,)
        if rh:
            print "  revid: %s" % (rh[-1],)
    print bzrlib.__copyright__
    print "http://bazaar-ng.org/"
    print
    print "bzr comes with ABSOLUTELY NO WARRANTY.  bzr is free software, and"
    print "you may use, modify and redistribute it under the terms of the GNU"
    print "General Public License version 2 or later."


class cmd_version(Command):
    """Show version of bzr."""
    @display_command
    def run(self):
        show_version()

class cmd_rocks(Command):
    """Statement of optimism."""
    hidden = True
    @display_command
    def run(self):
        print "it sure does!"


class cmd_find_merge_base(Command):
    """Find and print a base revision for merging two branches.
    """
    # TODO: Options to specify revisions on either side, as if
    #       merging only part of the history.
    takes_args = ['branch', 'other']
    hidden = True
    
    @display_command
    def run(self, branch, other):
        from bzrlib.revision import common_ancestor, MultipleRevisionSources
        
        branch1 = Branch.open_containing(branch)[0]
        branch2 = Branch.open_containing(other)[0]

        history_1 = branch1.revision_history()
        history_2 = branch2.revision_history()

        last1 = branch1.last_revision()
        last2 = branch2.last_revision()

        source = MultipleRevisionSources(branch1.repository, 
                                         branch2.repository)
        
        base_rev_id = common_ancestor(last1, last2, source)

        print 'merge base is revision %s' % base_rev_id
        
        return

        if base_revno is None:
            raise bzrlib.errors.UnrelatedBranches()

        print ' r%-6d in %s' % (base_revno, branch)

        other_revno = branch2.revision_id_to_revno(base_revid)
        
        print ' r%-6d in %s' % (other_revno, other)



class cmd_merge(Command):
    """Perform a three-way merge.
    
    The branch is the branch you will merge from.  By default, it will
    merge the latest revision.  If you specify a revision, that
    revision will be merged.  If you specify two revisions, the first
    will be used as a BASE, and the second one as OTHER.  Revision
    numbers are always relative to the specified branch.

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
    default, use --remember.

    Examples:

    To merge the latest revision from bzr.dev
    bzr merge ../bzr.dev

    To merge changes up to and including revision 82 from bzr.dev
    bzr merge -r 82 ../bzr.dev

    To merge the changes introduced by 82, without previous changes:
    bzr merge -r 81..82 ../bzr.dev
    
    merge refuses to run if there are any uncommitted changes, unless
    --force is given.
    """
    takes_args = ['branch?']
    takes_options = ['revision', 'force', 'merge-type', 'reprocess', 'remember',
                     Option('show-base', help="Show base revision text in "
                            "conflicts")]

    def run(self, branch=None, revision=None, force=False, merge_type=None,
            show_base=False, reprocess=False, remember=False):
        if merge_type is None:
            merge_type = Merge3Merger

        tree = WorkingTree.open_containing(u'.')[0]
        stored_loc = tree.branch.get_parent()
        if branch is None:
            if stored_loc is None:
                raise BzrCommandError("No merge branch known or specified.")
            else:
                print "Using saved branch: %s" % stored_loc
                branch = stored_loc

        if tree.branch.get_parent() is None or remember:
            tree.branch.set_parent(branch)

        if revision is None or len(revision) < 1:
            base = [None, None]
            other = [branch, -1]
            other_branch, path = Branch.open_containing(branch)
        else:
            if len(revision) == 1:
                base = [None, None]
                other_branch, path = Branch.open_containing(branch)
                revno = revision[0].in_history(other_branch).revno
                other = [branch, revno]
            else:
                assert len(revision) == 2
                if None in revision:
                    raise BzrCommandError(
                        "Merge doesn't permit that revision specifier.")
                b, path = Branch.open_containing(branch)

                base = [branch, revision[0].in_history(b).revno]
                other = [branch, revision[1].in_history(b).revno]
        if path != "":
            interesting_files = [path]
        else:
            interesting_files = None
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            try:
                conflict_count = merge(other, base, check_clean=(not force),
                                       merge_type=merge_type, 
                                       reprocess=reprocess,
                                       show_base=show_base, 
                                       pb=pb, file_list=interesting_files)
            finally:
                pb.finished()
            if conflict_count != 0:
                return 1
            else:
                return 0
        except bzrlib.errors.AmbiguousBase, e:
            m = ("sorry, bzr can't determine the right merge base yet\n"
                 "candidates are:\n  "
                 + "\n  ".join(e.bases)
                 + "\n"
                 "please specify an explicit base with -r,\n"
                 "and (if you want) report this to the bzr developers\n")
            log_error(m)


class cmd_remerge(Command):
    """Redo a merge.
    """
    takes_args = ['file*']
    takes_options = ['merge-type', 'reprocess',
                     Option('show-base', help="Show base revision text in "
                            "conflicts")]

    def run(self, file_list=None, merge_type=None, show_base=False,
            reprocess=False):
        from bzrlib.merge import merge_inner, transform_tree
        if merge_type is None:
            merge_type = Merge3Merger
        tree, file_list = tree_files(file_list)
        tree.lock_write()
        try:
            pending_merges = tree.pending_merges() 
            if len(pending_merges) != 1:
                raise BzrCommandError("Sorry, remerge only works after normal"
                                      + " merges.  Not cherrypicking or"
                                      + "multi-merges.")
            repository = tree.branch.repository
            base_revision = common_ancestor(tree.branch.last_revision(), 
                                            pending_merges[0], repository)
            base_tree = repository.revision_tree(base_revision)
            other_tree = repository.revision_tree(pending_merges[0])
            interesting_ids = None
            if file_list is not None:
                interesting_ids = set()
                for filename in file_list:
                    file_id = tree.path2id(filename)
                    if file_id is None:
                        raise NotVersionedError(filename)
                    interesting_ids.add(file_id)
                    if tree.kind(file_id) != "directory":
                        continue
                    
                    for name, ie in tree.inventory.iter_entries(file_id):
                        interesting_ids.add(ie.file_id)
            transform_tree(tree, tree.basis_tree(), interesting_ids)
            if file_list is None:
                restore_files = list(tree.iter_conflicts())
            else:
                restore_files = file_list
            for filename in restore_files:
                try:
                    restore(tree.abspath(filename))
                except NotConflicted:
                    pass
            conflicts =  merge_inner(tree.branch, other_tree, base_tree,
                                     this_tree=tree,
                                     interesting_ids = interesting_ids, 
                                     other_rev_id=pending_merges[0], 
                                     merge_type=merge_type, 
                                     show_base=show_base,
                                     reprocess=reprocess)
        finally:
            tree.unlock()
        if conflicts > 0:
            return 1
        else:
            return 0

class cmd_revert(Command):
    """Reverse all changes since the last commit.

    Only versioned files are affected.  Specify filenames to revert only 
    those files.  By default, any files that are changed will be backed up
    first.  Backup files have a '~' appended to their name.
    """
    takes_options = ['revision', 'no-backup']
    takes_args = ['file*']
    aliases = ['merge-revert']

    def run(self, revision=None, no_backup=False, file_list=None):
        from bzrlib.commands import parse_spec
        if file_list is not None:
            if len(file_list) == 0:
                raise BzrCommandError("No files specified")
        else:
            file_list = []
        
        tree, file_list = tree_files(file_list)
        if revision is None:
            # FIXME should be tree.last_revision
            rev_id = tree.last_revision()
        elif len(revision) != 1:
            raise BzrCommandError('bzr revert --revision takes exactly 1 argument')
        else:
            rev_id = revision[0].in_history(tree.branch).rev_id
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            tree.revert(file_list, 
                        tree.branch.repository.revision_tree(rev_id),
                        not no_backup, pb)
        finally:
            pb.finished()


class cmd_assert_fail(Command):
    """Test reporting of assertion failures"""
    hidden = True
    def run(self):
        assert False, "always fails"


class cmd_help(Command):
    """Show help on a command or other topic.

    For a list of all available commands, say 'bzr help commands'."""
    takes_options = [Option('long', 'show help on all commands')]
    takes_args = ['topic?']
    aliases = ['?', '--help', '-?', '-h']
    
    @display_command
    def run(self, topic=None, long=False):
        import help
        if topic is None and long:
            topic = "commands"
        help.help(topic)


class cmd_shell_complete(Command):
    """Show appropriate completions for context.

    For a list of all available commands, say 'bzr shell-complete'."""
    takes_args = ['context?']
    aliases = ['s-c']
    hidden = True
    
    @display_command
    def run(self, context=None):
        import shellcomplete
        shellcomplete.shellcomplete(context)


class cmd_fetch(Command):
    """Copy in history from another branch but don't merge it.

    This is an internal method used for pull and merge."""
    hidden = True
    takes_args = ['from_branch', 'to_branch']
    def run(self, from_branch, to_branch):
        from bzrlib.fetch import Fetcher
        from bzrlib.branch import Branch
        from_b = Branch.open(from_branch)
        to_b = Branch.open(to_branch)
        Fetcher(to_b, from_b)


class cmd_missing(Command):
    """Show unmerged/unpulled revisions between two branches.

    OTHER_BRANCH may be local or remote."""
    takes_args = ['other_branch?']
    takes_options = [Option('reverse', 'Reverse the order of revisions'),
                     Option('mine-only', 
                            'Display changes in the local branch only'),
                     Option('theirs-only', 
                            'Display changes in the remote branch only'), 
                     'log-format',
                     'line',
                     'long', 
                     'short',
                     'show-ids',
                     'verbose'
                     ]

    def run(self, other_branch=None, reverse=False, mine_only=False,
            theirs_only=False, log_format=None, long=False, short=False, line=False, 
            show_ids=False, verbose=False):
        from bzrlib.missing import find_unmerged, iter_log_data
        from bzrlib.log import log_formatter
        local_branch = bzrlib.branch.Branch.open_containing(u".")[0]
        parent = local_branch.get_parent()
        if other_branch is None:
            other_branch = parent
            if other_branch is None:
                raise BzrCommandError("No missing location known or specified.")
            print "Using last location: " + local_branch.get_parent()
        remote_branch = bzrlib.branch.Branch.open(other_branch)
        if remote_branch.base == local_branch.base:
            remote_branch = local_branch
        local_branch.lock_read()
        try:
            remote_branch.lock_read()
            try:
                local_extra, remote_extra = find_unmerged(local_branch, remote_branch)
                if (log_format == None):
                    default = bzrlib.config.BranchConfig(local_branch).log_format()
                    log_format = get_log_format(long=long, short=short, line=line, default=default)
                lf = log_formatter(log_format, sys.stdout,
                                   show_ids=show_ids,
                                   show_timezone='original')
                if reverse is False:
                    local_extra.reverse()
                    remote_extra.reverse()
                if local_extra and not theirs_only:
                    print "You have %d extra revision(s):" % len(local_extra)
                    for data in iter_log_data(local_extra, local_branch.repository,
                                              verbose):
                        lf.show(*data)
                    printed_local = True
                else:
                    printed_local = False
                if remote_extra and not mine_only:
                    if printed_local is True:
                        print "\n\n"
                    print "You are missing %d revision(s):" % len(remote_extra)
                    for data in iter_log_data(remote_extra, remote_branch.repository, 
                                              verbose):
                        lf.show(*data)
                if not remote_extra and not local_extra:
                    status_code = 0
                    print "Branches are up to date."
                else:
                    status_code = 1
            finally:
                remote_branch.unlock()
        finally:
            local_branch.unlock()
        if not status_code and parent is None and other_branch is not None:
            local_branch.lock_write()
            try:
                # handle race conditions - a parent might be set while we run.
                if local_branch.get_parent() is None:
                    local_branch.set_parent(other_branch)
            finally:
                local_branch.unlock()
        return status_code


class cmd_plugins(Command):
    """List plugins"""
    hidden = True
    @display_command
    def run(self):
        import bzrlib.plugin
        from inspect import getdoc
        for name, plugin in bzrlib.plugin.all_plugins().items():
            if hasattr(plugin, '__path__'):
                print plugin.__path__[0]
            elif hasattr(plugin, '__file__'):
                print plugin.__file__
            else:
                print `plugin`
                
            d = getdoc(plugin)
            if d:
                print '\t', d.split('\n')[0]


class cmd_testament(Command):
    """Show testament (signing-form) of a revision."""
    takes_options = ['revision', 'long']
    takes_args = ['branch?']
    @display_command
    def run(self, branch=u'.', revision=None, long=False):
        from bzrlib.testament import Testament
        b = WorkingTree.open_containing(branch)[0].branch
        b.lock_read()
        try:
            if revision is None:
                rev_id = b.last_revision()
            else:
                rev_id = revision[0].in_history(b).rev_id
            t = Testament.from_revision(b.repository, rev_id)
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
    # TODO: annotate a previous version of a file
    # TODO: if the working copy is modified, show annotations on that 
    #       with new uncommitted lines marked
    aliases = ['blame', 'praise']
    takes_args = ['filename']
    takes_options = [Option('all', help='show annotations on all lines'),
                     Option('long', help='show date in annotations'),
                     ]

    @display_command
    def run(self, filename, all=False, long=False):
        from bzrlib.annotate import annotate_file
        tree, relpath = WorkingTree.open_containing(filename)
        branch = tree.branch
        branch.lock_read()
        try:
            file_id = tree.inventory.path2id(relpath)
            tree = branch.repository.revision_tree(branch.last_revision())
            file_version = tree.inventory[file_id].revision
            annotate_file(branch, file_version, file_id, long, all, sys.stdout)
        finally:
            branch.unlock()


class cmd_re_sign(Command):
    """Create a digital signature for an existing revision."""
    # TODO be able to replace existing ones.

    hidden = True # is this right ?
    takes_args = ['revision_id*']
    takes_options = ['revision']
    
    def run(self, revision_id_list=None, revision=None):
        import bzrlib.config as config
        import bzrlib.gpg as gpg
        if revision_id_list is not None and revision is not None:
            raise BzrCommandError('You can only supply one of revision_id or --revision')
        if revision_id_list is None and revision is None:
            raise BzrCommandError('You must supply either --revision or a revision_id')
        b = WorkingTree.open_containing(u'.')[0].branch
        gpg_strategy = gpg.GPGStrategy(config.BranchConfig(b))
        if revision_id_list is not None:
            for revision_id in revision_id_list:
                b.repository.sign_revision(revision_id, gpg_strategy)
        elif revision is not None:
            if len(revision) == 1:
                revno, rev_id = revision[0].in_history(b)
                b.repository.sign_revision(rev_id, gpg_strategy)
            elif len(revision) == 2:
                # are they both on rh- if so we can walk between them
                # might be nice to have a range helper for arbitrary
                # revision paths. hmm.
                from_revno, from_revid = revision[0].in_history(b)
                to_revno, to_revid = revision[1].in_history(b)
                if to_revid is None:
                    to_revno = b.revno()
                if from_revno is None or to_revno is None:
                    raise BzrCommandError('Cannot sign a range of non-revision-history revisions')
                for revno in range(from_revno, to_revno + 1):
                    b.repository.sign_revision(b.get_rev_id(revno), 
                                               gpg_strategy)
            else:
                raise BzrCommandError('Please supply either one revision, or a range.')


class cmd_bind(Command):
    """Bind the current branch to a master branch.

    After binding, commits must succeed on the master branch
    before they are executed on the local one.
    """

    takes_args = ['location']
    takes_options = []

    def run(self, location=None):
        b, relpath = Branch.open_containing(u'.')
        b_other = Branch.open(location)
        try:
            b.bind(b_other)
        except DivergedBranches:
            raise BzrCommandError('These branches have diverged.'
                                  ' Try merging, and then bind again.')


class cmd_unbind(Command):
    """Bind the current branch to its parent.

    After unbinding, the local branch is considered independent.
    """

    takes_args = []
    takes_options = []

    def run(self):
        b, relpath = Branch.open_containing(u'.')
        if not b.unbind():
            raise BzrCommandError('Local branch is not bound')


class cmd_uncommit(bzrlib.commands.Command):
    """Remove the last committed revision.

    By supplying the --all flag, it will not only remove the entry 
    from revision_history, but also remove all of the entries in the
    stores.

    --verbose will print out what is being removed.
    --dry-run will go through all the motions, but not actually
    remove anything.
    
    In the future, uncommit will create a changeset, which can then
    be re-applied.
    """

    # TODO: jam 20060108 Add an option to allow uncommit to remove
    # unreferenced information in 'branch-as-repostory' branches.
    # TODO: jam 20060108 Add the ability for uncommit to remove unreferenced
    # information in shared branches as well.
    takes_options = ['verbose', 'revision',
                    Option('dry-run', help='Don\'t actually make changes'),
                    Option('force', help='Say yes to all questions.')]
    takes_args = ['location?']
    aliases = []

    def run(self, location=None, 
            dry_run=False, verbose=False,
            revision=None, force=False):
        from bzrlib.branch import Branch
        from bzrlib.log import log_formatter
        import sys
        from bzrlib.uncommit import uncommit

        if location is None:
            location = u'.'
        control, relpath = bzrdir.BzrDir.open_containing(location)
        try:
            tree = control.open_workingtree()
            b = tree.branch
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            tree = None
            b = control.open_branch()

        if revision is None:
            revno = b.revno()
            rev_id = b.last_revision()
        else:
            revno, rev_id = revision[0].in_history(b)
        if rev_id is None:
            print 'No revisions to uncommit.'

        for r in range(revno, b.revno()+1):
            rev_id = b.get_rev_id(r)
            lf = log_formatter('short', to_file=sys.stdout,show_timezone='original')
            lf.show(r, b.repository.get_revision(rev_id), None)

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

        uncommit(b, tree=tree, dry_run=dry_run, verbose=verbose,
                revno=revno)


class cmd_break_lock(Command):
    """Break a dead lock on a repository, branch or working directory.

    CAUTION: Locks should only be broken when you are sure that the process
    holding the lock has been stopped.
    
    example:
        bzr break-lock .
    """
    takes_args = ['location']
    takes_options = [Option('show',
                            help="just show information on the lock, " \
                                 "don't break it"),
                    ]
    def run(self, location, show=False):
        raise NotImplementedError("sorry, break-lock is not complete yet; "
                "you can remove the 'held' directory manually to break the lock")


# command-line interpretation helper for merge-related commands
def merge(other_revision, base_revision,
          check_clean=True, ignore_zero=False,
          this_dir=None, backup_files=False, merge_type=Merge3Merger,
          file_list=None, show_base=False, reprocess=False,
          pb=DummyProgress()):
    """Merge changes into a tree.

    base_revision
        list(path, revno) Base for three-way merge.  
        If [None, None] then a base will be automatically determined.
    other_revision
        list(path, revno) Other revision for three-way merge.
    this_dir
        Directory to merge changes into; '.' by default.
    check_clean
        If true, this_dir must have no uncommitted changes before the
        merge begins.
    ignore_zero - If true, suppress the "zero conflicts" message when 
        there are no conflicts; should be set when doing something we expect
        to complete perfectly.
    file_list - If supplied, merge only changes to selected files.

    All available ancestors of other_revision and base_revision are
    automatically pulled into the branch.

    The revno may be -1 to indicate the last revision on the branch, which is
    the typical case.

    This function is intended for use from the command line; programmatic
    clients might prefer to call merge.merge_inner(), which has less magic 
    behavior.
    """
    from bzrlib.merge import Merger
    if this_dir is None:
        this_dir = u'.'
    this_tree = WorkingTree.open_containing(this_dir)[0]
    if show_base and not merge_type is Merge3Merger:
        raise BzrCommandError("Show-base is not supported for this merge"
                              " type. %s" % merge_type)
    if reprocess and not merge_type is Merge3Merger:
        raise BzrCommandError("Reprocess is not supported for this merge"
                              " type. %s" % merge_type)
    if reprocess and show_base:
        raise BzrCommandError("Cannot reprocess and show base.")
    try:
        merger = Merger(this_tree.branch, this_tree=this_tree, pb=pb)
        merger.pp = ProgressPhase("Merge phase", 5, pb)
        merger.pp.next_phase()
        merger.check_basis(check_clean)
        merger.set_other(other_revision)
        merger.pp.next_phase()
        merger.set_base(base_revision)
        if merger.base_rev_id == merger.other_rev_id:
            note('Nothing to do.')
            return 0
        merger.backup_files = backup_files
        merger.merge_type = merge_type 
        merger.set_interesting_files(file_list)
        merger.show_base = show_base 
        merger.reprocess = reprocess
        conflicts = merger.do_merge()
        if file_list is None:
            merger.set_pending()
    finally:
        pb.clear()
    return conflicts


# these get imported and then picked up by the scan for cmd_*
# TODO: Some more consistent way to split command definitions across files;
# we do need to load at least some information about them to know of 
# aliases.  ideally we would avoid loading the implementation until the
# details were needed.
from bzrlib.conflicts import cmd_resolve, cmd_conflicts, restore
from bzrlib.sign_my_commits import cmd_sign_my_commits
from bzrlib.weave_commands import cmd_weave_list, cmd_weave_join, \
        cmd_weave_plan_merge, cmd_weave_merge_text
