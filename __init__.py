# Copyright (C) 2008 Canonical Ltd
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

r"""FastImport Plugin
=================

The fastimport plugin provides stream-based importing and exporting of
data into and out of Bazaar. As well as enabling interchange between
multiple VCS tools, fastimport/export can be useful for complex branch
operations, e.g. partitioning off part of a code base in order to Open
Source it.

The normal import recipe is::

  bzr fast-export-from-xxx SOURCE project.fi
  bzr fast-import project.fi project.bzr

If fast-export-from-xxx doesn't exist yet for the tool you're importing
from, the alternative recipe is::

  front-end > project.fi
  bzr fast-import project.fi project.bzr

In either case, if you wish to save disk space, project.fi can be
compressed to gzip format after it is generated like this::

  (generate project.fi)
  gzip project.fi
  bzr fast-import project.fi.gz project.bzr

The list of known front-ends and their status is documented on
http://bazaar-vcs.org/BzrFastImport/FrontEnds. The fast-export-from-xxx
commands provide simplified access to these so that the majority of users
can generate a fast-import dump file without needing to study up on all
the options - and the best combination of them to use - for the front-end
relevant to them. In some cases, a fast-export-from-xxx wrapper will require
that certain dependencies are installed so it checks for these before
starting. A wrapper may also provide a limited set of options. See the
online help for the individual commands for details::

  bzr help fast-export-from-cvs
  bzr help fast-export-from-darcs
  bzr help fast-export-from-hg
  bzr help fast-export-from-git
  bzr help fast-export-from-mtn
  bzr help fast-export-from-p4
  bzr help fast-export-from-svn

Once a fast-import dump file is created, it can be imported into a
Bazaar repository using the fast-import command. If required, you can
manipulate the stream first using the fast-import-filter command.
This is useful for creating a repository with just part of a project
or for removing large old binaries (say) from history that are no longer
valuable to retain. For further details on importing, manipulating and
reporting on fast-import streams, see the online help for the commands::

  bzr help fast-import
  bzr help fast-import-filter
  bzr help fast-import-info
  bzr help fast-import-query

Finally, you may wish to generate a fast-import dump file from a Bazaar
repository. The fast-export command is provided for that purpose.

To report bugs or publish enhancements, visit the bzr-fastimport project
page on Launchpad, https://launchpad.net/bzr-fastimport.
"""

from info import (
    bzr_plugin_version as version_info,
    )

from bzrlib.commands import plugin_cmds


def load_fastimport():
    """Load the fastimport module or raise an appropriate exception."""
    try:
        import fastimport
    except ImportError, e:
        from bzrlib.errors import DependencyNotPresent
        raise DependencyNotPresent("fastimport",
            "bzr-fastimport requires the fasimport python module")


def test_suite():
    import tests
    return tests.test_suite()


for name in [
        "fast_import",
        "fast_import_filter",
        "fast_import_info",
        "fast_import_query",
        "fast_export",
        "fast_export_from_cvs",
        "fast_export_from_darcs",
        "fast_export_from_hg",
        "fast_export_from_git",
        "fast_export_from_mtn",
        "fast_export_from_p4",
        "fast_export_from_svn"
        ]:
    plugin_cmds.register_lazy("cmd_%s" % name, [], "bzrlib.plugins.fastimport.cmds")
