# Copyright (C) 2006 by Canonical Ltd
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


# TODO: probably should say which arguments are candidates for glob
# expansion on windows and do that at the command level.

# TODO: Define arguments by objects, rather than just using names.
# Those objects can specify the expected type of the argument, which
# would help with validation and shell completion.  They could also provide
# help/explanation for that argument in a structured way.

# TODO: Specific "examples" property on commands for consistent formatting.

# TODO: "--profile=cum", to change sort order.  Is there any value in leaving
# the profile output behind so it can be interactively examined?

import codecs
import errno
import os
from warnings import warn
import sys

import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import (BzrError,
                           BzrCommandError,
                           BzrCheckError,
                           NotBranchError)
from bzrlib import option
from bzrlib.option import Option
import bzrlib.osutils
from bzrlib.revisionspec import RevisionSpec
from bzrlib.symbol_versioning import (deprecated_method, zero_eight)
import bzrlib.trace
from bzrlib.trace import mutter, note, log_error, warning, be_quiet

plugin_cmds = {}


def register_command(cmd, decorate=False):
    """Utility function to help register a command

    :param cmd: Command subclass to register
    :param decorate: If true, allow overriding an existing command
        of the same name; the old command is returned by this function.
        Otherwise it is an error to try to override an existing command.
    """
    global plugin_cmds
    k = cmd.__name__
    if k.startswith("cmd_"):
        k_unsquished = _unsquish_command_name(k)
    else:
        k_unsquished = k
    if not plugin_cmds.has_key(k_unsquished):
        plugin_cmds[k_unsquished] = cmd
        mutter('registered plugin command %s', k_unsquished)
        if decorate and k_unsquished in builtin_command_names():
            return _builtin_commands()[k_unsquished]
    elif decorate:
        result = plugin_cmds[k_unsquished]
        plugin_cmds[k_unsquished] = cmd
        return result
    else:
        log_error('Two plugins defined the same command: %r' % k)
        log_error('Not loading the one in %r' % sys.modules[cmd.__module__])


def _squish_command_name(cmd):
    return 'cmd_' + cmd.replace('-', '_')


def _unsquish_command_name(cmd):
    assert cmd.startswith("cmd_")
    return cmd[4:].replace('_','-')


def _builtin_commands():
    import bzrlib.builtins
    r = {}
    builtins = bzrlib.builtins.__dict__
    for name in builtins:
        if name.startswith("cmd_"):
            real_name = _unsquish_command_name(name)
            r[real_name] = builtins[name]
    return r
            

def builtin_command_names():
    """Return list of builtin command names."""
    return _builtin_commands().keys()
    

def plugin_command_names():
    return plugin_cmds.keys()


def _get_cmd_dict(plugins_override=True):
    """Return name->class mapping for all commands."""
    d = _builtin_commands()
    if plugins_override:
        d.update(plugin_cmds)
    return d

    
def get_all_cmds(plugins_override=True):
    """Return canonical name and class for all registered commands."""
    for k, v in _get_cmd_dict(plugins_override=plugins_override).iteritems():
        yield k,v


def get_cmd_object(cmd_name, plugins_override=True):
    """Return the canonical name and command class for a command.

    plugins_override
        If true, plugin commands can override builtins.
    """
    from bzrlib.externalcommand import ExternalCommand

    # We want only 'ascii' command names, but the user may have typed
    # in a Unicode name. In that case, they should just get a
    # 'command not found' error later.
    # In the future, we may actually support Unicode command names.

    # first look up this command under the specified name
    cmds = _get_cmd_dict(plugins_override=plugins_override)
    try:
        return cmds[cmd_name]()
    except KeyError:
        pass

    # look for any command which claims this as an alias
    for real_cmd_name, cmd_class in cmds.iteritems():
        if cmd_name in cmd_class.aliases:
            return cmd_class()

    cmd_obj = ExternalCommand.find_command(cmd_name)
    if cmd_obj:
        return cmd_obj

    raise BzrCommandError('unknown command "%s"' % cmd_name)


