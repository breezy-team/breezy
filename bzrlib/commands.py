# Copyright (C) 2006, 2008 Canonical Ltd
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

import os
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import codecs
import errno
from warnings import warn

import bzrlib
from bzrlib import (
    debug,
    errors,
    option,
    osutils,
    trace,
    win32utils,
    )
""")

from bzrlib import registry
# Compatibility
from bzrlib.hooks import HookPoint, Hooks
from bzrlib.option import Option


class CommandInfo(object):
    """Information about a command."""

    def __init__(self, aliases):
        """The list of aliases for the command."""
        self.aliases = aliases

    @classmethod
    def from_command(klass, command):
        """Factory to construct a CommandInfo from a command."""
        return klass(command.aliases)


class CommandRegistry(registry.Registry):

    @staticmethod
    def _get_name(command_name):
        if command_name.startswith("cmd_"):
            return _unsquish_command_name(command_name)
        else:
            return command_name

    def register(self, cmd, decorate=False):
        """Utility function to help register a command

        :param cmd: Command subclass to register
        :param decorate: If true, allow overriding an existing command
            of the same name; the old command is returned by this function.
            Otherwise it is an error to try to override an existing command.
        """
        k = cmd.__name__
        k_unsquished = self._get_name(k)
        try:
            previous = self.get(k_unsquished)
        except KeyError:
            previous = _builtin_commands().get(k_unsquished)
        info = CommandInfo.from_command(cmd)
        try:
            registry.Registry.register(self, k_unsquished, cmd,
                                       override_existing=decorate, info=info)
        except KeyError:
            trace.log_error('Two plugins defined the same command: %r' % k)
            trace.log_error('Not loading the one in %r' %
                            sys.modules[cmd.__module__])
            trace.log_error('Previously this command was registered from %r' %
                            sys.modules[previous.__module__])
        return previous

    def register_lazy(self, command_name, aliases, module_name):
        """Register a command without loading its module.

        :param command_name: The primary name of the command.
        :param aliases: A list of aliases for the command.
        :module_name: The module that the command lives in.
        """
        key = self._get_name(command_name)
        registry.Registry.register_lazy(self, key, module_name, command_name,
                                        info=CommandInfo(aliases))


plugin_cmds = CommandRegistry()


def register_command(cmd, decorate=False):
    global plugin_cmds
    return plugin_cmds.register(cmd, decorate)


def _squish_command_name(cmd):
    return 'cmd_' + cmd.replace('-', '_')


def _unsquish_command_name(cmd):
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
        d.update(plugin_cmds.iteritems())
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
    try:
        cmd = _get_cmd_object(cmd_name, plugins_override)
        # Allow plugins to extend commands
        for hook in Command.hooks['extend_command']:
            hook(cmd)
        return cmd
    except KeyError:
        raise errors.BzrCommandError('unknown command "%s"' % cmd_name)


def _get_cmd_object(cmd_name, plugins_override=True):
    """Worker for get_cmd_object which raises KeyError rather than BzrCommandError."""
    from bzrlib.externalcommand import ExternalCommand

    # We want only 'ascii' command names, but the user may have typed
    # in a Unicode name. In that case, they should just get a
    # 'command not found' error later.
    # In the future, we may actually support Unicode command names.

    # first look up this command under the specified name
    if plugins_override:
        try:
            return plugin_cmds.get(cmd_name)()
        except KeyError:
            pass
    cmds = _get_cmd_dict(plugins_override=False)
    try:
        return cmds[cmd_name]()
    except KeyError:
        pass
    if plugins_override:
        for key in plugin_cmds.keys():
            info = plugin_cmds.get_info(key)
            if cmd_name in info.aliases:
                return plugin_cmds.get(key)()
    # look for any command which claims this as an alias
    for real_cmd_name, cmd_class in cmds.iteritems():
        if cmd_name in cmd_class.aliases:
            return cmd_class()

    cmd_obj = ExternalCommand.find_command(cmd_name)
    if cmd_obj:
        return cmd_obj

    # look for plugins that provide this command but aren't installed
    for provider in command_providers_registry:
        try:
            plugin_metadata = provider.plugin_for_command(cmd_name)
        except errors.NoPluginAvailable:
            pass
        else:
            raise errors.CommandAvailableInPlugin(cmd_name,
                                                  plugin_metadata, provider)
    raise KeyError


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

            NOTE: by default on Windows, sys.stdout is opened as a text
            stream, therefore LF line-endings are converted to CRLF.
            When a command uses encoding_type = 'exact', then
            sys.stdout is forced to be a binary stream, and line-endings
            will not mangled.

    :cvar hooks: An instance of CommandHooks.
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
        # List of standard options directly supported
        self.supported_std_options = []

    def _maybe_expand_globs(self, file_list):
        """Glob expand file_list if the platform does not do that itself.

        :return: A possibly empty list of unicode paths.

        Introduced in bzrlib 0.18.
        """
        if not file_list:
            file_list = []
        if sys.platform == 'win32':
            file_list = win32utils.glob_expand(file_list)
        return list(file_list)

    def _usage(self):
        """Return single-line grammar for this command.

        Only describes arguments, not options.
        """
        s = 'bzr ' + self.name() + ' '
        for aname in self.takes_args:
            aname = aname.upper()
            if aname[-1] in ['$', '+']:
                aname = aname[:-1] + '...'
            elif aname[-1] == '?':
                aname = '[' + aname[:-1] + ']'
            elif aname[-1] == '*':
                aname = '[' + aname[:-1] + '...]'
            s += aname + ' '
        s = s[:-1]      # remove last space
        return s

    def get_help_text(self, additional_see_also=None, plain=True,
                      see_also_as_links=False, verbose=True):
        """Return a text string with help for this command.

        :param additional_see_also: Additional help topics to be
            cross-referenced.
        :param plain: if False, raw help (reStructuredText) is
            returned instead of plain text.
        :param see_also_as_links: if True, convert items in 'See also'
            list to internal links (used by bzr_man rstx generator)
        :param verbose: if True, display the full help, otherwise
            leave out the descriptive sections and just display
            concise help (e.g. Purpose, Usage, Options) with a
            message pointing to "help -v" for more information.
        """
        doc = self.help()
        if doc is None:
            raise NotImplementedError("sorry, no detailed help yet for %r" % self.name())

        # Extract the summary (purpose) and sections out from the text
        purpose,sections,order = self._get_help_parts(doc)

        # If a custom usage section was provided, use it
        if sections.has_key('Usage'):
            usage = sections.pop('Usage')
        else:
            usage = self._usage()

        # The header is the purpose and usage
        result = ""
        result += ':Purpose: %s\n' % purpose
        if usage.find('\n') >= 0:
            result += ':Usage:\n%s\n' % usage
        else:
            result += ':Usage:   %s\n' % usage
        result += '\n'

        # Add the options
        options = option.get_optparser(self.options()).format_option_help()
        if options.startswith('Options:'):
            result += ':' + options
        elif options.startswith('options:'):
            # Python 2.4 version of optparse
            result += ':Options:' + options[len('options:'):]
        else:
            result += options
        result += '\n'

        if verbose:
            # Add the description, indenting it 2 spaces
            # to match the indentation of the options
            if sections.has_key(None):
                text = sections.pop(None)
                text = '\n  '.join(text.splitlines())
                result += ':%s:\n  %s\n\n' % ('Description',text)

            # Add the custom sections (e.g. Examples). Note that there's no need
            # to indent these as they must be indented already in the source.
            if sections:
                for label in order:
                    if sections.has_key(label):
                        result += ':%s:\n%s\n' % (label,sections[label])
                result += '\n'
        else:
            result += ("See bzr help %s for more details and examples.\n\n"
                % self.name())

        # Add the aliases, source (plug-in) and see also links, if any
        if self.aliases:
            result += ':Aliases:  '
            result += ', '.join(self.aliases) + '\n'
        plugin_name = self.plugin_name()
        if plugin_name is not None:
            result += ':From:     plugin "%s"\n' % plugin_name
        see_also = self.get_see_also(additional_see_also)
        if see_also:
            if not plain and see_also_as_links:
                see_also_links = []
                for item in see_also:
                    if item == 'topics':
                        # topics doesn't have an independent section
                        # so don't create a real link
                        see_also_links.append(item)
                    else:
                        # Use a reST link for this entry
                        see_also_links.append("`%s`_" % (item,))
                see_also = see_also_links
            result += ':See also: '
            result += ', '.join(see_also) + '\n'

        # If this will be rendered as plain text, convert it
        if plain:
            import bzrlib.help_topics
            result = bzrlib.help_topics.help_as_plain_text(result)
        return result

    @staticmethod
    def _get_help_parts(text):
        """Split help text into a summary and named sections.

        :return: (summary,sections,order) where summary is the top line and
            sections is a dictionary of the rest indexed by section name.
            order is the order the section appear in the text.
            A section starts with a heading line of the form ":xxx:".
            Indented text on following lines is the section value.
            All text found outside a named section is assigned to the
            default section which is given the key of None.
        """
        def save_section(sections, order, label, section):
            if len(section) > 0:
                if sections.has_key(label):
                    sections[label] += '\n' + section
                else:
                    order.append(label)
                    sections[label] = section

        lines = text.rstrip().splitlines()
        summary = lines.pop(0)
        sections = {}
        order = []
        label,section = None,''
        for line in lines:
            if line.startswith(':') and line.endswith(':') and len(line) > 2:
                save_section(sections, order, label, section)
                label,section = line[1:-1],''
            elif (label is not None) and len(line) > 1 and not line[0].isspace():
                save_section(sections, order, label, section)
                label,section = None,line
            else:
                if len(section) > 0:
                    section += '\n' + line
                else:
                    section = line
        save_section(sections, order, label, section)
        return summary, sections, order

    def get_help_topic(self):
        """Return the commands help topic - its name."""
        return self.name()

    def get_see_also(self, additional_terms=None):
        """Return a list of help topics that are related to this command.

        The list is derived from the content of the _see_also attribute. Any
        duplicates are removed and the result is in lexical order.
        :param additional_terms: Additional help topics to cross-reference.
        :return: A list of help topics.
        """
        see_also = set(getattr(self, '_see_also', []))
        if additional_terms:
            see_also.update(additional_terms)
        return sorted(see_also)

    def options(self):
        """Return dict of valid options for this command.

        Maps from long option name to option object."""
        r = Option.STD_OPTIONS.copy()
        std_names = r.keys()
        for o in self.takes_options:
            if isinstance(o, basestring):
                o = option.Option.OPTIONS[o]
            r[o.name] = o
            if o.name in std_names:
                self.supported_std_options.append(o.name)
        return r

    def _setup_outf(self):
        """Return a file linked to stdout, which has proper encoding."""
        # Originally I was using self.stdout, but that looks
        # *way* too much like sys.stdout
        if self.encoding_type == 'exact':
            # force sys.stdout to be binary stream on win32
            if sys.platform == 'win32':
                fileno = getattr(sys.stdout, 'fileno', None)
                if fileno:
                    import msvcrt
                    msvcrt.setmode(fileno(), os.O_BINARY)
            self.outf = sys.stdout
            return

        output_encoding = osutils.get_terminal_encoding()

        self.outf = codecs.getwriter(output_encoding)(sys.stdout,
                        errors=self.encoding_type)
        # For whatever reason codecs.getwriter() does not advertise its encoding
        # it just returns the encoding of the wrapped file, which is completely
        # bogus. So set the attribute, so we can find the correct encoding later.
        self.outf.encoding = output_encoding

    def run_argv_aliases(self, argv, alias_argv=None):
        """Parse the command line and run with extra aliases in alias_argv."""
        if argv is None:
            warn("Passing None for [] is deprecated from bzrlib 0.10",
                 DeprecationWarning, stacklevel=2)
            argv = []
        args, opts = parse_args(self, argv, alias_argv)

        # Process the standard options
        if 'help' in opts:  # e.g. bzr add --help
            sys.stdout.write(self.get_help_text())
            return 0
        if 'usage' in opts:  # e.g. bzr add --usage
            sys.stdout.write(self.get_help_text(verbose=False))
            return 0
        trace.set_verbosity_level(option._verbosity_level)
        if 'verbose' in self.supported_std_options:
            opts['verbose'] = trace.is_verbose()
        elif opts.has_key('verbose'):
            del opts['verbose']
        if 'quiet' in self.supported_std_options:
            opts['quiet'] = trace.is_quiet()
        elif opts.has_key('quiet'):
            del opts['quiet']

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


class CommandHooks(Hooks):
    """Hooks related to Command object creation/enumeration."""

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        Hooks.__init__(self)
        self.create_hook(HookPoint('extend_command',
            "Called after creating a command object to allow modifications "
            "such as adding or removing options, docs etc. Called with the "
            "new bzrlib.commands.Command object.", (1, 13), None))

Command.hooks = CommandHooks()


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
                raise errors.BzrCommandError("command %r needs one or more %s"
                                             % (cmd, argname.upper()))
            else:
                argdict[argname + '_list'] = args[:]
                args = []
        elif ap[-1] == '$': # all but one
            if len(args) < 2:
                raise errors.BzrCommandError("command %r needs one or more %s"
                                             % (cmd, argname.upper()))
            argdict[argname + '_list'] = args[:-1]
            args[:-1] = []
        else:
            # just a plain arg
            argname = ap
            if not args:
                raise errors.BzrCommandError("command %r requires argument %s"
                               % (cmd, argname.upper()))
            else:
                argdict[argname] = args.pop(0)

    if args:
        raise errors.BzrCommandError("extra argument to command %s: %s"
                                     % (cmd, args[0]))

    return argdict

def apply_coveraged(dirname, the_callable, *args, **kwargs):
    # Cannot use "import trace", as that would import bzrlib.trace instead of
    # the standard library's trace.
    trace = __import__('trace')

    tracer = trace.Trace(count=1, trace=0)
    sys.settrace(tracer.globaltrace)

    try:
        return exception_to_return_code(the_callable, *args, **kwargs)
    finally:
        sys.settrace(None)
        results = tracer.results()
        results.write_results(show_missing=1, summary=False,
                              coverdir=dirname)


def apply_profiled(the_callable, *args, **kwargs):
    import hotshot
    import tempfile
    import hotshot.stats
    pffileno, pfname = tempfile.mkstemp()
    try:
        prof = hotshot.Profile(pfname)
        try:
            ret = prof.runcall(exception_to_return_code, the_callable, *args,
                **kwargs) or 0
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


def exception_to_return_code(the_callable, *args, **kwargs):
    """UI level helper for profiling and coverage.

    This transforms exceptions into a return value of 3. As such its only
    relevant to the UI layer, and should never be called where catching
    exceptions may be desirable.
    """
    try:
        return the_callable(*args, **kwargs)
    except (KeyboardInterrupt, Exception), e:
        # used to handle AssertionError and KeyboardInterrupt
        # specially here, but hopefully they're handled ok by the logger now
        exc_info = sys.exc_info()
        exitcode = trace.report_exception(exc_info, sys.stderr)
        if os.environ.get('BZR_PDB'):
            print '**** entering debugger'
            tb = exc_info[2]
            import pdb
            if sys.version_info[:2] < (2, 6):
                # XXX: we want to do
                #    pdb.post_mortem(tb)
                # but because pdb.post_mortem gives bad results for tracebacks
                # from inside generators, we do it manually.
                # (http://bugs.python.org/issue4150, fixed in Python 2.6)

                # Setup pdb on the traceback
                p = pdb.Pdb()
                p.reset()
                p.setup(tb.tb_frame, tb)
                # Point the debugger at the deepest frame of the stack
                p.curindex = len(p.stack) - 1
                p.curframe = p.stack[p.curindex][0]
                # Start the pdb prompt.
                p.print_stack_entry(p.stack[p.curindex])
                p.execRcLines()
                p.cmdloop()
            else:
                pdb.post_mortem(tb)
        return exitcode


def apply_lsprofiled(filename, the_callable, *args, **kwargs):
    from bzrlib.lsprof import profile
    ret, stats = profile(exception_to_return_code, the_callable, *args, **kwargs)
    stats.sort()
    if filename is None:
        stats.pprint()
    else:
        stats.save(filename)
        trace.note('Profile data written to "%s".', filename)
    return ret


def shlex_split_unicode(unsplit):
    import shlex
    return [u.decode('utf-8') for u in shlex.split(unsplit.encode('utf-8'))]


def get_alias(cmd, config=None):
    """Return an expanded alias, or None if no alias exists.

    cmd
        Command to be checked for an alias.
    config
        Used to specify an alternative config to use,
        which is especially useful for testing.
        If it is unspecified, the global config will be used.
    """
    if config is None:
        import bzrlib.config
        config = bzrlib.config.GlobalConfig()
    alias = config.get_alias(cmd)
    if (alias):
        return shlex_split_unicode(alias)
    return None


def run_bzr(argv):
    """Execute a command.

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

    --coverage
        Generate line coverage report in the specified directory.
    """
    argv = list(argv)
    trace.mutter("bzr arguments: %r", argv)

    opt_lsprof = opt_profile = opt_no_plugins = opt_builtin =  \
                opt_no_aliases = False
    opt_lsprof_file = opt_coverage_dir = None

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
        elif a == '--coverage':
            opt_coverage_dir = argv[i + 1]
            i += 1
        elif a.startswith('-D'):
            debug.debug_flags.add(a[2:])
        else:
            argv_copy.append(a)
        i += 1

    debug.set_debug_flags_from_config()

    argv = argv_copy
    if (not argv):
        from bzrlib.builtins import cmd_help
        cmd_help().run_argv_aliases([])
        return 0

    if argv[0] == '--version':
        from bzrlib.builtins import cmd_version
        cmd_version().run_argv_aliases([])
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
            user_encoding = osutils.get_user_encoding()
            alias_argv = [a.decode(user_encoding) for a in alias_argv]
            argv[0] = alias_argv.pop(0)

    cmd = argv.pop(0)
    # We want only 'ascii' command names, but the user may have typed
    # in a Unicode name. In that case, they should just get a
    # 'command not found' error later.

    cmd_obj = get_cmd_object(cmd, plugins_override=not opt_builtin)
    run = cmd_obj.run_argv_aliases
    run_argv = [argv, alias_argv]

    try:
        # We can be called recursively (tests for example), but we don't want
        # the verbosity level to propagate.
        saved_verbosity_level = option._verbosity_level
        option._verbosity_level = 0
        if opt_lsprof:
            if opt_coverage_dir:
                trace.warning(
                    '--coverage ignored, because --lsprof is in use.')
            ret = apply_lsprofiled(opt_lsprof_file, run, *run_argv)
        elif opt_profile:
            if opt_coverage_dir:
                trace.warning(
                    '--coverage ignored, because --profile is in use.')
            ret = apply_profiled(run, *run_argv)
        elif opt_coverage_dir:
            ret = apply_coveraged(opt_coverage_dir, run, *run_argv)
        else:
            ret = run(*run_argv)
        if 'memory' in debug.debug_flags:
            trace.debug_memory('Process status after command:', short=False)
        return ret or 0
    finally:
        # reset, in case we may do other commands later within the same
        # process. Commands that want to execute sub-commands must propagate
        # --verbose in their own way.
        option._verbosity_level = saved_verbosity_level


def display_command(func):
    """Decorator that suppresses pipe/interrupt errors."""
    def ignore_pipe(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            sys.stdout.flush()
            return result
        except IOError, e:
            if getattr(e, 'errno', None) is None:
                raise
            if e.errno != errno.EPIPE:
                # Win32 raises IOError with errno=0 on a broken pipe
                if sys.platform != 'win32' or (e.errno not in (0, errno.EINVAL)):
                    raise
            pass
        except KeyboardInterrupt:
            pass
    return ignore_pipe


def main(argv):
    import bzrlib.ui
    bzrlib.ui.ui_factory = bzrlib.ui.make_ui_for_terminal(
        sys.stdin, sys.stdout, sys.stderr)

    # Is this a final release version? If so, we should suppress warnings
    if bzrlib.version_info[3] == 'final':
        from bzrlib import symbol_versioning
        symbol_versioning.suppress_deprecation_warnings(override=False)
    try:
        user_encoding = osutils.get_user_encoding()
        argv = [a.decode(user_encoding) for a in argv[1:]]
    except UnicodeDecodeError:
        raise errors.BzrError(("Parameter '%r' is unsupported by the current "
                                                            "encoding." % a))
    ret = run_bzr_catch_errors(argv)
    trace.mutter("return code %d", ret)
    return ret


def run_bzr_catch_errors(argv):
    """Run a bzr command with parameters as described by argv.

    This function assumed that that UI layer is setup, that symbol deprecations
    are already applied, and that unicode decoding has already been performed on argv.
    """
    return exception_to_return_code(run_bzr, argv)


def run_bzr_catch_user_errors(argv):
    """Run bzr and report user errors, but let internal errors propagate.

    This is used for the test suite, and might be useful for other programs
    that want to wrap the commandline interface.
    """
    try:
        return run_bzr(argv)
    except Exception, e:
        if (isinstance(e, (OSError, IOError))
            or not getattr(e, 'internal_error', True)):
            trace.report_exception(sys.exc_info(), sys.stderr)
            return 3
        else:
            raise


class HelpCommandIndex(object):
    """A index for bzr help that returns commands."""

    def __init__(self):
        self.prefix = 'commands/'

    def get_topics(self, topic):
        """Search for topic amongst commands.

        :param topic: A topic to search for.
        :return: A list which is either empty or contains a single
            Command entry.
        """
        if topic and topic.startswith(self.prefix):
            topic = topic[len(self.prefix):]
        try:
            cmd = _get_cmd_object(topic)
        except KeyError:
            return []
        else:
            return [cmd]


class Provider(object):
    '''Generic class to be overriden by plugins'''

    def plugin_for_command(self, cmd_name):
        '''Takes a command and returns the information for that plugin

        :return: A dictionary with all the available information
        for the requested plugin
        '''
        raise NotImplementedError


class ProvidersRegistry(registry.Registry):
    '''This registry exists to allow other providers to exist'''

    def __iter__(self):
        for key, provider in self.iteritems():
            yield provider

command_providers_registry = ProvidersRegistry()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
