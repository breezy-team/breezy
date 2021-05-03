# Copyright (C) 2019 Breezy Developers
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

import os

from ..propose import (
    determine_title,
    get_proposal_by_url,
    get_hoster,
    Hoster,
    MergeProposal,
    UnsupportedHoster,
    )
from .. import (
    propose as _mod_propose,
    registry,
    urlutils,
    )

from .. import (
    tests,
    )


class SampleMergeProposal(MergeProposal):
    """Sample merge proposal."""


class SampleHoster(Hoster):

    _locations = []

    @classmethod
    def _add_location(cls, url):
        cls._locations.append(url)

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        for b in cls._locations:
            if url.startswith(b):
                return cls()
        raise UnsupportedHoster(url)

    def hosts(self, branch):
        for b in self._locations:
            if branch.user_url.startswith(b):
                return True
        return False

    @classmethod
    def iter_instances(cls):
        return iter([cls()])

    def get_proposal_by_url(self, url):
        for b in self._locations:
            if url.startswith(b):
                return MergeProposal()
        raise UnsupportedHoster(url)


class SampleHosterTestCase(tests.TestCaseWithTransport):

    def setUp(self):
        super(SampleHosterTestCase, self).setUp()
        self._old_hosters = _mod_propose.hosters
        _mod_propose.hosters = registry.Registry()
        self.hoster = SampleHoster()
        os.mkdir('hosted')
        SampleHoster._add_location(
            urlutils.local_path_to_url(os.path.join(self.test_dir, 'hosted')))
        _mod_propose.hosters.register('sample', self.hoster)

    def tearDown(self):
        super(SampleHosterTestCase, self).tearDown()
        _mod_propose.hosters = self._old_hosters
        SampleHoster._locations = []


class TestGetHosterTests(SampleHosterTestCase):

    def test_get_hoster(self):
        tree = self.make_branch_and_tree('hosted/branch')
        self.assertIs(self.hoster, get_hoster(tree.branch, [self.hoster]))
        self.assertIsInstance(get_hoster(tree.branch), SampleHoster)

        tree = self.make_branch_and_tree('blah')
        self.assertRaises(UnsupportedHoster, get_hoster, tree.branch)


class TestGetProposal(SampleHosterTestCase):

    def test_get_proposal_by_url(self):
        self.assertRaises(UnsupportedHoster, get_proposal_by_url, 'blah')

        url = urlutils.local_path_to_url(os.path.join(self.test_dir, 'hosted', 'proposal'))
        self.assertIsInstance(get_proposal_by_url(url), MergeProposal)


class DetermineTitleTests(tests.TestCase):

    def test_determine_title(self):
        self.assertEqual('Make some change', determine_title("""\
Make some change.

And here are some more details.
"""))
        self.assertEqual('Make some change', determine_title("""\
Make some change. And another one.

With details.
"""))
        self.assertEqual('Release version 5.1', determine_title("""\
Release version 5.1

And here are some more details.
"""))
        self.assertEqual('Release version 5.1', determine_title("""\

Release version 5.1

And here are some more details.
"""))
