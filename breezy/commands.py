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

# TODO: Define arguments by objects, rather than just using names.
# Those objects can specify the expected type of the argument, which
# would help with validation and shell completion.  They could also provide
# help/explanation for that argument in a structured way.

# TODO: Specific "examples" property on commands for consistent formatting.

__docformat__ = "google"

import contextlib
import os
import sys
from typing import List, Optional, Union

from . import i18n, option, trace
from .lazy_import import lazy_import

lazy_import(
    globals(),
    """

import breezy
from breezy import (
    cmdline,
    debug,
    ui,
    )
""",
)

from . import errors, registry
from .hooks import Hooks
from .i18n import gettext
from .plugin import disable_plugins, load_plugins, plugin_name


class CommandAvailableInPlugin(Exception):
    internal_error = False

    def __init__(self, cmd_name, plugin_metadata, provider):
        self.plugin_metadata = plugin_metadata
        self.cmd_name = cmd_name
        self.provider = provider

    def __str__(self):
        _fmt = (
            '"{}" is not a standard brz command. \n'
            "However, the following official plugin provides this command: {}\n"
            "You can install it by going to: {}".format(self.cmd_name, self.plugin_metadata["name"], self.plugin_metadata["url"])
        )

        return _fmt


class CommandInfo:
    """Information about a command."""

    def __init__(self, aliases):
        """The list of aliases for the command."""
        self.aliases = aliases

    @classmethod
    def from_command(klass, command):
        """Factory to construct a CommandInfo from a command."""
        return klass(command.aliases)


class CommandRegistry(registry.Registry):
    """Special registry mapping command names to command classes.

    Attributes:
      overridden_registry: Look in this registry for commands being
        overridden by this registry.  This can be used to tell plugin commands
        about the builtin they're decorating.
    """

    def __init__(self):
        registry.Registry.__init__(self)
        self.overridden_registry = None
        # map from aliases to the real command that implements the name
        self._alias_dict = {}

    def get(self, command_name):
        real_name = self._alias_dict.get(command_name, command_name)
        return registry.Registry.get(self, real_name)

    @staticmethod
    def _get_name(command_name):
        if command_name.startswith("cmd_"):
            return _unsquish_command_name(command_name)
        else:
            return command_name

    def register(self, cmd, decorate=False):
        """Utility function to help register a command.

        Args:
          cmd: Command subclass to register
          decorate: If true, allow overriding an existing command
            of the same name; the old command is returned by this function.
            Otherwise it is an error to try to override an existing command.
        """
        k = cmd.__name__
        k_unsquished = self._get_name(k)
        try:
            previous = self.get(k_unsquished)
        except KeyError:
            previous = None
            if self.overridden_registry:
                try:
                    previous = self.overridden_registry.get(k_unsquished)
                except KeyError:
                    pass
        info = CommandInfo.from_command(cmd)
        try:
            registry.Registry.register(
                self, k_unsquished, cmd, override_existing=decorate, info=info
            )
        except KeyError:
            trace.warning("Two plugins defined the same command: {!r}".format(k))
            trace.warning("Not loading the one in {!r}".format(sys.modules[cmd.__module__]))
            trace.warning(
                "Previously this command was registered from {!r}".format(sys.modules[previous.__module__])
            )
        for a in cmd.aliases:
            self._alias_dict[a] = k_unsquished
        return previous

    def register_lazy(self, command_name, aliases, module_name):
        """Register a command without loading its module.

        Args:
          command_name: The primary name of the command.
          aliases: A list of aliases for the command.
          module_name: The module that the command lives in.
        """
        key = self._get_name(command_name)
        registry.Registry.register_lazy(
            self, key, module_name, command_name, info=CommandInfo(aliases)
        )
        for a in aliases:
            self._alias_dict[a] = key


plugin_cmds = CommandRegistry()
builtin_command_registry = CommandRegistry()
plugin_cmds.overridden_registry = builtin_command_registry


