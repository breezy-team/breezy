# Copyright (C) 2004, 2005 by Martin Pool
# Copyright (C) 2005 by Canonical Ltd


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

"""Bazaar-NG -- a free distributed version-control tool

**WARNING: THIS IS AN UNSTABLE DEVELOPMENT VERSION**

Current limitation include:

* Metadata format is not stable yet -- you may need to
  discard history in the future.

* Insufficient error handling.

* Many commands unimplemented or partially implemented.

* Space-inefficient storage.

* No merge operators yet.

Interesting commands::

  bzr help [COMMAND]
       Show help screen
  bzr version
       Show software version/licence/non-warranty.
  bzr init
       Start versioning the current directory
  bzr add FILE...
       Make files versioned.
  bzr log
       Show revision history.
  bzr diff
       Show changes from last revision to working copy.
  bzr commit -m 'MESSAGE'
       Store current state as new revision.
  bzr export REVNO DESTINATION
       Export the branch state at a previous version.
  bzr status
       Show summary of pending changes.
  bzr remove FILE...
       Make a file not versioned.
  bzr info
       Show statistics about this branch.
"""




import sys, os, random, time, sha, sets, types, re, shutil, tempfile
import traceback, socket, fnmatch, difflib
from os import path
from sets import Set
from pprint import pprint
from stat import *
from glob import glob

import bzrlib
from bzrlib.store import ImmutableStore
from bzrlib.trace import mutter, note, log_error
from bzrlib.errors import bailout, BzrError
from bzrlib.osutils import quotefn, pumpfile, isdir, isfile
from bzrlib.tree import RevisionTree, EmptyTree, WorkingTree, Tree
from bzrlib.revision import Revision
from bzrlib import Branch, Inventory, InventoryEntry, ScratchBranch, BZRDIR, \
     format_date

BZR_DIFF_FORMAT = "## Bazaar-NG diff, format 0 ##\n"
BZR_PATCHNAME_FORMAT = 'cset:sha1:%s'

## standard representation
NONE_STRING = '(none)'
EMPTY = 'empty'


## TODO: Perhaps a different version of inventory commands that
## returns iterators...

## TODO: Perhaps an AtomicFile class that writes to a temporary file and then renames.

## TODO: Some kind of locking on branches.  Perhaps there should be a
## parameter to the branch object saying whether we want a read or
## write lock; release it from destructor.  Perhaps don't even need a
## read lock to look at immutable objects?

## TODO: Perhaps make UUIDs predictable in test mode to make it easier
## to compare output?

## TODO: Some kind of global code to generate the right Branch object
## to work on.  Almost, but not quite all, commands need one, and it
## can be taken either from their parameters or their working
## directory.

## TODO: rename command, needed soon: check destination doesn't exist
## either in working copy or tree; move working copy; update
## inventory; write out

## TODO: move command; check destination is a directory and will not
## clash; move it.

## TODO: command to show renames, one per line, as to->from




def cmd_status(all=False):
    """Display status summary.

    For each file there is a single line giving its file state and name.
    The name is that in the current revision unless it is deleted or
    missing, in which case the old name is shown.

    :todo: Don't show unchanged files unless ``--all`` is given?
    """
    Branch('.').show_status(show_all=all)



######################################################################
# examining history
def cmd_get_revision(revision_id):
    Branch('.').get_revision(revision_id).write_xml(sys.stdout)


def cmd_get_file_text(text_id):
    """Get contents of a file by hash."""
    sf = Branch('.').text_store[text_id]
    pumpfile(sf, sys.stdout)



######################################################################
# commands
    

def cmd_revno():
    """Show number of revisions on this branch"""
    print Branch('.').revno()
    

    
def cmd_add(file_list, verbose=False):
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
    """
    bzrlib.add.smart_add(file_list, verbose)
    

def cmd_relpath(filename):
    """Show path of file relative to root"""
    print Branch(filename).relpath(filename)


def cmd_inventory(revision=None):
    """Show inventory of the current working copy."""
    ## TODO: Also optionally show a previous inventory
    ## TODO: Format options
    b = Branch('.')
    if revision == None:
        inv = b.read_working_inventory()
    else:
        inv = b.get_revision_inventory(b.lookup_revision(revision))
        
    for path, entry in inv.iter_entries():
        print '%-50s %s' % (entry.file_id, path)



def cmd_info():
    """info: Show statistical information for this branch

