#!/usr/bin/python
# Copyright (C) 2008 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib.branch import Branch
import sys

b = Branch.open(".")

DOWNLOAD_URL = "http://samba.org/~jelmer/bzr"

def write_releaselist(f):
    f.write("\nReleases\n")
    f.write("--------\n\n")

    versions = []

    for release in b.tags.get_tag_dict():
        (name, version) = release.rsplit("-", 1)
        assert name == "bzr-svn"
        versions.append(version)

    def version_sort(a, b):
        def versiontuple(a):
            a = a.rstrip("~rc1")
            return [int(x) for x in a.split(".")]
        return cmp(versiontuple(a), versiontuple(b))

    print versions
    versions.sort(version_sort, reverse=True)

    for version in versions:
        f.write("* %s_\n" % version)

    f.write("\n")

    for version in versions:
        f.write(".. _%s: %s/bzr-svn-%s.tar.gz\n" % (version, DOWNLOAD_URL, version))

    f.write("\n")

f = sys.stdout
f.write("#FORMAT rst\n")
f.write(open("README", "r").read())
write_releaselist(f)
f.write(open("INSTALL", "r").read())
f.write("""
Credits
-------
bzr-svn was written by JelmerVernooij_ with the help from various other people.
See the AUTHORS file in the source distribution for a list.

.. _JelmerVernooij: http://samba.org/~jelmer/

""")
