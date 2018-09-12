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

from ... import urlutils
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

        sources = apt_pkg.SourceRecords()

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
            raise urlutils.InvalidURL(path=url, extra='no URLs found')

        if version is None:
            # Try the latest version
            version = sorted(urls, cmp=apt_pkg.version_compare)[-1]

        if not version in urls:
            raise urlutils.InvalidURL(path=url,
                    extra='version %s not found' % version)

        # TODO(jelmer): some packages seem to use [PATH] behind the URL to
        # indicate a subdirectory inside of the versioned tree.

        if "Bzr" in urls[version]:
            url = urls[version]["Bzr"]
        elif "Darcs" in urls[version]:
            url = urls[version]["Darcs"]
        elif "Svn" in urls[version]:
            url = urls[version]["Svn"]
        elif "Git" in urls[version]:
            from breezy.git.urls import git_url_to_bzr_url
            url = urls[version]["Git"]
            if ' -b ' in url:
                (url, branch) = url.split(' -b ', 1)
                url = urlutils.join_segment_parameters(
                    url, {'branch': branch})
            url = git_url_to_bzr_url(url)
        elif "Hg" in urls[version]:
            url = urls[version]["Hg"]
        else:
            if "Browser" in urls[version]:
                del urls[version]["Browser"]

            if not urls[version]:
                raise urlutils.InvalidURL(path=url, extra='only Vcs-Browser set')

            note("Retrieving Vcs locating from %s Debian version %s", name, version)
            raise urlutils.InvalidURL(path=url,
                extra='unsupported VCSes %r found' % urls[version].keys())

        note("Resolved package URL from Debian package %s/%s: %s", name, version, url)
        return url


def upstream_branch_alias(b):
    from ...directory_service import directories
    from .util import debuild_config
    with b.lock_read():
        tree = b.basis_tree()
        config = debuild_config(tree, False)
        return directories.dereference(config.upstream_branch)

