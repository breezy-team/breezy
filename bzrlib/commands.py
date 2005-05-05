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



import sys, os, time, os.path
from sets import Set

import bzrlib
from bzrlib.trace import mutter, note, log_error
from bzrlib.errors import bailout, BzrError, BzrCheckError, BzrCommandError
from bzrlib.osutils import quotefn, pumpfile, isdir, isfile
from bzrlib.tree import RevisionTree, EmptyTree, WorkingTree, Tree
from bzrlib.revision import Revision
from bzrlib import Branch, Inventory, InventoryEntry, ScratchBranch, BZRDIR, \
     format_date


def _squish_command_name(cmd):
    return 'cmd_' + cmd.replace('-', '_')


def _unsquish_command_name(cmd):
    assert cmd.startswith("cmd_")
    return cmd[4:].replace('_','-')

def get_all_cmds():
    """Return canonical name and class for all registered commands."""
    for k, v in globals().iteritems():
        if k.startswith("cmd_"):
            yield _unsquish_command_name(k), v

def get_cmd_class(cmd):
    """Return the canonical name and command class for a command.
    """
    cmd = str(cmd)                      # not unicode

    # first look up this command under the specified name
    try:
        return cmd, globals()[_squish_command_name(cmd)]
    except KeyError:
        pass

    # look for any command which claims this as an alias
    for cmdname, cmdclass in get_all_cmds():
        if cmd in cmdclass.aliases:
            return cmdname, cmdclass
    else:
        raise BzrCommandError("unknown command %r" % cmd)


class Command:
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



class cmd_status(Command):
    """Display status summary.

    For each file there is a single line giving its file state and name.
    The name is that in the current revision unless it is deleted or
    missing, in which case the old name is shown.
    """
    takes_options = ['all']
    aliases = ['st', 'stat']
    
    def run(self, all=False):
        #import bzrlib.status
        #bzrlib.status.tree_status(Branch('.'))
        Branch('.').show_status(show_all=all)


class cmd_cat_revision(Command):
    """Write out metadata for a revision."""

    hidden = True
    takes_args = ['revision_id']
    
    def run(self, revision_id):
        Branch('.').get_revision(revision_id).write_xml(sys.stdout)


class cmd_revno(Command):
    """Show current revision number.

    This is equal to the number of revisions on this branch."""
    def run(self):
        print Branch('.').revno()

    
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
    takes_options = ['verbose']
    
    def run(self, file_list, verbose=False):
        bzrlib.add.smart_add(file_list, verbose)


def Relpath(Command):
    """Show path of a file relative to root"""
    takes_args = ('filename')
    
    def run(self):
        print Branch(self.args['filename']).relpath(filename)



class cmd_inventory(Command):
    """Show inventory of the current working copy or a revision."""
    takes_options = ['revision']
    
    def run(self, revision=None):
        b = Branch('.')
        if revision == None:
            inv = b.read_working_inventory()
        else:
            inv = b.get_revision_inventory(b.lookup_revision(revision))

        for path, entry in inv.iter_entries():
            print '%-50s %s' % (entry.file_id, path)


class cmd_move(Command):
    """Move files to a different directory.

    examples:
        bzr move *.txt doc

    The destination must be a versioned directory in the same branch.
    """
    takes_args = ['source$', 'dest']
    def run(self, source_list, dest):
        b = Branch('.')

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
        b = Branch('.')
        b.rename_one(b.relpath(from_name), b.relpath(to_name))



class cmd_renames(Command):
    """Show list of renamed files.

    TODO: Option to show renames between two historical versions.

    TODO: Only show renames under dir, rather than in the whole branch.
    """
    takes_args = ['dir?']

    def run(self, dir='.'):
        b = Branch(dir)
        old_inv = b.basis_tree().inventory
        new_inv = b.read_working_inventory()

        renames = list(bzrlib.tree.find_renames(old_inv, new_inv))
        renames.sort()
        for old_name, new_name in renames:
            print "%s => %s" % (old_name, new_name)        


class cmd_info(Command):
    """Show statistical information for this branch"""
    def run(self):
        import info
        info.show_info(Branch('.'))        


