# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tests that use BrokenRepoScenario objects.

That is, tests for reconcile and check.
"""

from breezy import osutils
from breezy.bzr.inventory import Inventory, InventoryFile
from breezy.bzr.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
)
from breezy.repository import WriteGroup
from breezy.revision import NULL_REVISION, Revision
from breezy.tests import TestNotApplicable, multiply_scenarios
from breezy.tests.scenarios import load_tests_apply_scenarios

load_tests = load_tests_apply_scenarios


class BrokenRepoScenario:
    """Base class for defining scenarios for testing check and reconcile.

    A subclass needs to define the following methods:
        :populate_repository: a method to use to populate a repository with
            sample revisions, inventories and file versions.
        :all_versions_after_reconcile: all the versions in repository after
            reconcile.  run_test verifies that the text of each of these
            versions of the file is unchanged by the reconcile.
        :populated_parents: a list of (parents list, revision).  Each version
            of the file is verified to have the given parents before running
            the reconcile.  i.e. this is used to assert that the repo from the
            factory is what we expect.
        :corrected_parents: a list of (parents list, revision).  Each version
            of the file is verified to have the given parents after the
            reconcile.  i.e. this is used to assert that reconcile made the
            changes we expect it to make.

    A subclass may define the following optional method as well:
        :corrected_fulltexts: a list of file versions that should be stored as
            fulltexts (not deltas) after reconcile.  run_test will verify that
            this occurs.
    """

    def __init__(self, test_case):
        self.test_case = test_case

    def make_one_file_inventory(
        self,
        repo,
        revision,
        parents,
        inv_revision=None,
        root_revision=None,
        file_contents=None,
        make_file_version=True,
    ):
        return self.test_case.make_one_file_inventory(
            repo,
            revision,
            parents,
            inv_revision=inv_revision,
            root_revision=root_revision,
            file_contents=file_contents,
            make_file_version=make_file_version,
        )

    def add_revision(self, repo, revision_id, inv, parent_ids):
        return self.test_case.add_revision(repo, revision_id, inv, parent_ids)

    def corrected_fulltexts(self):
        return []

    def repository_text_key_index(self):
        result = {}
        if self.versioned_root:
            result.update(self.versioned_repository_text_keys())
        result.update(self.repository_text_keys())
        return result


class UndamagedRepositoryScenario(BrokenRepoScenario):
    """A scenario where the repository has no damage.

    It has a single revision, 'rev1a', with a single file.
    """

    def all_versions_after_reconcile(self):
        return (b"rev1a",)

    def populated_parents(self):
        return (((), b"rev1a"),)

    def corrected_parents(self):
        # Same as the populated parents, because there was nothing wrong.
        return self.populated_parents()

    def check_regexes(self, repo):
        return ["0 unreferenced text versions"]

    def populate_repository(self, repo):
        # make rev1a: A well-formed revision, containing 'a-file'
        inv = self.make_one_file_inventory(repo, b"rev1a", [], root_revision=b"rev1a")
        self.add_revision(repo, b"rev1a", inv, [])
        self.versioned_root = repo.supports_rich_root()

    def repository_text_key_references(self):
        result = {}
        if self.versioned_root:
            result.update({(b"TREE_ROOT", b"rev1a"): True})
        result.update({(b"a-file-id", b"rev1a"): True})
        return result

    def repository_text_keys(self):
        return {(b"a-file-id", b"rev1a"): [NULL_REVISION]}

    def versioned_repository_text_keys(self):
        return {(b"TREE_ROOT", b"rev1a"): [NULL_REVISION]}


class FileParentIsNotInRevisionAncestryScenario(BrokenRepoScenario):
    """A scenario where a revision 'rev2' has 'a-file' with a
    parent 'rev1b' that is not in the revision ancestry.

    Reconcile should remove 'rev1b' from the parents list of 'a-file' in
    'rev2', preserving 'rev1a' as a parent.
    """

    def all_versions_after_reconcile(self):
        return (b"rev1a", b"rev2")

    def populated_parents(self):
        return (
            ((), b"rev1a"),
            ((), b"rev1b"),  # Will be gc'd
            ((b"rev1a", b"rev1b"), b"rev2"),
        )  # Will have parents trimmed

    def corrected_parents(self):
        return (((), b"rev1a"), (None, b"rev1b"), ((b"rev1a",), b"rev2"))

    def check_regexes(self, repo):
        return [
            r"\* a-file-id version rev2 has parents \(rev1a, rev1b\) "
            r"but should have \(rev1a\)",
            "1 unreferenced text versions",
        ]

    def populate_repository(self, repo):
        # make rev1a: A well-formed revision, containing 'a-file'
        inv = self.make_one_file_inventory(repo, b"rev1a", [], root_revision=b"rev1a")
        self.add_revision(repo, b"rev1a", inv, [])

        # make rev1b, which has no Revision, but has an Inventory, and
        # a-file
        inv = self.make_one_file_inventory(repo, b"rev1b", [], root_revision=b"rev1b")
        repo.add_inventory(b"rev1b", inv, [])

        # make rev2, with a-file.
        # a-file has 'rev1b' as an ancestor, even though this is not
        # mentioned by 'rev1a', making it an unreferenced ancestor
        inv = self.make_one_file_inventory(repo, b"rev2", [b"rev1a", b"rev1b"])
        self.add_revision(repo, b"rev2", inv, [b"rev1a"])
        self.versioned_root = repo.supports_rich_root()

    def repository_text_key_references(self):
        result = {}
        if self.versioned_root:
            result.update(
                {(b"TREE_ROOT", b"rev1a"): True, (b"TREE_ROOT", b"rev2"): True}
            )
        result.update({(b"a-file-id", b"rev1a"): True, (b"a-file-id", b"rev2"): True})
        return result

    def repository_text_keys(self):
        return {
            (b"a-file-id", b"rev1a"): [NULL_REVISION],
            (b"a-file-id", b"rev2"): [(b"a-file-id", b"rev1a")],
        }

    def versioned_repository_text_keys(self):
        return {
            (b"TREE_ROOT", b"rev1a"): [NULL_REVISION],
            (b"TREE_ROOT", b"rev2"): [(b"TREE_ROOT", b"rev1a")],
        }


class FileParentHasInaccessibleInventoryScenario(BrokenRepoScenario):
    """A scenario where a revision 'rev3' containing 'a-file' modified in
    'rev3', and with a parent which is in the revision ancestory, but whose
    inventory cannot be accessed at all.

    Reconcile should remove the file version parent whose inventory is
    inaccessbile (i.e. remove 'rev1c' from the parents of a-file's rev3).
    """

    def all_versions_after_reconcile(self):
        return (b"rev2", b"rev3")

    def populated_parents(self):
        return (((), b"rev2"), ((b"rev1c",), b"rev3"))

    def corrected_parents(self):
        return (((), b"rev2"), ((), b"rev3"))

    def check_regexes(self, repo):
        return [
            r"\* a-file-id version rev3 has parents " r"\(rev1c\) but should have \(\)",
        ]

    def populate_repository(self, repo):
        # make rev2, with a-file
        # a-file is sane
        inv = self.make_one_file_inventory(repo, b"rev2", [])
        self.add_revision(repo, b"rev2", inv, [])

        # make ghost revision rev1c, with a version of a-file present so
        # that we generate a knit delta against this version.  In real life
        # the ghost might never have been present or rev3 might have been
        # generated against a revision that was present at the time.  So
        # currently we have the full history of a-file present even though
        # the inventory and revision objects are not.
        self.make_one_file_inventory(repo, b"rev1c", [])

        # make rev3 with a-file
        # a-file refers to 'rev1c', which is a ghost in this repository, so
        # a-file cannot have rev1c as its ancestor.
        inv = self.make_one_file_inventory(repo, b"rev3", [b"rev1c"])
        self.add_revision(repo, b"rev3", inv, [b"rev1c", b"rev1a"])
        self.versioned_root = repo.supports_rich_root()

    def repository_text_key_references(self):
        result = {}
        if self.versioned_root:
            result.update(
                {(b"TREE_ROOT", b"rev2"): True, (b"TREE_ROOT", b"rev3"): True}
            )
        result.update({(b"a-file-id", b"rev2"): True, (b"a-file-id", b"rev3"): True})
        return result

    def repository_text_keys(self):
        return {
            (b"a-file-id", b"rev2"): [NULL_REVISION],
            (b"a-file-id", b"rev3"): [NULL_REVISION],
        }

    def versioned_repository_text_keys(self):
        return {
            (b"TREE_ROOT", b"rev2"): [NULL_REVISION],
            (b"TREE_ROOT", b"rev3"): [NULL_REVISION],
        }


class FileParentsNotReferencedByAnyInventoryScenario(BrokenRepoScenario):
    """A scenario where a repository with file 'a-file' which has extra
    per-file versions that are not referenced by any inventory (even though
    they have the same ID as actual revisions).  The inventory of 'rev2'
    references 'rev1a' of 'a-file', but there is a 'rev2' of 'some-file' stored
    and erroneously referenced by later per-file versions (revisions 'rev4' and
    'rev5').

    Reconcile should remove the file parents that are not referenced by any
    inventory.
    """

    def all_versions_after_reconcile(self):
        return (b"rev1a", b"rev2c", b"rev4", b"rev5")

    def populated_parents(self):
        return [
            ((b"rev1a",), b"rev2"),
            ((b"rev1a",), b"rev2b"),
            ((b"rev2",), b"rev3"),
            ((b"rev2",), b"rev4"),
            ((b"rev2", b"rev2c"), b"rev5"),
        ]

    def corrected_parents(self):
        return (
            # rev2 and rev2b have been removed.
            (None, b"rev2"),
            (None, b"rev2b"),
            # rev3's accessible parent inventories all have rev1a as the last
            # modifier.
            ((b"rev1a",), b"rev3"),
            # rev1a features in both rev4's parents but should only appear once
            # in the result
            ((b"rev1a",), b"rev4"),
            # rev2c is the head of rev1a and rev2c, the inventory provided
            # per-file last-modified revisions.
            ((b"rev2c",), b"rev5"),
        )

    def check_regexes(self, repo):
        if repo.supports_rich_root():
            # TREE_ROOT will be wrong; but we're not testing it. so just adjust
            # the expected count of errors.
            count = 9
        else:
            count = 3
        return [
            # will be gc'd
            r"unreferenced version: {rev2} in a-file-id",
            r"unreferenced version: {rev2b} in a-file-id",
            # will be corrected
            r"a-file-id version rev3 has parents \(rev2\) "
            r"but should have \(rev1a\)",
            r"a-file-id version rev5 has parents \(rev2, rev2c\) "
            r"but should have \(rev2c\)",
            r"a-file-id version rev4 has parents \(rev2\) "
            r"but should have \(rev1a\)",
            "%d inconsistent parents" % count,
        ]

    def populate_repository(self, repo):
        # make rev1a: A well-formed revision, containing 'a-file'
        inv = self.make_one_file_inventory(repo, b"rev1a", [], root_revision=b"rev1a")
        self.add_revision(repo, b"rev1a", inv, [])

        # make rev2, with a-file.
        # a-file is unmodified from rev1a, and an unreferenced rev2 file
        # version is present in the repository.
        self.make_one_file_inventory(repo, b"rev2", [b"rev1a"], inv_revision=b"rev1a")
        self.add_revision(repo, b"rev2", inv, [b"rev1a"])

        # make rev3 with a-file
        # a-file has 'rev2' as its ancestor, but the revision in 'rev2' was
        # rev1a so this is inconsistent with rev2's inventory - it should
        # be rev1a, and at the revision level 1c is not present - it is a
        # ghost, so only the details from rev1a are available for
        # determining whether a delta is acceptable, or a full is needed,
        # and what the correct parents are.
        inv = self.make_one_file_inventory(repo, b"rev3", [b"rev2"])
        self.add_revision(repo, b"rev3", inv, [b"rev1c", b"rev1a"])

        # In rev2b, the true last-modifying-revision of a-file is rev1a,
        # inherited from rev2, but there is a version rev2b of the file, which
        # reconcile could remove, leaving no rev2b.  Most importantly,
        # revisions descending from rev2b should not have per-file parents of
        # a-file-rev2b.
        # ??? This is to test deduplication in fixing rev4
        inv = self.make_one_file_inventory(
            repo, b"rev2b", [b"rev1a"], inv_revision=b"rev1a"
        )
        self.add_revision(repo, b"rev2b", inv, [b"rev1a"])

        # rev4 is for testing that when the last modified of a file in
        # multiple parent revisions is the same, that it only appears once
        # in the generated per file parents list: rev2 and rev2b both
        # descend from 1a and do not change the file a-file, so there should
        # be no version of a-file 'rev2' or 'rev2b', but rev4 does change
        # a-file, and is a merge of rev2 and rev2b, so it should end up with
        # a parent of just rev1a - the starting file parents list is simply
        # completely wrong.
        inv = self.make_one_file_inventory(repo, b"rev4", [b"rev2"])
        self.add_revision(repo, b"rev4", inv, [b"rev2", b"rev2b"])

        # rev2c changes a-file from rev1a, so the version it of a-file it
        # introduces is a head revision when rev5 is checked.
        inv = self.make_one_file_inventory(repo, b"rev2c", [b"rev1a"])
        self.add_revision(repo, b"rev2c", inv, [b"rev1a"])

        # rev5 descends from rev2 and rev2c; as rev2 does not alter a-file,
        # but rev2c does, this should use rev2c as the parent for the per
        # file history, even though more than one per-file parent is
        # available, because we use the heads of the revision parents for
        # the inventory modification revisions of the file to determine the
        # parents for the per file graph.
        inv = self.make_one_file_inventory(repo, b"rev5", [b"rev2", b"rev2c"])
        self.add_revision(repo, b"rev5", inv, [b"rev2", b"rev2c"])
        self.versioned_root = repo.supports_rich_root()

    def repository_text_key_references(self):
        result = {}
        if self.versioned_root:
            result.update(
                {
                    (b"TREE_ROOT", b"rev1a"): True,
                    (b"TREE_ROOT", b"rev2"): True,
                    (b"TREE_ROOT", b"rev2b"): True,
                    (b"TREE_ROOT", b"rev2c"): True,
                    (b"TREE_ROOT", b"rev3"): True,
                    (b"TREE_ROOT", b"rev4"): True,
                    (b"TREE_ROOT", b"rev5"): True,
                }
            )
        result.update(
            {
                (b"a-file-id", b"rev1a"): True,
                (b"a-file-id", b"rev2c"): True,
                (b"a-file-id", b"rev3"): True,
                (b"a-file-id", b"rev4"): True,
                (b"a-file-id", b"rev5"): True,
            }
        )
        return result

    def repository_text_keys(self):
        return {
            (b"a-file-id", b"rev1a"): [NULL_REVISION],
            (b"a-file-id", b"rev2c"): [(b"a-file-id", b"rev1a")],
            (b"a-file-id", b"rev3"): [(b"a-file-id", b"rev1a")],
            (b"a-file-id", b"rev4"): [(b"a-file-id", b"rev1a")],
            (b"a-file-id", b"rev5"): [(b"a-file-id", b"rev2c")],
        }

    def versioned_repository_text_keys(self):
        return {
            (b"TREE_ROOT", b"rev1a"): [NULL_REVISION],
            (b"TREE_ROOT", b"rev2"): [(b"TREE_ROOT", b"rev1a")],
            (b"TREE_ROOT", b"rev2b"): [(b"TREE_ROOT", b"rev1a")],
            (b"TREE_ROOT", b"rev2c"): [(b"TREE_ROOT", b"rev1a")],
            (b"TREE_ROOT", b"rev3"): [(b"TREE_ROOT", b"rev1a")],
            (b"TREE_ROOT", b"rev4"): [
                (b"TREE_ROOT", b"rev2"),
                (b"TREE_ROOT", b"rev2b"),
            ],
            (b"TREE_ROOT", b"rev5"): [
                (b"TREE_ROOT", b"rev2"),
                (b"TREE_ROOT", b"rev2c"),
            ],
        }


class UnreferencedFileParentsFromNoOpMergeScenario(BrokenRepoScenario):
    """rev1a and rev1b with identical contents
    rev2 revision has parents of [rev1a, rev1b]
    There is a a-file:rev2 file version, not referenced by the inventory.
    """

    def all_versions_after_reconcile(self):
        return (b"rev1a", b"rev1b", b"rev2", b"rev4")

    def populated_parents(self):
        return (
            ((), b"rev1a"),
            ((), b"rev1b"),
            ((b"rev1a", b"rev1b"), b"rev2"),
            (None, b"rev3"),
            ((b"rev2",), b"rev4"),
        )

    def corrected_parents(self):
        return (
            ((), b"rev1a"),
            ((), b"rev1b"),
            ((), b"rev2"),
            (None, b"rev3"),
            ((b"rev2",), b"rev4"),
        )

    def corrected_fulltexts(self):
        return [b"rev2"]

    def check_regexes(self, repo):
        return []

    def populate_repository(self, repo):
        # make rev1a: A well-formed revision, containing 'a-file'
        inv1a = self.make_one_file_inventory(repo, b"rev1a", [], root_revision=b"rev1a")
        self.add_revision(repo, b"rev1a", inv1a, [])

        # make rev1b: A well-formed revision, containing 'a-file'
        # rev1b of a-file has the exact same contents as rev1a.
        file_contents = next(
            repo.texts.get_record_stream([(b"a-file-id", b"rev1a")], "unordered", False)
        ).get_bytes_as("fulltext")
        inv = self.make_one_file_inventory(
            repo, b"rev1b", [], root_revision=b"rev1b", file_contents=file_contents
        )
        self.add_revision(repo, b"rev1b", inv, [])

        # make rev2, a merge of rev1a and rev1b, with a-file.
        # a-file is unmodified from rev1a and rev1b, but a new version is
        # wrongly present anyway.
        inv = self.make_one_file_inventory(
            repo,
            b"rev2",
            [b"rev1a", b"rev1b"],
            inv_revision=b"rev1a",
            file_contents=file_contents,
        )
        self.add_revision(repo, b"rev2", inv, [b"rev1a", b"rev1b"])

        # rev3: a-file unchanged from rev2, but wrongly referencing rev2 of the
        # file in its inventory.
        inv = self.make_one_file_inventory(
            repo,
            b"rev3",
            [b"rev2"],
            inv_revision=b"rev2",
            file_contents=file_contents,
            make_file_version=False,
        )
        self.add_revision(repo, b"rev3", inv, [b"rev2"])

        # rev4: a modification of a-file on top of rev3.
        inv = self.make_one_file_inventory(repo, b"rev4", [b"rev2"])
        self.add_revision(repo, b"rev4", inv, [b"rev3"])
        self.versioned_root = repo.supports_rich_root()

    def repository_text_key_references(self):
        result = {}
        if self.versioned_root:
            result.update(
                {
                    (b"TREE_ROOT", b"rev1a"): True,
                    (b"TREE_ROOT", b"rev1b"): True,
                    (b"TREE_ROOT", b"rev2"): True,
                    (b"TREE_ROOT", b"rev3"): True,
                    (b"TREE_ROOT", b"rev4"): True,
                }
            )
        result.update(
            {
                (b"a-file-id", b"rev1a"): True,
                (b"a-file-id", b"rev1b"): True,
                (b"a-file-id", b"rev2"): False,
                (b"a-file-id", b"rev4"): True,
            }
        )
        return result

    def repository_text_keys(self):
        return {
            (b"a-file-id", b"rev1a"): [NULL_REVISION],
            (b"a-file-id", b"rev1b"): [NULL_REVISION],
            (b"a-file-id", b"rev2"): [NULL_REVISION],
            (b"a-file-id", b"rev4"): [(b"a-file-id", b"rev2")],
        }

    def versioned_repository_text_keys(self):
        return {
            (b"TREE_ROOT", b"rev1a"): [NULL_REVISION],
            (b"TREE_ROOT", b"rev1b"): [NULL_REVISION],
            (b"TREE_ROOT", b"rev2"): [
                (b"TREE_ROOT", b"rev1a"),
                (b"TREE_ROOT", b"rev1b"),
            ],
            (b"TREE_ROOT", b"rev3"): [(b"TREE_ROOT", b"rev2")],
            (b"TREE_ROOT", b"rev4"): [(b"TREE_ROOT", b"rev3")],
        }


class TooManyParentsScenario(BrokenRepoScenario):
    """A scenario where 'broken-revision' of 'a-file' claims to have parents
    ['good-parent', 'bad-parent'].  However 'bad-parent' is in the ancestry of
    'good-parent', so the correct parent list for that file version are is just
    ['good-parent'].
    """

    def all_versions_after_reconcile(self):
        return (b"bad-parent", b"good-parent", b"broken-revision")

    def populated_parents(self):
        return (
            ((), b"bad-parent"),
            ((b"bad-parent",), b"good-parent"),
            ((b"good-parent", b"bad-parent"), b"broken-revision"),
        )

    def corrected_parents(self):
        return (
            ((), b"bad-parent"),
            ((b"bad-parent",), b"good-parent"),
            ((b"good-parent",), b"broken-revision"),
        )

    def check_regexes(self, repo):
        if repo.supports_rich_root():
            # TREE_ROOT will be wrong; but we're not testing it. so just adjust
            # the expected count of errors.
            count = 3
        else:
            count = 1
        return (
            "     %d inconsistent parents" % count,
            (
                r"      \* a-file-id version broken-revision has parents "
                r"\(good-parent, bad-parent\) but "
                r"should have \(good-parent\)"
            ),
        )

    def populate_repository(self, repo):
        inv = self.make_one_file_inventory(
            repo, b"bad-parent", (), root_revision=b"bad-parent"
        )
        self.add_revision(repo, b"bad-parent", inv, ())

        inv = self.make_one_file_inventory(repo, b"good-parent", (b"bad-parent",))
        self.add_revision(repo, b"good-parent", inv, (b"bad-parent",))

        inv = self.make_one_file_inventory(
            repo, b"broken-revision", (b"good-parent", b"bad-parent")
        )
        self.add_revision(repo, b"broken-revision", inv, (b"good-parent",))
        self.versioned_root = repo.supports_rich_root()

    def repository_text_key_references(self):
        result = {}
        if self.versioned_root:
            result.update(
                {
                    (b"TREE_ROOT", b"bad-parent"): True,
                    (b"TREE_ROOT", b"broken-revision"): True,
                    (b"TREE_ROOT", b"good-parent"): True,
                }
            )
        result.update(
            {
                (b"a-file-id", b"bad-parent"): True,
                (b"a-file-id", b"broken-revision"): True,
                (b"a-file-id", b"good-parent"): True,
            }
        )
        return result

    def repository_text_keys(self):
        return {
            (b"a-file-id", b"bad-parent"): [NULL_REVISION],
            (b"a-file-id", b"broken-revision"): [(b"a-file-id", b"good-parent")],
            (b"a-file-id", b"good-parent"): [(b"a-file-id", b"bad-parent")],
        }

    def versioned_repository_text_keys(self):
        return {
            (b"TREE_ROOT", b"bad-parent"): [NULL_REVISION],
            (b"TREE_ROOT", b"broken-revision"): [(b"TREE_ROOT", b"good-parent")],
            (b"TREE_ROOT", b"good-parent"): [(b"TREE_ROOT", b"bad-parent")],
        }


class ClaimedFileParentDidNotModifyFileScenario(BrokenRepoScenario):
    """A scenario where the file parent is the same as the revision parent, but
    should not be because that revision did not modify the file.

    Specifically, the parent revision of 'current' is
    'modified-something-else', which does not modify 'a-file', but the
    'current' version of 'a-file' erroneously claims that
    'modified-something-else' is the parent file version.
    """

    def all_versions_after_reconcile(self):
        return (b"basis", b"current")

    def populated_parents(self):
        return (
            ((), b"basis"),
            ((b"basis",), b"modified-something-else"),
            ((b"modified-something-else",), b"current"),
        )

    def corrected_parents(self):
        return (
            ((), b"basis"),
            (None, b"modified-something-else"),
            ((b"basis",), b"current"),
        )

    def check_regexes(self, repo):
        if repo.supports_rich_root():
            # TREE_ROOT will be wrong; but we're not testing it. so just adjust
            # the expected count of errors.
            count = 3
        else:
            count = 1
        return (
            "%d inconsistent parents" % count,
            r"\* a-file-id version current has parents "
            r"\(modified-something-else\) but should have \(basis\)",
        )

    def populate_repository(self, repo):
        inv = self.make_one_file_inventory(repo, b"basis", ())
        self.add_revision(repo, b"basis", inv, ())

        # 'modified-something-else' is a correctly recorded revision, but it
        # does not modify the file we are looking at, so the inventory for that
        # file in this revision points to 'basis'.
        inv = self.make_one_file_inventory(
            repo, b"modified-something-else", (b"basis",), inv_revision=b"basis"
        )
        self.add_revision(repo, b"modified-something-else", inv, (b"basis",))

        # The 'current' revision has 'modified-something-else' as its parent,
        # but the 'current' version of 'a-file' should have 'basis' as its
        # parent.
        inv = self.make_one_file_inventory(
            repo, b"current", (b"modified-something-else",)
        )
        self.add_revision(repo, b"current", inv, (b"modified-something-else",))
        self.versioned_root = repo.supports_rich_root()

    def repository_text_key_references(self):
        result = {}
        if self.versioned_root:
            result.update(
                {
                    (b"TREE_ROOT", b"basis"): True,
                    (b"TREE_ROOT", b"current"): True,
                    (b"TREE_ROOT", b"modified-something-else"): True,
                }
            )
        result.update(
            {(b"a-file-id", b"basis"): True, (b"a-file-id", b"current"): True}
        )
        return result

    def repository_text_keys(self):
        return {
            (b"a-file-id", b"basis"): [NULL_REVISION],
            (b"a-file-id", b"current"): [(b"a-file-id", b"basis")],
        }

    def versioned_repository_text_keys(self):
        return {
            (b"TREE_ROOT", b"basis"): [b"null:"],
            (b"TREE_ROOT", b"current"): [(b"TREE_ROOT", b"modified-something-else")],
            (b"TREE_ROOT", b"modified-something-else"): [(b"TREE_ROOT", b"basis")],
        }


class IncorrectlyOrderedParentsScenario(BrokenRepoScenario):
    """A scenario where the set parents of a version of a file are correct, but
    the order of those parents is incorrect.

    This defines a 'broken-revision-1-2' and a 'broken-revision-2-1' which both
    have their file version parents reversed compared to the revision parents,
    which is invalid.  (We use two revisions with opposite orderings of the
    same parents to make sure that accidentally relying on dictionary/set
    ordering cannot make the test pass; the assumption is that while dict/set
    iteration order is arbitrary, it is also consistent within a single test).
    """

    def all_versions_after_reconcile(self):
        return [
            b"parent-1",
            b"parent-2",
            b"broken-revision-1-2",
            b"broken-revision-2-1",
        ]

    def populated_parents(self):
        return (
            ((), b"parent-1"),
            ((), b"parent-2"),
            ((b"parent-2", b"parent-1"), b"broken-revision-1-2"),
            ((b"parent-1", b"parent-2"), b"broken-revision-2-1"),
        )

    def corrected_parents(self):
        return (
            ((), b"parent-1"),
            ((), b"parent-2"),
            ((b"parent-1", b"parent-2"), b"broken-revision-1-2"),
            ((b"parent-2", b"parent-1"), b"broken-revision-2-1"),
        )

    def check_regexes(self, repo):
        if repo.supports_rich_root():
            # TREE_ROOT will be wrong; but we're not testing it. so just adjust
            # the expected count of errors.
            count = 4
        else:
            count = 2
        return (
            "%d inconsistent parents" % count,
            r"\* a-file-id version broken-revision-1-2 has parents "
            r"\(parent-2, parent-1\) but should have "
            r"\(parent-1, parent-2\)",
            r"\* a-file-id version broken-revision-2-1 has parents "
            r"\(parent-1, parent-2\) but should have "
            r"\(parent-2, parent-1\)",
        )

    def populate_repository(self, repo):
        inv = self.make_one_file_inventory(repo, b"parent-1", [])
        self.add_revision(repo, b"parent-1", inv, [])

        inv = self.make_one_file_inventory(repo, b"parent-2", [])
        self.add_revision(repo, b"parent-2", inv, [])

        inv = self.make_one_file_inventory(
            repo, b"broken-revision-1-2", [b"parent-2", b"parent-1"]
        )
        self.add_revision(repo, b"broken-revision-1-2", inv, [b"parent-1", b"parent-2"])

        inv = self.make_one_file_inventory(
            repo, b"broken-revision-2-1", [b"parent-1", b"parent-2"]
        )
        self.add_revision(repo, b"broken-revision-2-1", inv, [b"parent-2", b"parent-1"])
        self.versioned_root = repo.supports_rich_root()

    def repository_text_key_references(self):
        result = {}
        if self.versioned_root:
            result.update(
                {
                    (b"TREE_ROOT", b"broken-revision-1-2"): True,
                    (b"TREE_ROOT", b"broken-revision-2-1"): True,
                    (b"TREE_ROOT", b"parent-1"): True,
                    (b"TREE_ROOT", b"parent-2"): True,
                }
            )
        result.update(
            {
                (b"a-file-id", b"broken-revision-1-2"): True,
                (b"a-file-id", b"broken-revision-2-1"): True,
                (b"a-file-id", b"parent-1"): True,
                (b"a-file-id", b"parent-2"): True,
            }
        )
        return result

    def repository_text_keys(self):
        return {
            (b"a-file-id", b"broken-revision-1-2"): [
                (b"a-file-id", b"parent-1"),
                (b"a-file-id", b"parent-2"),
            ],
            (b"a-file-id", b"broken-revision-2-1"): [
                (b"a-file-id", b"parent-2"),
                (b"a-file-id", b"parent-1"),
            ],
            (b"a-file-id", b"parent-1"): [NULL_REVISION],
            (b"a-file-id", b"parent-2"): [NULL_REVISION],
        }

    def versioned_repository_text_keys(self):
        return {
            (b"TREE_ROOT", b"broken-revision-1-2"): [
                (b"TREE_ROOT", b"parent-1"),
                (b"TREE_ROOT", b"parent-2"),
            ],
            (b"TREE_ROOT", b"broken-revision-2-1"): [
                (b"TREE_ROOT", b"parent-2"),
                (b"TREE_ROOT", b"parent-1"),
            ],
            (b"TREE_ROOT", b"parent-1"): [NULL_REVISION],
            (b"TREE_ROOT", b"parent-2"): [NULL_REVISION],
        }


all_broken_scenario_classes = [
    UndamagedRepositoryScenario,
    FileParentIsNotInRevisionAncestryScenario,
    FileParentHasInaccessibleInventoryScenario,
    FileParentsNotReferencedByAnyInventoryScenario,
    TooManyParentsScenario,
    ClaimedFileParentDidNotModifyFileScenario,
    IncorrectlyOrderedParentsScenario,
    UnreferencedFileParentsFromNoOpMergeScenario,
]


def broken_scenarios_for_all_formats():
    format_scenarios = all_repository_vf_format_scenarios()
    # test_check_reconcile needs to be parameterized by format *and* by broken
    # repository scenario.
    broken_scenarios = [
        (s.__name__, {"scenario_class": s}) for s in all_broken_scenario_classes
    ]
    return multiply_scenarios(format_scenarios, broken_scenarios)


class TestFileParentReconciliation(TestCaseWithRepository):
    """Tests for how reconcile corrects errors in parents of file versions."""

    scenarios = broken_scenarios_for_all_formats()

    def make_populated_repository(self, factory):
        """Create a new repository populated by the given factory."""
        repo = self.make_repository("broken-repo")
        with repo.lock_write(), WriteGroup(repo):
            factory(repo)
            return repo

    def add_revision(self, repo, revision_id, inv, parent_ids):
        """Add a revision with a given inventory and parents to a repository.

        :param repo: a repository.
        :param revision_id: the revision ID for the new revision.
        :param inv: an inventory (such as created by
            `make_one_file_inventory`).
        :param parent_ids: the parents for the new revision.
        """
        inv.revision_id = revision_id
        inv.root.revision = revision_id
        if repo.supports_rich_root():
            root_id = inv.root.file_id
            repo.texts.add_lines((root_id, revision_id), [], [])
        repo.add_inventory(revision_id, inv, parent_ids)
        revision = Revision(
            revision_id,
            committer="jrandom@example.com",
            timestamp=0,
            inventory_sha1="",
            timezone=0,
            message="foo",
            parent_ids=parent_ids,
        )
        repo.add_revision(revision_id, revision, inv)

    def make_one_file_inventory(
        self,
        repo,
        revision,
        parents,
        inv_revision=None,
        root_revision=None,
        file_contents=None,
        make_file_version=True,
    ):
        """Make an inventory containing a version of a file with ID 'a-file'.

        The file's ID will be 'a-file', and its filename will be 'a file name',
        stored at the tree root.

        :param repo: a repository to add the new file version to.
        :param revision: the revision ID of the new inventory.
        :param parents: the parents for this revision of 'a-file'.
        :param inv_revision: if not None, the revision ID to store in the
            inventory entry.  Otherwise, this defaults to revision.
        :param root_revision: if not None, the inventory's root.revision will
            be set to this.
        :param file_contents: if not None, the contents of this file version.
            Otherwise a unique default (based on revision ID) will be
            generated.
        """
        inv = Inventory(revision_id=revision)
        if root_revision is not None:
            inv.root.revision = root_revision
        file_id = b"a-file-id"
        entry = InventoryFile(file_id, "a file name", b"TREE_ROOT")
        if inv_revision is not None:
            entry.revision = inv_revision
        else:
            entry.revision = revision
        entry.text_size = 0
        if file_contents is None:
            file_contents = b"%sline\n" % entry.revision
        entry.text_sha1 = osutils.sha_string(file_contents)
        inv.add(entry)
        if make_file_version:
            repo.texts.add_lines(
                (file_id, revision),
                [(file_id, parent) for parent in parents],
                [file_contents],
            )
        return inv

    def require_repo_suffers_text_parent_corruption(self, repo):
        if not repo._reconcile_fixes_text_parents:
            raise TestNotApplicable(
                "Format does not support text parent reconciliation"
            )

    def file_parents(self, repo, revision_id):
        key = (b"a-file-id", revision_id)
        parent_map = repo.texts.get_parent_map([key])
        return tuple(parent[-1] for parent in parent_map[key])

    def assertFileVersionAbsent(self, repo, revision_id):
        self.assertEqual({}, repo.texts.get_parent_map([(b"a-file-id", revision_id)]))

    def assertParentsMatch(self, expected_parents_for_versions, repo, when_description):
        for expected_parents, version in expected_parents_for_versions:
            if expected_parents is None:
                self.assertFileVersionAbsent(repo, version)
            else:
                found_parents = self.file_parents(repo, version)
                self.assertEqual(
                    expected_parents,
                    found_parents,
                    "%s reconcile %s has parents %s, should have %s."
                    % (when_description, version, found_parents, expected_parents),
                )

    def prepare_test_repository(self):
        """Prepare a repository to test with from the test scenario.

        :return: A repository, and the scenario instance.
        """
        scenario = self.scenario_class(self)
        repo = self.make_populated_repository(scenario.populate_repository)
        self.require_repo_suffers_text_parent_corruption(repo)
        return repo, scenario

    def shas_for_versions_of_file(self, repo, versions):
        """Get the SHA-1 hashes of the versions of 'a-file' in the repository.

        :param repo: the repository to get the hashes from.
        :param versions: a list of versions to get hashes for.

        :returns: A dict of `{version: hash}`.
        """
        keys = [(b"a-file-id", version) for version in versions]
        return repo.texts.get_sha1s(keys)

    def test_reconcile_behaviour(self):
        """Populate a repository and reconcile it, verifying the state before
        and after.
        """
        repo, scenario = self.prepare_test_repository()
        with repo.lock_read():
            self.assertParentsMatch(scenario.populated_parents(), repo, b"before")
            vf_shas = self.shas_for_versions_of_file(
                repo, scenario.all_versions_after_reconcile()
            )
        result = repo.reconcile(thorough=True)
        with repo.lock_read():
            self.assertParentsMatch(scenario.corrected_parents(), repo, b"after")
            # The contents of the versions in the versionedfile should be the
            # same after the reconcile.
            self.assertEqual(
                vf_shas,
                self.shas_for_versions_of_file(
                    repo, scenario.all_versions_after_reconcile()
                ),
            )

            # Scenario.corrected_fulltexts contains texts which the test wants
            # to assert are now fulltexts. However this is an abstraction
            # violation; really we care that:
            # - the text is reconstructable
            # - it has an empty parents list
            # (we specify it this way because a store can use arbitrary
            # compression pointers in principle.
            for file_version in scenario.corrected_fulltexts():
                key = (b"a-file-id", file_version)
                self.assertEqual({key: ()}, repo.texts.get_parent_map([key]))
                self.assertIsInstance(
                    next(
                        repo.texts.get_record_stream([key], "unordered", True)
                    ).get_bytes_as("fulltext"),
                    bytes,
                )

    def test_check_behaviour(self):
        """Populate a repository and check it, and verify the output."""
        repo, scenario = self.prepare_test_repository()
        check_result = repo.check()
        check_result.report_results(verbose=True)
        log = self.get_log()
        for pattern in scenario.check_regexes(repo):
            self.assertContainsRe(log, pattern)

    def test_find_text_key_references(self):
        """Test that find_text_key_references finds erroneous references."""
        repo, scenario = self.prepare_test_repository()
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(
            scenario.repository_text_key_references(), repo.find_text_key_references()
        )

    def test__generate_text_key_index(self):
        """Test that the generated text key index has all entries."""
        repo, scenario = self.prepare_test_repository()
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(
            scenario.repository_text_key_index(), repo._generate_text_key_index()
        )