def register_command(cmd, decorate=False):
    """Register a plugin command.

    Should generally be avoided in favor of lazy registration.
    """
    global plugin_cmds
    return plugin_cmds.register(cmd, decorate)


def _squish_command_name(cmd):
    return "cmd_" + cmd.replace("-", "_")


def _unsquish_command_name(cmd):
    return cmd[4:].replace("_", "-")


def _register_builtin_commands():
    if builtin_command_registry.keys():
        # only load once
        return
    import breezy.builtins

    for cmd_class in _scan_module_for_commands(breezy.builtins):
        builtin_command_registry.register(cmd_class)
    breezy.builtins._register_lazy_builtins()


def _scan_module_for_commands(module):
    module_dict = module.__dict__
    for name in module_dict:
        if name.startswith("cmd_"):
            yield module_dict[name]


def _list_bzr_commands(names):
    """Find commands from bzr's core and plugins.

    This is not the public interface, just the default hook called by
    all_command_names.
    """
    # to eliminate duplicates
    names.update(builtin_command_names())
    names.update(plugin_command_names())
    return names


def all_command_names():
    """Return a set of all command names."""
    names = set()
    for hook in Command.hooks["list_commands"]:
        names = hook(names)
        if names is None:
            raise AssertionError(
                "hook {} returned None".format(Command.hooks.get_hook_name(hook))
            )
    return names


def builtin_command_names():
    """Return list of builtin command names.

    Use of all_command_names() is encouraged rather than builtin_command_names
    and/or plugin_command_names.
    """
    _register_builtin_commands()
    return builtin_command_registry.keys()


def plugin_command_names():
    """Returns command names from commands registered by plugins."""
    return plugin_cmds.keys()


# Overrides for common mispellings that heuristics get wrong
_GUESS_OVERRIDES = {
    "ic": {"ci": 0},  # heuristic finds nick
}


def guess_command(cmd_name):
    """Guess what command a user typoed.

    Args:
      cmd_name: Command to search for
    Returns:
      None if no command was found, name of a command otherwise
    """
    names = set()
    for name in all_command_names():
        names.add(name)
        cmd = get_cmd_object(name)
        names.update(cmd.aliases)
    # candidate: modified levenshtein distance against cmd_name.
    costs = {}
    import patiencediff

    for name in sorted(names):
        matcher = patiencediff.PatienceSequenceMatcher(None, cmd_name, name)
        distance = 0.0
        opcodes = matcher.get_opcodes()
        for opcode, l1, l2, r1, r2 in opcodes:
            if opcode == "delete":
                distance += l2 - l1
            elif opcode == "replace":
                distance += max(l2 - l1, r2 - l1)
            elif opcode == "insert":
                distance += r2 - r1
            elif opcode == "equal":
                # Score equal ranges lower, making similar commands of equal
                # length closer than arbitrary same length commands.
                distance -= 0.1 * (l2 - l1)
        costs[name] = distance
    costs.update(_GUESS_OVERRIDES.get(cmd_name, {}))
    costs = sorted((costs[key], key) for key in costs)
    if not costs:
        return
    if costs[0][0] > 4:
        return
    candidate = costs[0][1]
    return candidate


def get_cmd_object(cmd_name: str, plugins_override: bool = True) -> "Command":
    """Return the command object for a command.

    plugins_override
        If true, plugin commands can override builtins.
    """
    try:
        return _get_cmd_object(cmd_name, plugins_override)
    except KeyError:
        # No command found, see if this was a typo
        candidate = guess_command(cmd_name)
        if candidate is not None:
            raise errors.CommandError(
                gettext('unknown command "%s". Perhaps you meant "%s"')
                % (cmd_name, candidate)
            )
        raise errors.CommandError(gettext('unknown command "%s"') % cmd_name)


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
    # We want only 'ascii' command names, but the user may have typed
    # in a Unicode name. In that case, they should just get a
    # 'command not found' error later.
    # In the future, we may actually support Unicode command names.
    cmd: Optional[Command] = None
    # Get a command
    for hook in Command.hooks["get_command"]:
        cmd = hook(cmd, cmd_name)
        if cmd is not None and not plugins_override and not cmd.plugin_name():
            # We've found a non-plugin command, don't permit it to be
            # overridden.
            break
    if cmd is None and check_missing:
        for hook in Command.hooks["get_missing_command"]:
            cmd = hook(cmd_name)
            if cmd is not None:
                break
    if cmd is None:
        # No command found.
        raise KeyError
    # Allow plugins to extend commands
    for hook in Command.hooks["extend_command"]:
        hook(cmd)
    if getattr(cmd, "invoked_as", None) is None:
        cmd.invoked_as = cmd_name
    return cmd


