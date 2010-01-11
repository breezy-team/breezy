#!/usr/bin/python

from bzrlib import plugin
from bzrlib import commands
from bzrlib import config
from bzrlib import help_topics

head="""\
# Programmable completion for the Bazaar-NG bzr command under bash. Source
# this file (or on some systems add it to ~/.bash_completion and start a new
# shell) and bash's completion mechanism will know all about bzr's options!

# Known to work with bash 2.05a with programmable completion and extended
# pattern matching enabled (use 'shopt -s extglob progcomp' to enable
# these if they are not already enabled).

# Based originally on the svn bash completition script.
# Customized by Sven Wilhelm/Icecrash.com
# Adjusted for automatic generation by Martin von Gagern

if shopt -q extglob; then
	_tmp_unset_extglob=""
else
	_tmp_unset_extglob="shopt -u extglob"
fi
shopt -s extglob progcomp
"""
fun="""\
%(function_name)s ()
{
	local cur cmds cmdOpts opt helpCmds optBase i

	COMPREPLY=()
	cur=${COMP_WORDS[COMP_CWORD]}

	cmds='%(cmds)s'

	if [[ $COMP_CWORD -eq 1 ]] ; then
		COMPREPLY=( $( compgen -W "$cmds" -- $cur ) )
		return 0
	fi

	# if not typing an option, or if the previous option required a
	# parameter, then fallback on ordinary filename expansion
	helpCmds='help|--help|h|\?'
	if [[ ${COMP_WORDS[1]} != @($helpCmds) ]] && \
	   [[ "$cur" != -* ]] ; then
		return 0
	fi

	cmdOpts=
	case ${COMP_WORDS[1]} in
%(cases)s\
	*)
		cmdOpts='--help -h'
		;;
	esac

	COMPREPLY=( $( compgen -W "$cmdOpts" -- $cur ) )

	return 0
}
"""
tail="""\
complete -F %(function_name)s -o default bzr
$_tmp_unset_extglob
unset _tmp_unset_extglob
"""

def bash_completion_function(out, function_name="_bzr", function_only=False):
    cmds = []
    cases = ""
    reqarg = {}

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
        for optname in sorted(cmd.options()):
            opt = opts[optname]
            for (name, short_name, optname, help) in opt.iter_switches():
                if short_name is not None:
                    switches.append("-" + short_name)
                if name is not None:
                    switches.append("--" + name)
        if 'help' == cmdname or 'help' in cmd.aliases:
            switches.extend(sorted(help_topics.topic_registry.keys()))
            switches.extend(all_cmds)
        cases += "\t\tcmdOpts='" + " ".join(switches) + "'\n"
        cases += "\t\t;;\n"
    if function_only:
        template = fun
    else:
        template = head + fun + tail
    out.write(template % {"cmds": " ".join(cmds),
                          "cases": cases,
                          "function_name": function_name,
                          })

if __name__ == '__main__':

    import sys
    import locale

    locale.setlocale(locale.LC_ALL, '')
    plugin.load_plugins()
    commands.install_bzr_command_hooks()
    bash_completion_function(sys.stdout)
