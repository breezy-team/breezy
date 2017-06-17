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

from __future__ import absolute_import

from ... import errors
from ...trace import note

import apt_pkg


class VcsDirectory(object):
    """Simple Bazaar directory service which uses dpkg Vcs-* fields."""

    def look_up(self, name, url):
        if "/" in name:
            (name, version) = name.split("/", 1)
        else:
            version = None

        apt_pkg.init()

        # Older versions of apt_pkg don't have SourceRecords,
        # newer versions give a deprecation warning when using
        # GetPkgSrcRecords.
        try:
            sources = apt_pkg.SourceRecords()
        except AttributeError:
            sources = apt_pkg.GetPkgSrcRecords()

        urls = {}
        lookup = getattr(sources, 'lookup', None) or sources.Lookup
        while lookup(name):
            record = getattr(sources, 'record', None) or sources.Record
            for l in record.splitlines():
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
            cmp = getattr(apt_pkg, 'version_compare',
                    getattr(apt_pkg, 'VersionCompare', None))
            version = sorted(urls,cmp=cmp)[0]

        if not version in urls:
            raise errors.InvalidURL(path=url,
                    extra='version %s not found' % version)
        
        note("Retrieving Vcs locating from %s Debian version %s", name, version)

        if "Bzr" in urls[version]:
            return urls[version]["Bzr"]

        if "Svn" in urls[version]:
            try:
                from .. import svn
            except ImportError:
                note("This package uses subversion. If you would like to "
                        "access it with bzr then please install brz-svn "
                        "and re-run the command.")
            else:
                return urls[version]["Svn"]

        if "Git" in urls[version]:
            try:
                from .. import git
            except ImportError:
                note("This package uses git. If you would like to "
                        "access it with bzr then please install brz-git "
                        "and re-run the command.")
            else:
                from breezy import urlutils
                url = urls[version]["Git"]
                if ' -b ' in url:
                    (url, branch) = url.split(' -b ', 1)
                    url = urlutils.join_segment_parameters(
                        url, {'branch': branch})
                return url

        if "Hg" in urls[version]:
            try:
                from .. import hg
            except ImportError:
                note("This package uses hg. If you would like to "
                        "access it with bzr then please install brz-hg"
                        "and re-run the command.")
            else:
                return urls[version]["Hg"]

        raise errors.InvalidURL(path=url,
            extra='unsupported VCSes %r found' % urls[version].keys())


def upstream_branch_alias(b):
    from ...directory_service import directories
    from .util import debuild_config
    b.lock_read()
    try:
        tree = b.basis_tree()
        config = debuild_config(tree, False)
        return directories.dereference(config.upstream_branch)
    finally:
        b.unlock()

