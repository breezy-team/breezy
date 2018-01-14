# modify PS1 to your preference and include this file in your bashrc
# or copy to /etc/bash_completions.d.

function __prompt_brz()
{
	local revno nick;
	revno=$(brz revno 2>/dev/null) || return
	nick=$(brz nick 2>/dev/null) || return
	echo "[brz://$revno@$nick]"
}

if [ "$PS1" ]; then
	PS1='\u@\h:$(__prompt_brz)\W\$ '
fi