class NoPluginAvailable(errors.BzrError):
    pass


def _try_plugin_provider(cmd_name):
    """Probe for a plugin provider having cmd_name."""
    try:
        plugin_metadata, provider = probe_for_provider(cmd_name)
        raise CommandAvailableInPlugin(cmd_name, plugin_metadata, provider)
    except NoPluginAvailable:
        pass


def probe_for_provider(cmd_name):
    """Look for a provider for cmd_name.

    Args:
      cmd_name: The command name.

    Returns:
      plugin_metadata, provider for getting cmd_name.

    Raises:
      NoPluginAvailable: When no provider can supply the plugin.
    """
    # look for providers that provide this command but aren't installed
    for provider in command_providers_registry:
        try:
            return provider.plugin_for_command(cmd_name), provider
        except NoPluginAvailable:
            pass
    raise NoPluginAvailable(cmd_name)


def _get_bzr_command(cmd_or_None, cmd_name):
    """Get a command from bzr's core."""
    try:
        cmd_class = builtin_command_registry.get(cmd_name)
    except KeyError:
        pass
    else:
        return cmd_class()
    return cmd_or_None


def _get_external_command(cmd_or_None, cmd_name):
    """Lookup a command that is a shell script."""
    # Only do external command lookups when no command is found so far.
    if cmd_or_None is not None:
        return cmd_or_None
    from breezy.externalcommand import ExternalCommand

    cmd_obj = ExternalCommand.find_command(cmd_name)
    if cmd_obj:
        return cmd_obj


def _get_plugin_command(cmd_or_None, cmd_name):
    """Get a command from brz's plugins."""
    try:
        return plugin_cmds.get(cmd_name)()
    except KeyError:
        pass
    for key in plugin_cmds.keys():
        info = plugin_cmds.get_info(key)
        if cmd_name in info.aliases:
            return plugin_cmds.get(key)()
    return cmd_or_None


