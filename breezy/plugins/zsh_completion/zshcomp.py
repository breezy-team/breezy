# Copyright (C) 2009, 2010 Canonical Ltd
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

"""Zsh shell completion generation for Breezy commands.

This module provides functionality to generate zsh completion scripts for Breezy
commands. It analyzes available commands, options, plugins, and user aliases to
create comprehensive shell completion support.

The main entry point is the cmd_zsh_completion command which outputs a complete
zsh completion function that can be sourced or evaluated to enable tab completion
for Breezy commands in zsh shells.
"""

import sys

import breezy

from ... import cmdline, commands, config, help_topics, option, plugin


class ZshCodeGen:
    """Generate a zsh script for given completion data."""

    def __init__(self, data, function_name="_brz", debug=False):
        """Initialize a zsh code generator.

        Args:
            data (CompletionData): The completion data to generate code for.
            function_name (str, optional): The name of the zsh function to generate.
                Defaults to "_brz".
            debug (bool, optional): Whether to enable debug output. Defaults to False.
        """
        self.data = data
        self.function_name = function_name
        self.debug = debug

    def script(self):
        """Generate the complete zsh completion script.

        Returns:
            str: A complete zsh completion script that can be sourced or evaluated
                to provide command completion for Breezy commands.
        """
        return """\
#compdef brz bzr

%(function_name)s ()
{
    local ret=1
    local -a args
    args+=(
%(global-options)s
    )

    _arguments $args[@] && ret=0

    return ret
}

%(function_name)s
""" % {"global-options": self.global_options(), "function_name": self.function_name}

    def global_options(self):
        """Generate zsh completion code for global Breezy options.

        Returns:
            str: Formatted zsh completion arguments for global options that can
                be used in the _arguments function.
        """
        lines = []
        for long, short, help in self.data.global_options:
            lines.append(
                f"      '({short + ' ' if short else ''}{long}){long}[{help}]'"
            )

        return "\n".join(lines)


class CompletionData:
    """Container for all completion data including commands, options, and plugins.

    This class holds all the information needed to generate zsh completion scripts
    for Breezy commands, including global options, command-specific data, and
    plugin information.

    Attributes:
        plugins (dict): Dictionary mapping plugin names to PluginData objects.
        global_options (list): List of tuples containing (long_name, short_name, help)
            for global options.
        commands (list): List of CommandData objects representing available commands.
    """

    def __init__(self):
        """Initialize empty completion data container."""
        self.plugins = {}
        self.global_options = []
        self.commands = []

    def all_command_aliases(self):
        """Generate all command aliases across all commands.

        Yields:
            str: Each alias name from all commands in the completion data.
        """
        for c in self.commands:
            yield from c.aliases


class CommandData:
    """Data container for a single Breezy command and its completion information.

    Attributes:
        name (str): The primary name of the command.
        aliases (list): List of all aliases for this command, including the primary name.
        plugin (PluginData or None): The plugin that provides this command, if any.
        options (list): List of OptionData objects for command-specific options.
        fixed_words (str or None): Fixed completion words for special commands like help.
    """

    def __init__(self, name):
        """Initialize command data with the given name.

        Args:
            name (str): The primary name of the command.
        """
        self.name = name
        self.aliases = [name]
        self.plugin = None
        self.options = []
        self.fixed_words = None


class PluginData:
    """Data container for plugin information used in completion generation.

    Attributes:
        name (str): The name of the plugin.
        version (str): The version of the plugin, or "unknown" if not available.
    """

    def __init__(self, name, version=None):
        """Initialize plugin data with name and optional version.

        Args:
            name (str): The name of the plugin.
            version (str, optional): The version of the plugin. If None, attempts
                to retrieve from the plugin's __version__ attribute. Defaults to None.
        """
        if version is None:
            try:
                version = breezy.plugin.plugins()[name].__version__
            except BaseException:
                version = "unknown"
        self.name = name
        self.version = version

    def __str__(self):
        """Return a string representation of the plugin.

        Returns:
            str: The plugin name, optionally followed by version if known.
        """
        if self.version == "unknown":
            return self.name
        return f"{self.name} {self.version}"