usage: bzr info"""
    import info
    info.show_info(Branch('.'))        
    


def cmd_remove(file_list, verbose=False):
    b = Branch(file_list[0])
    b.remove([b.relpath(f) for f in file_list], verbose=verbose)



def cmd_file_id(filename):
    b = Branch(filename)
    i = b.inventory.path2id(b.relpath(filename))
    if i is None:
        bailout("%s is not a versioned file" % filename)
    else:
        print i


def cmd_find_filename(fileid):
    n = find_filename(fileid)
    if n is None:
        bailout("%s is not a live file id" % fileid)
    else:
        print n


def cmd_revision_history():
    for patchid in Branch('.').revision_history():
        print patchid



def cmd_init():
    # TODO: Check we're not already in a working directory?  At the
    # moment you'll get an ugly error.
    
    # TODO: What if we're in a subdirectory of a branch?  Would like
    # to allow that, but then the parent may need to understand that
    # the children have disappeared, or should they be versioned in
    # both?

    # TODO: Take an argument/option for branch name.
    Branch('.', init=True)


def cmd_diff(revision=None):
    """bzr diff: Show differences in working tree.
    
usage: bzr diff [-r REV]

--revision REV
    Show changes since REV, rather than predecessor.

TODO: Given two revision arguments, show the difference between them.

TODO: Allow diff across branches.

TODO: Option to use external diff command; could be GNU diff, wdiff,
or a graphical diff.

TODO: Diff selected files.
"""

    ## TODO: Shouldn't be in the cmd function.

    b = Branch('.')

    if revision == None:
        old_tree = b.basis_tree()
    else:
        old_tree = b.revision_tree(b.lookup_revision(revision))
        
    new_tree = b.working_tree()
    old_inv = old_tree.inventory
    new_inv = new_tree.inventory

    # TODO: Options to control putting on a prefix or suffix, perhaps as a format string
    old_label = ''
    new_label = ''

    DEVNULL = '/dev/null'
    # Windows users, don't panic about this filename -- it is a
    # special signal to GNU patch that the file should be created or
    # deleted respectively.

    # TODO: Generation of pseudo-diffs for added/deleted files could
    # be usefully made into a much faster special case.

    # TODO: Better to return them in sorted order I think.
    
    for file_state, fid, old_name, new_name, kind in bzrlib.diff_trees(old_tree, new_tree):
        d = None

        # Don't show this by default; maybe do it if an option is passed
        # idlabel = '      {%s}' % fid
        idlabel = ''

        # FIXME: Something about the diff format makes patch unhappy
        # with newly-added files.

        def diffit(*a, **kw):
            sys.stdout.writelines(difflib.unified_diff(*a, **kw))
            print
        
        if file_state in ['.', '?', 'I']:
            continue
        elif file_state == 'A':
            print '*** added %s %r' % (kind, new_name)
            if kind == 'file':
                diffit([],
                       new_tree.get_file(fid).readlines(),
                       fromfile=DEVNULL,
                       tofile=new_label + new_name + idlabel)
        elif file_state == 'D':
            assert isinstance(old_name, types.StringTypes)
            print '*** deleted %s %r' % (kind, old_name)
            if kind == 'file':
                diffit(old_tree.get_file(fid).readlines(), [],
                       fromfile=old_label + old_name + idlabel,
                       tofile=DEVNULL)
        elif file_state in ['M', 'R']:
            if file_state == 'M':
                assert kind == 'file'
                assert old_name == new_name
                print '*** modified %s %r' % (kind, new_name)
            elif file_state == 'R':
                print '*** renamed %s %r => %r' % (kind, old_name, new_name)

            if kind == 'file':
                diffit(old_tree.get_file(fid).readlines(),
                       new_tree.get_file(fid).readlines(),
                       fromfile=old_label + old_name + idlabel,
                       tofile=new_label + new_name)
        else:
            bailout("can't represent state %s {%s}" % (file_state, fid))



def cmd_deleted(show_ids=False):
    """List files deleted in the working tree.