class Command:
    """Base class for commands.

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

    aliases: List[str] = []
    takes_args: List[str] = []
    takes_options: List[Union[str, option.Option]] = []
    encoding_type: str = "strict"
    invoked_as: Optional[str] = None
    l10n: bool = True
    _see_also: List[str]

    hidden: bool = False

    hooks: Hooks

    def __init__(self):
        """Construct an instance of this command."""
        # List of standard options directly supported
        self.supported_std_options = []
        self._setup_run()

    def add_cleanup(self, cleanup_func, *args, **kwargs):
        """Register a function to call after self.run returns or raises.

        Functions will be called in LIFO order.
        """
        self._exit_stack.callback(cleanup_func, *args, **kwargs)

    def cleanup_now(self):
        """Execute and empty pending cleanup functions immediately.

        After cleanup_now all registered cleanups are forgotten.  add_cleanup
        may be called again after cleanup_now; these cleanups will be called
        after self.run returns or raises (or when cleanup_now is next called).

        This is useful for releasing expensive or contentious resources (such
        as write locks) before doing further work that does not require those
        resources (such as writing results to self.outf). Note though, that
        as it releases all resources, this may release locks that the command
        wants to hold, so use should be done with care.
        """
        self._exit_stack.close()

    def enter_context(self, cm):
        return self._exit_stack.enter_context(cm)

    def _usage(self):
        """Return single-line grammar for this command.

        Only describes arguments, not options.
        """
        s = "brz " + self.name() + " "
        for aname in self.takes_args:
            aname = aname.upper()
            if aname[-1] in ["$", "+"]:
                aname = aname[:-1] + "..."
            elif aname[-1] == "?":
                aname = "[" + aname[:-1] + "]"
            elif aname[-1] == "*":
                aname = "[" + aname[:-1] + "...]"
            s += aname + " "
        s = s[:-1]  # remove last space
        return s

    def get_help_text(
        self,
        additional_see_also=None,
        plain=True,
        see_also_as_links=False,
        verbose=True,
    ):
        """Return a text string with help for this command.

        Args:
          additional_see_also: Additional help topics to be
            cross-referenced.
          plain: if False, raw help (reStructuredText) is
            returned instead of plain text.
          see_also_as_links: if True, convert items in 'See also'
            list to internal links (used by bzr_man rstx generator)
          verbose: if True, display the full help, otherwise
            leave out the descriptive sections and just display
            usage help (e.g. Purpose, Usage, Options) with a
            message explaining how to obtain full help.
        """
        if self.l10n:
            i18n.install()  # Install i18n only for get_help_text for now.
        doc = self.help()
        if doc:
            # Note: If self.gettext() translates ':Usage:\n', the section will
            # be shown after "Description" section and we don't want to
            # translate the usage string.
            # Though, brz export-pot don't exports :Usage: section and it must
            # not be translated.
            doc = self.gettext(doc)
        else:
            doc = gettext("No help for this command.")

        # Extract the summary (purpose) and sections out from the text
        purpose, sections, order = self._get_help_parts(doc)

        # If a custom usage section was provided, use it
        if "Usage" in sections:
            usage = sections.pop("Usage")
        else:
            usage = self._usage()

        # The header is the purpose and usage
        result = ""
        result += gettext(":Purpose: %s\n") % (purpose,)
        if usage.find("\n") >= 0:
            result += gettext(":Usage:\n%s\n") % (usage,)
        else:
            result += gettext(":Usage:   %s\n") % (usage,)
        result += "\n"

        # Add the options
        #
        # XXX: optparse implicitly rewraps the help, and not always perfectly,
        # so we get <https://bugs.launchpad.net/bzr/+bug/249908>.  -- mbp
        # 20090319
        parser = option.get_optparser([v for k, v in sorted(self.options().items())])
        options = parser.format_option_help()
        # FIXME: According to the spec, ReST option lists actually don't
        # support options like --1.14 so that causes syntax errors (in Sphinx
        # at least).  As that pattern always appears in the commands that
        # break, we trap on that and then format that block of 'format' options
        # as a literal block. We use the most recent format still listed so we
        # don't have to do that too often -- vila 20110514
        if not plain and options.find("  --1.14  ") != -1:
            options = options.replace(" format:\n", " format::\n\n", 1)
        if options.startswith("Options:"):
            result += gettext(":Options:%s") % (options[len("options:") :],)
        else:
            result += options
        result += "\n"

        if verbose:
            # Add the description, indenting it 2 spaces
            # to match the indentation of the options
            if None in sections:
                text = sections.pop(None)
                text = "\n  ".join(text.splitlines())
                result += gettext(":Description:\n  %s\n\n") % (text,)

            # Add the custom sections (e.g. Examples). Note that there's no need
            # to indent these as they must be indented already in the source.
            if sections:
                for label in order:
                    if label in sections:
                        result += ":{}:\n{}\n".format(label, sections[label])
                result += "\n"
        else:
            result += (
                gettext("See brz help %s for more details and examples.\n\n")
                % self.name()
            )

        # Add the aliases, source (plug-in) and see also links, if any
        if self.aliases:
            result += gettext(":Aliases:  ")
            result += ", ".join(self.aliases) + "\n"
        plugin_name = self.plugin_name()
        if plugin_name is not None:
            result += gettext(':From:     plugin "%s"\n') % plugin_name
        see_also = self.get_see_also(additional_see_also)
        if see_also:
            if not plain and see_also_as_links:
                see_also_links = []
                for item in see_also:
                    if item == "topics":
                        # topics doesn't have an independent section
                        # so don't create a real link
                        see_also_links.append(item)
                    else:
                        # Use a Sphinx link for this entry
                        link_text = gettext(":doc:`{0} <{1}-help>`").format(item, item)
                        see_also_links.append(link_text)
                see_also = see_also_links
            result += gettext(":See also: %s") % ", ".join(see_also) + "\n"

        # If this will be rendered as plain text, convert it
        if plain:
            import breezy.help_topics

            result = breezy.help_topics.help_as_plain_text(result)
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
                if label in sections:
                    sections[label] += "\n" + section
                else:
                    order.append(label)
                    sections[label] = section

        lines = text.rstrip().splitlines()
        summary = lines.pop(0)
        sections = {}
        order = []
        label, section = None, ""
        for line in lines:
            if line.startswith(":") and line.endswith(":") and len(line) > 2:
                save_section(sections, order, label, section)
                label, section = line[1:-1], ""
            elif label is not None and len(line) > 1 and not line[0].isspace():
                save_section(sections, order, label, section)
                label, section = None, line
            else:
                if len(section) > 0:
                    section += "\n" + line
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

        Args:
          additional_terms: Additional help topics to cross-reference.

        Returns:
          A list of help topics.
        """
        see_also = set(getattr(self, "_see_also", []))
        if additional_terms:
            see_also.update(additional_terms)
        return sorted(see_also)

    def options(self):
        """Return dict of valid options for this command.

        Maps from long option name to option object.
        """
        r = option.Option.STD_OPTIONS.copy()
        std_names = set(r)
        for o in self.takes_options:
            if isinstance(o, str):
                o = option.Option.OPTIONS[o]
            r[o.name] = o
            if o.name in std_names:
                self.supported_std_options.append(o.name)
        return r

    def _setup_outf(self):
        """Return a file linked to stdout, which has proper encoding."""
        self.outf = ui.ui_factory.make_output_stream(encoding_type=self.encoding_type)

    def run_argv_aliases(self, argv, alias_argv=None):
        """Parse the command line and run with extra aliases in alias_argv."""
        args, opts = parse_args(self, argv, alias_argv)
        self._setup_outf()

        # Process the standard options
        if "help" in opts:  # e.g. brz add --help
            self.outf.write(self.get_help_text())
            return 0
        if "usage" in opts:  # e.g. brz add --usage
            self.outf.write(self.get_help_text(verbose=False))
            return 0
        trace.set_verbosity_level(option._verbosity_level)
        if "verbose" in self.supported_std_options:
            opts["verbose"] = trace.is_verbose()
        elif "verbose" in opts:
            del opts["verbose"]
        if "quiet" in self.supported_std_options:
            opts["quiet"] = trace.is_quiet()
        elif "quiet" in opts:
            del opts["quiet"]
        # mix arguments and options into one dictionary
        cmdargs = _match_argform(self.name(), self.takes_args, args)
        cmdopts = {}
        for k, v in opts.items():
            cmdopts[k.replace("-", "_")] = v

        all_cmd_args = cmdargs.copy()
        all_cmd_args.update(cmdopts)

        try:
            return self.run(**all_cmd_args)
        finally:
            # reset it, so that other commands run in the same process won't
            # inherit state. Before we reset it, log any activity, so that it
            # gets properly tracked.
            ui.ui_factory.log_transport_activity(display=("bytes" in debug.debug_flags))
            trace.set_verbosity_level(0)

    def _setup_run(self):
        """Wrap the defined run method on self with a cleanup.

        This is called by __init__ to make the Command be able to be run
        by just calling run(), as it could be before cleanups were added.

        If a different form of cleanups are in use by your Command subclass,
        you can override this method.
        """
        class_run = self.run

        def run(*args, **kwargs):
            for hook in Command.hooks["pre_command"]:
                hook(self)
            try:
                with contextlib.ExitStack() as self._exit_stack:
                    return class_run(*args, **kwargs)
            finally:
                for hook in Command.hooks["post_command"]:
                    hook(self)

        self.run = run

    def run(self):  # type: ignore
        """Actually run the command.

        This is invoked with the options and arguments bound to
        keyword parameters.

        Return 0 or None if the command was successful, or a non-zero
        shell error code if not.  It's OK for this method to allow
        an exception to raise up.

        This method is automatically wrapped by Command.__init__ with a
        ExitStack, stored as self._exit_stack. This can be used
        via self.add_cleanup to perform automatic cleanups at the end of
        run().

        The argument for run are assembled by introspection. So for instance,
        if your command takes an argument files, you would declare::

            def run(self, files=None):
                pass
        """
        raise NotImplementedError("no implementation of command {!r}".format(self.name()))

    def help(self):
        """Return help message for this class."""
        from inspect import getdoc

        if self.__doc__ is Command.__doc__:
            return None
        return getdoc(self)

    def gettext(self, message):
        """Returns the gettext function used to translate this command's help.

        Commands provided by plugins should override this to use their
        own i18n system.
        """
        return i18n.gettext_per_paragraph(message)

    def name(self):
        """Return the canonical name for this command.

        The name under which it was actually invoked is available in invoked_as
        """
        return _unsquish_command_name(self.__class__.__name__)

    def plugin_name(self):
        """Get the name of the plugin that provides this command.

        :return: The name of the plugin or None if the command is builtin.
        """
        return plugin_name(self.__module__)


