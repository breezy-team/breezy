# Copyright (C) 2011 Canonical Ltd
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

"""Tools for dealing with the Launchpad API without using launchpadlib.
"""

import socket

from bzrlib import tests
from bzrlib.plugins import launchpad
from bzrlib.plugins.launchpad import lp_api_lite

class _JSONParserFeature(tests.Feature):

    def _probe(self):
        return lp_api_lite.json is not None

    def feature_name(self):
        return 'simplejson or json'

JSONParserFeature = _JSONParserFeature()

_example_response = r"""
{
    "total_size": 2,
    "start": 0,
    "next_collection_link": "https://api.launchpad.net/1.0/ubuntu/+archive/primary?distro_series=%2Fubuntu%2Flucid&exact_match=true&source_name=%22bzr%22&status=Published&ws.op=getPublishedSources&ws.start=1&ws.size=1",
    "entries": [
        {
            "package_creator_link": "https://api.launchpad.net/1.0/~maxb",
            "package_signer_link": "https://api.launchpad.net/1.0/~jelmer",
            "source_package_name": "bzr",
            "removal_comment": null,
            "display_name": "bzr 2.1.4-0ubuntu1 in lucid",
            "date_made_pending": null,
            "source_package_version": "2.1.4-0ubuntu1",
            "date_superseded": null,
            "http_etag": "\"9ba966152dec474dc0fe1629d0bbce2452efaf3b-5f4c3fbb3eaf26d502db4089777a9b6a0537ffab\"",
            "self_link": "https://api.launchpad.net/1.0/ubuntu/+archive/primary/+sourcepub/1750327",
            "distro_series_link": "https://api.launchpad.net/1.0/ubuntu/lucid",
            "component_name": "main",
            "status": "Published",
            "date_removed": null,
            "pocket": "Updates",
            "date_published": "2011-05-30T06:09:58.653984+00:00",
            "removed_by_link": null,
            "section_name": "devel",
            "resource_type_link": "https://api.launchpad.net/1.0/#source_package_publishing_history",
            "archive_link": "https://api.launchpad.net/1.0/ubuntu/+archive/primary",
            "package_maintainer_link": "https://api.launchpad.net/1.0/~ubuntu-devel-discuss-lists",
            "date_created": "2011-05-30T05:19:12.233621+00:00",
            "scheduled_deletion_date": null
        }
    ]
}"""

_no_versions_response = '{"total_size": 0, "start": 0, "entries": []}'


