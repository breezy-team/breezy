#!/usr/bin/env python
# Copyright (C) 2009 Canonical Ltd
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

"""A script that converts a bzr merge .plan file into a .BASE file."""

import sys


def plan_lines_to_base_lines(plan_lines):
    _ghost_warning = False
    base_lines = []
    for line in plan_lines:
        action, content = line.split('|', 1)
        action = action.strip()
        if action in ('killed-a', 'killed-b', 'killed-both', 'unchanged'):
            # If lines were removed by a or b or both, then they must have been
            # in the base. if unchanged, then they are copied from the base
            base_lines.append(content)
        elif action in ('killed-base', 'irrelevant', 'ghost-a', 'ghost-b',
                        'new-a', 'new-b'):
            # The first 4 are ones that are always suppressed
            # the last 2 are lines that are in A or B, but *not* in BASE, so we
            # ignore them
            continue
        else:
            sys.stderr.write('Unknown action: %s\n' % (action,))
    return base_lines


def plan_file_to_base_file(plan_filename):
    if not plan_filename.endswith('.plan'):
        sys.stderr.write('"%s" does not look like a .plan file\n'
                         % (plan_filename,))
        return
    plan_file = open(plan_filename, 'rb')
    try:
        plan_lines = plan_file.readlines()
    finally:
        plan_file.close()
    base_filename = plan_filename[:-4] + 'BASE'
    base_lines = plan_lines_to_base_lines(plan_lines)
    f = open(base_filename, 'wb')
    try:
        f.writelines(base_lines)
    finally:
        f.close()


def main(args):
    import optparse
    p = optparse.OptionParser('%prog foo.plan*')

    opts, args = p.parse_args(args)
    if len(args) < 1:
        sys.stderr.write('You must supply exactly a .plan file.\n')
        return 1
    for arg in args:
        plan_file_to_base_file(arg)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
