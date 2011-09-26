from bzrlib import export_pot

import commands
import info

import sys

export_pot._FOUND_MSGID = set()

for command in info.bzr_commands:
    command_object = eval("commands.cmd_" + command)()
    export_pot._write_command_help(sys.stdout, command_object)
