#!/usr/bin/env python
"""\
This encapsulates the functionality for trying to rsync a local
working tree to/from a remote rsync accessible location.
"""

import os
import bzrlib

_rsync_location = 'x-rsync-data'
_parent_locations = ['parent', 'pull', 'x-pull']

def temp_branch():
    import tempfile
    dirname = tempfile.mkdtemp("temp-branch")
    return bzrlib.Branch(dirname, init=True)

def rm_branch(branch):
    import shutil
    shutil.rmtree(branch.base)

def is_clean(branch):
    """
    Return true if no files are modifed or unknown
    >>> br = temp_branch()
    >>> is_clean(br)
    True
    >>> fooname = os.path.join(br.base, "foo")
    >>> file(fooname, "wb").write("bar")
    >>> is_clean(br)
    False
    >>> bzrlib.add.smart_add([fooname])
    >>> is_clean(br)
    False
    >>> br.commit("added file")
    >>> is_clean(br)
    True
    >>> rm_branch(br)
    """
    old_tree = branch.basis_tree()
    new_tree = branch.working_tree()
    for path, file_class, kind, file_id in new_tree.list_files():
        if file_class == '?':
            return False
    delta = bzrlib.compare_trees(old_tree, new_tree, want_unchanged=False)
    if len(delta.added) > 0 or len(delta.removed) > 0 or \
        len(delta.modified) > 0:
        return False
    return True

def get_default_remote_info(branch):
    """Return the value stored in .bzr/x-rsync-location if it exists.
    
    >>> br = temp_branch()
    >>> get_default_remote_info(br)
    (None, 0, None)
    >>> import bzrlib.commit
    >>> bzrlib.commit.commit(br, 'test commit', rev_id='test-id-12345')
    >>> set_default_remote_info(br, 'http://somewhere')
    >>> get_default_remote_info(br)
    ('http://somewhere', 1, 'test-id-12345')
    """
    def_remote = None
    revno = 0
    revision = None
    def_remote_filename = branch.controlfilename(_rsync_location)
    if os.path.isfile(def_remote_filename):
        [def_remote,revno, revision] = [x.strip() for x in open(def_remote_filename).readlines()]
    return def_remote, int(revno), revision

def set_default_remote_info(branch, location):
    """Store the location into the .bzr/x-rsync-location.
    
    """
    from bzrlib.atomicfile import AtomicFile
    remote, revno, revision = get_default_remote_info(branch)
    if (remote == location 
        and revno == branch.revno()
        and revision == branch.last_patch()):
        return #Nothing would change, so skip it
    # TODO: Consider adding to x-pull so that we can try a RemoteBranch
    # for checking the need to update
    f = AtomicFile(branch.controlfilename(_rsync_location))
    f.write(location)
    f.write('\n')
    f.write(str(branch.revno()))
    f.write('\n')
    f.write(branch.last_patch())
    f.write('\n')
    f.commit()

def get_parent_branch(branch):
    """Try to get the pull location, in case this directory supports the normal bzr pull.
    
    The idea is that we can use RemoteBranch to see if we actually need to do anything,
    and then we can decide whether to run rsync or not.
    """
    import errno
    stored_loc = None
    for fname in _parent_locations:
        try:
            stored_loc = branch.controlfile(fname, 'rb').read().rstrip('\n')
        except IOError, e:
            if e.errno != errno.ENOENT:
                raise

        if stored_loc:
            break

    if stored_loc:
        from bzrlib.branch import find_branch
        return find_branch(stored_loc)
    return None

def get_branch_remote_update(local=None, remote=None, alt_remote=None):
    from bzrlib.errors import BzrCommandError
    from bzrlib.branch import find_branch
    if local is None:
        local = '.'

    if remote is not None and remote[-1:] != '/':
        remote += '/'

    if alt_remote is not None and alt_remote[-1:] != '/':
        alt_remote += '/'

    if not os.path.exists(local):
        if remote is None:
            remote = alt_remote
        if remote is None:
            raise BzrCommandError('No remote location specified while creating a new local location')
        return local, remote, 0, None

    b = find_branch(local)

    def_remote, last_revno, last_revision = get_default_remote_info(b)
    if remote is None:
        if def_remote is None:
            if alt_remote is None:
                raise BzrCommandError('No remote location specified, and no default exists.')
            else:
                remote = alt_remote
        else:
            remote = def_remote

    if remote[-1:] != '/':
        remote += '/'

    return b, remote, last_revno, last_revision

def check_should_pull(branch, last_revno, last_revision):
    if isinstance(branch, basestring): # We don't even have a local branch yet
        return True

    if not is_clean(branch):
        print '** Local tree is not clean. Either has unknown or modified files.'
        return False

    b_parent = get_parent_branch(branch)
    if b_parent is not None:
        from bzrlib.branch import DivergedBranches
        # This may throw a Diverged branches.
        try:
            missing_revisions = branch.missing_revisions(b_parent)
        except DivergedBranches:
            print '** Local tree history has diverged from remote.'
            print '** Not allowing you to overwrite local changes.'
            return False
        if len(missing_revisions) == 0:
            # There is nothing to do, the remote branch has no changes
            missing_revisions = b_parent.missing_revisions(branch)
            if len(missing_revisions) > 0:
                print '** Local tree is up-to-date with remote.'
                print '** But remote tree is missing local revisions.'
                print '** Consider using bzr rsync-push'
            else:
                print '** Both trees fully up-to-date.'
            return False
        # We are sure that we are missing remote revisions
        return True

    if last_revno == branch.revno() and last_revision == branch.last_patch():
        # We can go ahead and try
        return True

    print 'Local working directory has a different revision than last rsync.'
    val = raw_input('Are you sure you want to download [y/N]? ')
    if val.lower() in ('y', 'yes'):
        return True
    return False

