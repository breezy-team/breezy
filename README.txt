=========================================
  bzr bash-completion script and plugin
=========================================

This script generates a shell function which can be used by bash to
automatically complete the currently typed command when the user
presses the completion key (usually tab).

It can be used either as a bzr plugin or directly.

----------------------------------------
 Installing as a plugin
----------------------------------------

You only need to do this if you want to use the script as a bzr
plugin.  Otherwise simply grab the bashcomp.py and place it wherever
you want.

  mkdir -p ~/.bazaar/plugins
  cd ~/.bazaar/plugins
  bzr co lp:bzr-bash-completion bash_completion


----------------------------------------
 Using as a plugin
----------------------------------------

This is the preferred method of generating initializing the
completion, as it will ensure proper bzr initialization.

  eval "`bzr bash-completion`"


----------------------------------------
 Using as a script
----------------------------------------

As an alternative, if bzrlib is available to python scripts, the
following invocation should yield the same results without requiring
you to add a plugin. Might have some issues, though.

  eval "`./bashcomp.py`"

----------------------------------------
 Design concept
----------------------------------------

The plugin (or script) is designed to generate a completion function
containing all the required information about the possible
completions. This is usually only done once when bash
initializes. After that, no more invocations of bzr are required. This
makes the function much faster than a possible implementation talking
to bzr for each and every completion. On the other hand, this has the
effect that updates to bzr or its plugins won't show up in the
completions immediately, but only after the completion function has
been regenerated.

----------------------------------------
 License
----------------------------------------

As this is built upon a bash completion script originally included in
the bzr source tree, and as the bzr sources are covered by the GPL 2,
this script here is licensed under these same terms.

If you require a more liberal license, you'll have to contact all
those who contributed code to this plugin, be it for bash or for
python.

----------------------------------------
 History
----------------------------------------

The plugin was created by Martin von Gagern in 2009, building on a
static completion function of very limited scope distributed together
with bzr.

----------------------------------------
 References
----------------------------------------

https://launchpad.net/bzr-bash-completion
http://bazaar.canonical.com/
