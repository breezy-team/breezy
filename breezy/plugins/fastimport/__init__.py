# Copyright (C) 2008-2011 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

r"""FastImport Plugin
=================

The fastimport plugin provides stream-based importing and exporting of
data into and out of Bazaar. As well as enabling interchange between
multiple VCS tools, fastimport/export can be useful for complex branch
operations, e.g. partitioning off part of a code base in order to Open
Source it.

The normal import recipe is::

  front-end > project.fi
  bzr fast-import project.fi project.bzr

In either case, if you wish to save disk space, project.fi can be
compressed to gzip format after it is generated like this::

  (generate project.fi)
  gzip project.fi
  bzr fast-import project.fi.gz project.bzr

The list of known front-ends and their status is documented on
http://bazaar-vcs.org/BzrFastImport/FrontEnds.

Once a fast-import dump file is created, it can be imported into a
Bazaar repository using the fast-import command. If required, you can
manipulate the stream first using the fast-import-filter command.
This is useful for creating a repository with just part of a project
or for removing large old binaries (say) from history that are no longer
valuable to retain. For further details on importing, manipulating and
reporting on fast-import streams, see the online help for the commands::

  bzr help fast-import

Finally, you may wish to generate a fast-import dump file from a Bazaar
repository. The fast-export command is provided for that purpose.

To report bugs or publish enhancements, visit the bzr-fastimport project
page on Launchpad, https://launchpad.net/bzr-fastimport.
"""

from ... import version_info  # noqa: F401
from ...commands import plugin_cmds


def load_fastimport():
    """Load the fastimport module or raise an appropriate exception."""
    try:
        import fastimport
    except ModuleNotFoundError:
        from ...errors import DependencyNotPresent

        raise DependencyNotPresent(
            "fastimport", "fastimport requires the fastimport python module"
        )
    if fastimport.__version__ < (0, 9, 8):
        from ...errors import DependencyNotPresent

        raise DependencyNotPresent(
            "fastimport",
            "fastimport requires at least version 0.9.8 of the "
            "fastimport python module",
        )


def test_suite():
    from . import tests

    return tests.test_suite()


for name in [
    "fast_import",
    "fast_export",
]:
    plugin_cmds.register_lazy("cmd_%s" % name, [], "breezy.plugins.fastimport.cmds")
