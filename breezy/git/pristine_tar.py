# Copyright (C) 2012-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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


"""Support for pristine tar deltas."""

import stat
from base64 import standard_b64decode

from dulwich.objects import Blob, Tree

README_CONTENTS = b"""\
This branch contains delta files that pristine-tar can use to
regenerate tarballs for its own releases.
"""


def revision_pristine_tar_data(rev):
    """Export the pristine tar data from a revision."""
    if "deb-pristine-delta" in rev.properties:
        uuencoded = rev.properties["deb-pristine-delta"]
        kind = "gz"
    elif "deb-pristine-delta-bz2" in rev.properties:
        uuencoded = rev.properties["deb-pristine-delta-bz2"]
        kind = "bz2"
    elif "deb-pristine-delta-xz" in rev.properties:
        uuencoded = rev.properties["deb-pristine-delta-xz"]
        kind = "xz"
    else:
        raise KeyError(rev.revision_id)

    return (standard_b64decode(uuencoded), kind)


def get_pristine_tar_tree(repo):
    """Retrieve the pristine tar tree for a repository."""
    try:
        cid = repo.refs[b"refs/heads/pristine-tar"]
    except KeyError:
        return Tree()
    tid = repo.object_store[cid].tree
    return repo.object_store[tid]


def read_git_pristine_tar_data(repo, filename):
    """Read pristine data from a Git repository.

    :param repo: Git repository to read from
    :param filename: Name of file to read
    :return: Tuple with delta and id
    """
    tree = get_pristine_tar_tree(repo)
    delta = tree[filename + b".delta"][1]
    gitid = tree[filename + b".id"][1]
    return (repo.object_store[delta].data, repo.object_store[gitid].data)


def store_git_pristine_tar_data(repo, filename, delta, gitid, message=None, **kwargs):
    """Add pristine tar data to a Git repository.

    :param repo: Git repository to add data to
    :param filename: Name of file to store for
    :param delta: pristine-tar delta
    :param gitid: Git id the pristine tar delta is generated against
    """
    delta_ob = Blob.from_string(delta)
    delta_name = filename + b".delta"
    id_ob = Blob.from_string(gitid)
    id_name = filename + b".id"
    objects = [(delta_ob, delta_name), (id_ob, id_name)]
    tree = get_pristine_tar_tree(repo)
    tree.add(delta_name, stat.S_IFREG | 0o644, delta_ob.id)
    tree.add(id_name, stat.S_IFREG | 0o644, id_ob.id)
    if b"README" not in tree:
        readme_ob = Blob.from_string(README_CONTENTS)
        objects.append((readme_ob, b"README"))
        tree.add(b"README", stat.S_IFREG | 0o644, readme_ob.id)
    objects.append((tree, ""))
    repo.object_store.add_objects(objects)
    if message is None:
        message = b"pristine-tar data for %s" % filename
    return repo.do_commit(
        ref=b"refs/heads/pristine-tar", tree=tree.id, message=message, **kwargs
    )
