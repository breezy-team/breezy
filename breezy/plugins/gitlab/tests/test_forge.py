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

import os
from datetime import datetime

from breezy import bedding, errors
from breezy.tests import TestCase, TestCaseInTempDir

from ..forge import (
    NotGitLabUrl,
    NotMergeRequestUrl,
    iter_tokens,
    parse_gitlab_merge_request_url,
    parse_timestring,
)


class ParseGitLabMergeRequestUrlTests(TestCase):
    def test_invalid(self):
        self.assertRaises(
            NotMergeRequestUrl,
            parse_gitlab_merge_request_url,
            "https://salsa.debian.org/",
        )
        self.assertRaises(
            NotGitLabUrl, parse_gitlab_merge_request_url, "bzr://salsa.debian.org/"
        )
        self.assertRaises(
            NotGitLabUrl, parse_gitlab_merge_request_url, "https:///salsa.debian.org/"
        )
        self.assertRaises(
            NotMergeRequestUrl,
            parse_gitlab_merge_request_url,
            "https://salsa.debian.org/jelmer/salsa",
        )

    def test_old_style(self):
        self.assertEqual(
            ("salsa.debian.org", "jelmer/salsa", 4),
            parse_gitlab_merge_request_url(
                "https://salsa.debian.org/jelmer/salsa/merge_requests/4"
            ),
        )

    def test_new_style(self):
        self.assertEqual(
            ("salsa.debian.org", "jelmer/salsa", 4),
            parse_gitlab_merge_request_url(
                "https://salsa.debian.org/jelmer/salsa/-/merge_requests/4"
            ),
        )


class ParseTimestringTests(TestCase):
    def test_simple(self):
        self.assertEqual(
            datetime(2018, 9, 7, 11, 16, 17, 520000),
            parse_timestring("2018-09-07T11:16:17.520Z"),
        )


class IterTokensTests(TestCaseInTempDir):
    def test_unparseable_gitlab_conf_is_a_user_error(self):
        bedding.ensure_config_dir_exists()
        with open(os.path.join(bedding.config_dir(), "gitlab.conf"), "w") as f:
            f.write("url = https://salsa.debian.org/\n")
        e = self.assertRaises(errors.BzrError, list, iter_tokens())
        self.assertContainsRe(str(e), r"gitlab\.conf")

    def test_unparseable_python_gitlab_cfg_is_a_user_error(self):
        path = os.path.expanduser("~/.python-gitlab.cfg")
        with open(path, "w") as f:
            f.write("url = https://salsa.debian.org/\n")
        e = self.assertRaises(errors.BzrError, list, iter_tokens())
        self.assertIn(path, str(e))
