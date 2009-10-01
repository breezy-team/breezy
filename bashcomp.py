#!/usr/bin/python

from bzrlib import plugin
from bzrlib import commands

template="""\
# Programmable completion for the Bazaar-NG bzr command under bash. Source
# this file (or on some systems add it to ~/.bash_completion and start a new
# shell) and bash's completion mechanism will know all about bzr's options!

# Known to work with bash 2.05a with programmable completion and extended
# pattern matching enabled (use 'shopt -s extglob progcomp' to enable
# these if they are not already enabled).

# Based originally on the svn bash completition script.
# Customized by Sven Wilhelm/Icecrash.com
# Adjusted for automatic generation by Martin von Gagern

shopt -s extglob progcomp
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

	cmdOpts=" $cmdOpts "

	# take out options already given
	for (( i=2; i<=$COMP_CWORD-1; ++i )) ; do
		opt=${COMP_WORDS[$i]}

		case $opt in
		--*)    optBase=${opt/=*/} ;;
		-*)     optBase=${opt:0:2} ;;
		esac

		cmdOpts=" $cmdOpts "
		cmdOpts=${cmdOpts/ ${optBase} / }

		# take out some alternatives
		case $optBase in
%(optalt)s\
		esac

		# skip next option if this one requires a parameter
		if [[ $opt == @($optsParam) ]] ; then
			((++i))
		fi
	done

	COMPREPLY=( $( compgen -W "$cmdOpts" -- $cur ) )

	return 0
}
complete -F %(function_name)s -o default bzr
"""

def bash_completion_function(out, function_name="_bzr"):
    aliases = []
    cases = ""
    optaliases = {}
    reqarg = {}
    for name in sorted(commands.all_command_names()):
        cmd = commands.get_cmd_object(name)
        cases += "\t" + name
        aliases.append(name)
        for alias in cmd.aliases:
            cases += "|" + alias
            aliases.append(alias)
        cases += ")\n"
        plugin = cmd.plugin_name()
        if plugin is not None:
            cases += "\t\t# plugin \"%s\"\n" % plugin
        opts = cmd.options()
        optnames = []
        for optname in sorted(cmd.options()):
            opt = opts[optname]
            optset = set()
            for (name, short_name, optname, help) in opt.iter_switches():
                if short_name is not None:
                    optset.add("-" + short_name)
                if name is not None:
                    optset.add("--" + name)
            for optname in optset:
                if optname not in optaliases:
                    optaliases[optname] = optset
                else:
                    optaliases[optname] &= optset
            optnames.extend(sorted(optset))
        cases += "\t\tcmdOpts='" + " ".join(optnames) + "'\n\t\t;;\n"
    optalt = ""
    for opt1 in sorted(optaliases):
        optset = optaliases[opt1]
        if len(optset) == 1:
            continue
        optalt += "\t\t" + opt1 + ")\n"
        for opt2 in sorted(optset):
            if opt1 != opt2:
                optalt += "\t\t\tcmdOpts=${cmdOpts/ " + opt2 + " / }\n"
        optalt += "\t\t\t;;\n"
    out.write(template % {"cmds": " ".join(aliases),
                          "cases": cases,
                          "optalt": optalt,
                          "function_name": function_name,
                          })

if __name__ == '__main__':

    import sys
    import locale

    locale.setlocale(locale.LC_ALL, '')
    plugin.load_plugins()
    commands.install_bzr_command_hooks()
    bash_completion_function(sys.stdout)
