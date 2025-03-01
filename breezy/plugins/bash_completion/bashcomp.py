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

from ... import cmdline, commands, config, help_topics, option, plugin


class BashCodeGen:
    """Generate a bash script for given completion data."""

    def __init__(self, data, function_name="_brz", debug=False):
        self.data = data
        self.function_name = function_name
        self.debug = debug

    def script(self):
        return """\
# Programmable completion for the Breezy brz command under bash.
# Known to work with bash 2.05a as well as bash 4.1.2, and probably
# all versions in between as well.

# Based originally on the svn bash completition script.
# Customized by Sven Wilhelm/Icecrash.com
# Adjusted for automatic generation by Martin von Gagern

# Generated using the bash_completion plugin.
# See https://launchpad.net/bzr-bash-completion for details.

# Commands and options of brz {brz_version}

shopt -s progcomp
{function}
complete -F {function_name} -o default brz
""".format(
            function_name=self.function_name,
            function=self.function(),
            brz_version=self.brz_version(),
        )

    def function(self):
        return """\
{function_name} ()
{{
    local cur cmds cmdIdx cmd cmdOpts fixedWords i globalOpts
    local curOpt optEnums
    local IFS=$' \\n'

    COMPREPLY=()
    cur=${{COMP_WORDS[COMP_CWORD]}}

    cmds='{cmds}'
    globalOpts=( {global_options} )

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
{debug}
    cmdOpts=( )
    optEnums=( )
    fixedWords=( )
    case $cmd in
{cases}\
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
""".format(
            cmds=self.command_names(),
            function_name=self.function_name,
            cases=self.command_cases(),
            global_options=self.global_options(),
            debug=self.debug_output(),
        )
        # Help Emacs terminate strings: "

    def command_names(self):
        return " ".join(self.data.all_command_aliases())

    def debug_output(self):
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
        brz_version = breezy.version_string
        if not self.data.plugins:
            brz_version += "."
        else:
            brz_version += " and the following plugins:"
            for _name, plugin in sorted(self.data.plugins.items()):
                brz_version += "\n# {}".format(plugin)
        return brz_version

    def global_options(self):
        return " ".join(sorted(self.data.global_options))

    def command_cases(self):
        cases = ""
        for command in self.data.commands:
            cases += self.command_case(command)
        return cases

    def command_case(self, command):
        case = "\t{})\n".format("|".join(command.aliases))
        if command.plugin:
            case += '\t\t# plugin "{}"\n'.format(command.plugin)
        options = []
        enums = []
        for option in command.options:
            for message in option.error_messages:
                case += "\t\t# {}\n".format(message)
            if option.registry_keys:
                for key in option.registry_keys:
                    options.append("{}={}".format(option, key))
                enums.append(
                    "{}) optEnums=( {} ) ;;".format(option, " ".join(option.registry_keys))
                )
            else:
                options.append(str(option))
        case += "\t\tcmdOpts=( {} )\n".format(" ".join(options))
        if command.fixed_words:
            fixed_words = command.fixed_words
            if isinstance(fixed_words, list):
                fixed_words = "( %s )" + " ".join(fixed_words)
            case += "\t\tfixedWords={}\n".format(fixed_words)
        if enums:
            case += "\t\tcase $curOpt in\n\t\t\t"
            case += "\n\t\t\t".join(enums)
            case += "\n\t\tesac\n"
        case += "\t\t;;\n"
        return case


class CompletionData:
    def __init__(self):
        self.plugins = {}
        self.global_options = set()
        self.commands = []

    def all_command_aliases(self):
        for c in self.commands:
            yield from c.aliases


class CommandData:
    def __init__(self, name):
        self.name = name
        self.aliases = [name]
        self.plugin = None
        self.options = []
        self.fixed_words = None


class PluginData:
    def __init__(self, name, version=None):
        if version is None:
            try:
                version = breezy.plugin.plugins()[name].__version__
            except:
                version = "unknown"
        self.name = name
        self.version = version

    def __str__(self):
        if self.version == "unknown":
            return self.name
        return "{} {}".format(self.name, self.version)


class OptionData:
    def __init__(self, name):
        self.name = name
        self.registry_keys = None
        self.error_messages = []

    def __str__(self):
        return self.name

    def __lt__(self, other):
        return self.name < other.name


class DataCollector:
    def __init__(self, no_plugins=False, selected_plugins=None):
        self.data = CompletionData()
        self.user_aliases = {}
        if no_plugins:
            self.selected_plugins = set()
        elif selected_plugins is None:
            self.selected_plugins = None
        else:
            self.selected_plugins = {x.replace("-", "_") for x in selected_plugins}

    def collect(self):
        self.global_options()
        self.aliases()
        self.commands()
        return self.data

    def global_options(self):
        re_switch = re.compile(r"\n(--[A-Za-z0-9-_]+)(?:, (-\S))?\s")
        help_text = help_topics.topic_registry.get_detail("global-options")
        for long, short in re_switch.findall(help_text):
            self.data.global_options.add(long)
            if short:
                self.data.global_options.add(short)

    def aliases(self):
        for alias, expansion in config.GlobalConfig().get_aliases().items():
            for token in cmdline.split(expansion):
                if not token.startswith("-"):
                    self.user_aliases.setdefault(token, set()).add(alias)
                    break

    def commands(self):
        for name in sorted(commands.all_command_names()):
            self.command(name)

    def command(self, name):
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
            cmd_data.fixed_words = "($cmds {})".format(" ".join(
                sorted(help_topics.topic_registry.keys())
            ))

        return cmd_data

    def option(self, opt):
        optswitches = {}
        parser = option.get_optparser([opt])
        parser = self.wrap_parser(optswitches, parser)
        optswitches.clear()
        opt.add_option(parser, opt.short_name())
        if isinstance(opt, option.RegistryOption) and opt.enum_switch:
            enum_switch = "--{}".format(opt.name)
            enum_data = optswitches.get(enum_switch)
            if enum_data:
                try:
                    enum_data.registry_keys = opt.registry.keys()
                except ImportError as e:
                    enum_data.error_messages.append(
                        "ERROR getting registry keys for '--{}': {}".format(opt.name, str(e).split("\n")[0])
                    )
        return sorted(optswitches.values())

    def wrap_container(self, optswitches, parser):
        def tweaked_add_option(*opts, **attrs):
            for name in opts:
                optswitches[name] = OptionData(name)

        parser.add_option = tweaked_add_option
        return parser

    def wrap_parser(self, optswitches, parser):
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
    dc = DataCollector(no_plugins=no_plugins, selected_plugins=selected_plugins)
    data = dc.collect()
    cg = BashCodeGen(data, function_name=function_name, debug=debug)
    if function_only:
        res = cg.function()
    else:
        res = cg.script()
    out.write(res)


class cmd_bash_completion(commands.Command):
    __doc__ = """Generate a shell function for bash command line completion.

    This command generates a shell function which can be used by bash to
    automatically complete the currently typed command when the user presses
    the completion key (usually tab).

    Commonly used like this:
        eval "`brz bash-completion`"
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
            "function-only",
            short_name="o",
            type=None,
            help="Generate only the shell function, don't enable it",
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
        plugin.load_plugins()
    commands.install_bzr_command_hooks()
    bash_completion_function(sys.stdout, **kwargs)
