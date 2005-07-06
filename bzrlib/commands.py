# Copyright (C) 2004, 2005 by Canonical Ltd

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



import sys, os

import bzrlib
from bzrlib.trace import mutter, note, log_error
from bzrlib.errors import BzrError, BzrCheckError, BzrCommandError
from bzrlib.branch import find_branch
from bzrlib import BZRDIR


plugin_cmds = {}


def register_command(cmd):
    "Utility function to help register a command"
    global plugin_cmds
    k = cmd.__name__
    if k.startswith("cmd_"):
        k_unsquished = _unsquish_command_name(k)
    else:
        k_unsquished = k
    if not plugin_cmds.has_key(k_unsquished):
        plugin_cmds[k_unsquished] = cmd
    else:
        log_error('Two plugins defined the same command: %r' % k)
        log_error('Not loading the one in %r' % sys.modules[cmd.__module__])


def _squish_command_name(cmd):
    return 'cmd_' + cmd.replace('-', '_')


def _unsquish_command_name(cmd):
    assert cmd.startswith("cmd_")
    return cmd[4:].replace('_','-')

def _parse_revision_str(revstr):
    """This handles a revision string -> revno. 

    There are several possibilities:

        '234'       -> 234
        '234:345'   -> [234, 345]
        ':234'      -> [None, 234]
        '234:'      -> [234, None]

    In the future we will also support:
        'uuid:blah-blah-blah'   -> ?
        'hash:blahblahblah'     -> ?
        potentially:
        'tag:mytag'             -> ?
    """
    if revstr.find(':') != -1:
        revs = revstr.split(':')
        if len(revs) > 2:
            raise ValueError('More than 2 pieces not supported for --revision: %r' % revstr)

        if not revs[0]:
            revs[0] = None
        else:
            revs[0] = int(revs[0])

        if not revs[1]:
            revs[1] = None
        else:
            revs[1] = int(revs[1])
    else:
        revs = int(revstr)
    return revs



def _get_cmd_dict(plugins_override=True):
    d = {}
    for k, v in globals().iteritems():
        if k.startswith("cmd_"):
            d[_unsquish_command_name(k)] = v
    # If we didn't load plugins, the plugin_cmds dict will be empty
    if plugins_override:
        d.update(plugin_cmds)
    else:
        d2 = plugin_cmds.copy()
        d2.update(d)
        d = d2
    return d

    
def get_all_cmds(plugins_override=True):
    """Return canonical name and class for all registered commands."""
    for k, v in _get_cmd_dict(plugins_override=plugins_override).iteritems():
        yield k,v


def get_cmd_class(cmd, plugins_override=True):
    """Return the canonical name and command class for a command.
    """
    cmd = str(cmd)                      # not unicode

    # first look up this command under the specified name
    cmds = _get_cmd_dict(plugins_override=plugins_override)
    try:
        return cmd, cmds[cmd]
    except KeyError:
        pass

    # look for any command which claims this as an alias
    for cmdname, cmdclass in cmds.iteritems():
        if cmd in cmdclass.aliases:
            return cmdname, cmdclass

    cmdclass = ExternalCommand.find_command(cmd)
    if cmdclass:
        return cmd, cmdclass

    raise BzrCommandError("unknown command %r" % cmd)


class Command(object):
    """Base class for commands.

    The docstring for an actual command should give a single-line
    summary, then a complete description of the command.  A grammar
    description will be inserted.

    takes_args
        List of argument forms, marked with whether they are optional,
        repeated, etc.

    takes_options
        List of options that may be given for this command.

    hidden
        If true, this command isn't advertised.
    """
    aliases = []
    
    takes_args = []
    takes_options = []

    hidden = False
    
    def __init__(self, options, arguments):
        """Construct and run the command.

        Sets self.status to the return value of run()."""
        assert isinstance(options, dict)
        assert isinstance(arguments, dict)
        cmdargs = options.copy()
        cmdargs.update(arguments)
        assert self.__doc__ != Command.__doc__, \
               ("No help message set for %r" % self)
        self.status = self.run(**cmdargs)

    
    def run(self):
        """Override this in sub-classes.

        This is invoked with the options and arguments bound to
        keyword parameters.

        Return 0 or None if the command was successful, or a shell
        error code if not.
        """
        return 0


