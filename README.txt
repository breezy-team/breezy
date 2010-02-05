=========================================
  bzr bash-completion script and plugin
=========================================

This script generates a shell function which can be used by bash to
automatically complete the currently typed command when the user
presses the completion key (usually tab).

It can be used either as a bzr plugin or directly.

----------------------------------------
1. Installing as a plugin

You only need to do this if you want to use the script as a bzr
plugin.  Otherwise simply grab the bashcomp.py and place it wherever
you want.

  mkdir -p ~/.bazaar/plugins
  cd ~/.bazaar/plugins
  bzr co lp:bzr-bash-completion bash_completion


----------------------------------------
2. Using as a plugin

This is the preferred method of generating the completion function, as
it will ensure proper bzr initialization.

  eval "`bzr bash-completion`"


----------------------------------------
3. Using as a script

As an alternative, if bzrlib is available to python scripts, the
following invocation should yield the same results without requiring
you to add a plugin. Might have some issues, though.

  eval "`./bashcomp.py`"

----------------------------------------
4. License

As this is built upon a bash completion script originally included in
the bzr source tree, and as the bzr sources are covered by the GPL 2,
this script here is licensed under these same terms.

If you require a more liberal license, you'll have to contact all
those who contributed code to this plugin, be it for bash or for
python.

----------------------------------------
5. History

The plugin was created by Martin von Gagern in 2009, building on a
static completion function of very limited scope distributed together
with bzr.

----------------------------------------
6. References

https://launchpad.net/bzr-bash-completion
http://bazaar-vcs.org/