class cmd_remove(Command):
    """Make a file unversioned.

    This makes bzr stop tracking changes to a versioned file.  It does
    not delete the working copy.
    """
    takes_args = ['file+']
    takes_options = ['verbose']
    
    def run(self, file_list, verbose=False):
        b = Branch(file_list[0])
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
        b = Branch(filename)
        i = b.inventory.path2id(b.relpath(filename))
        if i == None:
            bailout("%r is not a versioned file" % filename)
        else:
            print i


class cmd_file_path(Command):
    """Print path of file_ids to a file or directory.

    This prints one line for each directory down to the target,
    starting at the branch root."""
    hidden = True
    takes_args = ['filename']
    def run(self, filename):
        b = Branch(filename)
        inv = b.inventory
        fid = inv.path2id(b.relpath(filename))
        if fid == None:
            bailout("%r is not a versioned file" % filename)
        for fip in inv.get_idpath(fid):
            print fip


class cmd_revision_history(Command):
    """Display list of revision ids on this branch."""
    def run(self):
        for patchid in Branch('.').revision_history():
            print patchid


class cmd_directories(Command):
    """Display list of versioned directories in this branch."""
    def run(self):
        for name, ie in Branch('.').read_working_inventory().directories():
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
    takes_options = ['revision']
    aliases = ['di']

    def run(self, revision=None, file_list=None):
        from bzrlib.diff import show_diff
    
        show_diff(Branch('.'), revision, file_list)


class cmd_deleted(Command):
    """List files deleted in the working tree.

    TODO: Show files deleted since a previous revision, or between two revisions.
    """
    def run(self, show_ids=False):
        b = Branch('.')
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

class cmd_root(Command):
    """Show the tree root directory.

    The root is the nearest enclosing directory with a .bzr control
    directory."""
    takes_args = ['filename?']
    def run(self, filename=None):
        """Print the branch root."""
        print bzrlib.branch.find_branch_root(filename)



class cmd_log(Command):
    """Show log of this branch.

    TODO: Option to limit range.

    TODO: Perhaps show most-recent first with an option for last.

    TODO: Option to limit to only a single file or to get log for a
          different directory.
    """
    takes_options = ['timezone', 'verbose', 'show-ids']
    def run(self, timezone='original', verbose=False, show_ids=False):
        b = Branch('.', lock_mode='r')
        bzrlib.show_log(b,
                        show_timezone=timezone,
                        verbose=verbose,
                        show_ids=show_ids)



class cmd_touching_revisions(Command):
    """Return revision-ids which affected a particular file."""
    hidden = True
    takes_args = ["filename"]
    def run(self, filename):
        b = Branch(filename, lock_mode='r')
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
        b = Branch('.')
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
    """List unknown files"""
    def run(self):
        for f in Branch('.').unknowns():
            print quotefn(f)



class cmd_ignore(Command):
    """Ignore a command or pattern"""
    takes_args = ['name_pattern']
    
    def run(self, name_pattern):
        b = Branch('.')

        # XXX: This will fail if it's a hardlink; should use an AtomicFile class.
        f = open(b.abspath('.bzrignore'), 'at')
        f.write(name_pattern + '\n')
        f.close()

        inv = b.working_tree().inventory
        if inv.path2id('.bzrignore'):
            mutter('.bzrignore is already versioned')
        else:
            mutter('need to make new .bzrignore file versioned')
            b.add(['.bzrignore'])



class cmd_ignored(Command):
    """List ignored files and the patterns that matched them."""
    def run(self):
        tree = Branch('.').working_tree()
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

        print Branch('.').lookup_revision(revno)


class cmd_export(Command):
    """Export past revision to destination directory.

    If no revision is specified this exports the last committed revision."""
    takes_args = ['dest']
    takes_options = ['revision']
    def run(self, dest, revno=None):
        b = Branch('.')
        if revno == None:
            rh = b.revision_history[-1]
        else:
            rh = b.lookup_revision(int(revno))
        t = b.revision_tree(rh)
        t.export(dest)


class cmd_cat(Command):
    """Write a file's text from a previous revision."""

    takes_options = ['revision']
    takes_args = ['filename']

    def run(self, filename, revision=None):
        if revision == None:
            raise BzrCommandError("bzr cat requires a revision number")
        b = Branch('.')
        b.print_file(b.relpath(filename), int(revision))