class ExternalCommand(Command):
    """Class to wrap external commands.

    We cheat a little here, when get_cmd_class() calls us we actually give it back
    an object we construct that has the appropriate path, help, options etc for the
    specified command.

    When run_bzr() tries to instantiate that 'class' it gets caught by the __call__
    method, which we override to call the Command.__init__ method. That then calls
    our run method which is pretty straight forward.

    The only wrinkle is that we have to map bzr's dictionary of options and arguments
    back into command line options and arguments for the script.
    """

    def find_command(cls, cmd):
        import os.path
        bzrpath = os.environ.get('BZRPATH', '')

        for dir in bzrpath.split(os.pathsep):
            path = os.path.join(dir, cmd)
            if os.path.isfile(path):
                return ExternalCommand(path)

        return None

    find_command = classmethod(find_command)

    def __init__(self, path):
        self.path = path

        pipe = os.popen('%s --bzr-usage' % path, 'r')
        self.takes_options = pipe.readline().split()

        for opt in self.takes_options:
            if not opt in OPTIONS:
                raise BzrError("Unknown option '%s' returned by external command %s"
                               % (opt, path))

        # TODO: Is there any way to check takes_args is valid here?
        self.takes_args = pipe.readline().split()

        if pipe.close() is not None:
            raise BzrError("Failed funning '%s --bzr-usage'" % path)

        pipe = os.popen('%s --bzr-help' % path, 'r')
        self.__doc__ = pipe.read()
        if pipe.close() is not None:
            raise BzrError("Failed funning '%s --bzr-help'" % path)

    def __call__(self, options, arguments):
        Command.__init__(self, options, arguments)
        return self

    def run(self, **kargs):
        opts = []
        args = []

        keys = kargs.keys()
        keys.sort()
        for name in keys:
            optname = name.replace('_','-')
            value = kargs[name]
            if OPTIONS.has_key(optname):
                # it's an option
                opts.append('--%s' % optname)
                if value is not None and value is not True:
                    opts.append(str(value))
            else:
                # it's an arg, or arg list
                if type(value) is not list:
                    value = [value]
                for v in value:
                    if v is not None:
                        args.append(str(v))

        self.status = os.spawnv(os.P_WAIT, self.path, [self.path] + opts + args)
        return self.status


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
    """
    takes_args = ['file*']
    takes_options = ['all', 'show-ids']
    aliases = ['st', 'stat']
    
    def run(self, all=False, show_ids=False, file_list=None):
        if file_list:
            b = find_branch(file_list[0])
            file_list = [b.relpath(x) for x in file_list]
            # special case: only one path was given and it's the root
            # of the branch
            if file_list == ['']:
                file_list = None
        else:
            b = find_branch('.')
        import status
        status.show_status(b, show_unchanged=all, show_ids=show_ids,
                           specific_files=file_list)


class cmd_cat_revision(Command):
    """Write out metadata for a revision."""

    hidden = True
    takes_args = ['revision_id']
    
    def run(self, revision_id):
        from bzrlib.xml import pack_xml
        pack_xml(find_branch('.').get_revision(revision_id), sys.stdout)


class cmd_revno(Command):
    """Show current revision number.

    This is equal to the number of revisions on this branch."""
    def run(self):
        print find_branch('.').revno()

    
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
    directories.

    Therefore simply saying 'bzr add .' will version all files that
    are currently unknown.

    TODO: Perhaps adding a file whose directly is not versioned should
    recursively add that parent, rather than giving an error?
    """
    takes_args = ['file+']
    takes_options = ['verbose', 'no-recurse']
    
    def run(self, file_list, verbose=False, no_recurse=False):
        from bzrlib.add import smart_add
        smart_add(file_list, verbose, not no_recurse)



class cmd_mkdir(Command):
    """Create a new versioned directory.

    This is equivalent to creating the directory and then adding it.
    """
    takes_args = ['dir+']

    def run(self, dir_list):
        b = None
        
        for d in dir_list:
            os.mkdir(d)
            if not b:
                b = find_branch(d)
            b.add([d], verbose=True)


class cmd_relpath(Command):
    """Show path of a file relative to root"""
    takes_args = ['filename']
    hidden = True
    
    def run(self, filename):
        print find_branch(filename).relpath(filename)



class cmd_inventory(Command):
    """Show inventory of the current working copy or a revision."""
    takes_options = ['revision', 'show-ids']
    
    def run(self, revision=None, show_ids=False):
        b = find_branch('.')
        if revision == None:
            inv = b.read_working_inventory()
        else:
            inv = b.get_revision_inventory(b.lookup_revision(revision))

        for path, entry in inv.entries():
            if show_ids:
                print '%-50s %s' % (path, entry.file_id)
            else:
                print path


class cmd_move(Command):
    """Move files to a different directory.

    examples:
        bzr move *.txt doc

    The destination must be a versioned directory in the same branch.
    """
    takes_args = ['source$', 'dest']
    def run(self, source_list, dest):
        b = find_branch('.')

        b.move([b.relpath(s) for s in source_list], b.relpath(dest))


class cmd_rename(Command):
    """Change the name of an entry.

    examples:
      bzr rename frob.c frobber.c
      bzr rename src/frob.c lib/frob.c

    It is an error if the destination name exists.

    See also the 'move' command, which moves files into a different
    directory without changing their name.

    TODO: Some way to rename multiple files without invoking bzr for each
    one?"""
    takes_args = ['from_name', 'to_name']
    
    def run(self, from_name, to_name):
        b = find_branch('.')
        b.rename_one(b.relpath(from_name), b.relpath(to_name))





class cmd_pull(Command):
    """Pull any changes from another branch into the current one.

    If the location is omitted, the last-used location will be used.
    Both the revision history and the working directory will be
    updated.

    This command only works on branches that have not diverged.  Branches are
    considered diverged if both branches have had commits without first
    pulling from the other.

    If branches have diverged, you can use 'bzr merge' to pull the text changes
    from one into the other.
    """
    takes_args = ['location?']

    def run(self, location=None):
        from bzrlib.merge import merge
        import tempfile
        from shutil import rmtree
        import errno
        
        br_to = find_branch('.')
        stored_loc = None
        try:
            stored_loc = br_to.controlfile("x-pull", "rb").read().rstrip('\n')
        except IOError, e:
            if e.errno != errno.ENOENT:
                raise
        if location is None:
            if stored_loc is None:
                raise BzrCommandError("No pull location known or specified.")
            else:
                print "Using last location: %s" % stored_loc
                location = stored_loc
        cache_root = tempfile.mkdtemp()
        from bzrlib.branch import DivergedBranches
        br_from = find_branch(location)
        location = pull_loc(br_from)
        old_revno = br_to.revno()
        try:
            from branch import find_cached_branch, DivergedBranches
            br_from = find_cached_branch(location, cache_root)
            location = pull_loc(br_from)
            old_revno = br_to.revno()
            try:
                br_to.update_revisions(br_from)
            except DivergedBranches:
                raise BzrCommandError("These branches have diverged."
                    "  Try merge.")
                
            merge(('.', -1), ('.', old_revno), check_clean=False)
            if location != stored_loc:
                br_to.controlfile("x-pull", "wb").write(location + "\n")
        finally:
            rmtree(cache_root)