class CommandHooks(Hooks):
    """Hooks related to Command object creation/enumeration."""

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        Hooks.__init__(self, "breezy.commands", "Command.hooks")
        self.add_hook(
            "extend_command",
            "Called after creating a command object to allow modifications "
            "such as adding or removing options, docs etc. Called with the "
            "new breezy.commands.Command object.",
            (1, 13),
        )
        self.add_hook(
            "get_command",
            "Called when creating a single command. Called with "
            "(cmd_or_None, command_name). get_command should either return "
            "the cmd_or_None parameter, or a replacement Command object that "
            "should be used for the command. Note that the Command.hooks "
            "hooks are core infrastructure. Many users will prefer to use "
            "breezy.commands.register_command or plugin_cmds.register_lazy.",
            (1, 17),
        )
        self.add_hook(
            "get_missing_command",
            "Called when creating a single command if no command could be "
            "found. Called with (command_name). get_missing_command should "
            "either return None, or a Command object to be used for the "
            "command.",
            (1, 17),
        )
        self.add_hook(
            "list_commands",
            "Called when enumerating commands. Called with a set of "
            "cmd_name strings for all the commands found so far. This set "
            " is safe to mutate - e.g. to remove a command. "
            "list_commands should return the updated set of command names.",
            (1, 17),
        )
        self.add_hook(
            "pre_command",
            "Called prior to executing a command. Called with the command object.",
            (2, 6),
        )
        self.add_hook(
            "post_command",
            "Called after executing a command. Called with the command object.",
            (2, 6),
        )


