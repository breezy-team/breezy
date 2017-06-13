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

"""guess - when a bzr command is mispelt, prompt for the nearest match."""


from ... import (
    hooks,
    )

def guess_command(cmd_name):
    from .guess import guess_command
    return guess_command(cmd_name)

hooks.install_lazy_named_hook("breezy.commands", "Command.hooks",
    "get_missing_command", guess_command, "Guess command name")