class cmd_branch(Command):
    """Create a new copy of a branch.

    If the TO_LOCATION is omitted, the last component of the FROM_LOCATION will
    be used.  In other words, "branch ../foo/bar" will attempt to create ./bar.

    To retrieve the branch as of a particular revision, supply the --revision
    parameter, as in "branch foo/bar -r 5".
    """
    takes_args = ['from_location', 'to_location?']
    takes_options = ['revision']

    def run(self, from_location, to_location=None, revision=None):
        import errno
        from bzrlib.merge import merge
        from bzrlib.branch import DivergedBranches, NoSuchRevision, \
             find_cached_branch, Branch
        from shutil import rmtree
        from meta_store import CachedStore
        import tempfile
        cache_root = tempfile.mkdtemp()
        try:
            try:
                br_from = find_cached_branch(from_location, cache_root)
            except OSError, e:
                if e.errno == errno.ENOENT:
                    raise BzrCommandError('Source location "%s" does not'
                                          ' exist.' % to_location)
                else:
                    raise

            if to_location is None:
                to_location = os.path.basename(from_location.rstrip("/\\"))

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
            br_to = Branch(to_location, init=True)

            try:
                br_to.update_revisions(br_from, stop_revision=revision)
            except NoSuchRevision:
                rmtree(to_location)
                msg = "The branch %s has no revision %d." % (from_location,
                                                             revision)
                raise BzrCommandError(msg)
            merge((to_location, -1), (to_location, 0), this_dir=to_location,
                  check_clean=False, ignore_zero=True)
            from_location = pull_loc(br_from)
            br_to.controlfile("x-pull", "wb").write(from_location + "\n")
        finally:
            rmtree(cache_root)


def pull_loc(branch):
    # TODO: Should perhaps just make attribute be 'base' in
    # RemoteBranch and Branch?
    if hasattr(branch, "baseurl"):
        return branch.baseurl
    else:
        return branch.base



class cmd_renames(Command):
    """Show list of renamed files.

    TODO: Option to show renames between two historical versions.

    TODO: Only show renames under dir, rather than in the whole branch.
    """
    takes_args = ['dir?']

    def run(self, dir='.'):
        b = find_branch(dir)
        old_inv = b.basis_tree().inventory
        new_inv = b.read_working_inventory()

        renames = list(bzrlib.tree.find_renames(old_inv, new_inv))
        renames.sort()
        for old_name, new_name in renames:
            print "%s => %s" % (old_name, new_name)        


class cmd_info(Command):
    """Show statistical information about a branch."""
    takes_args = ['branch?']
    
    def run(self, branch=None):
        import info

        b = find_branch(branch)
        info.show_info(b)


class cmd_remove(Command):
    """Make a file unversioned.

    This makes bzr stop tracking changes to a versioned file.  It does
    not delete the working copy.
    """
    takes_args = ['file+']
    takes_options = ['verbose']
    
    def run(self, file_list, verbose=False):
        b = find_branch(file_list[0])
        b.remove([b.relpath(f) for f in file_list], verbose=verbose)


class cmd_file_id(Command):
    """Print file_id of a particular file or directory.

    The file_id is assigned when the file is first added and remains the
    same through all revisions where the file exists, even when it is
    moved or renamed.
    """
    hidden = True
    takes_args = ['filename']
    def run(self, filename):
        b = find_branch(filename)
        i = b.inventory.path2id(b.relpath(filename))
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
    def run(self, filename):
        b = find_branch(filename)
        inv = b.inventory
        fid = inv.path2id(b.relpath(filename))
        if fid == None:
            raise BzrError("%r is not a versioned file" % filename)
        for fip in inv.get_idpath(fid):
            print fip


class cmd_revision_history(Command):
    """Display list of revision ids on this branch."""
    hidden = True
    def run(self):
        for patchid in find_branch('.').revision_history():
            print patchid


class cmd_directories(Command):
    """Display list of versioned directories in this branch."""
    def run(self):
        for name, ie in find_branch('.').read_working_inventory().directories():
            if name == '':
                print '.'
            else:
                print name


class cmd_init(Command):
    """Make a directory into a versioned branch.

    Use this to create an empty branch, or before importing an
    existing project.

    Recipe for importing a tree of files:
        cd ~/project
        bzr init
        bzr add -v .
        bzr status
        bzr commit -m 'imported project'
    """
    def run(self):
        from bzrlib.branch import Branch
        Branch('.', init=True)


