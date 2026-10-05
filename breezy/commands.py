# Copyright (C) 2005-2011 Canonical Ltd
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

"""Infrastructure for command handling in Breezy.

This module provides the command registry, base Command class, and supporting
infrastructure for the breezy command-line interface. It handles command
discovery, argument parsing, help generation, and execution.

Commands are registered with the builtin_command_registry or plugin_cmds
registry, and are automatically discovered and made available to the user.
"""

# TODO: Define arguments by objects, rather than just using names.
# Those objects can specify the expected type of the argument, which
# would help with validation and shell completion.  They could also provide
# help/explanation for that argument in a structured way.

# TODO: Specific "examples" property on commands for consistent formatting.

__docformat__ = "google"

import os
import sys

from . import i18n, trace
from .lazy_import import lazy_import

lazy_import(
    globals(),
    """

import breezy
from breezy import (
    cmdline,
    ui,
    )
""",
)


from . import errors
from ._cmd_rs import commands as _commands_rs
from .hooks import Hooks
from .plugin import disable_plugins, load_plugins


class CommandAvailableInPlugin(Exception):
    """Exception indicating a command is available in a plugin."""

    internal_error = False

    def __init__(self, cmd_name, plugin_metadata, provider):
        """Initialize CommandAvailableInPlugin.

        Args:
            cmd_name: Name of the command.
            plugin_metadata: Metadata about the plugin providing the command.
            provider: Provider object for the plugin.
        """
        self.plugin_metadata = plugin_metadata
        self.cmd_name = cmd_name
        self.provider = provider

    def __str__(self):
        """Return string representation of the exception."""
        return _commands_rs.command_available_in_plugin(
            self.cmd_name, self.plugin_metadata["name"], self.plugin_metadata["url"]
        )


# A command registered in plugin_cmds overrides the builtin one of the same
# name.
from ._cmd_rs.commands import CommandInfo, CommandRegistry  # noqa: F401

builtin_command_registry = _commands_rs.builtin_command_registry()
plugin_cmds = _commands_rs.plugin_command_registry(builtin_command_registry)


def register_command(cmd, decorate=False):
    """Register a plugin command.

    Should generally be avoided in favor of lazy registration.
    """
    return _commands_rs.register_command(cmd, decorate)


_register_builtin_commands = _commands_rs.register_builtin_commands
_scan_module_for_commands = _commands_rs.scan_module_for_commands


def all_command_names():
    """Return a set of all command names."""
    return _commands_rs.all_command_names()


def builtin_command_names():
    """Return list of builtin command names.

    Use of all_command_names() is encouraged rather than builtin_command_names
    and/or plugin_command_names.
    """
    return _commands_rs.builtin_command_names()


def plugin_command_names():
    """Returns command names from commands registered by plugins."""
    return _commands_rs.plugin_command_names()


def guess_command(cmd_name):
    """Guess what command a user typoed.

    Args:
      cmd_name: Command to search for
    Returns:
      None if no command was found, name of a command otherwise
    """
    return _commands_rs.guess_typoed_command(cmd_name)


def get_cmd_object(cmd_name: str, plugins_override: bool = True) -> "Command":
    """Return the command object for a command.

    plugins_override
        If true, plugin commands can override builtins.
    """
    return _commands_rs.get_cmd_object(cmd_name, plugins_override)


def _get_cmd_object(
    cmd_name: str, plugins_override: bool = True, check_missing: bool = True
) -> "Command":
    """Get a command object.

    Args:
      cmd_name: The name of the command.
      plugins_override: Allow plugins to override builtins.
      check_missing: Look up commands not found in the regular index via
        the get_missing_command hook.

    Returns:
      A Command object instance

    Raises:
      KeyError: If no command is found.
    """
    cmd = _commands_rs.get_cmd_object_inner(cmd_name, plugins_override, check_missing)
    if cmd is None:
        raise KeyError
    return cmd


class NoPluginAvailable(errors.BzrError):
    """Error raised when no plugin is available to provide a command."""

    pass


# Registered as a get_missing_command hook.
_try_plugin_provider = _commands_rs.try_plugin_provider


def probe_for_provider(cmd_name):
    """Look for a provider for cmd_name.

    Args:
      cmd_name: The command name.

    Returns:
      plugin_metadata, provider for getting cmd_name.

    Raises:
      NoPluginAvailable: When no provider can supply the plugin.
    """
    return _commands_rs.probe_for_provider(cmd_name)


# Looks up a command that is a shell script; registered as a get_command hook.
_get_external_command = _commands_rs.get_external_command


# The class-attribute defaults and the base docstring are set on the class
# here so that subclass overrides resolve through the normal MRO and help()'s
# `self.__doc__ is Command.__doc__` identity check works.
from ._cmd_rs.commands import Command

