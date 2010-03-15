# Copyright (C) 2010  Martin von Gagern
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

# Programmable completion for the Bazaar-NG bzr command under bash.
# Source this file (or add it to your ~/.bash_completion or ~/.bashrc
# file, depending on your system configuration, and start a new shell)
# and bash's completion mechanism will know all about bzr's options!
#
# This completion function assumes you have the bzr-bash-completion
# plugin installed as a bzr plugin. It will generate the full
# completion function at first invocation, thus avoiding long delays
# for every shell you start.

shopt -s progcomp
_bzr_lazy ()
{
	unset _bzr
	eval "$(bzr bash-completion)"
	if [[ $(type -t _bzr) == function ]]; then
		unset _bzr_lazy
		_bzr
		return $?
	else
		return 1
	fi
}
complete -F _bzr_lazy -o default bzr