class cmd_diff(Command):
    """Show differences in working tree.
    
    If files are listed, only the changes in those files are listed.
    Otherwise, all changes for the tree are listed.

    TODO: Given two revision arguments, show the difference between them.

    TODO: Allow diff across branches.

    TODO: Option to use external diff command; could be GNU diff, wdiff,
          or a graphical diff.

    TODO: Python difflib is not exactly the same as unidiff; should
          either fix it up or prefer to use an external diff.

    TODO: If a directory is given, diff everything under that.

    TODO: Selected-file diff is inefficient and doesn't show you
          deleted files.

    TODO: This probably handles non-Unix newlines poorly.
    """
    
    takes_args = ['file*']
    takes_options = ['revision', 'diff-options']
    aliases = ['di', 'dif']

    def run(self, revision=None, file_list=None, diff_options=None):
        from bzrlib.diff import show_diff

        if file_list:
            b = find_branch(file_list[0])
            file_list = [b.relpath(f) for f in file_list]
            if file_list == ['']:
                # just pointing to top-of-tree
                file_list = None
        else:
            b = find_branch('.')
    
        show_diff(b, revision, specific_files=file_list,
                  external_diff_options=diff_options)


        


class cmd_deleted(Command):
    """List files deleted in the working tree.

    TODO: Show files deleted since a previous revision, or between two revisions.
    """
    def run(self, show_ids=False):
        b = find_branch('.')
        old = b.basis_tree()
        new = b.working_tree()

        ## TODO: Much more efficient way to do this: read in new
        ## directories with readdir, rather than stating each one.  Same
        ## level of effort but possibly much less IO.  (Or possibly not,
        ## if the directories are very large...)

        for path, ie in old.inventory.iter_entries():
            if not new.has_id(ie.file_id):
                if show_ids:
                    print '%-50s %s' % (path, ie.file_id)
                else:
                    print path


class cmd_modified(Command):
    """List files modified in working tree."""
    hidden = True
    def run(self):
        from bzrlib.statcache import update_cache, SC_SHA1
        b = find_branch('.')
        inv = b.read_working_inventory()
        sc = update_cache(b, inv)
        basis = b.basis_tree()
        basis_inv = basis.inventory
        
        # We used to do this through iter_entries(), but that's slow
        # when most of the files are unmodified, as is usually the
        # case.  So instead we iterate by inventory entry, and only
        # calculate paths as necessary.

        for file_id in basis_inv:
            cacheentry = sc.get(file_id)
            if not cacheentry:                 # deleted
                continue
            ie = basis_inv[file_id]
            if cacheentry[SC_SHA1] != ie.text_sha1:
                path = inv.id2path(file_id)
                print path



class cmd_added(Command):
    """List files added in working tree."""
    hidden = True
    def run(self):
        b = find_branch('.')
        wt = b.working_tree()
        basis_inv = b.basis_tree().inventory
        inv = wt.inventory
        for file_id in inv:
            if file_id in basis_inv:
                continue
            path = inv.id2path(file_id)
            if not os.access(b.abspath(path), os.F_OK):
                continue
            print path
                
        

class cmd_root(Command):
    """Show the tree root directory.

    The root is the nearest enclosing directory with a .bzr control
    directory."""
    takes_args = ['filename?']
    def run(self, filename=None):
        """Print the branch root."""
        b = find_branch(filename)
        print getattr(b, 'base', None) or getattr(b, 'baseurl')


class cmd_log(Command):
    """Show log of this branch.

    To request a range of logs, you can use the command -r begin:end
    -r revision requests a specific revision, -r :end or -r begin: are
    also valid.

    TODO: Make --revision support uuid: and hash: [future tag:] notation.
  
    """

    takes_args = ['filename?']
    takes_options = ['forward', 'timezone', 'verbose', 'show-ids', 'revision','long']
    
    def run(self, filename=None, timezone='original',
            verbose=False,
            show_ids=False,
            forward=False,
            revision=None,
            long=False):
        from bzrlib.branch import find_branch
        from bzrlib.log import log_formatter, show_log
        import codecs

        direction = (forward and 'forward') or 'reverse'
        
        if filename:
            b = find_branch(filename)
            fp = b.relpath(filename)
            if fp:
                file_id = b.read_working_inventory().path2id(fp)
            else:
                file_id = None  # points to branch root
        else:
            b = find_branch('.')
            file_id = None

        if revision == None:
            revision = [None, None]
        elif isinstance(revision, int):
            revision = [revision, revision]
        else:
            # pair of revisions?
            pass
            
        assert len(revision) == 2

        mutter('encoding log as %r' % bzrlib.user_encoding)

        # use 'replace' so that we don't abort if trying to write out
        # in e.g. the default C locale.
        outf = codecs.getwriter(bzrlib.user_encoding)(sys.stdout, errors='replace')

        if long:
            log_format = 'long'
        else:
            log_format = 'short'
        lf = log_formatter(log_format,
                           show_ids=show_ids,
                           to_file=outf,
                           show_timezone=timezone)

        show_log(b,
                 lf,
                 file_id,
                 verbose=verbose,
                 direction=direction,
                 start_revision=revision[0],
                 end_revision=revision[1])



class cmd_touching_revisions(Command):
    """Return revision-ids which affected a particular file.

    A more user-friendly interface is "bzr log FILE"."""
    hidden = True
    takes_args = ["filename"]
    def run(self, filename):
        b = find_branch(filename)
        inv = b.read_working_inventory()
        file_id = inv.path2id(b.relpath(filename))
        for revno, revision_id, what in bzrlib.log.find_touching_revisions(b, file_id):
            print "%6d %s" % (revno, what)