Command.__doc__ = """Base class for commands.

    Commands are the heart of the command-line brz interface.

    The command object mostly handles the mapping of command-line
    parameters into one or more breezy operations, and of the results
    into textual output.

    Commands normally don't have any state.  All their arguments are
    passed in to the run method.  (Subclasses may take a different
    policy if the behaviour of the instance needs to depend on e.g. a
    shell plugin and not just its Python class.)

    The docstring for an actual command should give a single-line
    summary, then a complete description of the command.  A grammar
    description will be inserted.

    Attributes:
      aliases: Other accepted names for this command.

      takes_args: List of argument forms, marked with whether they are
        optional, repeated, etc.  Examples::

            ['to_location', 'from_branch?', 'file*']

        * 'to_location' is required
        * 'from_branch' is optional
        * 'file' can be specified 0 or more times

      takes_options: List of options that may be given for this command.
        These can be either strings, referring to globally-defined options, or
        option objects.  Retrieve through options().

      hidden: If true, this command isn't advertised.  This is typically
        for commands intended for expert users.

      encoding_type: Command objects will get a 'outf' attribute, which has
        been setup to properly handle encoding of unicode strings.
        encoding_type determines what will happen when characters cannot be
        encoded:

        * strict - abort if we cannot decode
        * replace - put in a bogus character (typically '?')
        * exact - do not encode sys.stdout

        NOTE: by default on Windows, sys.stdout is opened as a text stream,
        therefore LF line-endings are converted to CRLF.  When a command uses
        encoding_type = 'exact', then sys.stdout is forced to be a binary
        stream, and line-endings will not mangled.

      invoked_as:
        A string indicating the real name under which this command was
        invoked, before expansion of aliases.
        (This may be None if the command was constructed and run in-process.)

      hooks: An instance of CommandHooks.

      __doc__: The help shown by 'brz help command' for this command.
        This is set by assigning explicitly to __doc__ so that -OO can
        be used::

            class Foo(Command):
                __doc__ = "My help goes here"
    """

Command.aliases = []
Command.takes_args = []
Command.takes_options = []
Command.encoding_type = "strict"
Command.invoked_as = None
Command.l10n = True
Command.hidden = False


class CommandHooks(Hooks):
    """Hooks related to Command object creation/enumeration."""

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        Hooks.__init__(self, "breezy.commands", "Command.hooks")
        _commands_rs.add_command_hooks(self)


Command.hooks = CommandHooks()  # type: ignore


def parse_args(command, argv, alias_argv=None):
    """Parse command line.

    Arguments and options are parsed at this level before being passed
    down to specific command handlers.  This routine knows, from a
    lookup table, something about the available options, what optargs
    they take, and which commands will accept them.
    """
    return _commands_rs.parse_args(command, argv, alias_argv)


def _match_argform(cmd, takes_args, args):
    return _commands_rs.match_argform(cmd, list(takes_args), list(args))


def apply_coveraged(the_callable, *args, **kwargs):
    """Run a callable under coverage measurement.

    Args:
        the_callable: Function to call under coverage.
        *args: Arguments to pass to the callable.
        **kwargs: Keyword arguments to pass to the callable.

    Returns:
        Result of calling the_callable.
    """
    import coverage

    cov = coverage.Coverage()
    config_file = cov.config.config_file
    os.environ["COVERAGE_PROCESS_START"] = config_file
    cov.start()
    try:
        return exception_to_return_code(the_callable, *args, **kwargs)
    finally:
        cov.stop()
        cov.save()


def apply_profiled(the_callable, *args, **kwargs):
    """Run a callable under hotshot profiler.

    Args:
        the_callable: Function to call under profiling.
        *args: Arguments to pass to the callable.
        **kwargs: Keyword arguments to pass to the callable.

    Returns:
        Result of calling the_callable.
    """
    import tempfile

    import hotshot
    import hotshot.stats

    pffileno, pfname = tempfile.mkstemp()
    try:
        prof = hotshot.Profile(pfname)
        try:
            ret = (
                prof.runcall(exception_to_return_code, the_callable, *args, **kwargs)
                or 0
            )
        finally:
            prof.close()
        stats = hotshot.stats.load(pfname)
        stats.strip_dirs()
        stats.sort_stats("cum")  # 'time'
        # XXX: Might like to write to stderr or the trace file instead but
        # print_stats seems hardcoded to stdout
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
    except (KeyboardInterrupt, Exception):
        # used to handle AssertionError and KeyboardInterrupt
        # specially here, but hopefully they're handled ok by the logger now
        exc_info = sys.exc_info()
        exitcode = trace.report_exception(exc_info, sys.stderr)
        if os.environ.get("BRZ_PDB"):
            print("**** entering debugger")
            import pdb

            pdb.post_mortem(exc_info[2])
        return exitcode


