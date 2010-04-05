# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
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

"""Conversion between refs and Bazaar revision pointers."""

def extract_tags(refs):
    """Extract the tags from a refs dictionary.

    :param refs: Refs to extract the tags from.
    :return: Dictionary mapping tag names to SHA1s.
    """
    ret = {}
    for k,v in refs.iteritems():
        if k.startswith("refs/tags/") and not k.endswith("^{}"):
            v = refs.get(k+"^{}", v)
            ret[k[len("refs/tags/"):]] = v
    return ret


def branch_name_to_ref(name, default=None):
    """Map a branch name to a ref.

    :param name: Branch name
    :return: ref string
    """
    if name is None:
        return default
    if name == "HEAD":
        return "HEAD"
    if not name.startswith("refs/"):
        return "refs/heads/%s" % name
    else:
        return name


def ref_to_branch_name(ref):
    """Map a ref to a branch name

    :param ref: Ref
    :return: A branch name
    """
    if ref == "HEAD":
        return "HEAD"
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    raise ValueError("unable to map ref %s back to branch name")