class cmd_ls(Command):
    """List files in a tree.

    TODO: Take a revision or remote path and list that tree instead.
    """
    hidden = True
    def run(self, revision=None, verbose=False):
        b = find_branch('.')
        if revision == None:
            tree = b.working_tree()
        else:
            tree = b.revision_tree(b.lookup_revision(revision))

        for fp, fc, kind, fid in tree.list_files():
            if verbose:
                if kind == 'directory':
                    kindch = '/'
                elif kind == 'file':
                    kindch = ''
                else:
                    kindch = '???'

                print '%-8s %s%s' % (fc, fp, kindch)
            else:
                print fp



class cmd_unknowns(Command):
    """List unknown files."""
    def run(self):
        from bzrlib.osutils import quotefn
        for f in find_branch('.').unknowns():
            print quotefn(f)



class cmd_ignore(Command):
    """Ignore a command or pattern.

    To remove patterns from the ignore list, edit the .bzrignore file.

    If the pattern contains a slash, it is compared to the whole path
    from the branch root.  Otherwise, it is comapred to only the last
    component of the path.

    Ignore patterns are case-insensitive on case-insensitive systems.

    Note: wildcards must be quoted from the shell on Unix.

    examples:
        bzr ignore ./Makefile
        bzr ignore '*.class'
    """
    takes_args = ['name_pattern']
    
    def run(self, name_pattern):
        from bzrlib.atomicfile import AtomicFile
        import os.path

        b = find_branch('.')
        ifn = b.abspath('.bzrignore')

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

        inv = b.working_tree().inventory
        if inv.path2id('.bzrignore'):
            mutter('.bzrignore is already versioned')
        else:
            mutter('need to make new .bzrignore file versioned')
            b.add(['.bzrignore'])



class cmd_ignored(Command):
    """List ignored files and the patterns that matched them.

    See also: bzr ignore"""
    def run(self):
        tree = find_branch('.').working_tree()
        for path, file_class, kind, file_id in tree.list_files():
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
    
    def run(self, revno):
        try:
            revno = int(revno)
        except ValueError:
            raise BzrCommandError("not a valid revision-number: %r" % revno)

        print find_branch('.').lookup_revision(revno)


class cmd_export(Command):
    """Export past revision to destination directory.

    If no revision is specified this exports the last committed revision.

    Format may be an "exporter" name, such as tar, tgz, tbz2.  If none is
    given, exports to a directory (equivalent to --format=dir)."""
    # TODO: list known exporters
    takes_args = ['dest']
    takes_options = ['revision', 'format']
    def run(self, dest, revision=None, format='dir'):
        b = find_branch('.')
        if revision == None:
            rh = b.revision_history()[-1]
        else:
            rh = b.lookup_revision(int(revision))
        t = b.revision_tree(rh)
        t.export(dest, format)


class cmd_cat(Command):
    """Write a file's text from a previous revision."""

    takes_options = ['revision']
    takes_args = ['filename']

    def run(self, filename, revision=None):
        if revision == None:
            raise BzrCommandError("bzr cat requires a revision number")
        b = find_branch('.')
        b.print_file(b.relpath(filename), int(revision))


class cmd_local_time_offset(Command):
    """Show the offset in seconds from GMT to local time."""
    hidden = True    
    def run(self):
        print bzrlib.osutils.local_time_offset()



class cmd_commit(Command):
    """Commit changes into a new revision.

    If selected files are specified, only changes to those files are
    committed.  If a directory is specified then its contents are also
    committed.

    A selected-file commit may fail in some cases where the committed
    tree would be invalid, such as trying to commit a file in a
    newly-added directory that is not itself committed.

    TODO: Run hooks on tree to-be-committed, and after commit.

    TODO: Strict commit that fails if there are unknown or deleted files.
    """
    takes_args = ['selected*']
    takes_options = ['message', 'file', 'verbose']
    aliases = ['ci', 'checkin']

    def run(self, message=None, file=None, verbose=True, selected_list=None):
        from bzrlib.commit import commit
        from bzrlib.osutils import get_text_message

        ## Warning: shadows builtin file()
        if not message and not file:
            import cStringIO
            stdout = sys.stdout
            catcher = cStringIO.StringIO()
            sys.stdout = catcher
            cmd_status({"file_list":selected_list}, {})
            info = catcher.getvalue()
            sys.stdout = stdout
            message = get_text_message(info)
            
            if message is None:
                raise BzrCommandError("please specify a commit message",
                                      ["use either --message or --file"])
        elif message and file:
            raise BzrCommandError("please specify either --message or --file")
        
        if file:
            import codecs
            message = codecs.open(file, 'rt', bzrlib.user_encoding).read()

        b = find_branch('.')
        commit(b, message, verbose=verbose, specific_files=selected_list)


class cmd_check(Command):
    """Validate consistency of branch history.

    This command checks various invariants about the branch storage to
    detect data corruption or bzr bugs.

    If given the --update flag, it will update some optional fields
    to help ensure data consistency.
    """
    takes_args = ['dir?']

    def run(self, dir='.'):
        from bzrlib.check import check
        check(find_branch(dir))



