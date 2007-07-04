# Copyright (C) 2006-2007 by Jelmer Vernooij
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.errors import UnknownFormatError
from bzrlib.generate_ids import gen_revision_id
from bzrlib.trace import mutter

REBASE_PLAN_FILENAME = 'rebase-plan'
REBASE_PLAN_VERSION = 1

def rebase_plan_exists(wt):
    """Check whether there is a rebase plan present.

    :param wt: Working tree for which to check.
    :return: boolean
    """
    return wt._control_files.get(REBASE_PLAN_FILENAME).read() != ''


def read_rebase_plan(wt):
    """Read a rebase plan file.

    :param wt: Working Tree for which to write the plan.
    :return: Tuple with last revision info and replace map.
    """
    text = wt._control_files.get(REBASE_PLAN_FILENAME).read()
    if text == '':
        raise BzrError("No rebase plan exists")
    return unmarshall_rebase_plan(text)


def write_rebase_plan(wt, replace_map):
    """Write a rebase plan file.

    :param wt: Working Tree for which to write the plan.
    :param replace_map: Replace map (old revid -> (new revid, new parents))
    """
    wt._control_files.put(REBASE_PLAN_FILENAME, 
            marshall_rebase_plan(wt.last_revision_info(), replace_map))


def remove_rebase_plan(wt):
    """Remove a rebase plan file.

    :param wt: Working Tree for which to remove the plan.
    """
    wt._control_files.put(REBASE_PLAN_FILENAME, '')


def marshall_rebase_plan(last_rev_info, replace_map):
    """Marshall a rebase plan.

    :param last_rev_info: Last revision info tuple.
    :param replace_map: Replace map (old revid -> (new revid, new parents))
    :return: string
    """
    ret = "# Bazaar rebase plan %d\n" % REBASE_PLAN_VERSION
    ret += "%d %s\n" % last_rev_info
    for oldrev in replace_map:
        (newrev, newparents) = replace_map[oldrev]
        ret += "%s %s" % (oldrev, newrev) + \
            "".join([" %s" % p for p in newparents]) + "\n"
    return ret


def unmarshall_rebase_plan(text):
    """Unmarshall a rebase plan.

    :param text: Text to parse
    :return: Tuple with last revision info, replace map.
    """
    lines = text.split('\n')
    # Make sure header is there
    if lines[0] != "# Bazaar rebase plan %d" % REBASE_PLAN_VERSION:
        raise UnknownFormatError(lines[0])

    pts = lines[1].split(" ", 1)
    last_revision_info = (int(pts[0]), pts[1])
    replace_map = {}
    for l in lines[2:]:
        if l == "":
            # Skip empty lines
            continue
        pts = l.split(" ")
        replace_map[pts[0]] = (pts[1], pts[2:])
    return (last_revision_info, replace_map)

def generate_simple_plan(subject_branch, start_revid, onto_revid):
    """Create a simple rebase plan that replays history based 
    on one revision being mapped.

    :param subject_branch: Branch that will be changed
    :param start_revid: Revision at which to start replaying
    :param onto_revid: Revision on top of which to replay

    :return: replace map
    """
    replace_map = {}

    need_rewrite = []

    for revid in need_rewrite:
        replace_map[revid] = gen_revision_id()
    # TODO
