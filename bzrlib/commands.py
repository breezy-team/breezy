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


# TODO: probably should say which arguments are candidates for glob
# expansion on windows and do that at the command level.

# TODO: Help messages for options.

# TODO: Define arguments by objects, rather than just using names.
# Those objects can specify the expected type of the argument, which
# would help with validation and shell completion.


import sys
import os

import bzrlib
import bzrlib.trace
from bzrlib.trace import mutter, note, log_error, warning
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
        mutter('registered plugin command %s', k_unsquished)      
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

    This always returns a list.  The list will have one element for 

    It supports integers directly, but everything else it
    defers for passing to Branch.get_revision_info()

    >>> _parse_revision_str('234')
    [234]
    >>> _parse_revision_str('234..567')
    [234, 567]
    >>> _parse_revision_str('..')
    [None, None]
    >>> _parse_revision_str('..234')
    [None, 234]
    >>> _parse_revision_str('234..')
    [234, None]
    >>> _parse_revision_str('234..456..789') # Maybe this should be an error
    [234, 456, 789]
    >>> _parse_revision_str('234....789') # Error?
    [234, None, 789]
    >>> _parse_revision_str('revid:test@other.com-234234')
    ['revid:test@other.com-234234']
    >>> _parse_revision_str('revid:test@other.com-234234..revid:test@other.com-234235')
    ['revid:test@other.com-234234', 'revid:test@other.com-234235']
    >>> _parse_revision_str('revid:test@other.com-234234..23')
    ['revid:test@other.com-234234', 23]
    >>> _parse_revision_str('date:2005-04-12')
    ['date:2005-04-12']
    >>> _parse_revision_str('date:2005-04-12 12:24:33')
    ['date:2005-04-12 12:24:33']
    >>> _parse_revision_str('date:2005-04-12T12:24:33')
    ['date:2005-04-12T12:24:33']
    >>> _parse_revision_str('date:2005-04-12,12:24:33')
    ['date:2005-04-12,12:24:33']
    >>> _parse_revision_str('-5..23')
    [-5, 23]
    >>> _parse_revision_str('-5')
    [-5]
    >>> _parse_revision_str('123a')
    ['123a']
    >>> _parse_revision_str('abc')
    ['abc']
    """
    import re
    old_format_re = re.compile('\d*:\d*')
    m = old_format_re.match(revstr)
    if m:
        warning('Colon separator for revision numbers is deprecated.'
                ' Use .. instead')
        revs = []
        for rev in revstr.split(':'):
            if rev:
                revs.append(int(rev))
            else:
                revs.append(None)
        return revs
    revs = []
    for x in revstr.split('..'):
        if not x:
            revs.append(None)
        else:
            try:
                revs.append(int(x))
            except ValueError:
                revs.append(x)
    return revs


def get_merge_type(typestring):
    """Attempt to find the merge class/factory associated with a string."""
    from merge import merge_types
    try:
        return merge_types[typestring][0]
    except KeyError:
        templ = '%s%%7s: %%s' % (' '*12)
        lines = [templ % (f[0], f[1][1]) for f in merge_types.iteritems()]
        type_list = '\n'.join(lines)
        msg = "No known merge type %s. Supported types are:\n%s" %\
            (typestring, type_list)
        raise BzrCommandError(msg)
    

def get_merge_type(typestring):
    """Attempt to find the merge class/factory associated with a string."""
    from merge import merge_types
    try:
        return merge_types[typestring][0]
    except KeyError:
        templ = '%s%%7s: %%s' % (' '*12)
        lines = [templ % (f[0], f[1][1]) for f in merge_types.iteritems()]
        type_list = '\n'.join(lines)
        msg = "No known merge type %s. Supported types are:\n%s" %\
            (typestring, type_list)
        raise BzrCommandError(msg)
    


def _get_cmd_dict(plugins_override=True):
    import bzrlib.builtins
    
    d = {}
    builtins = bzrlib.builtins.__dict__
    for name in builtins:
        if name.startswith("cmd_"):
            d[_unsquish_command_name(name)] = builtins[name]
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
    mutter("all commands: %r", cmds.keys())
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
        if self.__doc__ == Command.__doc__:
            from warnings import warn
            warn("No help message set for %r" % self)
        self.status = self.run(**cmdargs)
        if self.status is None:
            self.status = 0

    
    def run(self, *args, **kwargs):
        """Override this in sub-classes.

        This is invoked with the options and arguments bound to
        keyword parameters.

        Return 0 or None if the command was successful, or a shell
        error code if not.
        """
        raise NotImplementedError()


class ExternalCommand(Command):
    """Class to wrap external commands.

    We cheat a little here, when get_cmd_class() calls us we actually
    give it back an object we construct that has the appropriate path,
    help, options etc for the specified command.

    When run_bzr() tries to instantiate that 'class' it gets caught by
    the __call__ method, which we override to call the Command.__init__
    method. That then calls our run method which is pretty straight
    forward.

    The only wrinkle is that we have to map bzr's dictionary of options
    and arguments back into command line options and arguments for the
    script.
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
    >>> parse_spec('./@revid:john@arbash-meinel.com-20050711044610-3ca0327c6a222f67')
    ['.', 'revid:john@arbash-meinel.com-20050711044610-3ca0327c6a222f67']
    """
    if spec is None:
        return [None, None]
    if '/@' in spec:
        parsed = spec.split('/@')
        assert len(parsed) == 2
        if parsed[1] == "":
            parsed[1] = -1
        else:
            try:
                parsed[1] = int(parsed[1])
            except ValueError:
                pass # We can allow stuff like ./@revid:blahblahblah
            else:
                assert parsed[1] >=0
    else:
        parsed = [spec, None]
    return parsed




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
    'short':                  None,
    'show-ids':               None,
    'timezone':               str,
    'verbose':                None,
    'version':                None,
    'email':                  None,
    'unchanged':              None,
    'update':                 None,
    'long':                   None,
    'root':                   str,
    'no-backup':              None,
    'merge-type':             get_merge_type,
    'pattern':                str,
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
    >>> parse_args('help -- --invalidcmd'.split())
    (['help', '--invalidcmd'], {})
    >>> parse_args('--version'.split())
    ([], {'version': True})
    >>> parse_args('status --all'.split())
    (['status'], {'all': True})
    >>> parse_args('commit --message=biter'.split())
    (['commit'], {'message': u'biter'})
    >>> parse_args('log -r 500'.split())
    (['log'], {'revision': [500]})
    >>> parse_args('log -r500..600'.split())
    (['log'], {'revision': [500, 600]})
    >>> parse_args('log -vr500..600'.split())
    (['log'], {'verbose': True, 'revision': [500, 600]})
    >>> parse_args('log -rv500..600'.split()) #the r takes an argument
    (['log'], {'revision': ['v500', 600]})
    """
    args = []
    opts = {}

    argsover = False
    while argv:
        a = argv.pop(0)
        if not argsover and a[0] == '-':
            # option names must not be unicode
            a = str(a)
            optarg = None
            if a[1] == '-':
                if a == '--':
                    # We've received a standalone -- No more flags
                    argsover = True
                    continue
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



