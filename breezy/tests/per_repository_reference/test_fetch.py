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


from breezy import branch
from breezy.bzr import vf_search
from breezy.tests.per_repository import TestCaseWithRepository


class TestFetchBase(TestCaseWithRepository):
    def make_source_branch(self):
        # It would be nice if there was a way to force this to be memory-only
        builder = self.make_branch_builder("source")
        content = [
            b"content lines\n"
            b"for the first revision\n"
            b"which is a marginal amount of content\n"
        ]
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"".join(content))),
            ],
            revision_id=b"A-id",
        )
        content.append(b"and some more lines for B\n")
        builder.build_snapshot(
            [b"A-id"], [("modify", ("a", b"".join(content)))], revision_id=b"B-id"
        )
        content.append(b"and yet even more content for C\n")
        builder.build_snapshot(
            [b"B-id"], [("modify", ("a", b"".join(content)))], revision_id=b"C-id"
        )
        builder.finish_series()
        source_b = builder.get_branch()
        source_b.lock_read()
        self.addCleanup(source_b.unlock)
        return content, source_b


class TestFetch(TestFetchBase):
    def test_sprout_from_stacked_with_short_history(self):
        content, source_b = self.make_source_branch()
        # Split the generated content into a base branch, and a stacked branch
        # Use 'make_branch' which gives us a bzr:// branch when appropriate,
        # rather than creating a branch-on-disk
        stack_b = self.make_branch("stack-on")
        stack_b.pull(source_b, stop_revision=b"B-id")
        target_b = self.make_branch("target")
        target_b.set_stacked_on_url("../stack-on")
        target_b.pull(source_b, stop_revision=b"C-id")
        # At this point, we should have a target branch, with 1 revision, on
        # top of the source.
        final_b = self.make_branch("final")
        final_b.pull(target_b)
        final_b.lock_read()
        self.addCleanup(final_b.unlock)
        self.assertEqual(b"C-id", final_b.last_revision())
        text_keys = [(b"a-id", b"A-id"), (b"a-id", b"B-id"), (b"a-id", b"C-id")]
        stream = final_b.repository.texts.get_record_stream(
            text_keys, "unordered", True
        )
        records = sorted([(r.key, r.get_bytes_as("fulltext")) for r in stream])
        self.assertEqual(
            [
                ((b"a-id", b"A-id"), b"".join(content[:-2])),
                ((b"a-id", b"B-id"), b"".join(content[:-1])),
                ((b"a-id", b"C-id"), b"".join(content)),
            ],
            records,
        )

    def test_sprout_from_smart_stacked_with_short_history(self):
        content, source_b = self.make_source_branch()
        transport = self.make_smart_server("server")
        transport.ensure_base()
        url = transport.abspath("")
        source_b.controldir.sprout(url + "/stack-on", revision_id=b"B-id")
        # self.make_branch only takes relative paths, so we do it the 'hard'
        # way
        target_transport = transport.clone("target")
        target_transport.ensure_base()
        target_bzrdir = self.bzrdir_format.initialize_on_transport(target_transport)
        target_bzrdir.create_repository()
        target_b = target_bzrdir.create_branch()
        target_b.set_stacked_on_url("../stack-on")
        target_b.pull(source_b, stop_revision=b"C-id")
        # Now we should be able to branch from the remote location to a local
        # location
        final_b = target_b.controldir.sprout("final").open_branch()
        self.assertEqual(b"C-id", final_b.last_revision())

        # bzrdir.sprout() has slightly different code paths if you supply a
        # revision_id versus not. If you supply revision_id, then you get a
        # PendingAncestryResult for the search, versus a SearchResult...
        target_b.controldir.sprout("final2", revision_id=b"C-id").open_branch()
        self.assertEqual(b"C-id", final_b.last_revision())

    def make_source_with_ghost_and_stacked_target(self):
        builder = self.make_branch_builder("source")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("file", b"file-id", "file", b"content\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot([b"A-id", b"ghost-id"], [], revision_id=b"B-id")
        builder.finish_series()
        source_b = builder.get_branch()
        source_b.lock_read()
        self.addCleanup(source_b.unlock)
        base = self.make_branch("base")
        base.pull(source_b, stop_revision=b"A-id")
        stacked = self.make_branch("stacked")
        stacked.set_stacked_on_url("../base")
        return source_b, base, stacked

    def test_fetch_with_ghost_stacked(self):
        (source_b, base, stacked) = self.make_source_with_ghost_and_stacked_target()
        stacked.pull(source_b, stop_revision=b"B-id")

    def test_fetch_into_smart_stacked_with_ghost(self):
        (source_b, base, stacked) = self.make_source_with_ghost_and_stacked_target()
        # Now, create a smart server on 'stacked' and re-open to force the
        # target to be a smart target
        trans = self.make_smart_server("stacked")
        stacked = branch.Branch.open(trans.base)
        stacked.lock_write()
        self.addCleanup(stacked.unlock)
        stacked.pull(source_b, stop_revision=b"B-id")

    def test_fetch_to_stacked_from_smart_with_ghost(self):
        (source_b, base, stacked) = self.make_source_with_ghost_and_stacked_target()
        # Now, create a smart server on 'source' and re-open to force the
        # target to be a smart target
        trans = self.make_smart_server("source")
        source_b = branch.Branch.open(trans.base)
        source_b.lock_read()
        self.addCleanup(source_b.unlock)
        stacked.pull(source_b, stop_revision=b"B-id")


class TestFetchFromRepoWithUnconfiguredFallbacks(TestFetchBase):
    def make_stacked_source_repo(self):
        _, source_b = self.make_source_branch()
        # Use 'make_branch' which gives us a bzr:// branch when appropriate,
        # rather than creating a branch-on-disk
        stack_b = self.make_branch("stack-on")
        stack_b.pull(source_b, stop_revision=b"B-id")
        stacked_b = self.make_branch("stacked")
        stacked_b.set_stacked_on_url("../stack-on")
        stacked_b.pull(source_b, stop_revision=b"C-id")
        return stacked_b.repository

    def test_fetch_everything_includes_parent_invs(self):
        stacked = self.make_stacked_source_repo()
        repo_missing_fallbacks = stacked.controldir.open_repository()
        self.addCleanup(repo_missing_fallbacks.lock_read().unlock)
        target = self.make_repository("target")
        self.addCleanup(target.lock_write().unlock)
        target.fetch(
            repo_missing_fallbacks,
            fetch_spec=vf_search.EverythingResult(repo_missing_fallbacks),
        )
        self.assertEqual(
            repo_missing_fallbacks.revisions.keys(), target.revisions.keys()
        )
        self.assertEqual(
            repo_missing_fallbacks.inventories.keys(), target.inventories.keys()
        )
        self.assertEqual([b"C-id"], sorted(k[-1] for k in target.revisions.keys()))
        self.assertEqual(
            [b"B-id", b"C-id"], sorted(k[-1] for k in target.inventories.keys())
        )
