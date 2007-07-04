# Copyright (C) 2006 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
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


"""InterVersioned implementation tests for bzr.

These test the conformance of all the interversionedfile variations to the
expected API including generally applicable corner cases.
Specific tests for individual cases are in the tests/test_versionedfile.py file 
rather than in tests/interversionedfile_implementations/*.py.
"""

from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestLoader,
                          TestScenarioApplier,
                          TestSuite,
                          )


class InterVersionedFileTestProviderAdapter(TestScenarioApplier):
    """A tool to generate a suite testing multiple inter versioned-file classes.

    This is done by copying the test once for each InterVersionedFile provider
    and injecting the transport_server, transport_readonly_server,
    versionedfile_factory and versionedfile_factory_to classes into each copy.
    Each copy is also given a new id() to make it easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self.scenarios = self.formats_to_scenarios(formats)
    
    def formats_to_scenarios(self, formats):
        """Transform the input formats to a list of scenarios.

        :param formats: A list of tuples:
            (interversionedfile_class, versionedfile_factory,
             versionedfile_factory_to).
        """
        result = []
        for (interversionedfile_class,
             versionedfile_factory,
             versionedfile_factory_to) in formats:
            scenario = (interversionedfile_class.__name__, {
                "transport_server":self._transport_server,
                "transport_readonly_server":self._transport_readonly_server,
                "interversionedfile_class":interversionedfile_class,
                "versionedfile_factory":versionedfile_factory,
                "versionedfile_factory_to":versionedfile_factory_to,
                })
            result.append(scenario)
        return result

    @staticmethod
    def default_test_list():
        """Generate the default list of interversionedfile permutations to test."""
        from bzrlib.versionedfile import InterVersionedFile
        from bzrlib.weave import WeaveFile
        from bzrlib.knit import KnitVersionedFile
        result = []
        # test the fallback InterVersionedFile from annotated knits to weave
        result.append((InterVersionedFile,
                       KnitVersionedFile,
                       WeaveFile))
        for optimiser in InterVersionedFile._optimisers:
            result.append((optimiser,
                           optimiser._matching_file_from_factory,
                           optimiser._matching_file_to_factory
                           ))
        # if there are specific combinations we want to use, we can add them 
        # here.
        return result


def test_suite():
    result = TestSuite()
    test_interversionedfile_implementations = [
        'bzrlib.tests.interversionedfile_implementations.test_join',
        ]
    adapter = InterVersionedFileTestProviderAdapter(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        InterVersionedFileTestProviderAdapter.default_test_list()
        )
    loader = TestLoader()
    adapt_modules(test_interversionedfile_implementations, adapter, loader, result)
    return result
