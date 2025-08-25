"""Bash completion script generation for Breezy commands.

This module provides functionality to generate bash completion scripts for the
Breezy version control system. It analyzes available commands, their options,
and plugins to create comprehensive tab completion support for the brz command
in bash shells.

The main entry point is the bash_completion_function() which collects command
and option data and generates the appropriate bash script code.
"""
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

import re
import sys

import breezy

from ... import cmdline, commands, config, help_topics
from ... import option as _mod_option
from ... import plugin as _mod_plugin


class BashCodeGen:
    """Generate a bash script for given completion data."""

    def __init__(self, data, function_name="_brz", debug=False):
        """Initialize a BashCodeGen instance.

        Args:
            data: CompletionData instance containing command and option information.
            function_name: Name of the bash completion function to generate.
                Defaults to "_brz".
            debug: Whether to include debugging code in the generated function.
                Defaults to False.
        """
        self.data = data
        self.function_name = function_name
        self.debug = debug

    def script(self):
        """Generate a complete bash completion script.

        Returns:
            str: A complete bash script including the completion function and
                the complete command to enable completion for brz.
        """
        return f"""# Programmable completion for the Breezy brz command under bash.
# Known to work with bash 2.05a as well as bash 4.1.2, and probably
# all versions in between as well.

# Based originally on the svn bash completition script.
# Customized by Sven Wilhelm/Icecrash.com
# Adjusted for automatic generation by Martin von Gagern

# Generated using the bash_completion plugin.
# See https://launchpad.net/bzr-bash-completion for details.

# Commands and options of brz {self.brz_version()}

shopt -s progcomp
{self.function()}
complete -F {self.function_name} -o default brz
"""

    def function(self):
        """Generate the bash completion function code.

        Returns:
            str: The bash function code that implements command completion
                logic for brz commands.
        """
        return f"""\
{self.function_name} ()
{{
    local cur cmds cmdIdx cmd cmdOpts fixedWords i globalOpts
    local curOpt optEnums
    local IFS=$' \\n'

    COMPREPLY=()
    cur=${{COMP_WORDS[COMP_CWORD]}}

    cmds='{self.command_names()}'
    globalOpts=( {self.global_options()} )

    # do ordinary expansion if we are anywhere after a -- argument
    for ((i = 1; i < COMP_CWORD; ++i)); do
        [[ ${{COMP_WORDS[i]}} == "--" ]] && return 0
    done

    # find the command; it's the first word not starting in -
    cmd=
    for ((cmdIdx = 1; cmdIdx < ${{#COMP_WORDS[@]}}; ++cmdIdx)); do
        if [[ ${{COMP_WORDS[cmdIdx]}} != -* ]]; then
            cmd=${{COMP_WORDS[cmdIdx]}}
            break
        fi
    done

    # complete command name if we are not already past the command
    if [[ $COMP_CWORD -le cmdIdx ]]; then
        COMPREPLY=( $( compgen -W "$cmds ${{globalOpts[*]}}" -- $cur ) )
        return 0
    fi

    # find the option for which we want to complete a value
    curOpt=
    if [[ $cur != -* ]] && [[ $COMP_CWORD -gt 1 ]]; then
        curOpt=${{COMP_WORDS[COMP_CWORD - 1]}}
        if [[ $curOpt == = ]]; then
            curOpt=${{COMP_WORDS[COMP_CWORD - 2]}}
        elif [[ $cur == : ]]; then
            cur=
            curOpt="$curOpt:"
        elif [[ $curOpt == : ]]; then
            curOpt=${{COMP_WORDS[COMP_CWORD - 2]}}:
        fi
    fi
{self.debug_output()}
    cmdOpts=( )
    optEnums=( )
    fixedWords=( )
    case $cmd in
{self.command_cases()}\
    *)
        cmdOpts=(--help -h)
        ;;
    esac

    IFS=$'\\n'
    if [[ ${{#fixedWords[@]}} -eq 0 ]] && [[ ${{#optEnums[@]}} -eq 0 ]] && [[ $cur != -* ]]; then
        case $curOpt in
            tag:|*..tag:)
                fixedWords=( $(brz tags 2>/dev/null | sed 's/  *[^ ]*$//; s/ /\\\\\\\\ /g;') )
                ;;
        esac
        case $cur in
            [\\"\\']tag:*)
                fixedWords=( $(brz tags 2>/dev/null | sed 's/  *[^ ]*$//; s/^/tag:/') )
                ;;
            [\\"\\']*..tag:*)
                fixedWords=( $(brz tags 2>/dev/null | sed 's/  *[^ ]*$//') )
                fixedWords=( $(for i in "${{fixedWords[@]}}"; do echo "${{cur%..tag:*}}..tag:${{i}}"; done) )
                ;;
        esac
    elif [[ $cur == = ]] && [[ ${{#optEnums[@]}} -gt 0 ]]; then
        # complete directly after "--option=", list all enum values
        COMPREPLY=( "${{optEnums[@]}}" )
        return 0
    else
        fixedWords=( "${{cmdOpts[@]}}"
                     "${{globalOpts[@]}}"
                     "${{optEnums[@]}}"
                     "${{fixedWords[@]}}" )
    fi

    if [[ ${{#fixedWords[@]}} -gt 0 ]]; then
        COMPREPLY=( $( compgen -W "${{fixedWords[*]}}" -- $cur ) )
    fi

    return 0
}}
"""
        # Help Emacs terminate strings: "

    def command_names(self):
        """Get a space-separated string of all command names and aliases.

        Returns:
            str: All command names and aliases joined by spaces, used in
                the bash completion function for command name completion.
        """
        return " ".join(self.data.all_command_aliases())

    def debug_output(self):
        """Generate debugging code for the bash completion function.

        Returns:
            str: Bash code that displays completion variables at the top
                of the terminal for debugging purposes, or empty string if
                debugging is disabled.
        """
        if not self.debug:
            return ""
        else:
            return r"""
    # Debugging code enabled using the --debug command line switch.
    # Will dump some variables to the top portion of the terminal.
    echo -ne '\e[s\e[H'
    for (( i=0; i < ${#COMP_WORDS[@]}; ++i)); do
        echo "\$COMP_WORDS[$i]='${COMP_WORDS[i]}'"$'\e[K'
    done
    for i in COMP_CWORD COMP_LINE COMP_POINT COMP_TYPE COMP_KEY cur curOpt; do
        echo "\$${i}=\"${!i}\""$'\e[K'
    done
    echo -ne '---\e[K\e[u'
"""

    def brz_version(self):
        """Generate version information string for the script header.

        Returns:
            str: A version string containing the Breezy version and
                information about loaded plugins for inclusion in the
                generated script as a comment.
        """
        brz_version = breezy.version_string
        if not self.data.plugins:
            brz_version += "."
        else:
            brz_version += " and the following plugins:"
            for _name, plugin in sorted(self.data.plugins.items()):
                brz_version += f"\n# {plugin}"
        return brz_version

    def global_options(self):
        """Get a space-separated string of global command-line options.

        Returns:
            str: All global options (like --verbose, --help) joined by
                spaces for use in bash completion.
        """
        return " ".join(sorted(self.data.global_options))

    def command_cases(self):
        """Generate bash case statements for all commands.

        Returns:
            str: Complete bash case statements containing completion logic
                for all available commands and their options.
        """
        cases = ""
        for command in self.data.commands:
            cases += self.command_case(command)
        return cases

    def command_case(self, command):
        """Generate a bash case statement for a single command.

        Args:
            command: CommandData instance containing command information.

        Returns:
            str: A bash case statement that handles completion for the
                given command, including its options and fixed word completions.
        """
        case = f"\t{'|'.join(command.aliases)})\n"
        if command.plugin:
            case += f'\t\t# plugin "{command.plugin}"\n'
        options = []
        enums = []
        for option in command.options:
            for message in option.error_messages:
                case += f"\t\t# {message}\n"
            if option.registry_keys:
                for key in option.registry_keys:
                    options.append(f"{option}={key}")
                enums.append(
                    "{}) optEnums=( {} ) ;;".format(
                        option, " ".join(option.registry_keys)
                    )
                )
            else:
                options.append(str(option))
        case += f"\t\tcmdOpts=( {' '.join(options)} )\n"
        if command.fixed_words:
            fixed_words = command.fixed_words
            if isinstance(fixed_words, list):
                fixed_words = "( %s )" + " ".join(fixed_words)
            case += f"\t\tfixedWords={fixed_words}\n"
        if enums:
            case += "\t\tcase $curOpt in\n\t\t\t"
            case += "\n\t\t\t".join(enums)
            case += "\n\t\tesac\n"
        case += "\t\t;;\n"
        return case