class cmd_upgrade(Command):
    """Upgrade branch storage to current format.

    This should normally be used only after the check command tells
    you to run it.
    """
    takes_args = ['dir?']

    def run(self, dir='.'):
        from bzrlib.upgrade import upgrade
        upgrade(find_branch(dir))



class cmd_whoami(Command):
    """Show bzr user id."""
    takes_options = ['email']
    
    def run(self, email=False):
        if email:
            print bzrlib.osutils.user_email()
        else:
            print bzrlib.osutils.username()


class cmd_selftest(Command):
    """Run internal test suite"""
    hidden = True
    def run(self):
        from bzrlib.selftest import selftest
        return int(not selftest())


class cmd_version(Command):
    """Show version of bzr."""
    def run(self):
        show_version()

def show_version():
    print "bzr (bazaar-ng) %s" % bzrlib.__version__
    # is bzrlib itself in a branch?
    bzrrev = bzrlib.get_bzr_revision()
    if bzrrev:
        print "  (bzr checkout, revision %d {%s})" % bzrrev
    print bzrlib.__copyright__
    print "http://bazaar-ng.org/"
    print
    print "bzr comes with ABSOLUTELY NO WARRANTY.  bzr is free software, and"
    print "you may use, modify and redistribute it under the terms of the GNU"
    print "General Public License version 2 or later."


class cmd_rocks(Command):
    """Statement of optimism."""
    hidden = True
    def run(self):
        print "it sure does!"

def parse_spec(spec):
    """
    >>> parse_spec(None)
    [None, None]
    >>> parse_spec("./")
    ['./', None]
    >>> parse_spec("../@")
    ['..', -1]
    >>> parse_spec("../f/@35")
    ['../f', 35]
    """
    if spec is None:
        return [None, None]
    if '/@' in spec:
        parsed = spec.split('/@')
        assert len(parsed) == 2
        if parsed[1] == "":
            parsed[1] = -1
        else:
            parsed[1] = int(parsed[1])
            assert parsed[1] >=0
    else:
        parsed = [spec, None]
    return parsed



class cmd_merge(Command):
    """Perform a three-way merge of trees.
    
    The SPEC parameters are working tree or revision specifiers.  Working trees
    are specified using standard paths or urls.  No component of a directory
    path may begin with '@'.
    
    Working tree examples: '.', '..', 'foo@', but NOT 'foo/@bar'

    Revisions are specified using a dirname/@revno pair, where dirname is the
    branch directory and revno is the revision within that branch.  If no revno
    is specified, the latest revision is used.

    Revision examples: './@127', 'foo/@', '../@1'

    The OTHER_SPEC parameter is required.  If the BASE_SPEC parameter is
    not supplied, the common ancestor of OTHER_SPEC the current branch is used
    as the BASE.

    merge refuses to run if there are any uncommitted changes, unless
    --force is given.
    """
    takes_args = ['other_spec', 'base_spec?']
    takes_options = ['force']

    def run(self, other_spec, base_spec=None, force=False):
        from bzrlib.merge import merge
        merge(parse_spec(other_spec), parse_spec(base_spec),
              check_clean=(not force))



class cmd_revert(Command):
    """Restore selected files from a previous revision.
    """
    takes_args = ['file+']
    def run(self, file_list):
        from bzrlib.branch import find_branch
        
        if not file_list:
            file_list = ['.']
            
        b = find_branch(file_list[0])

        b.revert([b.relpath(f) for f in file_list])


class cmd_merge_revert(Command):
    """Reverse all changes since the last commit.

    Only versioned files are affected.

    TODO: Store backups of any files that will be reverted, so
          that the revert can be undone.          
    """
    takes_options = ['revision']

    def run(self, revision=-1):
        from bzrlib.merge import merge
        merge(('.', revision), parse_spec('.'),
              check_clean=False,
              ignore_zero=True)


class cmd_assert_fail(Command):
    """Test reporting of assertion failures"""
    hidden = True
    def run(self):
        assert False, "always fails"


class cmd_help(Command):
    """Show help on a command or other topic.

    For a list of all available commands, say 'bzr help commands'."""
    takes_args = ['topic?']
    aliases = ['?']
    
    def run(self, topic=None):
        import help
        help.help(topic)


class cmd_update_stat_cache(Command):
    """Update stat-cache mapping inodes to SHA-1 hashes.

    For testing only."""
    hidden = True
    def run(self):
        from bzrlib.statcache import update_cache
        b = find_branch('.')
        update_cache(b.base, b.read_working_inventory())



class cmd_plugins(Command):
    """List plugins"""
    hidden = True
    def run(self):
        import bzrlib.plugin
        from pprint import pprint
        pprint(bzrlib.plugin.all_plugins)



# list of all available options; the rhs can be either None for an
# option that takes no argument, or a constructor function that checks
# the type.
OPTIONS = {
    'all':                    None,
    'diff-options':           str,
    'help':                   None,
    'file':                   unicode,
    'force':                  None,
    'format':                 unicode,
    'forward':                None,
    'message':                unicode,
    'no-recurse':             None,
    'profile':                None,
    'revision':               _parse_revision_str,
    'show-ids':               None,
    'timezone':               str,
    'verbose':                None,
    'version':                None,
    'email':                  None,
    'update':                 None,
    'long':                   None,
    }

SHORT_OPTIONS = {
    'F':                      'file', 
    'h':                      'help',
    'm':                      'message',
    'r':                      'revision',
    'v':                      'verbose',
    'l':                      'long',
}