TODO: Show files deleted since a previous revision, or between two revisions.
    """
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



def cmd_parse_inventory():
    import cElementTree
    
    cElementTree.ElementTree().parse(file('.bzr/inventory'))



def cmd_load_inventory():
    inv = Branch('.').basis_tree().inventory



def cmd_dump_new_inventory():
    import bzrlib.newinventory
    inv = Branch('.').basis_tree().inventory
    bzrlib.newinventory.write_inventory(inv, sys.stdout)


def cmd_load_new_inventory():
    import bzrlib.newinventory
    bzrlib.newinventory.read_new_inventory(sys.stdin)
                
    
def cmd_dump_slacker_inventory():
    import bzrlib.newinventory
    inv = Branch('.').basis_tree().inventory
    bzrlib.newinventory.write_slacker_inventory(inv, sys.stdout)
                
    

def cmd_root(filename=None):
    """Print the branch root."""
    print bzrlib.branch.find_branch_root(filename)
    

def cmd_log(timezone='original'):
    """Show log of this branch.

    :todo: Options for utc; to show ids; to limit range; etc.
    """
    Branch('.').write_log(show_timezone=timezone)


def cmd_ls(revision=None, verbose=False):
    """List files in a tree.

    :todo: Take a revision or remote path and list that tree instead.
    """
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
    
    

def cmd_unknowns():
    """List unknown files"""
    for f in Branch('.').unknowns():
        print quotefn(f)



def cmd_ignored(verbose=True):
    """List ignored files and the patterns that matched them.
      """
    tree = Branch('.').working_tree()
    for path, file_class, kind, id in tree.list_files():
        if file_class != 'I':
            continue
        ## XXX: Slightly inefficient since this was already calculated
        pat = tree.is_ignored(path)
        print '%-50s %s' % (path, pat)


def cmd_lookup_revision(revno):
    try:
        revno = int(revno)
    except ValueError:
        bailout("usage: lookup-revision REVNO",
                ["REVNO is a non-negative revision number for this branch"])

    print Branch('.').lookup_revision(revno) or NONE_STRING



def cmd_export(revno, dest):
    """Export past revision to destination directory."""
    b = Branch('.')
    rh = b.lookup_revision(int(revno))
    t = b.revision_tree(rh)
    t.export(dest)



######################################################################
# internal/test commands


def cmd_uuid():
    """Print a newly-generated UUID."""
    print bzrlib.osutils.uuid()



def cmd_local_time_offset():
    print bzrlib.osutils.local_time_offset()



def cmd_commit(message=None, verbose=False):
    """Commit changes to a new revision.

--message MESSAGE
    Description of changes in this revision; free form text.
    It is recommended that the first line be a single-sentence
    summary.
--verbose
    Show status of changed files,

TODO: Commit only selected files.

TODO: Run hooks on tree to-be-committed, and after commit.

TODO: Strict commit that fails if there are unknown or deleted files.
"""

    if not message:
        bailout("please specify a commit message")
    Branch('.').commit(message, verbose=verbose)


def cmd_check(dir='.'):
    """check: Consistency check of branch history.

usage: bzr check [-v] [BRANCH]

options:
  --verbose, -v         Show progress of checking.