class CompletionData:
    """Container for all completion data used to generate bash completion scripts.

    This class holds information about available commands, global options,
    and loaded plugins that will be used to generate the bash completion function.
    """

    def __init__(self):
        """Initialize an empty CompletionData instance.

        Initializes empty containers for plugins, global options, and commands.
        """
        self.plugins = {}
        self.global_options = set()
        self.commands = []

    def all_command_aliases(self):
        """Yield all command names and aliases.

        Yields:
            str: Each command name and alias across all commands.
        """
        for c in self.commands:
            yield from c.aliases


class CommandData:
    """Data container for a single command's completion information.

    Holds information about a command including its name, aliases, options,
    and associated plugin (if any).
    """

    def __init__(self, name):
        """Initialize command data for the given command name.

        Args:
            name: The primary name of the command.
        """
        self.name = name
        self.aliases = [name]
        self.plugin = None
        self.options = []
        self.fixed_words = None


class PluginData:
    """Data container for plugin information used in completion generation.

    Stores plugin name and version information for display in the
    generated completion script.
    """

    def __init__(self, name, version=None):
        """Initialize plugin data.

        Args:
            name: The plugin name.
            version: The plugin version. If None, attempts to get version
                from the loaded plugin, defaults to "unknown" if unavailable.
        """
        if version is None:
            try:
                version = breezy.plugin.plugins()[name].__version__
            except BaseException:
                version = "unknown"
        self.name = name
        self.version = version

    def __str__(self):
        """Return string representation of plugin information.

        Returns:
            str: Plugin name with version, or just name if version is unknown.
        """
        if self.version == "unknown":
            return self.name
        return f"{self.name} {self.version}"