class Command(object):
    """Base class for commands.

    Commands are the heart of the command-line bzr interface.

    The command object mostly handles the mapping of command-line
    parameters into one or more bzrlib operations, and of the results
    into textual output.

    Commands normally don't have any state.  All their arguments are
    passed in to the run method.  (Subclasses may take a different
    policy if the behaviour of the instance needs to depend on e.g. a
    shell plugin and not just its Python class.)

    The docstring for an actual command should give a single-line
    summary, then a complete description of the command.  A grammar
    description will be inserted.

    aliases
        Other accepted names for this command.

    takes_args
        List of argument forms, marked with whether they are optional,
        repeated, etc.

                Examples:

                ['to_location', 'from_branch?', 'file*']

                'to_location' is required
                'from_branch' is optional
                'file' can be specified 0 or more times

    takes_options
        List of options that may be given for this command.  These can
        be either strings, referring to globally-defined options,
        or option objects.  Retrieve through options().

    hidden
        If true, this command isn't advertised.  This is typically
        for commands intended for expert users.

    encoding_type
        Command objects will get a 'outf' attribute, which has been
        setup to properly handle encoding of unicode strings.
        encoding_type determines what will happen when characters cannot
        be encoded
            strict - abort if we cannot decode
            replace - put in a bogus character (typically '?')
            exact - do not encode sys.stdout

    """
    aliases = []
    takes_args = []
    takes_options = []
    encoding_type = 'strict'

    hidden = False
    
    def __init__(self):
        """Construct an instance of this command."""
        if self.__doc__ == Command.__doc__:
            warn("No help message set for %r" % self)

    def options(self):
        """Return dict of valid options for this command.

        Maps from long option name to option object."""
        r = dict()
        r['help'] = Option.OPTIONS['help']
        for o in self.takes_options:
            if isinstance(o, basestring):
                o = Option.OPTIONS[o]
            r[o.name] = o
        return r

    def _setup_outf(self):
        """Return a file linked to stdout, which has proper encoding."""
        assert self.encoding_type in ['strict', 'exact', 'replace']

        # Originally I was using self.stdout, but that looks
        # *way* too much like sys.stdout
        if self.encoding_type == 'exact':
            self.outf = sys.stdout
            return

        output_encoding = bzrlib.osutils.get_terminal_encoding()

        # use 'replace' so that we don't abort if trying to write out
        # in e.g. the default C locale.
        self.outf = codecs.getwriter(output_encoding)(sys.stdout, errors=self.encoding_type)
        # For whatever reason codecs.getwriter() does not advertise its encoding
        # it just returns the encoding of the wrapped file, which is completely
        # bogus. So set the attribute, so we can find the correct encoding later.
        self.outf.encoding = output_encoding

    @deprecated_method(zero_eight)
    def run_argv(self, argv):
        """Parse command line and run.
        
        See run_argv_aliases for the 0.8 and beyond api.
        """
        return self.run_argv_aliases(argv)

    def run_argv_aliases(self, argv, alias_argv=None):
        """Parse the command line and run with extra aliases in alias_argv."""
        if argv is None:
            warn("Passing None for [] is deprecated from bzrlib 0.10", 
                 DeprecationWarning, stacklevel=2)
            argv = []
        args, opts = parse_args(self, argv, alias_argv)
        if 'help' in opts:  # e.g. bzr add --help
            from bzrlib.help import help_on_command
            help_on_command(self.name())
            return 0
        # mix arguments and options into one dictionary
        cmdargs = _match_argform(self.name(), self.takes_args, args)
        cmdopts = {}
        for k, v in opts.items():
            cmdopts[k.replace('-', '_')] = v

        all_cmd_args = cmdargs.copy()
        all_cmd_args.update(cmdopts)

        self._setup_outf()

        return self.run(**all_cmd_args)
    
    def run(self):
        """Actually run the command.

        This is invoked with the options and arguments bound to
        keyword parameters.

        Return 0 or None if the command was successful, or a non-zero
        shell error code if not.  It's OK for this method to allow
        an exception to raise up.
        """
        raise NotImplementedError('no implementation of command %r' 
                                  % self.name())

    def help(self):
        """Return help message for this class."""
        from inspect import getdoc
        if self.__doc__ is Command.__doc__:
            return None
        return getdoc(self)

    def name(self):
        return _unsquish_command_name(self.__class__.__name__)

    def plugin_name(self):
        """Get the name of the plugin that provides this command.

        :return: The name of the plugin or None if the command is builtin.
        """
        mod_parts = self.__module__.split('.')
        if len(mod_parts) >= 3 and mod_parts[1] == 'plugins':
            return mod_parts[2]
        else:
            return None


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

def parse_args(command, argv, alias_argv=None):
    """Parse command line.
    
    Arguments and options are parsed at this level before being passed
    down to specific command handlers.  This routine knows, from a
    lookup table, something about the available options, what optargs
    they take, and which commands will accept them.
    """
    # TODO: make it a method of the Command?
    parser = option.get_optparser(command.options())
    if alias_argv is not None:
        args = alias_argv + argv
    else:
        args = argv

    options, args = parser.parse_args(args)
    opts = dict([(k, v) for k, v in options.__dict__.iteritems() if 
                 v is not option.OptionParser.DEFAULT_VALUE])
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



def apply_profiled(the_callable, *args, **kwargs):
    import hotshot
    import tempfile
    import hotshot.stats
    pffileno, pfname = tempfile.mkstemp()
    try:
        prof = hotshot.Profile(pfname)
        try:
            ret = prof.runcall(the_callable, *args, **kwargs) or 0
        finally:
            prof.close()
        stats = hotshot.stats.load(pfname)
        stats.strip_dirs()
        stats.sort_stats('cum')   # 'time'
        ## XXX: Might like to write to stderr or the trace file instead but
        ## print_stats seems hardcoded to stdout
        stats.print_stats(20)
        return ret
    finally:
        os.close(pffileno)
        os.remove(pfname)