def parse_args(argv):
    """Parse command line.
    
    Arguments and options are parsed at this level before being passed
    down to specific command handlers.  This routine knows, from a
    lookup table, something about the available options, what optargs
    they take, and which commands will accept them.

    >>> parse_args('--help'.split())
    ([], {'help': True})
    >>> parse_args('--version'.split())
    ([], {'version': True})
    >>> parse_args('status --all'.split())
    (['status'], {'all': True})
    >>> parse_args('commit --message=biter'.split())
    (['commit'], {'message': u'biter'})
    >>> parse_args('log -r 500'.split())
    (['log'], {'revision': 500})
    >>> parse_args('log -r500:600'.split())
    (['log'], {'revision': [500, 600]})
    >>> parse_args('log -vr500:600'.split())
    (['log'], {'verbose': True, 'revision': [500, 600]})
    >>> parse_args('log -rv500:600'.split()) #the r takes an argument
    Traceback (most recent call last):
    ...
    ValueError: invalid literal for int(): v500
    """
    args = []
    opts = {}

    # TODO: Maybe handle '--' to end options?

    while argv:
        a = argv.pop(0)
        if a[0] == '-':
            # option names must not be unicode
            a = str(a)
            optarg = None
            if a[1] == '-':
                mutter("  got option %r" % a)
                if '=' in a:
                    optname, optarg = a[2:].split('=', 1)
                else:
                    optname = a[2:]
                if optname not in OPTIONS:
                    raise BzrError('unknown long option %r' % a)
            else:
                shortopt = a[1:]
                if shortopt in SHORT_OPTIONS:
                    # Multi-character options must have a space to delimit
                    # their value
                    optname = SHORT_OPTIONS[shortopt]
                else:
                    # Single character short options, can be chained,
                    # and have their value appended to their name
                    shortopt = a[1:2]
                    if shortopt not in SHORT_OPTIONS:
                        # We didn't find the multi-character name, and we
                        # didn't find the single char name
                        raise BzrError('unknown short option %r' % a)
                    optname = SHORT_OPTIONS[shortopt]

                    if a[2:]:
                        # There are extra things on this option
                        # see if it is the value, or if it is another
                        # short option
                        optargfn = OPTIONS[optname]
                        if optargfn is None:
                            # This option does not take an argument, so the
                            # next entry is another short option, pack it back
                            # into the list
                            argv.insert(0, '-' + a[2:])
                        else:
                            # This option takes an argument, so pack it
                            # into the array
                            optarg = a[2:]
            
            if optname in opts:
                # XXX: Do we ever want to support this, e.g. for -r?
                raise BzrError('repeated option %r' % a)
                
            optargfn = OPTIONS[optname]
            if optargfn:
                if optarg == None:
                    if not argv:
                        raise BzrError('option %r needs an argument' % a)
                    else:
                        optarg = argv.pop(0)
                opts[optname] = optargfn(optarg)
            else:
                if optarg != None:
                    raise BzrError('option %r takes no argument' % optname)
                opts[optname] = True
        else:
            args.append(a)

    return args, opts




def _match_argform(cmd, takes_args, args):
    argdict = {}

    # step through args and takes_args, allowing appropriate 0-many matches
    for ap in takes_args:
        argname = ap[:-1]
        if ap[-1] == '?':
            if args:
                argdict[argname] = args.pop(0)
        elif ap[-1] == '*': # all remaining arguments
            if args:
                argdict[argname + '_list'] = args[:]
                args = []
            else:
                argdict[argname + '_list'] = None
        elif ap[-1] == '+':
            if not args:
                raise BzrCommandError("command %r needs one or more %s"
                        % (cmd, argname.upper()))
            else:
                argdict[argname + '_list'] = args[:]
                args = []
        elif ap[-1] == '$': # all but one
            if len(args) < 2:
                raise BzrCommandError("command %r needs one or more %s"
                        % (cmd, argname.upper()))
            argdict[argname + '_list'] = args[:-1]
            args[:-1] = []                
        else:
            # just a plain arg
            argname = ap
            if not args:
                raise BzrCommandError("command %r requires argument %s"
                        % (cmd, argname.upper()))
            else:
                argdict[argname] = args.pop(0)
            
    if args:
        raise BzrCommandError("extra argument to command %s: %s"
                              % (cmd, args[0]))

    return argdict


