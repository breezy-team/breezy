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

import sys

import breezy

from ... import cmdline, commands, config, help_topics, option, plugin


class ZshCodeGen:
    """Generate a zsh script for given completion data."""

    def __init__(self, data, function_name="_brz", debug=False):
        self.data = data
        self.function_name = function_name
        self.debug = debug

    def script(self):
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
        lines = []
        for long, short, help in self.data.global_options:
            lines.append(
                "      '({}{}){}[{}]'".format(
                    (short + " ") if short else "", long, long, help
                )
            )

        return "\n".join(lines)


class CompletionData:
    def __init__(self):
        self.plugins = {}
        self.global_options = []
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
        for name, item in option.Option.OPTIONS.items():
            self.data.global_options.append(
                (
                    "--" + item.name,
                    "-" + item.short_name() if item.short_name() else None,
                    item.help.rstrip(),
                )
            )

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
        for optname, opt in sorted(opts.items()):
            cmd_data.options.extend(self.option(opt))

        if name == "help" or "help" in cmd.aliases:
            cmd_data.fixed_words = "($cmds %s)" % " ".join(
                sorted(help_topics.topic_registry.keys())
            )

        return cmd_data

    def option(self, opt):
        optswitches = {}
        parser = option.get_optparser([opt])
        parser = self.wrap_parser(optswitches, parser)
        optswitches.clear()
        opt.add_option(parser, opt.short_name())
        if isinstance(opt, option.RegistryOption) and opt.enum_switch:
            enum_switch = "--%s" % opt.name
            enum_data = optswitches.get(enum_switch)
            if enum_data:
                try:
                    enum_data.registry_keys = opt.registry.keys()
                except ImportError as e:
                    enum_data.error_messages.append(
                        "ERROR getting registry keys for '--%s': %s"
                        % (opt.name, str(e).split("\n")[0])
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


def zsh_completion_function(
    out, function_name="_brz", debug=False, no_plugins=False, selected_plugins=None
):
    dc = DataCollector(no_plugins=no_plugins, selected_plugins=selected_plugins)
    data = dc.collect()
    cg = ZshCodeGen(data, function_name=function_name, debug=debug)
    res = cg.script()
    out.write(res)


class cmd_zsh_completion(commands.Command):
    __doc__ = """Generate a shell function for zsh command line completion.

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
        if "plugin" in kwargs:
            # work around bug #387117 which prevents us from using param_name
            if len(kwargs["plugin"]) > 0:
                kwargs["selected_plugins"] = kwargs["plugin"]
            del kwargs["plugin"]
        zsh_completion_function(sys.stdout, **kwargs)
