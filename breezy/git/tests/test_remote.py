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

from io import BytesIO

import os
import time

from ...controldir import ControlDir
from ...errors import (
    DivergedBranches,
    NotBranchError,
    NoSuchTag,
    PermissionDenied,
    )

from ...tests import (
    TestCase,
    TestCaseWithTransport,
    )
from ...tests.features import ExecutableFeature

from ..mapping import default_mapping
from ..remote import (
    split_git_url,
    parse_git_error,
    HeadUpdateFailed,
    RemoteGitError,
    RemoteGitBranchFormat,
    )

from dulwich import porcelain
from dulwich.repo import Repo as GitRepo


class SplitUrlTests(TestCase):

    def test_simple(self):
        self.assertEqual(("foo", None, None, "/bar"),
                         split_git_url("git://foo/bar"))

    def test_port(self):
        self.assertEqual(("foo", 343, None, "/bar"),
                         split_git_url("git://foo:343/bar"))

    def test_username(self):
        self.assertEqual(("foo", None, "la", "/bar"),
                         split_git_url("git://la@foo/bar"))

    def test_nopath(self):
        self.assertEqual(("foo", None, None, "/"),
                         split_git_url("git://foo/"))

    def test_slashpath(self):
        self.assertEqual(("foo", None, None, "//bar"),
                         split_git_url("git://foo//bar"))

    def test_homedir(self):
        self.assertEqual(("foo", None, None, "~bar"),
                         split_git_url("git://foo/~bar"))


class ParseGitErrorTests(TestCase):

    def test_unknown(self):
        e = parse_git_error("url", "foo")
        self.assertIsInstance(e, RemoteGitError)

    def test_notbrancherror(self):
        e = parse_git_error("url", "\n Could not find Repository foo/bar")
        self.assertIsInstance(e, NotBranchError)

    def test_notbrancherror_launchpad(self):
        e = parse_git_error("url", "Repository 'foo/bar' not found.")
        self.assertIsInstance(e, NotBranchError)

    def test_notbrancherror_github(self):
        e = parse_git_error("url", "Repository not found.\n")
        self.assertIsInstance(e, NotBranchError)

    def test_notbrancherror_normal(self):
        e = parse_git_error(
            "url", "fatal: '/srv/git/lintian-brush' does not appear to be a git repository")
        self.assertIsInstance(e, NotBranchError)

    def test_head_update(self):
        e = parse_git_error("url", "HEAD failed to update\n")
        self.assertIsInstance(e, HeadUpdateFailed)

    def test_permission_dnied(self):
        e = parse_git_error(
            "url",
            "access denied or repository not exported: /debian/altermime.git")
        self.assertIsInstance(e, PermissionDenied)

    def test_permission_denied_gitlab(self):
        e = parse_git_error(
            "url",
            'GitLab: You are not allowed to push code to this project.\n')
        self.assertIsInstance(e, PermissionDenied)

    def test_permission_denied_github(self):
        e = parse_git_error(
            "url",
            'Permission to porridge/gaduhistory.git denied to jelmer.')
        self.assertIsInstance(e, PermissionDenied)
        self.assertEqual(e.path, 'porridge/gaduhistory.git')
        self.assertEqual(e.extra, ': denied to jelmer')


class TestRemoteGitBranchFormat(TestCase):

    def setUp(self):
        super(TestRemoteGitBranchFormat, self).setUp()
        self.format = RemoteGitBranchFormat()

    def test_get_format_description(self):
        self.assertEqual("Remote Git Branch",
                         self.format.get_format_description())

    def test_get_network_name(self):
        self.assertEqual(b"git", self.format.network_name())

    def test_supports_tags(self):
        self.assertTrue(self.format.supports_tags())


class TestRemoteGitBranch(TestCaseWithTransport):

    _test_needs_features = [ExecutableFeature('git')]

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.remote_real = GitRepo.init('remote', mkdir=True)
        self.remote_url = 'git://%s/' % os.path.abspath(self.remote_real.path)
        self.permit_url(self.remote_url)

    def test_set_last_revision_info(self):
        c1 = self.remote_real.do_commit(
            message=b'message 1',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>',
            ref=b'refs/heads/newbranch')
        c2 = self.remote_real.do_commit(
            message=b'message 2',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>',
            ref=b'refs/heads/newbranch')

        remote = ControlDir.open(self.remote_url)
        newbranch = remote.open_branch('newbranch')
        self.assertEqual(newbranch.lookup_foreign_revision_id(c2),
                         newbranch.last_revision())
        newbranch.set_last_revision_info(
            1, newbranch.lookup_foreign_revision_id(c1))
        self.assertEqual(c1, self.remote_real.refs[b'refs/heads/newbranch'])
        self.assertEqual(newbranch.last_revision(),
                         newbranch.lookup_foreign_revision_id(c1))


