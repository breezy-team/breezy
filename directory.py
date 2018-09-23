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
from ...directory_service import directories
from ...trace import note

import apt_pkg
from debian.deb822 import Deb822


def vcs_git_url_to_bzr_url(url):
    """Convert a Vcs-Git string to a Breezy URL."""
    from breezy.git.urls import git_url_to_bzr_url
    if ' -b ' in url:
        (url, branch) = url.split(' -b ', 1)
    else:
        branch = None
    url = git_url_to_bzr_url(url)
    if branch:
        branch = urlutils.quote(branch, '')
        url = urlutils.join_segment_parameters(
            url, {'branch': branch})
    return url


def vcs_bzr_url_to_bzr_url(url):
    return directories.dereference(url)


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
        while sources.lookup(name):
            control = Deb822(sources.record)
            pkg_version = control["Version"]
            for field, value in control.items():
                if field.startswith("X-Vcs-") or field.startswith("Vcs-") or field.startswith("XS-Vcs-"):
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
            url = vcs_bzr_url_to_bzr_url(urls[version]["Bzr"])
        elif "Darcs" in urls[version]:
            url = urls[version]["Darcs"]
        elif "Svn" in urls[version]:
            url = urls[version]["Svn"]
        elif "Git" in urls[version]:
            url = vcs_git_url_to_bzr_url(urls[version]["Git"])
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


class DgitDirectory(object):
    """Directory that looks up the URL according to a Dgit control field."""

    def look_up(self, name, url):
        if "/" in name:
            (name, version) = name.split("/", 1)
        else:
            version = None

        apt_pkg.init()

        sources = apt_pkg.SourceRecords()

        urls = {}
        while sources.lookup(name):
            control = Deb822(sources.record)
            pkg_version = control["Version"]
            try:
                urls[pkg_version] = control["Dgit"].split(' ')
            except KeyError:
                pass

        if len(urls) == 0:
            raise urlutils.InvalidURL(path=url, extra='no URLs found')

        if version is None:
            # Try the latest version
            version = sorted(urls, cmp=apt_pkg.version_compare)[-1]

        if not version in urls:
            raise urlutils.InvalidURL(path=url,
                    extra='version %s not found' % version)

        url = urlutils.join_segment_parameters(
                urls[version][3],
                {"tag": urlutils.quote(urls[version][2], '')})

        note("Resolved package URL from Debian package %s/%s: %s",
             name, version, url)
        return url


def upstream_branch_alias(b):
    from .util import debuild_config
    with b.lock_read():
        tree = b.basis_tree()
        config = debuild_config(tree, False)
        return directories.dereference(config.upstream_branch)