Command.hooks = CommandHooks()  # type: ignore


def parse_args(command, argv, alias_argv=None):
    """Parse command line.

    Arguments and options are parsed at this level before being passed
    down to specific command handlers.  This routine knows, from a
    lookup table, something about the available options, what optargs
    they take, and which commands will accept them.
    """
    # TODO: make it a method of the Command?
    parser = option.get_optparser([v for k, v in sorted(command.options().items())])
    if alias_argv is not None:
        args = alias_argv + argv
    else:
        args = argv

    # python 2's optparse raises this exception if a non-ascii
    # option name is given.  See http://bugs.python.org/issue2931
    try:
        options, args = parser.parse_args(args)
    except UnicodeEncodeError:
        raise errors.CommandError(gettext("Only ASCII permitted in option names"))

    opts = {
        k: v
        for k, v in options.__dict__.items()
        if v is not option.OptionParser.DEFAULT_VALUE
    }
    return args, opts


def _match_argform(cmd, takes_args, args):
    argdict = {}

    # step through args and takes_args, allowing appropriate 0-many matches
    for ap in takes_args:
        argname = ap[:-1]
        if ap[-1] == "?":
            if args:
                argdict[argname] = args.pop(0)
        elif ap[-1] == "*":  # all remaining arguments
            if args:
                argdict[argname + "_list"] = args[:]
                args = []
            else:
                argdict[argname + "_list"] = None
        elif ap[-1] == "+":
            if not args:
                raise errors.CommandError(
                    gettext("command {0!r} needs one or more {1}").format(
                        cmd, argname.upper()
                    )
                )
            else:
                argdict[argname + "_list"] = args[:]
                args = []
        elif ap[-1] == "$":  # all but one
            if len(args) < 2:
                raise errors.CommandError(
                    gettext("command {0!r} needs one or more {1}").format(
                        cmd, argname.upper()
                    )
                )
            argdict[argname + "_list"] = args[:-1]
            args[:-1] = []
        else:
            # just a plain arg
            argname = ap
            if not args:
                raise errors.CommandError(
                    gettext("command {0!r} requires argument {1}").format(
                        cmd, argname.upper()
                    )
                )
            else:
                argdict[argname] = args.pop(0)

    if args:
        raise errors.CommandError(
            gettext("extra argument to command {0}: {1}").format(cmd, args[0])
        )

    return argdict


