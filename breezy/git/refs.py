# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Conversion between refs and Bazaar revision pointers."""

from dulwich.refs import LOCAL_BRANCH_PREFIX, LOCAL_TAG_PREFIX

from dulwich.refs import PEELED_TAG_SUFFIX

from dulwich.repo import RefsContainer

from .. import controldir, errors
from .. import revision as _mod_revision


def is_tag(x):
    return x.startswith(LOCAL_TAG_PREFIX)


def is_peeled(x):
    return x.endswith(PEELED_TAG_SUFFIX)


def branch_name_to_ref(name):
    """Map a branch name to a ref.

    :param name: Branch name
    :return: ref string
    """
    if name == "":
        return b"HEAD"
    if not name.startswith("refs/"):
        return LOCAL_BRANCH_PREFIX + name.encode("utf-8")
    else:
        return name.encode("utf-8")


def tag_name_to_ref(name):
    """Map a tag name to a ref.

    :param name: Tag name
    :return: ref string
    """
    return LOCAL_TAG_PREFIX + name.encode("utf-8")


def ref_to_branch_name(ref):
    """Map a ref to a branch name.

    :param ref: Ref
    :return: A branch name
    """
    if ref == b"HEAD":
        return ""
    if ref is None:
        return ref
    if ref.startswith(LOCAL_BRANCH_PREFIX):
        return ref[len(LOCAL_BRANCH_PREFIX) :].decode("utf-8")
    raise ValueError(f"unable to map ref {ref} back to branch name")


def ref_to_tag_name(ref):
    if ref.startswith(LOCAL_TAG_PREFIX):
        return ref[len(LOCAL_TAG_PREFIX) :].decode("utf-8")
    raise ValueError(f"unable to map ref {ref} back to tag name")


class BazaarRefsContainer(RefsContainer):
    def __init__(self, dir, object_store):
        self.dir = dir
        self.object_store = object_store

    def get_packed_refs(self):
        return {}

    def set_symbolic_ref(self, name, other):
        if name == b"HEAD":
            pass  # FIXME: Switch default branch
        else:
            raise NotImplementedError(
                "Symbolic references not supported for anything other than HEAD"
            )

    def _get_revid_by_tag_name(self, tag_name):
        for branch in self.dir.list_branches():
            try:
                # FIXME: This is ambiguous!
                return branch.tags.lookup_tag(tag_name)
            except errors.NoSuchTag:
                pass
        return None

    def _get_revid_by_branch_name(self, branch_name):
        try:
            branch = self.dir.open_branch(branch_name)
        except controldir.NoColocatedBranchSupport:
            if branch_name in ("HEAD", "master"):
                branch = self.dir.open_branch()
            else:
                raise
        return branch.last_revision()

    def read_loose_ref(self, ref):
        try:
            branch_name = ref_to_branch_name(ref)
        except ValueError:
            tag_name = ref_to_tag_name(ref)
            revid = self._get_revid_by_tag_name(tag_name)
        else:
            revid = self._get_revid_by_branch_name(branch_name)
        if revid == _mod_revision.NULL_REVISION:
            return None
        # FIXME: Unpeel if necessary
        with self.object_store.lock_read():
            return self.object_store._lookup_revision_sha1(revid)

    def get_peeled(self, ref):
        return self.read_loose_ref(ref)

    def allkeys(self):
        keys = set()
        for branch in self.dir.list_branches():
            repo = branch.repository
            if repo.has_revision(branch.last_revision()):
                ref = branch_name_to_ref(getattr(branch, "name", ""))
                keys.add(ref)
            try:
                for tag_name, revid in branch.tags.get_tag_dict().items():
                    if repo.has_revision(revid):
                        keys.add(tag_name_to_ref(tag_name))
            except errors.TagsNotSupported:
                pass
        return keys

    def __delitem__(self, ref):
        try:
            branch_name = ref_to_branch_name(ref)
        except ValueError:
            return  # FIXME: Cope with tags!
        self.dir.destroy_branch(branch_name)

    def __setitem__(self, ref, sha):
        try:
            branch_name = ref_to_branch_name(ref)
        except ValueError:
            # FIXME: Cope with tags!
            return
        try:
            target_branch = self.repo_dir.open_branch(branch_name)
        except errors.NotBranchError:
            target_branch = self.repo.create_branch(branch_name)

        rev_id = self.mapping.revision_id_foreign_to_bzr(sha)
        with target_branch.lock_write():
            target_branch.generate_revision_history(rev_id)


def get_refs_container(controldir, object_store):
    fn = getattr(controldir, "get_refs_container", None)
    if fn is not None:
        return fn()
    return BazaarRefsContainer(controldir, object_store)