class TestLatestPublication(tests.TestCase):

    def make_latest_publication(self, archive='ubuntu', series='natty',
                                project='bzr'):
        return lp_api_lite.LatestPublication(archive, series, project)

    def test_init(self):
        latest_pub = self.make_latest_publication()
        self.assertEqual('ubuntu', latest_pub._archive)
        self.assertEqual('natty', latest_pub._series)
        self.assertEqual('bzr', latest_pub._project)
        self.assertEqual('Release', latest_pub._pocket)

    def test__archive_URL(self):
        latest_pub = self.make_latest_publication()
        self.assertEqual(
            'https://api.launchpad.net/1.0/ubuntu/+archive/primary',
            latest_pub._archive_URL())

    def test__publication_status_for_ubuntu(self):
        latest_pub = self.make_latest_publication()
        self.assertEqual('Published', latest_pub._publication_status())

    def test__publication_status_for_debian(self):
        latest_pub = self.make_latest_publication(archive='debian')
        self.assertEqual('Pending', latest_pub._publication_status())

    def test_pocket(self):
        latest_pub = self.make_latest_publication(series='natty-proposed')
        self.assertEqual('natty', latest_pub._series)
        self.assertEqual('Proposed', latest_pub._pocket)

    def test_series_None(self):
        latest_pub = self.make_latest_publication(series=None)
        self.assertEqual('ubuntu', latest_pub._archive)
        self.assertEqual(None, latest_pub._series)
        self.assertEqual('bzr', latest_pub._project)
        self.assertEqual('Release', latest_pub._pocket)

    def test__query_params(self):
        latest_pub = self.make_latest_publication()
        self.assertEqual({'ws.op': 'getPublishedSources',
                          'exact_match': 'true',
                          'source_name': '"bzr"',
                          'status': 'Published',
                          'ws.size': '1',
                          'distro_series': '/ubuntu/natty',
                          'pocket': 'Release',
                         }, latest_pub._query_params())

    def test__query_params_no_series(self):
        latest_pub = self.make_latest_publication(series=None)
        self.assertEqual({'ws.op': 'getPublishedSources',
                          'exact_match': 'true',
                          'source_name': '"bzr"',
                          'status': 'Published',
                          'ws.size': '1',
                          'pocket': 'Release',
                         }, latest_pub._query_params())

    def test__query_params_pocket(self):
        latest_pub = self.make_latest_publication(series='natty-proposed')
        self.assertEqual({'ws.op': 'getPublishedSources',
                          'exact_match': 'true',
                          'source_name': '"bzr"',
                          'status': 'Published',
                          'ws.size': '1',
                          'distro_series': '/ubuntu/natty',
                          'pocket': 'Proposed',
                         }, latest_pub._query_params())

    def test__query_URL(self):
        latest_pub = self.make_latest_publication()
        # we explicitly sort params, so we can be sure this URL matches exactly
        self.assertEqual(
            'https://api.launchpad.net/1.0/ubuntu/+archive/primary'
            '?distro_series=%2Fubuntu%2Fnatty&exact_match=true'
            '&pocket=Release&source_name=%22bzr%22&status=Published'
            '&ws.op=getPublishedSources&ws.size=1',
            latest_pub._query_URL())

    def DONT_test__gracefully_handle_failed_rpc_connection(self):
        # TODO: This test kind of sucks. We intentionally create an arbitrary
        #       port and don't listen to it, because we want the request to fail.
        #       However, it seems to take 1s for it to timeout. Is there a way
        #       to make it fail faster?
        latest_pub = self.make_latest_publication()
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        addr, port = s.getsockname()
        latest_pub.LP_API_ROOT = 'http://%s:%s/' % (addr, port)
        s.close()
        self.assertIs(None, latest_pub._get_lp_info())

    def DONT_test__query_launchpad(self):
        # TODO: This is a test that we are making a valid request against
        #       launchpad. This seems important, but it is slow, requires net
        #       access, and requires launchpad to be up and running. So for
        #       now, it is commented out for production tests.
        latest_pub = self.make_latest_publication()
        json_txt = latest_pub._get_lp_info()
        self.assertIsNot(None, json_txt)
        if lp_api_lite.json is None:
            # We don't have a way to parse the text
            return
        # The content should be a valid json result
        content = lp_api_lite.json.loads(json_txt)
        entries = content['entries'] # It should have an 'entries' field.
        # ws.size should mean we get 0 or 1, and there should be something
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertEqual('bzr', entry['source_package_name'])
        version = entry['source_package_version']
        self.assertIsNot(None, version)

    def test__get_lp_info_no_json(self):
        # If we can't parse the json, we don't make the query.
        self.overrideAttr(lp_api_lite, 'json', None)
        latest_pub = self.make_latest_publication()
        self.assertIs(None, latest_pub._get_lp_info())

    def test__parse_json_info_no_module(self):
        # If a json parsing module isn't available, we just return None here.
        self.overrideAttr(lp_api_lite, 'json', None)
        latest_pub = self.make_latest_publication()
        self.assertIs(None, latest_pub._parse_json_info(_example_response))

    def test__parse_json_example_response(self):
        self.requireFeature(JSONParserFeature)
        latest_pub = self.make_latest_publication()
        content = latest_pub._parse_json_info(_example_response)
        self.assertIsNot(None, content)
        self.assertEqual(2, content['total_size'])
        entries = content['entries']
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertEqual('bzr', entry['source_package_name'])
        self.assertEqual("2.1.4-0ubuntu1", entry["source_package_version"])

    def test__parse_json_not_json(self):
        self.requireFeature(JSONParserFeature)
        latest_pub = self.make_latest_publication()
        self.assertIs(None, latest_pub._parse_json_info('Not_valid_json'))

    def test_get_latest_version_no_response(self):
        latest_pub = self.make_latest_publication()
        latest_pub._get_lp_info = lambda: None
        self.assertEqual(None, latest_pub.get_latest_version())

    def test_get_latest_version_no_json(self):
        self.overrideAttr(lp_api_lite, 'json', None)
        latest_pub = self.make_latest_publication()
        self.assertEqual(None, latest_pub.get_latest_version())

    def test_get_latest_version_invalid_json(self):
        self.requireFeature(JSONParserFeature)
        latest_pub = self.make_latest_publication()
        latest_pub._get_lp_info = lambda: "not json"
        self.assertEqual(None, latest_pub.get_latest_version())

    def test_get_latest_version_no_versions(self):
        self.requireFeature(JSONParserFeature)
        latest_pub = self.make_latest_publication()
        latest_pub._get_lp_info = lambda: _no_versions_response
        self.assertEqual(None, latest_pub.get_latest_version())

    def test_get_latest_version_missing_entries(self):
        # Launchpad's no-entries response does have an empty entries value.
        # However, lets test that we handle other failures without tracebacks
        self.requireFeature(JSONParserFeature)
        latest_pub = self.make_latest_publication()
        latest_pub._get_lp_info = lambda: '{}'
        self.assertEqual(None, latest_pub.get_latest_version())

    def test_get_latest_version_invalid_entries(self):
        # Make sure we sanely handle a json response we don't understand
        self.requireFeature(JSONParserFeature)
        latest_pub = self.make_latest_publication()
        latest_pub._get_lp_info = lambda: '{"entries": {"a": 1}}'
        self.assertEqual(None, latest_pub.get_latest_version())

    def test_get_latest_version_example(self):
        self.requireFeature(JSONParserFeature)
        latest_pub = self.make_latest_publication()
        latest_pub._get_lp_info = lambda: _example_response
        self.assertEqual("2.1.4-0ubuntu1", latest_pub.get_latest_version())

    def DONT_test_get_latest_version_from_launchpad(self):
        self.requireFeature(JSONParserFeature)
        latest_pub = self.make_latest_publication()
        self.assertIsNot(None, latest_pub.get_latest_version())


class TestIsUpToDate(tests.TestCase):

    def assertPackageBranchRe(self, url, user, archive, series, project):
        m = launchpad.package_branch.search(url)
        if m is None:
            self.fail('package_branch regex did not match url: %s' % (url,))
        self.assertEqual(
            (user, archive, series, project),
            m.group('user', 'archive', 'series', 'project'))

    def test_package_branch_regex(self):
        self.assertPackageBranchRe(
            'http://bazaar.launchpad.net/+branch/ubuntu/foo',
            None, 'ubuntu', None, 'foo')