def _parse_master_args(argv):
    """Parse the arguments that always go with the original command.
    These are things like bzr --no-plugins, etc.

    There are now 2 types of option flags. Ones that come *before* the command,
    and ones that come *after* the command.
    Ones coming *before* the command are applied against all possible commands.
    And are generally applied before plugins are loaded.

    The current list are:
        --builtin   Allow plugins to load, but don't let them override builtin commands,
                    they will still be allowed if they do not override a builtin.
        --no-plugins    Don't load any plugins. This lets you get back to official source
                        behavior.
        --profile   Enable the hotspot profile before running the command.
                    For backwards compatibility, this is also a non-master option.
        --version   Spit out the version of bzr that is running and exit.
                    This is also a non-master option.
        --help      Run help and exit, also a non-master option (I think that should stay, though)

    >>> argv, opts = _parse_master_args(['bzr', '--test'])
    Traceback (most recent call last):
    ...
    BzrCommandError: Invalid master option: 'test'
    >>> argv, opts = _parse_master_args(['bzr', '--version', 'command'])
    >>> print argv
    ['command']
    >>> print opts['version']
    True
    >>> argv, opts = _parse_master_args(['bzr', '--profile', 'command', '--more-options'])
    >>> print argv
    ['command', '--more-options']
    >>> print opts['profile']
    True
    >>> argv, opts = _parse_master_args(['bzr', '--no-plugins', 'command'])
    >>> print argv
    ['command']
    >>> print opts['no-plugins']
    True
    >>> print opts['profile']
    False
    >>> argv, opts = _parse_master_args(['bzr', 'command', '--profile'])
    >>> print argv
    ['command', '--profile']
    >>> print opts['profile']
    False
    """
    master_opts = {'builtin':False,
        'no-plugins':False,
        'version':False,
        'profile':False,
        'help':False
    }

    # This is the point where we could hook into argv[0] to determine
    # what front-end is supposed to be run
    # For now, we are just ignoring it.
    cmd_name = argv.pop(0)
    for arg in argv[:]:
        if arg[:2] != '--': # at the first non-option, we return the rest
            break
        arg = arg[2:] # Remove '--'
        if arg not in master_opts:
            # We could say that this is not an error, that we should
            # just let it be handled by the main section instead
            raise BzrCommandError('Invalid master option: %r' % arg)
        argv.pop(0) # We are consuming this entry
        master_opts[arg] = True
    return argv, master_opts



def run_bzr(argv):
    """Execute a command.

    This is similar to main(), but without all the trappings for
    logging and error handling.  
    """
    argv = [a.decode(bzrlib.user_encoding) for a in argv]
    
    try:
        # some options like --builtin and --no-plugins have special effects
        argv, master_opts = _parse_master_args(argv)
        if not master_opts['no-plugins']:
            from bzrlib.plugin import load_plugins
            load_plugins()

        args, opts = parse_args(argv)

        if master_opts['help']:
            from bzrlib.help import help
            if argv:
                help(argv[0])
            else:
                help()
            return 0            
            
        if 'help' in opts:
            from bzrlib.help import help
            if args:
                help(args[0])
            else:
                help()
            return 0
        elif 'version' in opts:
            show_version()
            return 0
        elif args and args[0] == 'builtin':
            include_plugins=False
            args = args[1:]
        cmd = str(args.pop(0))
    except IndexError:
        import help
        help.help()
        return 1
          

    plugins_override = not (master_opts['builtin'])
    canonical_cmd, cmd_class = get_cmd_class(cmd, plugins_override=plugins_override)

    profile = master_opts['profile']
    # For backwards compatibility, I would rather stick with --profile being a
    # master/global option
    if 'profile' in opts:
        profile = True
        del opts['profile']

    # check options are reasonable
    allowed = cmd_class.takes_options
    for oname in opts:
        if oname not in allowed:
            raise BzrCommandError("option '--%s' is not allowed for command %r"
                                  % (oname, cmd))

    # mix arguments and options into one dictionary
    cmdargs = _match_argform(cmd, cmd_class.takes_args, args)
    cmdopts = {}
    for k, v in opts.items():
        cmdopts[k.replace('-', '_')] = v

    if profile:
        import hotshot, tempfile
        pffileno, pfname = tempfile.mkstemp()
        try:
            prof = hotshot.Profile(pfname)
            ret = prof.runcall(cmd_class, cmdopts, cmdargs) or 0
            prof.close()

            import hotshot.stats
            stats = hotshot.stats.load(pfname)
            #stats.strip_dirs()
            stats.sort_stats('time')
            ## XXX: Might like to write to stderr or the trace file instead but
            ## print_stats seems hardcoded to stdout
            stats.print_stats(20)
            
            return ret.status

        finally:
            os.close(pffileno)
            os.remove(pfname)
    else:
        return cmd_class(cmdopts, cmdargs).status 


def _report_exception(summary, quiet=False):
    import traceback
    log_error('bzr: ' + summary)
    bzrlib.trace.log_exception()

    if not quiet:
        tb = sys.exc_info()[2]
        exinfo = traceback.extract_tb(tb)
        if exinfo:
            sys.stderr.write('  at %s:%d in %s()\n' % exinfo[-1][:3])
        sys.stderr.write('  see ~/.bzr.log for debug information\n')



def main(argv):
    
    bzrlib.trace.open_tracefile(argv)

    try:
        try:
            try:
                return run_bzr(argv)
            finally:
                # do this here inside the exception wrappers to catch EPIPE
                sys.stdout.flush()
        except BzrError, e:
            quiet = isinstance(e, (BzrCommandError))
            _report_exception('error: ' + e.args[0], quiet=quiet)
            if len(e.args) > 1:
                for h in e.args[1]:
                    # some explanation or hints
                    log_error('  ' + h)
            return 1
        except AssertionError, e:
            msg = 'assertion failed'
            if str(e):
                msg += ': ' + str(e)
            _report_exception(msg)
            return 2
        except KeyboardInterrupt, e:
            _report_exception('interrupted', quiet=True)
            return 2
        except Exception, e:
            import errno
            quiet = False
            if (isinstance(e, IOError) 
                and hasattr(e, 'errno')
                and e.errno == errno.EPIPE):
                quiet = True
                msg = 'broken pipe'
            else:
                msg = str(e).rstrip('\n')
            _report_exception(msg, quiet)
            return 2
    finally:
        bzrlib.trace.close_trace()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
