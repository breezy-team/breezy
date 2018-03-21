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

"""Test the smart client."""

from __future__ import absolute_import

import os

from ....controldir import ControlDir
from ....errors import (
    BzrError,
    NotBranchError,
    )

from ....tests import (
    TestCase,
    TestCaseWithTransport,
    )
from ....tests.features import ExecutableFeature

from ..mapping import default_mapping
from ..remote import (
    split_git_url,
    parse_git_error,
    RemoteGitBranchFormat,
    )

from dulwich.repo import Repo as GitRepo


class SplitUrlTests(TestCase):

    def test_simple(self):
        self.assertEquals(("foo", None, None, "/bar"),
            split_git_url("git://foo/bar"))

    def test_port(self):
        self.assertEquals(("foo", 343, None, "/bar"),
            split_git_url("git://foo:343/bar"))

    def test_username(self):
        self.assertEquals(("foo", None, "la", "/bar"),
            split_git_url("git://la@foo/bar"))

    def test_nopath(self):
        self.assertEquals(("foo", None, None, "/"),
            split_git_url("git://foo/"))

    def test_slashpath(self):
        self.assertEquals(("foo", None, None, "//bar"),
            split_git_url("git://foo//bar"))

    def test_homedir(self):
        self.assertEquals(("foo", None, None, "~bar"),
            split_git_url("git://foo/~bar"))


class ParseGitErrorTests(TestCase):

    def test_unknown(self):
        e = parse_git_error("url", "foo")
        self.assertIsInstance(e, BzrError)

    def test_notbrancherror(self):
        e = parse_git_error("url", "\n Could not find Repository foo/bar")
        self.assertIsInstance(e, NotBranchError)


class TestRemoteGitBranchFormat(TestCase):

    def setUp(self):
        super(TestRemoteGitBranchFormat, self).setUp()
        self.format = RemoteGitBranchFormat()

    def test_get_format_description(self):
        self.assertEquals("Remote Git Branch", self.format.get_format_description())

    def test_get_network_name(self):
        self.assertEquals("git", self.format.network_name())

    def test_supports_tags(self):
        self.assertTrue(self.format.supports_tags())


class TestFetchFromRemote(TestCaseWithTransport):

    _test_needs_features = [ExecutableFeature('git')]

    def setUp(self):
        super(TestFetchFromRemote, self).setUp()
        self.remote_real = GitRepo.init('remote', mkdir=True)
        self.remote_url = 'git://%s/' % os.path.abspath(self.remote_real.path)
        self.permit_url(self.remote_url)

    def test_sprout_simple(self):
        self.remote_real.do_commit(
                message='message',
                committer='committer <committer@example.com>',
                author='author <author@example.com>')

        self.make_branch_and_tree('.')
        remote = ControlDir.open(self.remote_url)
        local = remote.sprout('local')
        self.assertEqual(
                default_mapping.revision_id_foreign_to_bzr(self.remote_real.head()),
                local.open_branch().last_revision())

    def test_sprout_with_tags(self):
        c1 = self.remote_real.do_commit(
                message='message',
                committer='committer <committer@example.com>',
                author='author <author@example.com>')
        c2 = self.remote_real.do_commit(
                message='another commit',
                committer='committer <committer@example.com>',
                author='author <author@example.com>',
                ref='refs/tags/another')
        self.remote_real.refs['refs/tags/blah'] = self.remote_real.head()

        self.make_branch_and_tree('.')
        remote = ControlDir.open(self.remote_url)
        local = remote.sprout('local')
        local_branch = local.open_branch()
        self.assertEqual(
                default_mapping.revision_id_foreign_to_bzr(c1),
                local_branch.last_revision())
        self.assertEqual(
                {'blah': local_branch.last_revision(),
                 'another': default_mapping.revision_id_foreign_to_bzr(c2)},
                local_branch.tags.get_tag_dict())


class TestPushToRemote(TestCaseWithTransport):

    _test_needs_features = [ExecutableFeature('git')]

    def setUp(self):
        super(TestPushToRemote, self).setUp()
        self.remote_real = GitRepo.init('remote', mkdir=True)
        self.remote_url = 'git://%s/' % os.path.abspath(self.remote_real.path)
        self.permit_url(self.remote_url)

    def test_push(self):
        c1 = self.remote_real.do_commit(
                message='message',
                committer='committer <committer@example.com>',
                author='author <author@example.com>')

        self.make_branch_and_tree('.')
        remote = ControlDir.open(self.remote_url)
        local = remote.sprout('local')
        self.build_tree(['local/blah'])
        wt = local.open_workingtree()
        wt.add(['blah'])
        revid = wt.commit('blah')
        wt.branch.tags.set_tag('sometag', revid)

        remote.push_branch(wt.branch)

        self.assertNotEqual(self.remote_real.head(), c1)
        self.assertEqual(
                {'refs/heads/master': self.remote_real.head(),
                 'HEAD': self.remote_real.head(),
                },
                self.remote_real.get_refs())
