#    directory.py -- Directory service that uses Debian Vcs-* fields
#    Copyright (C) 2008 Jelmer Vernooij <jelmer@samba.org>
#    
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from bzrlib import errors
from bzrlib.trace import info

import apt_pkg


class VcsDirectory(object):
    """Simple Bazaar directory service which uses dpkg Vcs-* fields."""

    def look_up(self, name, url):
        if "/" in name:
            (name, version) = name.split("/", 1)
        else:
            version = None

        apt_pkg.init()

        sources = apt_pkg.GetPkgSrcRecords()

        urls = {}
        while sources.Lookup(name):
            for l in sources.Record.splitlines():
                if not ": " in l:
                    continue
                (field, value) = l.strip("\n").split(": ", 1)

                if field == "Version":
                    pkg_version = value
                elif field.startswith("X-Vcs-") or field.startswith("Vcs-"):
                    vcs = field.split("-")[-1]
                    urls.setdefault(pkg_version,{})[vcs] = value

        if len(urls) == 0:
            raise errors.InvalidURL(path=url, extra='no URLs found')

        if version is None:
            # Try the latest version
            version = sorted(urls,cmp=apt_pkg.VersionCompare)[0]

        if not version in urls:
            raise errors.InvalidURL(path=url, extra='version %s not found' % version)
        
        info("Retrieving Vcs locating from %s Debian version %s", name, version)

        if "Bzr" in urls[version]:
            return urls[version]["Bzr"]

        if "Svn" in urls[version]:
            return urls[version]["Svn"]

        raise errors.InvalidURL(path=url,
            extra='unsupported VCSes %r found' % urls[version].keys())
