# Copyright (C) 2006 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
# -*- coding: utf-8 -*-
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


"""InterRepository implementation tests for bzr.

These test the conformance of all the interrepository variations to the
expected API including generally applicable corner cases.
Specific tests for individual formats are in the tests/test_repository.py file 
rather than in tests/interrepository_implementations/*.py.
"""


from bzrlib.errors import (
    FileExists,
    UninitializableFormat,
    )

from bzrlib.repository import (
                               InterKnitRepo,
                               InterKnit1and2,
                               InterModel1and2,
                               InterRepository,
                               )
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestScenarioApplier,
                          )
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.transport import get_transport


class InterRepositoryTestProviderAdapter(TestScenarioApplier):
    """A tool to generate a suite testing multiple inter repository formats.

    This is done by copying the test once for each interrepo provider and injecting
    the transport_server, transport_readonly_server, repository_format and 
    repository_to_format classes into each copy.
    Each copy is also given a new id() to make it easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        TestScenarioApplier.__init__(self)
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self.scenarios = self.formats_to_scenarios(formats)
    
    def formats_to_scenarios(self, formats):
        """Transform the input formats to a list of scenarios.

        :param formats: A list of tuples:
            (interrepo_class, repository_format, repository_format_to).
        """
        result = []
        for interrepo_class, repository_format, repository_format_to in formats:
            id = '%s,%s,%s' % (interrepo_class.__name__,
                                repository_format.__class__.__name__,
                                repository_format_to.__class__.__name__)
            scenario = (id,
                {"transport_server":self._transport_server,
                 "transport_readonly_server":self._transport_readonly_server,
                 "repository_format":repository_format,
                 "interrepo_class":interrepo_class,
                 "repository_format_to":repository_format_to,
                 })
            result.append(scenario)
        return result
    
    @staticmethod
    def default_test_list():
        """Generate the default list of interrepo permutations to test."""
        from bzrlib.repofmt import knitrepo, pack_repo, weaverepo
        result = []
        # test the default InterRepository between format 6 and the current 
        # default format.
        # XXX: robertc 20060220 reinstate this when there are two supported
        # formats which do not have an optimal code path between them.
        #result.append((InterRepository,
        #               RepositoryFormat6(),
        #               RepositoryFormatKnit1()))
        for optimiser_class in InterRepository._optimisers:
            format_to_test = optimiser_class._get_repo_format_to_test()
            if format_to_test is not None:
                result.append((optimiser_class,
                               format_to_test, format_to_test))
        # if there are specific combinations we want to use, we can add them 
        # here.
        result.append((InterModel1and2,
                       weaverepo.RepositoryFormat5(),
                       knitrepo.RepositoryFormatKnit3()))
        result.append((InterModel1and2,
                       knitrepo.RepositoryFormatKnit1(),
                       knitrepo.RepositoryFormatKnit3()))
        result.append((InterKnit1and2,
                       knitrepo.RepositoryFormatKnit1(),
                       knitrepo.RepositoryFormatKnit3()))
        result.append((InterKnitRepo,
                       knitrepo.RepositoryFormatKnit1(),
                       pack_repo.RepositoryFormatKnitPack1()))
        result.append((InterKnitRepo,
                       pack_repo.RepositoryFormatKnitPack1(),
                       knitrepo.RepositoryFormatKnit1()))
        result.append((InterKnitRepo,
                       knitrepo.RepositoryFormatKnit3(),
                       pack_repo.RepositoryFormatKnitPack3()))
        result.append((InterKnitRepo,
                       pack_repo.RepositoryFormatKnitPack3(),
                       knitrepo.RepositoryFormatKnit3()))
        return result


class TestCaseWithInterRepository(TestCaseWithBzrDir):

    def setUp(self):
        super(TestCaseWithInterRepository, self).setUp()

    def make_branch(self, relpath, format=None):
        repo = self.make_repository(relpath, format=format)
        return repo.bzrdir.create_branch()

    def make_bzrdir(self, relpath, format=None):
        try:
            url = self.get_url(relpath)
            segments = url.split('/')
            if segments and segments[-1] not in ('', '.'):
                parent = '/'.join(segments[:-1])
                t = get_transport(parent)
                try:
                    t.mkdir(segments[-1])
                except FileExists:
                    pass
            if format is None:
                format = self.repository_format._matchingbzrdir
            return format.initialize(url)
        except UninitializableFormat:
            raise TestSkipped("Format %s is not initializable." % format)

    def make_repository(self, relpath, format=None):
        made_control = self.make_bzrdir(relpath, format=format)
        return self.repository_format.initialize(made_control)

    def make_to_repository(self, relpath):
        made_control = self.make_bzrdir(relpath,
            self.repository_format_to._matchingbzrdir)
        return self.repository_format_to.initialize(made_control)


def load_tests(basic_tests, module, loader):
    result = loader.suiteClass()
    # add the tests for this module
    result.addTests(basic_tests)

    test_interrepository_implementations = [
        'bzrlib.tests.interrepository_implementations.test_fetch',
        'bzrlib.tests.interrepository_implementations.test_interrepository',
        ]
    adapter = InterRepositoryTestProviderAdapter(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        InterRepositoryTestProviderAdapter.default_test_list()
        )
    # add the tests for the sub modules
    adapt_modules(test_interrepository_implementations, adapter, loader, result)
    return result
