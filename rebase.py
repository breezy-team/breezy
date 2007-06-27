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

REBASE_PLAN_FILENAME = 'rebase-plan'

def rebase_plan_exists(wt):
    """Check whether there is a rebase plan present.

    :param wt: Working tree for which to check.
    :return: boolean
    """
    return wt._control_files.get(REBASE_PLAN_FILENAME).read() != ''


def read_rebase_plan(wt):
    """Read a rebase plan file.

    :param wt: Working Tree for which to write the plan.
    :return: Tuple with last revision info, replace map and rewrite map.
    """
    text = wt._control_files.get(REBASE_PLAN_FILENAME).read()
    if text == '':
        raise BzrError("No rebase plan exists")
    return parse_rebase_plan(text)


def write_rebase_plan(wt, replace_map, rewrite_map):
    """Write a rebase plan file.

    :param wt: Working Tree for which to write the plan.
    :param replace_map: Replace map (old revid -> new revid)
    :param rewrite_map: Rewrite map (old revid -> new revid)
    """
    wt._control_files.put(REBASE_PLAN_FILENAME, 
            generate_rebase_plan(wt.last_revision_info(), replace_map, 
                                 rewrite_map))


def remove_rebase_plan(wt):
    """Remove a rebase plan file.

    :param wt: Working Tree for which to remove the plan.
    """
    wt._control_files.put(REBASE_PLAN_FILENAME, '')


def generate_rebase_plan(last_rev_info, replace_map, rewrite_map):
    """Marshall a rebase plan.

    :param last_rev_info: Last revision info tuple.
    :param replace_map: Replace map (old revid -> new revid)
    :param rewrite_map: Rewrite map (old revid -> new revid)
    :return: string
    """
    # TODO


def parse_rebase_plan(text):
    """Unmarshall a rebase plan.

    :param text: Text to parse
    :return: Tuple with last revision info, replace map and rewrite map.
    """
    # TODO


def generate_simple_plan(subject_branch, upstream_branch, onto):
    """Create a simple rebase plan that replays history based 
    on one revision being mapped.

    :param subject_branch: Branch that will be changed
    :param upstream_branch: Branch 
    :param onto: Revision on top of which subject will be replayed 

    :return: tuple with last_revision_info, replace map and rewrite map
    """
    # TODO