def apply_lsprofiled(filename, the_callable, *args, **kwargs):
    from bzrlib.lsprof import profile
    import cPickle
    ret, stats = profile(the_callable, *args, **kwargs)
    stats.sort()
    if filename is None:
        ## stats.pprint(top=50)
        stats.pprint()
    else:
        stats.freeze()
        cPickle.dump(stats, open(filename, 'w'), 2)
        print 'Profile data written to %r.' % filename
    return ret


def get_alias(cmd):
    """Return an expanded alias, or None if no alias exists"""
    import bzrlib.config
    alias = bzrlib.config.GlobalConfig().get_alias(cmd)
    if (alias):
        return alias.split(' ')
    return None


def run_bzr(argv):
    """Execute a command.

    This is similar to main(), but without all the trappings for
    logging and error handling.  
    
    argv
       The command-line arguments, without the program name from argv[0]
       These should already be decoded. All library/test code calling
       run_bzr should be passing valid strings (don't need decoding).
    
    Returns a command status or raises an exception.

    Special master options: these must come before the command because
    they control how the command is interpreted.

    --no-plugins
        Do not load plugin modules at all

    --no-aliases
        Do not allow aliases

    --builtin
        Only use builtin commands.  (Plugins are still allowed to change
        other behaviour.)

    --profile
        Run under the Python hotshot profiler.

    --lsprof
        Run under the Python lsprof profiler.
    """
    argv = list(argv)

    opt_lsprof = opt_profile = opt_no_plugins = opt_builtin =  \
                opt_no_aliases = False
    opt_lsprof_file = None

    # --no-plugins is handled specially at a very early stage. We need
    # to load plugins before doing other command parsing so that they
    # can override commands, but this needs to happen first.

    argv_copy = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--profile':
            opt_profile = True
        elif a == '--lsprof':
            opt_lsprof = True
        elif a == '--lsprof-file':
            opt_lsprof = True
            opt_lsprof_file = argv[i + 1]
            i += 1
        elif a == '--no-plugins':
            opt_no_plugins = True
        elif a == '--no-aliases':
            opt_no_aliases = True
        elif a == '--builtin':
            opt_builtin = True
        elif a in ('--quiet', '-q'):
            be_quiet()
        else:
            argv_copy.append(a)
        i += 1

    argv = argv_copy
    if (not argv):
        from bzrlib.builtins import cmd_help
        cmd_help().run_argv_aliases([])
        return 0

    if argv[0] == '--version':
        from bzrlib.version import show_version
        show_version()
        return 0
        
    if not opt_no_plugins:
        from bzrlib.plugin import load_plugins
        load_plugins()
    else:
        from bzrlib.plugin import disable_plugins
        disable_plugins()

    alias_argv = None

    if not opt_no_aliases:
        alias_argv = get_alias(argv[0])
        if alias_argv:
            alias_argv = [a.decode(bzrlib.user_encoding) for a in alias_argv]
            argv[0] = alias_argv.pop(0)

    cmd = argv.pop(0)
    # We want only 'ascii' command names, but the user may have typed
    # in a Unicode name. In that case, they should just get a
    # 'command not found' error later.

    cmd_obj = get_cmd_object(cmd, plugins_override=not opt_builtin)
    if not getattr(cmd_obj.run_argv, 'is_deprecated', False):
        run = cmd_obj.run_argv
        run_argv = [argv]
    else:
        run = cmd_obj.run_argv_aliases
        run_argv = [argv, alias_argv]

    try:
        if opt_lsprof:
            ret = apply_lsprofiled(opt_lsprof_file, run, *run_argv)
        elif opt_profile:
            ret = apply_profiled(run, *run_argv)
        else:
            ret = run(*run_argv)
        return ret or 0
    finally:
        # reset, in case we may do other commands later within the same process
        be_quiet(False)

def display_command(func):
    """Decorator that suppresses pipe/interrupt errors."""
    def ignore_pipe(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            sys.stdout.flush()
            return result
        except IOError, e:
            if not hasattr(e, 'errno'):
                raise
            if e.errno != errno.EPIPE:
                # Win32 raises IOError with errno=0 on a broken pipe
                if sys.platform != 'win32' or e.errno != 0:
                    raise
            pass
        except KeyboardInterrupt:
            pass
    return ignore_pipe


def main(argv):
    import bzrlib.ui
    from bzrlib.ui.text import TextUIFactory
    bzrlib.ui.ui_factory = TextUIFactory()
    argv = [a.decode(bzrlib.user_encoding) for a in argv[1:]]
    ret = run_bzr_catch_errors(argv)
    mutter("return code %d", ret)
    return ret


def run_bzr_catch_errors(argv):
    try:
        return run_bzr(argv)
        # do this here inside the exception wrappers to catch EPIPE
        sys.stdout.flush()
    except Exception, e:
        # used to handle AssertionError and KeyboardInterrupt
        # specially here, but hopefully they're handled ok by the logger now
        bzrlib.trace.report_exception(sys.exc_info(), sys.stderr)
        if os.environ.get('BZR_PDB'):
            print '**** entering debugger'
            import pdb
            pdb.post_mortem(sys.exc_traceback)
        return 3

if __name__ == '__main__':
    sys.exit(main(sys.argv))
