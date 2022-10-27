# Copyright (C) 2020 Jelmer Vernooij <jelmer@jelmer.uk>
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

from breezy.tests import TestCase

from breezy.plugins.gitlab.forge import (
    parse_gitlab_merge_request_url,
    NotMergeRequestUrl,
    NotGitLabUrl,
    )


class ParseGitLabMergeRequestUrlTests(TestCase):

    def test_invalid(self):
        self.assertRaises(
            NotMergeRequestUrl, parse_gitlab_merge_request_url,
            "https://salsa.debian.org/")
        self.assertRaises(
            NotGitLabUrl, parse_gitlab_merge_request_url,
            "bzr://salsa.debian.org/")
        self.assertRaises(
            NotGitLabUrl, parse_gitlab_merge_request_url,
            "https:///salsa.debian.org/")
        self.assertRaises(
            NotMergeRequestUrl, parse_gitlab_merge_request_url,
            "https://salsa.debian.org/jelmer/salsa")

    def test_old_style(self):
        self.assertEqual(
            ('salsa.debian.org', 'jelmer/salsa', 4),
            parse_gitlab_merge_request_url(
                'https://salsa.debian.org/jelmer/salsa/merge_requests/4'))

    def test_new_style(self):
        self.assertEqual(
            ('salsa.debian.org', 'jelmer/salsa', 4),
            parse_gitlab_merge_request_url(
                'https://salsa.debian.org/jelmer/salsa/-/merge_requests/4'))
