# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Utility functions for dealing with changes dictionaries as return by Subversions' log functions."""

def path_is_child(branch_path, path):
    return (branch_path == "" or 
            branch_path == path or 
            path.startswith(branch_path+"/"))


def find_prev_location(paths, branch_path, revnum):
    assert isinstance(paths, dict)
    assert isinstance(branch_path, str)
    assert isinstance(revnum, int)
    if revnum == 0:
        assert branch_path == ""
        return None
    # If there are no special cases, just go try the 
    # next revnum in history
    revnum -= 1

    if branch_path == "":
        return (branch_path, revnum)

    # Make sure we get the right location for next time, if 
    # the branch itself was copied
    if (paths.has_key(branch_path) and 
        paths[branch_path][0] in ('R', 'A')):
        if paths[branch_path][1] is None: 
            return None # Was added here
        revnum = paths[branch_path][2]
        branch_path = paths[branch_path][1].encode("utf-8")
        return (branch_path, revnum)
    
    # Make sure we get the right location for the next time if 
    # one of the parents changed

    # Path names need to be sorted so the longer paths 
    # override the shorter ones
    for p in sorted(paths.keys(), reverse=True):
        if paths[p][0] == 'M':
            continue
        if branch_path.startswith(p+"/"):
            assert paths[p][0] in ('A', 'R'), "Parent %r wasn't added" % p
            assert paths[p][1] is not None, \
                "Empty parent %r added, but child %r wasn't added !?" % (p, branch_path)

            revnum = paths[p][2]
            branch_path = paths[p][1].encode("utf-8") + branch_path[len(p):]
            return (branch_path, revnum)

    return (branch_path, revnum)


def changes_path(changes, path, parents=False):
    """Check if one of the specified changes applies 
    to path or one of its children.

    :param parents: Whether to consider a parent moving a change.
    """
    for p in changes:
        assert isinstance(p, str)
        if path_is_child(path, p):
            return True
        if parents and path.startswith(p+"/") and changes[p][0] in ('R', 'A'):
            return True
    return False