This command checks various invariants about the branch storage to
detect data corruption or bzr bugs.
"""
    import bzrlib.check
    bzrlib.check.check(Branch(dir, find_root=False))


def cmd_is(pred, *rest):
    """Test whether PREDICATE is true."""
    try:
        cmd_handler = globals()['assert_' + pred.replace('-', '_')]
    except KeyError:
        bailout("unknown predicate: %s" % quotefn(pred))
        
    try:
        cmd_handler(*rest)
    except BzrCheckError:
        # by default we don't print the message so that this can
        # be used from shell scripts without producing noise
        sys.exit(1)


def cmd_username():
    print bzrlib.osutils.username()


def cmd_user_email():
    print bzrlib.osutils.user_email()


def cmd_gen_revision_id():
    import time
    print bzrlib.branch._gen_revision_id(time.time())


def cmd_selftest(verbose=False):
    """Run internal test suite"""
    ## -v, if present, is seen by doctest; the argument is just here
    ## so our parser doesn't complain

    ## TODO: --verbose option

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



# deprecated
cmd_doctest = cmd_selftest


######################################################################
# help


def cmd_help(topic=None):
    if topic == None:
        print __doc__
        return

    # otherwise, maybe the name of a command?
    try:
        cmdfn = globals()['cmd_' + topic.replace('-', '_')]
    except KeyError:
        bailout("no help for %r" % topic)

    doc = cmdfn.__doc__
    if doc == None:
        bailout("sorry, no detailed help yet for %r" % topic)

    print doc
        



def cmd_version():
    print "bzr (bazaar-ng) %s" % bzrlib.__version__
    print bzrlib.__copyright__
    print "http://bazaar-ng.org/"
    print
    print \
"""bzr comes with ABSOLUTELY NO WARRANTY.  bzr is free software, and
you may use, modify and redistribute it under the terms of the GNU 
General Public License version 2 or later."""


def cmd_rocks():
    """Statement of optimism."""
    print "it sure does!"



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
    }

SHORT_OPTIONS = {
    'm':                      'message',
    'r':                      'revision',
    'v':                      'verbose',
}

# List of options that apply to particular commands; commands not
# listed take none.
cmd_options = {
    'add':                    ['verbose'],
    'commit':                 ['message', 'verbose'],
    'deleted':                ['show-ids'],
    'diff':                   ['revision'],
    'inventory':              ['revision'],
    'log':                    ['timezone'],
    'ls':                     ['revision', 'verbose'],
    'remove':                 ['verbose'],
    'status':                 ['all'],
    }


cmd_args = {
    'add':                    ['file+'],
    'commit':                 [],
    'diff':                   [],
    'export':                 ['revno', 'dest'],
    'file-id':                ['filename'],
    'get-file-text':          ['text_id'],
    'get-inventory':          ['inventory_id'],
    'get-revision':           ['revision_id'],
    'get-revision-inventory': ['revision_id'],
    'help':                   ['topic?'],
    'init':                   [],
    'log':                    [],
    'lookup-revision':        ['revno'],
    'relpath':                ['filename'],
    'remove':                 ['file+'],
    'root':                   ['filename?'],
    'status':                 [],
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



def _match_args(cmd, args):
    """Check non-option arguments match required pattern.

    >>> _match_args('status', ['asdasdsadasd'])
    Traceback (most recent call last):
    ...
    BzrError: ("extra arguments to command status: ['asdasdsadasd']", [])
    >>> _match_args('add', ['asdasdsadasd'])
    {'file_list': ['asdasdsadasd']}
    >>> _match_args('add', 'abc def gj'.split())
    {'file_list': ['abc', 'def', 'gj']}
    """
    # match argument pattern
    argform = cmd_args.get(cmd, [])
    argdict = {}
    # TODO: Need a way to express 'cp SRC... DEST', where it matches
    # all but one.

    # step through args and argform, allowing appropriate 0-many matches
    for ap in argform:
        argname = ap[:-1]
        if ap[-1] == '?':
            if args:
                argdict[argname] = args.pop(0)
        elif ap[-1] == '*':
            assert 0
        elif ap[-1] == '+':
            if not args:
                bailout("command %r needs one or more %s"
                        % (cmd, argname.upper()))
            else:
                argdict[argname + '_list'] = args[:]
                args = []
        else:
            # just a plain arg
            argname = ap
            if not args:
                bailout("command %r requires argument %s"
                        % (cmd, argname.upper()))
            else:
                argdict[argname] = args.pop(0)
            
    if args:
        bailout("extra arguments to command %s: %r"
                % (cmd, args))

    return argdict



def run_bzr(argv):
    """Execute a command.

    This is similar to main(), but without all the trappings for
    logging and error handling.
    """
    try:
        args, opts = parse_args(argv[1:])
        if 'help' in opts:
            # TODO: pass down other arguments in case they asked for
            # help on a command name?
            cmd_help()
            return 0
        elif 'version' in opts:
            cmd_version()
            return 0
        cmd = args.pop(0)
    except IndexError:
        log_error('usage: bzr COMMAND\n')
        log_error('  try "bzr help"\n')
        return 1

    try:
        cmd_handler = globals()['cmd_' + cmd.replace('-', '_')]
    except KeyError:
        bailout("unknown command " + `cmd`)

    # global option
    if 'profile' in opts:
        profile = True
        del opts['profile']
    else:
        profile = False

    # check options are reasonable
    allowed = cmd_options.get(cmd, [])
    for oname in opts:
        if oname not in allowed:
            bailout("option %r is not allowed for command %r"
                    % (oname, cmd))

    # mix arguments and options into one dictionary
    cmdargs = _match_args(cmd, args)
    for k, v in opts.items():
        cmdargs[k.replace('-', '_')] = v

    if profile:
        import hotshot
        prof = hotshot.Profile('.bzr.profile')
        ret = prof.runcall(cmd_handler, **cmdargs) or 0
        prof.close()

        import hotshot.stats
        stats = hotshot.stats.load('.bzr.profile')
        #stats.strip_dirs()
        stats.sort_stats('time')
        stats.print_stats(20)
    else:
        return cmd_handler(**cmdargs) or 0



def main(argv):
    ## TODO: Handle command-line options; probably know what options are valid for
    ## each command

    ## TODO: If the arguments are wrong, give a usage message rather
    ## than just a backtrace.

    bzrlib.trace.create_tracefile(argv)
    
    try:
        ret = run_bzr(argv)
        return ret
    except BzrError, e:
        log_error('bzr: error: ' + e.args[0] + '\n')
        if len(e.args) > 1:
            for h in e.args[1]:
                log_error('  ' + h + '\n')
        return 1
    except Exception, e:
        log_error('bzr: exception: %s\n' % e)
        log_error('    see .bzr.log for details\n')
        traceback.print_exc(None, bzrlib.trace._tracefile)
        traceback.print_exc(None, sys.stderr)
        return 1

    # TODO: Maybe nicer handling of IOError?



if __name__ == '__main__':
    sys.exit(main(sys.argv))
    ##import profile
    ##profile.run('main(sys.argv)')
    