class OptionData:
    """Data container for command option completion information.

    Stores information about a command option including its name,
    possible values (registry keys), and any error messages.
    """

    def __init__(self, name):
        """Initialize option data.

        Args:
            name: The option name (e.g., '--verbose' or '-v').
        """
        self.name = name
        self.registry_keys = None
        self.error_messages = []

    def __str__(self):
        """Return string representation of the option.

        Returns:
            str: The option name.
        """
        return self.name

    def __lt__(self, other):
        """Compare options by name for sorting.

        Args:
            other: Another OptionData instance to compare against.

        Returns:
            bool: True if this option's name is lexically less than the other.
        """
        return self.name < other.name


class DataCollector:
    """Collects completion data from Breezy commands, options, and plugins.

    This class traverses the available commands and their options to build
    a comprehensive data structure for bash completion generation.
    """

    def __init__(self, no_plugins=False, selected_plugins=None):
        """Initialize the data collector.

        Args:
            no_plugins: If True, don't collect data from any plugins.
            selected_plugins: List of specific plugin names to include.
                If None, all plugins are included. Plugin names with hyphens
                are converted to underscores for internal processing.
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
        """Collect all completion data.

        Gathers global options, user aliases, and command-specific data
        from the Breezy command registry.

        Returns:
            CompletionData: The collected completion data.
        """
        self.global_options()
        self.aliases()
        self.commands()
        return self.data

    def global_options(self):
        """Extract global command-line options from help text.

        Parses the global options help topic to find all global options
        that are available across all commands.
        """
        re_switch = re.compile(r"\n(--[A-Za-z0-9-_]+)(?:, (-\S))?\s")
        help_text = help_topics.topic_registry.get_detail("global-options")
        for long, short in re_switch.findall(help_text):
            self.data.global_options.add(long)
            if short:
                self.data.global_options.add(short)

    def aliases(self):
        """Collect user-defined command aliases from configuration.

        Parses user configuration to find command aliases and maps them
        back to their underlying commands for completion purposes.
        """
        for alias, expansion in config.GlobalConfig().get_aliases().items():
            for token in cmdline.split(expansion):
                if not token.startswith("-"):
                    self.user_aliases.setdefault(token, set()).add(alias)
                    break

    def commands(self):
        """Collect completion data for all available commands.

        Iterates through all registered commands and collects their
        completion data including options and aliases.
        """
        for name in sorted(commands.all_command_names()):
            self.command(name)

    def command(self, name):
        """Collect completion data for a specific command.

        Args:
            name: The name of the command to collect data for.

        Returns:
            CommandData or None: The command data, or None if the command
                is from a plugin that wasn't selected.
        """
        cmd = commands.get_cmd_object(name)
        cmd_data = CommandData(name)

        plugin_name = cmd.plugin_name()
        if plugin_name is not None:
            if (
                self.selected_plugins is not None
                and plugin_name not in self.selected_plugins
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
        """Collect completion data for a command option.

        Args:
            opt: The option object to collect data for.

        Returns:
            list: A list of OptionData objects for the option and its variants.
        """
        optswitches = {}
        parser = _mod_option.get_optparser([opt])
        parser = self.wrap_parser(optswitches, parser)
        optswitches.clear()
        opt.add_option(parser, opt.short_name())
        if isinstance(opt, _mod_option.RegistryOption) and opt.enum_switch:
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
        """Wrap an option container to collect option data.

        Args:
            optswitches: Dictionary to store collected option data.
            parser: The option parser or container to wrap.

        Returns:
            The wrapped parser with modified add_option method.
        """

        def tweaked_add_option(*opts, **attrs):
            for name in opts:
                optswitches[name] = OptionData(name)

        parser.add_option = tweaked_add_option
        return parser

    def wrap_parser(self, optswitches, parser):
        """Wrap an option parser to collect option data from all groups.

        Args:
            optswitches: Dictionary to store collected option data.
            parser: The option parser to wrap.

        Returns:
            The wrapped parser that collects options from all groups.
        """
        orig_add_option_group = parser.add_option_group

        def tweaked_add_option_group(*opts, **attrs):
            return self.wrap_container(
                optswitches, orig_add_option_group(*opts, **attrs)
            )

        parser.add_option_group = tweaked_add_option_group
        return self.wrap_container(optswitches, parser)


def bash_completion_function(
    out,
    function_name="_brz",
    function_only=False,
    debug=False,
    no_plugins=False,
    selected_plugins=None,
):
    """Generate and write a bash completion function to output stream.

    This is the main entry point for generating bash completion scripts.
    It collects completion data from available commands and generates
    the appropriate bash function.

    Args:
        out: Output stream to write the completion script to.
        function_name: Name of the bash function to generate. Defaults to "_brz".
        function_only: If True, generate only the function without the complete
            command to enable it. Defaults to False.
        debug: If True, include debugging code in the generated function.
            Defaults to False.
        no_plugins: If True, don't include completion for any plugins.
            Defaults to False.
        selected_plugins: List of specific plugin names to include completion
            for. If None, all plugins are included.
    """
    dc = DataCollector(no_plugins=no_plugins, selected_plugins=selected_plugins)
    data = dc.collect()
    cg = BashCodeGen(data, function_name=function_name, debug=debug)
    res = cg.function() if function_only else cg.script()
    out.write(res)


class cmd_bash_completion(commands.Command):
    """Generate a shell function for bash command line completion.

    This command generates a shell function which can be used by bash to
    automatically complete the currently typed command when the user presses
    the completion key (usually tab).

    Commonly used like this:
        eval "`brz bash-completion`"
    """

    takes_options = [
        _mod_option.Option(
            "function-name",
            short_name="f",
            type=str,
            argname="name",
            help="Name of the generated function (default: _brz)",
        ),
        _mod_option.Option(
            "function-only",
            short_name="o",
            type=None,
            help="Generate only the shell function, don't enable it",
        ),
        _mod_option.Option(
            "debug",
            type=None,
            hidden=True,
            help="Enable shell code useful for debugging",
        ),
        _mod_option.ListOption(
            "plugin",
            type=str,
            argname="name",
            # param_name="selected_plugins", # doesn't work, bug #387117
            help="Enable completions for the selected plugin"
            + " (default: all plugins)",
        ),
    ]

    def run(self, **kwargs):
        """Execute the bash-completion command.

        Args:
            **kwargs: Command-line arguments passed from the option parser.
                Includes function_name, function_only, debug, and plugin options.
        """
        if "plugin" in kwargs:
            # work around bug #387117 which prevents us from using param_name
            if len(kwargs["plugin"]) > 0:
                kwargs["selected_plugins"] = kwargs["plugin"]
            del kwargs["plugin"]
        bash_completion_function(sys.stdout, **kwargs)


if __name__ == "__main__":
    import locale
    import optparse

    def plugin_callback(option, opt, value, parser):
        """Callback function for handling --plugin command-line option.

        Args:
            option: The Option instance that's calling the callback.
            opt: The option string seen on the command-line.
            value: The argument to this option seen on the command-line.
            parser: The OptionParser instance driving the whole thing.
        """
        values = parser.values.selected_plugins
        if value == "-":
            del values[:]
        else:
            values.append(value)

    parser = optparse.OptionParser(usage="%prog [-f NAME] [-o]")
    parser.add_option(
        "--function-name",
        "-f",
        metavar="NAME",
        help="Name of the generated function (default: _brz)",
    )
    parser.add_option(
        "--function-only",
        "-o",
        action="store_true",
        help="Generate only the shell function, don't enable it",
    )
    parser.add_option("--debug", action="store_true", help=optparse.SUPPRESS_HELP)
    parser.add_option(
        "--no-plugins", action="store_true", help="Don't load any brz plugins"
    )
    parser.add_option(
        "--plugin",
        metavar="NAME",
        type="string",
        dest="selected_plugins",
        default=[],
        action="callback",
        callback=plugin_callback,
        help="Enable completions for the selected plugin" + " (default: all plugins)",
    )
    (opts, args) = parser.parse_args()
    if args:
        parser.error("script does not take positional arguments")
    kwargs = {}
    for name, value in opts.__dict__.items():
        if value is not None:
            kwargs[name] = value

    locale.setlocale(locale.LC_ALL, "")
    if not kwargs.get("no_plugins", False):
        _mod_plugin.load_plugins()
    commands.install_bzr_command_hooks()
    bash_completion_function(sys.stdout, **kwargs)
