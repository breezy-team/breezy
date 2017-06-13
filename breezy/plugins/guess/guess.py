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

# Overrides for common mispellings that heuristics get wrong
_overrides = {
    'ic': {'ci': 0}, # heuristic finds nick
    }

import traceback

from ... import (
    commands,
    patiencediff,
    ui,
    )


def guess_command(cmd_name):
    if not cmd_name:
        return
    names = set()
    for name in commands.all_command_names():
        names.add(name)
        cmd = commands.get_cmd_object(name)
        names.update(cmd.aliases)
    # candidate: modified levenshtein distance against cmd_name.
    costs = {}
    for name in sorted(names):
        matcher = patiencediff.PatienceSequenceMatcher(None, cmd_name, name)
        distance = 0.0
        opcodes = matcher.get_opcodes()
        for opcode, l1, l2, r1, r2 in opcodes:
            if opcode == 'delete':
                distance += l2-l1
            elif opcode == 'replace':
                distance += max(l2-l1, r2-l1)
            elif opcode == 'insert':
                distance += r2-r1
            elif opcode == 'equal':
                # Score equal ranges lower, making similar commands of equal
                # length closer than arbitrary same length commands.
                distance -= 0.1 *(l2-l1)
        costs[name] = distance
    costs = sorted((value, key) for key, value in costs.iteritems())
    if not costs:
        return
    for tr in traceback.format_stack(limit=6):
        if "in help" in str(tr):
            return
    candidate = costs[0][1]
    prompt = "Command '%s' not found, perhaps you meant '%s'" % (
        cmd_name, candidate)
    if ui.ui_factory.get_boolean(prompt):
        return commands.get_cmd_object(candidate)