class OptionData:
    """Data container for command-line option completion information.

    Attributes:
        name (str): The name of the option (including leading dashes).
        registry_keys (list or None): Available registry keys for registry options.
        error_messages (list): List of error messages encountered while processing
            this option.
    """

    def __init__(self, name):
        """Initialize option data with the given name.

        Args:
            name (str): The name of the option (including leading dashes).
        """
        self.name = name
        self.registry_keys = None
        self.error_messages = []

    def __str__(self):
        """Return the string representation of the option.

        Returns:
            str: The option name.
        """
        return self.name

    def __lt__(self, other):
        """Compare options for sorting by name.

        Args:
            other (OptionData): Another OptionData object to compare with.

        Returns:
            bool: True if this option's name is lexicographically less than the other's.
        """
        return self.name < other.name


class DataCollector:
    """Collects completion data from Breezy commands, options, and plugins.

    This class is responsible for gathering all the information needed to generate
    zsh completion scripts by examining available commands, their options, global
    options, user aliases, and plugin information.

    Attributes:
        data (CompletionData): The collected completion data.
        user_aliases (dict): Dictionary mapping command names to sets of user-defined aliases.
        selected_plugins (set or None): Set of selected plugin names, None for all plugins,
            or empty set for no plugins.
    """

    def __init__(self, no_plugins=False, selected_plugins=None):
        """Initialize the data collector with plugin selection options.

        Args:
            no_plugins (bool, optional): If True, exclude all plugins from completion.
                Defaults to False.
            selected_plugins (list or None, optional): List of plugin names to include
                in completion. If None, includes all plugins. Defaults to None.
        """
        self.data = CompletionData()
        self.user_aliases = {}
        if no_plugins:
            self.selected_plugins = set()
        elif selected_plugins is None:
            self.selected_plugins = None
        else:
            self.selected_plugins = {x.replace("-", "_") for x in selected_plugins}

    def collect(self):
        """Collect all completion data from the Breezy installation.

        This method orchestrates the collection of global options, user aliases,
        and command information to build a complete CompletionData object.

        Returns:
            CompletionData: A complete data structure containing all information
                needed for zsh completion generation.
        """
        self.global_options()
        self.aliases()
        self.commands()
        return self.data

    def global_options(self):
        """Collect global command-line options available to all commands.

        Populates the global_options list in the completion data with tuples
        containing the long form, short form, and help text for each global option.
        """
        for _name, item in option.Option.OPTIONS.items():
            self.data.global_options.append(
                (
                    "--" + item.name,
                    "-" + item.short_name() if item.short_name() else None,
                    item.help.rstrip(),
                )
            )

    def aliases(self):
        """Collect user-defined command aliases from the global configuration.

        Parses the user's alias configuration to build a mapping from command names
        to the aliases that expand to them. Only considers the first non-option token
        in each alias expansion.
        """
        for alias, expansion in config.GlobalConfig().get_aliases().items():
            for token in cmdline.split(expansion):
                if not token.startswith("-"):
                    self.user_aliases.setdefault(token, set()).add(alias)
                    break

    def commands(self):
        """Collect completion data for all available Breezy commands.

        Iterates through all registered command names and collects their completion
        data, respecting plugin selection criteria.
        """
        for name in sorted(commands.all_command_names()):
            self.command(name)

    def command(self, name):
        """Collect completion data for a specific command.

        Args:
            name (str): The name of the command to collect data for.

        Returns:
            CommandData or None: The collected command data, or None if the command
                is from an excluded plugin.
        """
        cmd = commands.get_cmd_object(name)
        cmd_data = CommandData(name)

        plugin_name = cmd.plugin_name()
        if plugin_name is not None:
            if (
                self.selected_plugins is not None
                and plugin not in self.selected_plugins
            ):
                return None
            plugin_data = self.data.plugins.get(plugin_name)
            if plugin_data is None:
                plugin_data = PluginData(plugin_name)
                self.data.plugins[plugin_name] = plugin_data
            cmd_data.plugin = plugin_data
        self.data.commands.append(cmd_data)

        # Find all aliases to the command; both cmd-defined and user-defined.
        # We assume a user won't override one command with a different one,
        # but will choose completely new names or add options to existing
        # ones while maintaining the actual command name unchanged.
        cmd_data.aliases.extend(cmd.aliases)
        cmd_data.aliases.extend(
            sorted(
                [
                    useralias
                    for cmdalias in cmd_data.aliases
                    if cmdalias in self.user_aliases
                    for useralias in self.user_aliases[cmdalias]
                    if useralias not in cmd_data.aliases
                ]
            )
        )

        opts = cmd.options()
        for _optname, opt in sorted(opts.items()):
            cmd_data.options.extend(self.option(opt))

        if name == "help" or "help" in cmd.aliases:
            cmd_data.fixed_words = "($cmds {})".format(
                " ".join(sorted(help_topics.topic_registry.keys()))
            )

        return cmd_data

    def option(self, opt):
        """Collect completion data for a command-line option.

        Args:
            opt (option.Option): The option object to collect data for.

        Returns:
            list: A sorted list of OptionData objects representing the option
                and any related switches.
        """
        optswitches = {}
        parser = option.get_optparser([opt])
        parser = self.wrap_parser(optswitches, parser)
        optswitches.clear()
        opt.add_option(parser, opt.short_name())
        if isinstance(opt, option.RegistryOption) and opt.enum_switch:
            enum_switch = f"--{opt.name}"
            enum_data = optswitches.get(enum_switch)
            if enum_data:
                try:
                    enum_data.registry_keys = opt.registry.keys()
                except ImportError as e:
                    enum_data.error_messages.append(
                        "ERROR getting registry keys for '--{}': {}".format(
                            opt.name, str(e).split("\n")[0]
                        )
                    )
        return sorted(optswitches.values())

    def wrap_container(self, optswitches, parser):
        """Wrap an option container to capture option names.

        Args:
            optswitches (dict): Dictionary to store captured OptionData objects.
            parser: The option parser or group to wrap.

        Returns:
            The wrapped parser with modified add_option method.
        """

        def tweaked_add_option(*opts, **attrs):
            for name in opts:
                optswitches[name] = OptionData(name)

        parser.add_option = tweaked_add_option
        return parser

    def wrap_parser(self, optswitches, parser):
        """Wrap an option parser to capture all option names including those in groups.

        Args:
            optswitches (dict): Dictionary to store captured OptionData objects.
            parser: The option parser to wrap.

        Returns:
            The wrapped parser with modified add_option and add_option_group methods.
        """
        orig_add_option_group = parser.add_option_group

        def tweaked_add_option_group(*opts, **attrs):
            return self.wrap_container(
                optswitches, orig_add_option_group(*opts, **attrs)
            )

        parser.add_option_group = tweaked_add_option_group
        return self.wrap_container(optswitches, parser)


