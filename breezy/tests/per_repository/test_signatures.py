# Copyright (C) 2011, 2012, 2016 Canonical Ltd
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

"""Tests for repository revision signatures."""

from breezy import (
    errors,
    gpg,
    tests,
    urlutils,
    )
from breezy.repository import WriteGroup
from breezy.bzr.testament import Testament
from breezy.tests import per_repository


class TestSignatures(per_repository.TestCaseWithRepository):

    def setUp(self):
        super(TestSignatures, self).setUp()
        if not self.repository_format.supports_revision_signatures:
            raise tests.TestNotApplicable(
                "repository does not support signing revisions")

# TODO 20051003 RBC:
# compare the gpg-to-sign info for a commit with a ghost and
#     an identical tree without a ghost
# fetch missing should rewrite the TOC of weaves to list newly available parents.

    def test_sign_existing_revision(self):
        wt = self.make_branch_and_tree('.')
        a = wt.commit("base", allow_pointless=True)
        strategy = gpg.LoopbackGPGStrategy(None)
        repo = wt.branch.repository
        self.addCleanup(repo.lock_write().unlock)
        repo.start_write_group()
        repo.sign_revision(a, strategy)
        repo.commit_write_group()
        self.assertEqual(b'-----BEGIN PSEUDO-SIGNED CONTENT-----\n'
                         + Testament.from_revision(repo,
                                                   a).as_short_text() +
                         b'-----END PSEUDO-SIGNED CONTENT-----\n',
                         repo.get_signature_text(a))

    def test_store_signature(self):
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        with branch.lock_write(), WriteGroup(branch.repository):
            try:
                branch.repository.store_revision_signature(
                    gpg.LoopbackGPGStrategy(None), b'FOO', b'A')
            except errors.NoSuchRevision:
                raise tests.TestNotApplicable(
                    "repository does not support signing non-present"
                    "revisions")
        # A signature without a revision should not be accessible.
        self.assertRaises(errors.NoSuchRevision,
                          branch.repository.has_signature_for_revision_id,
                          b'A')
        if wt.branch.repository._format.supports_setting_revision_ids:
            wt.commit("base", rev_id=b'A', allow_pointless=True)
            self.assertEqual(b'-----BEGIN PSEUDO-SIGNED CONTENT-----\n'
                             b'FOO-----END PSEUDO-SIGNED CONTENT-----\n',
                             branch.repository.get_signature_text(b'A'))

    def test_clone_preserves_signatures(self):
        wt = self.make_branch_and_tree('source')
        a = wt.commit('A', allow_pointless=True)
        repo = wt.branch.repository
        repo.lock_write()
        repo.start_write_group()
        repo.sign_revision(a, gpg.LoopbackGPGStrategy(None))
        repo.commit_write_group()
        repo.unlock()
        # FIXME: clone should work to urls,
        # wt.clone should work to disks.
        self.build_tree(['target/'])
        d2 = repo.controldir.clone(urlutils.local_path_to_url('target'))
        self.assertEqual(repo.get_signature_text(a),
                         d2.open_repository().get_signature_text(a))

    def test_verify_revision_signature_not_signed(self):
        wt = self.make_branch_and_tree('.')
        a = wt.commit("base", allow_pointless=True)
        strategy = gpg.LoopbackGPGStrategy(None)
        self.assertEqual(
            (gpg.SIGNATURE_NOT_SIGNED, None),
            wt.branch.repository.verify_revision_signature(a, strategy))

    def test_verify_revision_signature(self):
        wt = self.make_branch_and_tree('.')
        a = wt.commit("base", allow_pointless=True)
        strategy = gpg.LoopbackGPGStrategy(None)
        repo = wt.branch.repository
        self.addCleanup(repo.lock_write().unlock)
        repo.start_write_group()
        repo.sign_revision(a, strategy)
        repo.commit_write_group()
        self.assertEqual(b'-----BEGIN PSEUDO-SIGNED CONTENT-----\n'
                         + Testament.from_revision(repo, a).as_short_text()
                         + b'-----END PSEUDO-SIGNED CONTENT-----\n',
                         repo.get_signature_text(a))
        self.assertEqual(
            (gpg.SIGNATURE_VALID, None),
            repo.verify_revision_signature(a, strategy))

    def test_verify_revision_signatures(self):
        wt = self.make_branch_and_tree('.')
        a = wt.commit("base", allow_pointless=True)
        b = wt.commit("second", allow_pointless=True)
        strategy = gpg.LoopbackGPGStrategy(None)
        repo = wt.branch.repository
        self.addCleanup(repo.lock_write().unlock)
        repo.start_write_group()
        repo.sign_revision(a, strategy)
        repo.commit_write_group()
        self.assertEqual(b'-----BEGIN PSEUDO-SIGNED CONTENT-----\n'
                         + Testament.from_revision(repo, a).as_short_text()
                         + b'-----END PSEUDO-SIGNED CONTENT-----\n',
                         repo.get_signature_text(a))
        self.assertEqual(
            [(a, gpg.SIGNATURE_VALID, None),
             (b, gpg.SIGNATURE_NOT_SIGNED, None)],
            list(repo.verify_revision_signatures([a, b], strategy)))


class TestUnsupportedSignatures(per_repository.TestCaseWithRepository):

    def test_sign_revision(self):
        if self.repository_format.supports_revision_signatures:
            raise tests.TestNotApplicable(
                "repository supports signing revisions")
        wt = self.make_branch_and_tree('source')
        a = wt.commit('A', allow_pointless=True)
        repo = wt.branch.repository
        repo.lock_write()
        repo.start_write_group()
        self.assertRaises(errors.UnsupportedOperation,
                          repo.sign_revision, a, gpg.LoopbackGPGStrategy(None))
        repo.commit_write_group()