class FetchFromRemoteTestBase(object):

    _test_needs_features = [ExecutableFeature('git')]

    _to_format = None

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.remote_real = GitRepo.init('remote', mkdir=True)
        self.remote_url = 'git://%s/' % os.path.abspath(self.remote_real.path)
        self.permit_url(self.remote_url)

    def test_sprout_simple(self):
        self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')

        remote = ControlDir.open(self.remote_url)
        self.make_controldir('local', format=self._to_format)
        local = remote.sprout('local')
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(
                self.remote_real.head()),
            local.open_branch().last_revision())

    def test_sprout_with_tags(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        c2 = self.remote_real.do_commit(
            message=b'another commit',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>',
            ref=b'refs/tags/another')
        self.remote_real.refs[b'refs/tags/blah'] = self.remote_real.head()

        remote = ControlDir.open(self.remote_url)
        self.make_controldir('local', format=self._to_format)
        local = remote.sprout('local')
        local_branch = local.open_branch()
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(c1),
            local_branch.last_revision())
        self.assertEqual(
            {'blah': local_branch.last_revision(),
             'another': default_mapping.revision_id_foreign_to_bzr(c2)},
            local_branch.tags.get_tag_dict())

    def test_sprout_with_annotated_tag(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        c2 = self.remote_real.do_commit(
            message=b'another commit',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>',
            ref=b'refs/heads/another')
        porcelain.tag_create(
            self.remote_real,
            tag=b"blah",
            author=b'author <author@example.com>',
            objectish=c2,
            tag_time=int(time.time()),
            tag_timezone=0,
            annotated=True,
            message=b"Annotated tag")

        remote = ControlDir.open(self.remote_url)
        self.make_controldir('local', format=self._to_format)
        local = remote.sprout(
            'local', revision_id=default_mapping.revision_id_foreign_to_bzr(c1))
        local_branch = local.open_branch()
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(c1),
            local_branch.last_revision())
        self.assertEqual(
            {'blah': default_mapping.revision_id_foreign_to_bzr(c2)},
            local_branch.tags.get_tag_dict())

    def test_sprout_with_annotated_tag_unreferenced(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        c2 = self.remote_real.do_commit(
            message=b'another commit',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        porcelain.tag_create(
            self.remote_real,
            tag=b"blah",
            author=b'author <author@example.com>',
            objectish=c1,
            tag_time=int(time.time()),
            tag_timezone=0,
            annotated=True,
            message=b"Annotated tag")

        remote = ControlDir.open(self.remote_url)
        self.make_controldir('local', format=self._to_format)
        local = remote.sprout(
            'local',
            revision_id=default_mapping.revision_id_foreign_to_bzr(c1))
        local_branch = local.open_branch()
        self.assertEqual(
            default_mapping.revision_id_foreign_to_bzr(c1),
            local_branch.last_revision())
        self.assertEqual(
            {'blah': default_mapping.revision_id_foreign_to_bzr(c1)},
            local_branch.tags.get_tag_dict())


class FetchFromRemoteToBzrTests(FetchFromRemoteTestBase, TestCaseWithTransport):

    _to_format = '2a'


class FetchFromRemoteToGitTests(FetchFromRemoteTestBase, TestCaseWithTransport):

    _to_format = 'git'


class PushToRemoteBase(object):

    _test_needs_features = [ExecutableFeature('git')]

    _from_format = None

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.remote_real = GitRepo.init('remote', mkdir=True)
        self.remote_url = 'git://%s/' % os.path.abspath(self.remote_real.path)
        self.permit_url(self.remote_url)

    def test_push_branch_new(self):
        remote = ControlDir.open(self.remote_url)
        wt = self.make_branch_and_tree('local', format=self._from_format)
        self.build_tree(['local/blah'])
        wt.add(['blah'])
        revid = wt.commit('blah')

        if self._from_format == 'git':
            result = remote.push_branch(wt.branch, name='newbranch')
        else:
            result = remote.push_branch(
                wt.branch, lossy=True, name='newbranch')

        self.assertEqual(0, result.old_revno)
        if self._from_format == 'git':
            self.assertEqual(1, result.new_revno)
        else:
            self.assertIs(None, result.new_revno)

        result.report(BytesIO())

        self.assertEqual(
            {b'refs/heads/newbranch': self.remote_real.refs[b'refs/heads/newbranch'],
             },
            self.remote_real.get_refs())

    def test_push(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')

        remote = ControlDir.open(self.remote_url)
        self.make_controldir('local', format=self._from_format)
        local = remote.sprout('local')
        self.build_tree(['local/blah'])
        wt = local.open_workingtree()
        wt.add(['blah'])
        revid = wt.commit('blah')
        wt.branch.tags.set_tag('sometag', revid)
        wt.branch.get_config_stack().set('branch.fetch_tags', True)

        if self._from_format == 'git':
            result = wt.branch.push(remote.create_branch('newbranch'))
        else:
            result = wt.branch.push(
                remote.create_branch('newbranch'), lossy=True)

        self.assertEqual(0, result.old_revno)
        self.assertEqual(2, result.new_revno)

        result.report(BytesIO())

        self.assertEqual(
            {b'refs/heads/master': self.remote_real.head(),
             b'HEAD': self.remote_real.head(),
             b'refs/heads/newbranch': self.remote_real.refs[b'refs/heads/newbranch'],
             b'refs/tags/sometag': self.remote_real.refs[b'refs/heads/newbranch'],
             },
            self.remote_real.get_refs())

    def test_push_diverged(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>',
            ref=b'refs/heads/newbranch')

        remote = ControlDir.open(self.remote_url)
        wt = self.make_branch_and_tree('local', format=self._from_format)
        self.build_tree(['local/blah'])
        wt.add(['blah'])
        revid = wt.commit('blah')

        newbranch = remote.open_branch('newbranch')
        if self._from_format == 'git':
            self.assertRaises(DivergedBranches, wt.branch.push, newbranch)
        else:
            self.assertRaises(DivergedBranches, wt.branch.push,
                              newbranch, lossy=True)

        self.assertEqual(
            {b'refs/heads/newbranch': c1},
            self.remote_real.get_refs())

        if self._from_format == 'git':
            wt.branch.push(newbranch, overwrite=True)
        else:
            wt.branch.push(newbranch, lossy=True, overwrite=True)

        self.assertNotEqual(c1, self.remote_real.refs[b'refs/heads/newbranch'])


class PushToRemoteFromBzrTests(PushToRemoteBase, TestCaseWithTransport):

    _from_format = '2a'


class PushToRemoteFromGitTests(PushToRemoteBase, TestCaseWithTransport):

    _from_format = 'git'


class RemoteControlDirTests(TestCaseWithTransport):

    _test_needs_features = [ExecutableFeature('git')]

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.remote_real = GitRepo.init('remote', mkdir=True)
        self.remote_url = 'git://%s/' % os.path.abspath(self.remote_real.path)
        self.permit_url(self.remote_url)

    def test_remove_branch(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        c2 = self.remote_real.do_commit(
            message=b'another commit',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>',
            ref=b'refs/heads/blah')

        remote = ControlDir.open(self.remote_url)
        remote.destroy_branch(name='blah')
        self.assertEqual(
            self.remote_real.get_refs(),
            {b'refs/heads/master': self.remote_real.head(),
             b'HEAD': self.remote_real.head(),
             })

    def test_list_branches(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        c2 = self.remote_real.do_commit(
            message=b'another commit',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>',
            ref=b'refs/heads/blah')

        remote = ControlDir.open(self.remote_url)
        self.assertEqual(
            set(['master', 'blah', 'master']),
            set([b.name for b in remote.list_branches()]))

    def test_get_branches(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        c2 = self.remote_real.do_commit(
            message=b'another commit',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>',
            ref=b'refs/heads/blah')

        remote = ControlDir.open(self.remote_url)
        self.assertEqual(
            {'': 'master', 'blah': 'blah', 'master': 'master'},
            {n: b.name for (n, b) in remote.get_branches().items()})

    def test_remove_tag(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        c2 = self.remote_real.do_commit(
            message=b'another commit',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>',
            ref=b'refs/tags/blah')

        remote = ControlDir.open(self.remote_url)
        remote_branch = remote.open_branch()
        remote_branch.tags.delete_tag('blah')
        self.assertRaises(NoSuchTag, remote_branch.tags.delete_tag, 'blah')
        self.assertEqual(
            self.remote_real.get_refs(),
            {b'refs/heads/master': self.remote_real.head(),
             b'HEAD': self.remote_real.head(),
             })

    def test_set_tag(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        c2 = self.remote_real.do_commit(
            message=b'another commit',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')

        remote = ControlDir.open(self.remote_url)
        remote.open_branch().tags.set_tag(
            b'blah', default_mapping.revision_id_foreign_to_bzr(c1))
        self.assertEqual(
            self.remote_real.get_refs(),
            {b'refs/heads/master': self.remote_real.head(),
             b'refs/tags/blah': c1,
             b'HEAD': self.remote_real.head(),
             })

    def test_annotated_tag(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        c2 = self.remote_real.do_commit(
            message=b'another commit',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')

        porcelain.tag_create(
            self.remote_real,
            tag=b"blah",
            author=b'author <author@example.com>',
            objectish=c2,
            tag_time=int(time.time()),
            tag_timezone=0,
            annotated=True,
            message=b"Annotated tag")

        remote = ControlDir.open(self.remote_url)
        remote_branch = remote.open_branch()
        self.assertEqual({
            'blah': default_mapping.revision_id_foreign_to_bzr(c2)},
            remote_branch.tags.get_tag_dict())

    def test_get_branch_reference(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        c2 = self.remote_real.do_commit(
            message=b'another commit',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')

        remote = ControlDir.open(self.remote_url)
        self.assertEqual(b'refs/heads/master', remote.get_branch_reference(''))
        self.assertEqual(None, remote.get_branch_reference('master'))

    def test_get_branch_nick(self):
        c1 = self.remote_real.do_commit(
            message=b'message',
            committer=b'committer <committer@example.com>',
            author=b'author <author@example.com>')
        remote = ControlDir.open(self.remote_url)
        self.assertEqual('master', remote.open_branch().nick)