def apply_coveraged(the_callable, *args, **kwargs):
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
    from breezy.lsprof import profile

    ret, stats = profile(exception_to_return_code, the_callable, *args, **kwargs)
    stats.sort()
    if filename is None:
        stats.pprint()
    else:
        stats.save(filename)
        trace.note(gettext('Profile data written to "%s".'), filename)
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
    trace.mutter("breezy version: " + breezy.__version__)
    argv = _specified_or_unicode_argv(argv)
    trace.mutter("brz arguments: %r", argv)

    opt_lsprof = opt_profile = opt_no_plugins = opt_builtin = opt_coverage = (
        opt_no_l10n
    ) = opt_no_aliases = False
    opt_lsprof_file = None

    # --no-plugins is handled specially at a very early stage. We need
    # to load plugins before doing other command parsing so that they
    # can override commands, but this needs to happen first.

    argv_copy = []
    i = 0
    override_config = []
    while i < len(argv):
        a = argv[i]
        if a == "--profile":
            opt_profile = True
        elif a == "--lsprof":
            opt_lsprof = True
        elif a == "--lsprof-file":
            opt_lsprof = True
            opt_lsprof_file = argv[i + 1]
            i += 1
        elif a == "--no-plugins":
            opt_no_plugins = True
        elif a == "--no-aliases":
            opt_no_aliases = True
        elif a == "--no-l10n":
            opt_no_l10n = True
        elif a == "--builtin":
            opt_builtin = True
        elif a == "--concurrency":
            os.environ["BRZ_CONCURRENCY"] = argv[i + 1]
            i += 1
        elif a == "--coverage":
            opt_coverage = True
        elif a == "--profile-imports":
            pass  # already handled in startup script Bug #588277
        elif a.startswith("-D"):
            debug.debug_flags.add(a[2:])
        elif a.startswith("-O"):
            override_config.append(a[2:])
        else:
            argv_copy.append(a)
        i += 1

    cmdline_overrides = breezy.get_global_state().cmdline_overrides
    cmdline_overrides._from_cmdline(override_config)

    debug.set_debug_flags_from_config()

    if not opt_no_plugins:
        from breezy import config

        c = config.GlobalConfig()
        warn_load_problems = not c.suppress_warning("plugin_load_failure")
        load_plugins(warn_load_problems=warn_load_problems)
    else:
        disable_plugins()

    argv = argv_copy
    if not argv:
        get_cmd_object("help").run_argv_aliases([])
        return 0

    if argv[0] == "--version":
        get_cmd_object("version").run_argv_aliases([])
        return 0

    alias_argv = None

    if not opt_no_aliases:
        alias_argv = get_alias(argv[0])
        if alias_argv:
            argv[0] = alias_argv.pop(0)

    cmd = argv.pop(0)
    cmd_obj = get_cmd_object(cmd, plugins_override=not opt_builtin)
    if opt_no_l10n:
        cmd_obj.l10n = False
    run = cmd_obj.run_argv_aliases
    run_argv = [argv, alias_argv]

    try:
        # We can be called recursively (tests for example), but we don't want
        # the verbosity level to propagate.
        saved_verbosity_level = option._verbosity_level
        option._verbosity_level = 0
        if opt_lsprof:
            if opt_coverage:
                trace.warning("--coverage ignored, because --lsprof is in use.")
            ret = apply_lsprofiled(opt_lsprof_file, run, *run_argv)
        elif opt_profile:
            if opt_coverage:
                trace.warning("--coverage ignored, because --profile is in use.")
            ret = apply_profiled(run, *run_argv)
        elif opt_coverage:
            ret = apply_coveraged(run, *run_argv)
        else:
            ret = run(*run_argv)
        return ret or 0
    finally:
        # reset, in case we may do other commands later within the same
        # process. Commands that want to execute sub-commands must propagate
        # --verbose in their own way.
        if "memory" in debug.debug_flags:
            trace.debug_memory("Process status after command:", short=False)
        option._verbosity_level = saved_verbosity_level
        # Reset the overrides
        cmdline_overrides._reset()


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
    if _list_bzr_commands in Command.hooks["list_commands"]:
        return
    Command.hooks.install_named_hook(
        "list_commands", _list_bzr_commands, "bzr commands"
    )
    Command.hooks.install_named_hook("get_command", _get_bzr_command, "bzr commands")
    Command.hooks.install_named_hook(
        "get_command", _get_plugin_command, "bzr plugin commands"
    )
    Command.hooks.install_named_hook(
        "get_command", _get_external_command, "bzr external command lookup"
    )
    Command.hooks.install_named_hook(
        "get_missing_command", _try_plugin_provider, "bzr plugin-provider-db check"
    )


