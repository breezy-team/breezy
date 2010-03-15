#!/usr/bin/env python

# Copyright (C) 2009, 2010  Martin von Gagern
#
# This file is part of bzr-bash-completion
#
# bzr-bash-completion free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 2 of the
# License, or (at your option) any later version.
#
# bzr-bash-completion is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from meta import __version__
from bzrlib import (
    commands,
    config,
    help_topics,
    option,
    plugin,
)
import re

head="""\
# Programmable completion for the Bazaar-NG bzr command under bash.
# Known to work with bash 2.05a as well as bash 4.1.2, and probably
# all versions in between as well.

# Based originally on the svn bash completition script.
# Customized by Sven Wilhelm/Icecrash.com
# Adjusted for automatic generation by Martin von Gagern

# Generated using the bzr-bash-completion plugin version %(version)s.
# See https://launchpad.net/bzr-bash-completion for details.

shopt -s progcomp
"""
fun="""\
%(function_name)s ()
{
	local cur cmds cmdIdx cmd cmdOpts fixedWords i globalOpts

	COMPREPLY=()
	cur=${COMP_WORDS[COMP_CWORD]}

	cmds='%(cmds)s'
	globalOpts='%(global_options)s'

	# do ordinary expansion if we are anywhere after a -- argument
	for ((i = 1; i < COMP_CWORD; ++i)); do
		[[ ${COMP_WORDS[i]} == "--" ]] && return 0
	done

	# find the command; it's the first word not starting in -
	cmd=
	for ((cmdIdx = 1; cmdIdx < ${#COMP_WORDS[@]}; ++cmdIdx)); do
		if [[ ${COMP_WORDS[cmdIdx]} != -* ]]; then
			cmd=${COMP_WORDS[cmdIdx]}
			break
		fi
	done

	# complete command name if we are not already past the command
	if [[ $COMP_CWORD -le cmdIdx ]] ; then
		COMPREPLY=( $( compgen -W "$cmds $globalOpts" -- $cur ) )
		return 0
	fi

	cmdOpts=
	fixedWords=
	case $cmd in
%(cases)s\
	*)
		cmdOpts='--help -h'
		;;
	esac

	# if not typing an option, and if we don't know all the
	# possible non-option arguments for the current command,
	# then fallback on ordinary filename expansion
	if [[ -z $fixedWords ]] && [[ $cur != -* ]] ; then
		return 0
	fi

	COMPREPLY=( $( compgen -W "$cmdOpts $globalOpts $fixedWords" -- $cur ) )

	return 0
}
"""
tail="""\
complete -F %(function_name)s -o default bzr
"""

def wrap_container(list, parser):
    def tweaked_add_option(*opts, **attrs):
        list.extend(opts)
    parser.add_option = tweaked_add_option
    return parser

def wrap_parser(list, parser):
    orig_add_option_group = parser.add_option_group
    def tweaked_add_option_group(*opts, **attrs):
        return wrap_container(list, orig_add_option_group(*opts, **attrs))
    parser.add_option_group = tweaked_add_option_group
    return wrap_container(list, parser)

def bash_completion_function(out, function_name="_bzr", function_only=False):
    cmds = []
    cases = ""
    reqarg = {}

    re_switch = re.compile(r'\n(--[A-Za-z0-9-_]+)(?:, (-\S))?\s')
    help_text = help_topics.topic_registry.get_detail('global-options')
    global_options = set()
    for long, short in re_switch.findall(help_text):
        global_options.add(long)
        if short:
            global_options.add(short)
    global_options = " ".join(sorted(global_options))

    user_aliases = {} # dict from cmd name to set of user-defined alias names
    for alias, expansion in config.GlobalConfig().get_aliases().iteritems():
        for token in commands.shlex_split_unicode(expansion):
            if not token.startswith("-"):
                user_aliases.setdefault(token, set()).add(alias)
                break

    all_cmds = sorted(commands.all_command_names())
    for cmdname in all_cmds:
        cmd = commands.get_cmd_object(cmdname)

        # Find all aliases to the command; both cmd-defined and user-defined.
        # We assume a user won't override one command with a different one,
        # but will choose completely new names or add options to existing
        # ones while maintaining the actual command name unchanged.
        aliases = [cmdname]
        aliases.extend(cmd.aliases)
        aliases.extend(sorted([alias
                               for name in aliases
                               if name in user_aliases
                               for alias in user_aliases[name]
                               if alias not in aliases]))
        cases += "\t%s)\n" % "|".join(aliases)
        cmds.extend(aliases)
        plugin = cmd.plugin_name()
        if plugin is not None:
            cases += "\t\t# plugin \"%s\"\n" % plugin
        opts = cmd.options()
        switches = []
        fixedWords = None
        for optname in sorted(cmd.options()):
            opt = opts[optname]
            optswitches = []
            parser = option.get_optparser({optname: opt})
            parser = wrap_parser(optswitches, parser)
            optswitches[:] = []
            opt.add_option(parser, opt.short_name())
            switches.extend(optswitches)
        if 'help' == cmdname or 'help' in cmd.aliases:
            fixedWords = " ".join(sorted(help_topics.topic_registry.keys()))
            fixedWords = '"$cmds %s"' % fixedWords

        cases += "\t\tcmdOpts='" + " ".join(switches) + "'\n"
        if fixedWords:
            if isinstance(fixedWords, list):
                fixedWords = "'" + join(fixedWords) + "'";
            cases += "\t\tfixedWords=" + fixedWords + "\n"
        cases += "\t\t;;\n"
    if function_only:
        template = fun
    else:
        template = head + fun + tail
    out.write(template % {"cmds": " ".join(cmds),
                          "cases": cases,
                          "function_name": function_name,
                          "version": __version__,
                          "global_options": global_options,
                          })

if __name__ == '__main__':

    import sys
    import locale

    locale.setlocale(locale.LC_ALL, '')
    plugin.load_plugins()
    commands.install_bzr_command_hooks()
    bash_completion_function(sys.stdout)
