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

import doctest
import socket

from ... import tests
from ...tests import features
from .. import launchpad
from . import lp_api_lite
from testtools.matchers import DocTestMatches


class _JSONParserFeature(features.Feature):

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

    def assertPlace(self, place, archive, series, project):
        lp = lp_api_lite.LatestPublication(archive, series, project)
        self.assertEqual(place, lp.place())

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
        entries = content['entries']  # It should have an 'entries' field.
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

    def test_place(self):
        self.assertPlace('Ubuntu', 'ubuntu', None, 'bzr')
        self.assertPlace('Ubuntu Natty', 'ubuntu', 'natty', 'bzr')
        self.assertPlace('Ubuntu Natty Proposed', 'ubuntu', 'natty-proposed',
                         'bzr')
        self.assertPlace('Debian', 'debian', None, 'bzr')
        self.assertPlace('Debian Sid', 'debian', 'sid', 'bzr')


class TestIsUpToDate(tests.TestCase):

    def assertPackageBranchRe(self, url, user, archive, series, project):
        m = launchpad._package_branch.search(url)
        if m is None:
            self.fail('package_branch regex did not match url: %s' % (url,))
        self.assertEqual(
            (user, archive, series, project),
            m.group('user', 'archive', 'series', 'project'))

    def assertNotPackageBranch(self, url):
        self.assertIs(None, launchpad._get_package_branch_info(url))

    def assertBranchInfo(self, url, archive, series, project):
        self.assertEqual((archive, series, project),
                         launchpad._get_package_branch_info(url))

    def test_package_branch_regex(self):
        self.assertPackageBranchRe(
            'http://bazaar.launchpad.net/+branch/ubuntu/foo',
            None, 'ubuntu', None, 'foo')
        self.assertPackageBranchRe(
            'bzr+ssh://bazaar.launchpad.net/+branch/ubuntu/natty/foo',
            None, 'ubuntu', 'natty/', 'foo')
        self.assertPackageBranchRe(
            'sftp://bazaar.launchpad.net/+branch/debian/foo',
            None, 'debian', None, 'foo')
        self.assertPackageBranchRe(
            'http://bazaar.launchpad.net/+branch/debian/sid/foo',
            None, 'debian', 'sid/', 'foo')
        self.assertPackageBranchRe(
            'http://bazaar.launchpad.net/+branch'
            '/~ubuntu-branches/ubuntu/natty/foo/natty',
            '~ubuntu-branches/', 'ubuntu', 'natty/', 'foo')
        self.assertPackageBranchRe(
            'http://bazaar.launchpad.net/+branch'
            '/~user/ubuntu/natty/foo/test',
            '~user/', 'ubuntu', 'natty/', 'foo')

    def test_package_branch_doesnt_match(self):
        self.assertNotPackageBranch('http://example.com/ubuntu/foo')
        self.assertNotPackageBranch(
            'http://bazaar.launchpad.net/+branch/bzr')
        self.assertNotPackageBranch(
            'http://bazaar.launchpad.net/+branch/~bzr-pqm/bzr/bzr.dev')
        # Not a packaging branch because ~user isn't ~ubuntu-branches
        self.assertNotPackageBranch(
            'http://bazaar.launchpad.net/+branch'
            '/~user/ubuntu/natty/foo/natty')
        # Older versions of bzr-svn/hg/git did not set Branch.base until after
        # they called Branch.__init__().
        self.assertNotPackageBranch(None)

    def test__get_package_branch_info(self):
        self.assertBranchInfo(
            'bzr+ssh://bazaar.launchpad.net/+branch/ubuntu/natty/foo',
            'ubuntu', 'natty', 'foo')
        self.assertBranchInfo(
            'bzr+ssh://bazaar.launchpad.net/+branch'
            '/~ubuntu-branches/ubuntu/natty/foo/natty',
            'ubuntu', 'natty', 'foo')
        self.assertBranchInfo(
            'http://bazaar.launchpad.net/+branch'
            '/~ubuntu-branches/debian/sid/foo/sid',
            'debian', 'sid', 'foo')