def _specified_or_unicode_argv(argv):
    # For internal or testing use, argv can be passed.  Otherwise, get it from
    # the process arguments.
    if argv is None:
        return sys.argv[1:]
    new_argv = []
    try:
        # ensure all arguments are unicode strings
        for a in argv:
            if not isinstance(a, str):
                raise ValueError("not native str or unicode: {!r}".format(a))
            new_argv.append(a)
    except (ValueError, UnicodeDecodeError):
        raise errors.BzrError("argv should be list of unicode strings.")
    return new_argv


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
    if argv is not None:
        argv = argv[1:]
    _register_builtin_commands()
    ret = run_bzr_catch_errors(argv)
    trace.mutter("return code %d", ret)
    return ret


def run_bzr_catch_errors(argv):
    """Run a bzr command with parameters as described by argv.

    This function assumed that that UI layer is setup, that symbol deprecations
    are already applied, and that unicode decoding has already been performed
    on argv.
    """
    # done here so that they're covered for every test run
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
        self.prefix = "commands/"

    def get_topics(self, topic):
        """Search for topic amongst commands.

        Args:
          topic: A topic to search for.

        Returns:
          A list which is either empty or contains a single
          Command entry.
        """
        if topic and topic.startswith(self.prefix):
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


class ProvidersRegistry(registry.Registry):
    """This registry exists to allow other providers to exist."""

    def __iter__(self):
        for _key, provider in self.items():
            yield provider


command_providers_registry = ProvidersRegistry()
