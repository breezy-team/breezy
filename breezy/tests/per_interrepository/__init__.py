# Copyright (C) 2006-2011, 2016 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""InterRepository implementation tests for bzr.

These test the conformance of all the interrepository variations to the
expected API including generally applicable corner cases.
Specific tests for individual formats are in the tests/test_repository.py file
rather than in tests/per_interrepository/*.py.
"""

import contextlib

from catalogus import pyutils

from breezy import transport
from breezy.tests import TestSkipped, default_transport, multiply_tests
from breezy.transport import FileExists

from ...bzr.vf_repository import InterDifferingSerializer
from ...errors import UninitializableFormat
from ...repository import InterRepository, format_registry
from ..per_controldir.test_controldir import TestCaseWithControlDir


def make_scenarios(transport_server, transport_readonly_server, formats):
    """Transform the input formats to a list of scenarios.

    :param formats: A list of tuples:
        (label, repository_format, repository_format_to).
    """
    result = []
    for label, repository_format, repository_format_to, extra_setup in formats:
        id = "{},{},{}".format(
            label,
            repository_format.__class__.__name__,
            repository_format_to.__class__.__name__,
        )
        scenario = (
            id,
            {
                "transport_server": transport_server,
                "transport_readonly_server": transport_readonly_server,
                "repository_format": repository_format,
                "repository_format_to": repository_format_to,
                "extra_setup": extra_setup,
            },
        )
        result.append(scenario)
    return result


def default_test_list():
    """Generate the default list of interrepo permutations to test."""
    from breezy.bzr import groupcompress_repo, knitpack_repo, knitrepo

    result = []

    def add_combo(interrepo_cls, from_format, to_format, extra_setup=None, label=None):
        if label is None:
            label = interrepo_cls.__name__
        result.append((label, from_format, to_format, extra_setup))

    # test the default InterRepository between format 6 and the current
    # default format.
    # XXX: robertc 20060220 reinstate this when there are two supported
    # formats which do not have an optimal code path between them.
    # result.append((InterRepository,
    #               RepositoryFormat6(),
    #               RepositoryFormatKnit1()))
    for optimiser_class in InterRepository.iter_optimisers():
        format_to_test = optimiser_class._get_repo_format_to_test()
        if format_to_test is not None:
            add_combo(optimiser_class, format_to_test, format_to_test)
    # if there are specific combinations we want to use, we can add them
    # here. We want to test rich root upgrading.
    # XXX: although we attach InterRepository class names to these scenarios,
    # there's nothing asserting that these labels correspond to what is
    # actually used.

    def force_known_graph(testcase):
        from ...bzr.fetch import Inter1and2Helper

        testcase.overrideAttr(Inter1and2Helper, "known_graph_threshold", -1)

    # Gather extra scenarios from the repository implementations,
    # as InterRepositories can be used by Repository implementations
    # they aren't aware of.
    for module_name in format_registry._get_all_modules():
        module = pyutils.get_named_object(module_name)
        try:
            get_extra_interrepo_test_combinations = (
                module.get_extra_interrepo_test_combinations
            )
        except AttributeError:
            continue
        for (
            interrepo_cls,
            from_format,
            to_format,
        ) in get_extra_interrepo_test_combinations():
            add_combo(interrepo_cls, from_format, to_format)
    add_combo(
        InterRepository,
        knitrepo.RepositoryFormatKnit1(),
        knitrepo.RepositoryFormatKnit3(),
    )
    add_combo(
        knitrepo.InterKnitRepo,
        knitrepo.RepositoryFormatKnit1(),
        knitpack_repo.RepositoryFormatKnitPack1(),
    )
    add_combo(
        knitrepo.InterKnitRepo,
        knitpack_repo.RepositoryFormatKnitPack1(),
        knitrepo.RepositoryFormatKnit1(),
    )
    add_combo(
        knitrepo.InterKnitRepo,
        knitrepo.RepositoryFormatKnit3(),
        knitpack_repo.RepositoryFormatKnitPack3(),
    )
    add_combo(
        knitrepo.InterKnitRepo,
        knitpack_repo.RepositoryFormatKnitPack3(),
        knitrepo.RepositoryFormatKnit3(),
    )
    add_combo(
        knitrepo.InterKnitRepo,
        knitpack_repo.RepositoryFormatKnitPack3(),
        knitpack_repo.RepositoryFormatKnitPack4(),
    )
    add_combo(
        InterDifferingSerializer,
        knitpack_repo.RepositoryFormatKnitPack1(),
        knitpack_repo.RepositoryFormatKnitPack6RichRoot(),
    )
    add_combo(
        InterDifferingSerializer,
        knitpack_repo.RepositoryFormatKnitPack1(),
        knitpack_repo.RepositoryFormatKnitPack6RichRoot(),
        force_known_graph,
        label="InterDifferingSerializer+get_known_graph_ancestry",
    )
    add_combo(
        InterDifferingSerializer,
        knitpack_repo.RepositoryFormatKnitPack6RichRoot(),
        groupcompress_repo.RepositoryFormat2a(),
    )
    add_combo(
        InterDifferingSerializer,
        groupcompress_repo.RepositoryFormat2a(),
        knitpack_repo.RepositoryFormatKnitPack6RichRoot(),
    )
    return result


class TestCaseWithInterRepository(TestCaseWithControlDir):
    def setUp(self):
        super().setUp()
        if self.extra_setup:
            self.extra_setup(self)

    def get_default_format(self):
        self.assertEqual(
            self.repository_format._matchingcontroldir.repository_format,
            self.repository_format,
        )
        return self.repository_format._matchingcontroldir

    def make_branch(self, relpath, format=None):
        repo = self.make_repository(relpath, format=format)
        return repo.controldir.create_branch()

    def make_controldir(self, relpath, format=None):
        try:
            url = self.get_url(relpath)
            segments = url.split("/")
            if segments and segments[-1] not in ("", "."):
                parent = "/".join(segments[:-1])
                t = transport.get_transport(parent)
                with contextlib.suppress(FileExists):
                    t.mkdir(segments[-1])
            if format is None:
                format = self.repository_format._matchingcontroldir
            return format.initialize(url)
        except UninitializableFormat as err:
            raise TestSkipped(f"Format {format} is not initializable.") from err

    def make_repository(self, relpath, format=None):
        made_control = self.make_controldir(relpath, format=format)
        return self.repository_format.initialize(made_control)

    def make_to_repository(self, relpath):
        made_control = self.make_controldir(
            relpath, self.repository_format_to._matchingcontroldir
        )
        return self.repository_format_to.initialize(made_control)


def load_tests(loader, standard_tests, pattern):
    submod_tests = loader.suiteClass()
    for module_name in [
        "breezy.tests.per_interrepository.test_fetch",
        "breezy.tests.per_interrepository.test_interrepository",
    ]:
        submod_tests.addTest(loader.loadTestsFromName(module_name))
    scenarios = make_scenarios(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        default_test_list(),
    )
    return multiply_tests(submod_tests, scenarios, standard_tests)
