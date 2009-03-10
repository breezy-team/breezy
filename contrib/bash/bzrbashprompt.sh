# modify PS1 to your preference and include this file in your bashrc
# or copy to /etc/bash_completions.d.

function __prompt_bzr()
{
	local revno nick;
	revno=$(bzr revno 2>/dev/null) || return
	nick=$(bzr nick 2>/dev/null) || return
	echo "[bzr://$revno@$nick]"
}

if [ "$PS1" ]; then
	PS1='\u@\h:$(__prompt_bzr)\W\$ '
fi