class cmd_local_time_offset(Command):
    """Show the offset in seconds from GMT to local time."""
    hidden = True    
    def run(self):
        print bzrlib.osutils.local_time_offset()



class cmd_commit(Command):
    """Commit changes into a new revision.

    TODO: Commit only selected files.

    TODO: Run hooks on tree to-be-committed, and after commit.

    TODO: Strict commit that fails if there are unknown or deleted files.
    """
    takes_options = ['message', 'verbose']
    aliases = ['ci', 'checkin']

    def run(self, message=None, verbose=False):
        if not message:
            raise BzrCommandError("please specify a commit message")
        Branch('.').commit(message, verbose=verbose)


class cmd_check(Command):
    """Validate consistency of branch history.

    This command checks various invariants about the branch storage to
    detect data corruption or bzr bugs.
    """
    takes_args = ['dir?']
    def run(self, dir='.'):
        import bzrlib.check
        bzrlib.check.check(Branch(dir, find_root=False))



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
        failures, tests = 0, 0

        import doctest, bzrlib.store, bzrlib.tests
        bzrlib.trace.verbose = False

        for m in bzrlib.store, bzrlib.inventory, bzrlib.branch, bzrlib.osutils, \
            bzrlib.tree, bzrlib.tests, bzrlib.commands, bzrlib.add:
            mf, mt = doctest.testmod(m)
            failures += mf
            tests += mt
            print '%-40s %3d tests' % (m.__name__, mt),
            if mf:
                print '%3d FAILED!' % mf
            else:
                print

        print '%-40s %3d tests' % ('total', tests),
        if failures:
            print '%3d FAILED!' % failures
        else:
            print



class cmd_version(Command):
    """Show version of bzr"""
    def run(self):
        show_version()

def show_version():
    print "bzr (bazaar-ng) %s" % bzrlib.__version__
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


######################################################################
# main routine


# list of all available options; the rhs can be either None for an
# option that takes no argument, or a constructor function that checks
# the type.
OPTIONS = {
    'all':                    None,
    'help':                   None,
    'message':                unicode,
    'profile':                None,
    'revision':               int,
    'show-ids':               None,
    'timezone':               str,
    'verbose':                None,
    'version':                None,
    'email':                  None,
    }

SHORT_OPTIONS = {
    'm':                      'message',
    'r':                      'revision',
    'v':                      'verbose',
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
                    bailout('unknown long option %r' % a)
            else:
                shortopt = a[1:]
                if shortopt not in SHORT_OPTIONS:
                    bailout('unknown short option %r' % a)
                optname = SHORT_OPTIONS[shortopt]
            
            if optname in opts:
                # XXX: Do we ever want to support this, e.g. for -r?
                bailout('repeated option %r' % a)
                
            optargfn = OPTIONS[optname]
            if optargfn:
                if optarg == None:
                    if not argv:
                        bailout('option %r needs an argument' % a)
                    else:
                        optarg = argv.pop(0)
                opts[optname] = optargfn(optarg)
            else:
                if optarg != None:
                    bailout('option %r takes no argument' % optname)
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



def run_bzr(argv):
    """Execute a command.

    This is similar to main(), but without all the trappings for
    logging and error handling.  
    """
    argv = [a.decode(bzrlib.user_encoding) for a in argv]
    
    try:
        args, opts = parse_args(argv[1:])
        if 'help' in opts:
            import help
            if args:
                help.help(args[0])
            else:
                help.help()
            return 0
        elif 'version' in opts:
            show_version()
            return 0
        cmd = str(args.pop(0))
    except IndexError:
        log_error('usage: bzr COMMAND')
        log_error('  try "bzr help"')
        return 1

    canonical_cmd, cmd_class = get_cmd_class(cmd)

    # global option
    if 'profile' in opts:
        profile = True
        del opts['profile']
    else:
        profile = False

    # check options are reasonable
    allowed = cmd_class.takes_options
    for oname in opts:
        if oname not in allowed:
            raise BzrCommandError("option %r is not allowed for command %r"
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
        cmdobj = cmd_class(cmdopts, cmdargs).status 


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
    import errno
    
    bzrlib.open_tracefile(argv)

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
            quiet = False
            if isinstance(e, IOError) and e.errno == errno.EPIPE:
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