def apply_lsprofiled(filename, the_callable, *args, **kwargs):
    """Run a callable under lsprof profiler.

    Args:
        filename: File to save profile data to, or None to print to stdout.
        the_callable: Function to call under profiling.
        *args: Arguments to pass to the callable.
        **kwargs: Keyword arguments to pass to the callable.

    Returns:
        Result of calling the_callable.
    """
    from .lsprof import profile

    ret, stats = profile(exception_to_return_code, the_callable, *args, **kwargs)
    stats.sort()
    if filename is None:
        stats.pprint()
    else:
        stats.save(filename)
        trace.note(i18n.gettext('Profile data written to "%s".'), filename)
    return ret


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
        import breezy.config

        config = breezy.config.GlobalConfig()
    alias = config.get_alias(cmd)
    if alias:
        return cmdline.split(alias)
    return None


def run_bzr(argv, load_plugins=load_plugins, disable_plugins=disable_plugins):
    """Execute a command.

    Args:
      argv: The command-line arguments, without the program name from
        argv[0] These should already be decoded. All library/test code calling
        run_bzr should be passing valid strings (don't need decoding).
      load_plugins: What function to call when triggering plugin loading.
        This function should take no arguments and cause all plugins to be
        loaded.
      disable_plugins: What function to call when disabling plugin
        loading. This function should take no arguments and cause all plugin
        loading to be prohibited (so that code paths in your application that
        know about some plugins possibly being present will fail to import
        those plugins even if they are installed.)

    Returns:
      Returns a command exit code or raises an exception.

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
        Generate code coverage report

    --concurrency
        Specify the number of processes that can be run concurrently
        (selftest).
    """
    return _commands_rs.run_bzr(argv, load_plugins, disable_plugins)


def display_command(func):
    """Decorator that suppresses pipe/interrupt errors."""

    def ignore_pipe(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            sys.stdout.flush()
            return result
        except OSError as e:
            import errno

            if getattr(e, "errno", None) is None:
                raise
            if e.errno != errno.EPIPE:
                # Win32 raises IOError with errno=0 on a broken pipe
                if sys.platform != "win32" or (e.errno not in (0, errno.EINVAL)):
                    raise
            pass
        except KeyboardInterrupt:
            pass

    return ignore_pipe


def install_bzr_command_hooks():
    """Install the hooks to supply bzr's own commands."""
    _commands_rs.install_bzr_command_hooks()


def main(argv=None):
    """Main entry point of command-line interface.

    Typically `breezy.initialize` should be called first.

    Args:
      argv: list of unicode command-line arguments similar to sys.argv.
        argv[0] is script name usually, it will be ignored.
        Don't pass here sys.argv because this list contains plain strings
        and not unicode; pass None instead.

    Returns:
      exit code of brz command.
    """
    return _commands_rs.main(argv)


def run_bzr_catch_errors(argv):
    """Run a bzr command with parameters as described by argv.

    This function assumes that the UI layer is set up, and that unicode
    decoding has already been performed on argv. An error is reported and
    turned into an exit code.
    """
    install_bzr_command_hooks()
    return exception_to_return_code(run_bzr, argv)


def run_bzr_catch_user_errors(argv):
    """Run brz and report user errors, but let internal errors propagate.

    This is used for the test suite, and might be useful for other programs
    that want to wrap the commandline interface.
    """
    # done here so that they're covered for every test run
    install_bzr_command_hooks()
    try:
        return run_bzr(argv)
    except Exception as e:
        if isinstance(e, (OSError, IOError)) or not getattr(e, "internal_error", True):
            trace.report_exception(sys.exc_info(), sys.stderr)
            return 3
        else:
            raise


class HelpCommandIndex:
    """A index for bzr help that returns commands."""

    def __init__(self):
        """Initialize HelpCommandIndex."""
        self.prefix = "commands/"

    def get_topics(self, topic):
        """Search for topic amongst commands.

        Args:
          topic: A topic to search for.

        Returns:
          A list which is either empty or contains a single
          Command entry.
        """
        if not topic:
            return []
        if topic.startswith(self.prefix):
            topic = topic[len(self.prefix) :]
        try:
            cmd = _get_cmd_object(topic, check_missing=False)
        except KeyError:
            return []
        else:
            return [cmd]


class Provider:
    """Generic class to be overriden by plugins."""

    def plugin_for_command(self, cmd_name):
        """Takes a command and returns the information for that plugin.

        :return: A dictionary with all the available information
            for the requested plugin
        """
        raise NotImplementedError


# Iterating a ProvidersRegistry yields the registered providers rather than
# their keys.
from ._cmd_rs.commands import ProvidersRegistry

command_providers_registry = ProvidersRegistry()