def check_should_push(branch, last_revno, last_revision):
    if not is_clean(branch):
        print '** Local tree is not clean (either modified or unknown files)'
        return False

    b_parent = get_parent_branch(branch)
    if b_parent is not None:
        from bzrlib.branch import DivergedBranches
        # This may throw a Diverged branches.
        try:
            missing_revisions = b_parent.missing_revisions(branch)
        except DivergedBranches:
            print '** Local tree history has diverged from remote.'
            print '** Not allowing you to overwrite remote changes.'
            return False
        if len(missing_revisions) == 0:
            # There is nothing to do, the remote branch is up to date
            missing_revisions = branch.missing_revisions(b_parent)
            if len(missing_revisions) > 0:
                print '** Remote tree is up-to-date with local.'
                print '** But local tree is missing remote revisions.'
                print '** Consider using bzr rsync-pull'
            else:
                print '** Both trees fully up-to-date.'
            return False
        # We are sure that we are missing remote revisions
        return True

    if last_revno is None and last_revision is None:
        print 'Local tree does not have a valid last rsync revision.'
        val = raw_input('push anyway [y/N]? ')
        if val.lower() in ('y', 'yes'):
            return True
        return False

    if last_revno == branch.revno() and last_revision == branch.last_patch():
        print 'No new revisions.'
        return False

    return True


def pull(branch, remote, verbose=False, dry_run=False):
    """Update the local repository from the location specified by 'remote'

    :param branch:  Either a string specifying a local path, or a Branch object.
                    If a local path, the download will be performed, and then
                    a Branch object will be created.

    :return:    Return the branch object that was created
    """
    if isinstance(branch, basestring):
        local = branch
        cur_revno = 0
    else:
        local = branch.base
        cur_revno = branch.revno()
    if remote[-1:] != '/':
        remote += '/'

    rsyncopts = ['-rltp', '--delete'
        # Don't pull in a new parent location
        , "--exclude '**/.bzr/x-rsync*'", "--exclude '**/.bzr/x-pull*'" 
        , "--exclude '**/.bzr/parent'", "--exclude '**/.bzr/pull'"
        ]

    # Note that when pulling, we do not delete excluded files
    rsync_exclude = os.path.join(local, '.rsyncexclude')
    if os.path.exists(rsync_exclude):
        rsyncopts.append('--exclude-from "%s"' % rsync_exclude)
    bzr_ignore = os.path.join(local, '.bzrignore')
    if os.path.exists(bzr_ignore):
        rsyncopts.append('--exclude-from "%s"' % bzr_ignore)

    if verbose:
        rsyncopts.append('-v')
    if dry_run:
        rsyncopts.append('--dry-run')

    cmd = 'rsync %s "%s" "%s"' % (' '.join(rsyncopts), remote, local)
    if verbose:
        print cmd

    status = os.system(cmd)
    if status != 0:
        from bzrlib.errors import BzrError
        raise BzrError('Rsync failed with error code: %s' % status)


    if isinstance(branch, basestring):
        from bzrlib.branch import Branch
        branch = Branch(branch)

    new_revno = branch.revno()
    if cur_revno == new_revno:
        print '** tree is up-to-date'

    if verbose:
        if cur_revno != new_revno:
            from bzrlib.log import show_log
            show_log(branch, direction='forward',
                    start_revision=cur_revno+1, end_revision=new_revno)

    return branch


def push(branch, remote, verbose=False, dry_run=False):
    """Update the local repository from the location specified by 'remote'

    :param branch:  Should always be a Branch object
    """
    if isinstance(branch, basestring):
        from bzrlib.errors import BzrError
        raise BzrError('rsync push requires a Branch object, not a string')
    local = branch.base
    if remote[-1:] != '/':
        remote += '/'

    rsyncopts = ['-rltp', '--include-from -'
        , '--include .bzr'
        # We don't want to push our local meta information to the remote
        , "--exclude '.bzr/x-rsync*'", "--exclude '.bzr/x-pull*'" 
        , "--exclude '.bzr/parent'", "--exclude '.bzr/pull'"
        , "--include '.bzr/**'"
        , "--exclude '*'", "--exclude '.*'"
        , '--delete', '--delete-excluded'
        ]

    rsync_exclude = os.path.join(local, '.rsyncexclude')
    if os.path.exists(rsync_exclude):
        rsyncopts.append('--exclude-from "%s"' % rsync_exclude)
    bzr_ignore = os.path.join(local, '.bzrignore')
    if os.path.exists(bzr_ignore):
        rsyncopts.append('--exclude-from "%s"' % bzr_ignore)

    if verbose:
        rsyncopts.append('-v')
    if dry_run:
        rsyncopts.append('--dry-run')

    cmd = 'rsync %s "." "%s"' % (' '.join(rsyncopts), remote)
    if verbose:
        print cmd

    pwd = os.getcwd()
    try:
        os.chdir(local)
        child = os.popen(cmd, 'w')
        inv = branch.read_working_inventory()
        for path, entry in inv.entries():
            child.write(path)
            child.write('\n')
        child.flush()
        retval = child.close()
        if retval is not None:
            from bzrlib.errors import BzrError
            raise BzrError('Rsync failed with error code: %s' % retval)
    finally:
        os.chdir(pwd)