def run_bzr(argv):
    """Execute a command.

    This is similar to main(), but without all the trappings for
    logging and error handling.  
    
    argv
       The command-line arguments, without the program name from argv[0]
    
    Returns a command status or raises an exception.

    Special master options: these must come before the command because
    they control how the command is interpreted.

    --no-plugins
        Do not load plugin modules at all

    --builtin
        Only use builtin commands.  (Plugins are still allowed to change
        other behaviour.)

    --profile
        Run under the Python profiler.
    """
    
    argv = [a.decode(bzrlib.user_encoding) for a in argv]

    opt_profile = opt_no_plugins = opt_builtin = False

    # --no-plugins is handled specially at a very early stage. We need
    # to load plugins before doing other command parsing so that they
    # can override commands, but this needs to happen first.

    for a in argv[:]:
        if a == '--profile':
            opt_profile = True
        elif a == '--no-plugins':
            opt_no_plugins = True
        elif a == '--builtin':
            opt_builtin = True
        else:
            break
        argv.remove(a)

    if not opt_no_plugins:
        from bzrlib.plugin import load_plugins
        load_plugins()

    args, opts = parse_args(argv)

    if 'help' in opts:
        from bzrlib.help import help
        if args:
            help(args[0])
        else:
            help()
        return 0            
        
    if 'version' in opts:
        from bzrlib.builtins import show_version
        show_version()
        return 0
    
    if not args:
        from bzrlib.help import help
        help(None)
        return 0
    
    cmd = str(args.pop(0))

    canonical_cmd, cmd_class = \
                   get_cmd_class(cmd, plugins_override=not opt_builtin)

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

    if opt_profile:
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


def main(argv):
    import bzrlib.ui
    bzrlib.trace.log_startup(argv)
    bzrlib.ui.ui_factory = bzrlib.ui.TextUIFactory()

    try:
        try:
            return run_bzr(argv[1:])
        finally:
            # do this here inside the exception wrappers to catch EPIPE
            sys.stdout.flush()
    except BzrCommandError, e:
        # command line syntax error, etc
        log_error(str(e))
        return 1
    except BzrError, e:
        bzrlib.trace.log_exception()
        return 1
    except AssertionError, e:
        bzrlib.trace.log_exception('assertion failed: ' + str(e))
        return 3
    except KeyboardInterrupt, e:
        bzrlib.trace.note('interrupted')
        return 2
    except Exception, e:
        import errno
        if (isinstance(e, IOError) 
            and hasattr(e, 'errno')
            and e.errno == errno.EPIPE):
            bzrlib.trace.note('broken pipe')
            return 2
        else:
            bzrlib.trace.log_exception()
            return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
