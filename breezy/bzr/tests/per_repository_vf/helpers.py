# Copyright (C) 2007 Canonical Ltd
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

"""Helper classes for repository implementation tests."""

from .... import (
    osutils,
    revision as _mod_revision,
    )
from ....repository import WriteGroup
from ... import (
    inventory,
    )
from ...knitrepo import RepositoryFormatKnit
from ....tests.per_repository import TestCaseWithRepository
from ....tests import TestNotApplicable


class TestCaseWithBrokenRevisionIndex(TestCaseWithRepository):

    def make_repo_with_extra_ghost_index(self):
        """Make a corrupt repository.

        It will contain one revision, b'revision-id'.  The knit index will claim
        that it has one parent, 'incorrect-parent', but the revision text will
        claim it has no parents.

        Note: only the *cache* of the knit index is corrupted.  Thus the
        corruption will only last while the repository is locked.  For this
        reason, the returned repo is locked.
        """
        if not isinstance(self.repository_format, RepositoryFormatKnit):
            # XXX: Broken revision graphs can happen to weaves too, but they're
            # pretty deprecated.  Ideally these tests should apply to any repo
            # where repo.revision_graph_can_have_wrong_parents() is True, but
            # at the moment we only know how to corrupt knit repos.
            raise TestNotApplicable(
                "%s isn't a knit format" % self.repository_format)

        repo = self.make_repository('broken')
        with repo.lock_write(), WriteGroup(repo):
            inv = inventory.Inventory(revision_id=b'revision-id')
            inv.root.revision = b'revision-id'
            inv_sha1 = repo.add_inventory(b'revision-id', inv, [])
            if repo.supports_rich_root():
                root_id = inv.root.file_id
                repo.texts.add_lines((root_id, b'revision-id'), [], [])
            revision = _mod_revision.Revision(b'revision-id',
                                              committer='jrandom@example.com', timestamp=0,
                                              inventory_sha1=inv_sha1, timezone=0, message='message',
                                              parent_ids=[])
            # Manually add the revision text using the RevisionStore API, with
            # bad parents.
            lines = repo._serializer.write_revision_to_lines(revision)
            repo.revisions.add_lines((revision.revision_id,),
                                     [(b'incorrect-parent',)],
                                     lines)

        repo.lock_write()
        self.addCleanup(repo.unlock)
        return repo