def zsh_completion_function(
    out, function_name="_brz", debug=False, no_plugins=False, selected_plugins=None
):
    """Generate a zsh completion function and write it to the given output stream.

    This is the main entry point for generating zsh completion scripts. It collects
    completion data from the Breezy installation and generates a complete zsh
    completion function.

    Args:
        out: Output stream to write the completion script to.
        function_name (str, optional): The name of the zsh completion function to generate.
            Defaults to "_brz".
        debug (bool, optional): Whether to enable debug features in the generated script.
            Defaults to False.
        no_plugins (bool, optional): If True, exclude all plugins from completion.
            Defaults to False.
        selected_plugins (list or None, optional): List of specific plugin names to include
            in completion. If None, includes all plugins. Defaults to None.
    """
    dc = DataCollector(no_plugins=no_plugins, selected_plugins=selected_plugins)
    data = dc.collect()
    cg = ZshCodeGen(data, function_name=function_name, debug=debug)
    res = cg.script()
    out.write(res)


class cmd_zsh_completion(commands.Command):
    """Generate a shell function for zsh command line completion.

    This command generates a shell function which can be used by zsh to
    automatically complete the currently typed command when the user presses
    the completion key (usually tab).

    Commonly used like this:
        eval "`brz zsh-completion`"
    """

    takes_options = [
        option.Option(
            "function-name",
            short_name="f",
            type=str,
            argname="name",
            help="Name of the generated function (default: _brz)",
        ),
        option.Option(
            "debug",
            type=None,
            hidden=True,
            help="Enable shell code useful for debugging",
        ),
        option.ListOption(
            "plugin",
            type=str,
            argname="name",
            # param_name="selected_plugins", # doesn't work, bug #387117
            help="Enable completions for the selected plugin"
            + " (default: all plugins)",
        ),
    ]

    def run(self, **kwargs):
        """Execute the zsh-completion command.

        Args:
            **kwargs: Keyword arguments containing the command options:
                - function_name (str, optional): Name of the generated function.
                - debug (bool, optional): Enable debug features.
                - plugin (list, optional): List of plugins to include.
        """
        if "plugin" in kwargs:
            # work around bug #387117 which prevents us from using param_name
            if len(kwargs["plugin"]) > 0:
                kwargs["selected_plugins"] = kwargs["plugin"]
            del kwargs["plugin"]
        zsh_completion_function(sys.stdout, **kwargs)