class TestGetMostRecentTag(tests.TestCaseWithMemoryTransport):

    def make_simple_builder(self):
        builder = self.make_branch_builder('tip')
        builder.build_snapshot([], [
            ('add', ('', b'root-id', 'directory', None))],
            revision_id=b'A')
        b = builder.get_branch()
        b.tags.set_tag('tip-1.0', b'A')
        return builder, b, b.tags.get_tag_dict()

    def test_get_most_recent_tag_tip(self):
        builder, b, tag_dict = self.make_simple_builder()
        self.assertEqual('tip-1.0',
                         lp_api_lite.get_most_recent_tag(tag_dict, b))

    def test_get_most_recent_tag_older(self):
        builder, b, tag_dict = self.make_simple_builder()
        builder.build_snapshot([b'A'], [], revision_id=b'B')
        self.assertEqual(b'B', b.last_revision())
        self.assertEqual('tip-1.0',
                         lp_api_lite.get_most_recent_tag(tag_dict, b))


class StubLatestPublication(object):

    def __init__(self, latest):
        self.called = False
        self.latest = latest

    def get_latest_version(self):
        self.called = True
        return self.latest

    def place(self):
        return 'Ubuntu Natty'


class TestReportFreshness(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        super(TestReportFreshness, self).setUp()
        builder = self.make_branch_builder('tip')
        builder.build_snapshot([], [
            ('add', ('', b'root-id', 'directory', None))],
            revision_id=b'A')
        self.branch = builder.get_branch()

    def assertFreshnessReports(self, verbosity, latest_version, content):
        """Assert that lp_api_lite.report_freshness reports the given content.

        :param verbosity: The reporting level
        :param latest_version: The version reported by StubLatestPublication
        :param content: The expected content. This should be in DocTest form.
        """
        orig_log_len = len(self.get_log())
        lp_api_lite.report_freshness(self.branch, verbosity,
                                     StubLatestPublication(latest_version))
        new_content = self.get_log()[orig_log_len:]
        # Strip out lines that have LatestPublication.get_* because those are
        # timing related lines. While interesting to log for now, they aren't
        # something we want to be testing
        new_content = new_content.split('\n')
        for i in range(2):
            if (len(new_content) > 0
                    and 'LatestPublication.get_' in new_content[0]):
                new_content = new_content[1:]
        new_content = '\n'.join(new_content)
        self.assertThat(new_content,
                        DocTestMatches(content,
                                       doctest.ELLIPSIS | doctest.REPORT_UDIFF))

    def test_verbosity_off_skips_check(self):
        # We force _get_package_branch_info so that we know it would otherwise
        # try to connect to launcphad
        self.overrideAttr(launchpad, '_get_package_branch_info',
                          lambda x: ('ubuntu', 'natty', 'bzr'))
        self.overrideAttr(lp_api_lite, 'LatestPublication',
                          lambda *args: self.fail('Tried to query launchpad'))
        c = self.branch.get_config_stack()
        c.set('launchpad.packaging_verbosity', 'off')
        orig_log_len = len(self.get_log())
        launchpad._check_is_up_to_date(self.branch)
        new_content = self.get_log()[orig_log_len:]
        self.assertContainsRe(new_content,
                              'not checking memory.*/tip/ because verbosity is turned off')

    def test_verbosity_off(self):
        latest_pub = StubLatestPublication('1.0-1ubuntu2')
        lp_api_lite.report_freshness(self.branch, 'off', latest_pub)
        self.assertFalse(latest_pub.called)

    def test_verbosity_all_out_of_date_smoke(self):
        self.branch.tags.set_tag('1.0-1ubuntu1', b'A')
        self.assertFreshnessReports('all', '1.0-1ubuntu2',
                                    '    INFO  Most recent Ubuntu Natty version: 1.0-1ubuntu2\n'
                                    'Packaging branch version: 1.0-1ubuntu1\n'
                                    'Packaging branch status: OUT-OF-DATE\n')


class Test_GetNewestVersions(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        super(Test_GetNewestVersions, self).setUp()
        builder = self.make_branch_builder('tip')
        builder.build_snapshot([], [
            ('add', ('', b'root-id', 'directory', None))],
            revision_id=b'A')
        self.branch = builder.get_branch()

    def assertLatestVersions(self, latest_branch_version, pub_version):
        if latest_branch_version is not None:
            self.branch.tags.set_tag(latest_branch_version, b'A')
        latest_pub = StubLatestPublication(pub_version)
        self.assertEqual((pub_version, latest_branch_version),
                         lp_api_lite._get_newest_versions(self.branch, latest_pub))

    def test_no_tags(self):
        self.assertLatestVersions(None, '1.0-1ubuntu2')

    def test_out_of_date(self):
        self.assertLatestVersions('1.0-1ubuntu1', '1.0-1ubuntu2')

    def test_up_to_date(self):
        self.assertLatestVersions('1.0-1ubuntu2', '1.0-1ubuntu2')

    def test_missing(self):
        self.assertLatestVersions(None, None)


class Test_ReportFreshness(tests.TestCase):

    def assertReportedFreshness(self, verbosity, latest_ver, branch_latest_ver,
                                content, place='Ubuntu Natty'):
        """Assert that lp_api_lite.report_freshness reports the given content.
        """
        reported = []

        def report_func(value):
            reported.append(value)

        lp_api_lite._report_freshness(latest_ver, branch_latest_ver, place,
                                      verbosity, report_func)
        new_content = '\n'.join(reported)
        self.assertThat(new_content,
                        DocTestMatches(content,
                                       doctest.ELLIPSIS | doctest.REPORT_UDIFF))

    def test_verbosity_minimal_no_tags(self):
        self.assertReportedFreshness('minimal', '1.0-1ubuntu2', None,
                                     'Branch is OUT-OF-DATE, Ubuntu Natty has 1.0-1ubuntu2\n')

    def test_verbosity_minimal_out_of_date(self):
        self.assertReportedFreshness('minimal', '1.0-1ubuntu2', '1.0-1ubuntu1',
                                     '1.0-1ubuntu1 is OUT-OF-DATE,'
                                     ' Ubuntu Natty has 1.0-1ubuntu2\n')

    def test_verbosity_minimal_up_to_date(self):
        self.assertReportedFreshness('minimal', '1.0-1ubuntu2', '1.0-1ubuntu2',
                                     '')

    def test_verbosity_minimal_missing(self):
        self.assertReportedFreshness('minimal', None, None,
                                     '')

    def test_verbosity_short_out_of_date(self):
        self.assertReportedFreshness('short', '1.0-1ubuntu2', '1.0-1ubuntu1',
                                     '1.0-1ubuntu1 is OUT-OF-DATE,'
                                     ' Ubuntu Natty has 1.0-1ubuntu2\n')

    def test_verbosity_short_up_to_date(self):
        self.assertReportedFreshness('short', '1.0-1ubuntu2', '1.0-1ubuntu2',
                                     '1.0-1ubuntu2 is CURRENT in Ubuntu Natty')

    def test_verbosity_short_missing(self):
        self.assertReportedFreshness('short', None, None,
                                     'Ubuntu Natty is MISSING a version')

    def test_verbosity_all_no_tags(self):
        self.assertReportedFreshness('all', '1.0-1ubuntu2', None,
                                     'Most recent Ubuntu Natty version: 1.0-1ubuntu2\n'
                                     'Packaging branch version: None\n'
                                     'Packaging branch status: OUT-OF-DATE\n')

    def test_verbosity_all_out_of_date(self):
        self.assertReportedFreshness('all', '1.0-1ubuntu2', '1.0-1ubuntu1',
                                     'Most recent Ubuntu Natty version: 1.0-1ubuntu2\n'
                                     'Packaging branch version: 1.0-1ubuntu1\n'
                                     'Packaging branch status: OUT-OF-DATE\n')

    def test_verbosity_all_up_to_date(self):
        self.assertReportedFreshness('all', '1.0-1ubuntu2', '1.0-1ubuntu2',
                                     'Most recent Ubuntu Natty version: 1.0-1ubuntu2\n'
                                     'Packaging branch status: CURRENT\n')

    def test_verbosity_all_missing(self):
        self.assertReportedFreshness('all', None, None,
                                     'Most recent Ubuntu Natty version: MISSING\n')

    def test_verbosity_None_is_all(self):
        self.assertReportedFreshness(None, '1.0-1ubuntu2', '1.0-1ubuntu2',
                                     'Most recent Ubuntu Natty version: 1.0-1ubuntu2\n'
                                     'Packaging branch status: CURRENT\n')
