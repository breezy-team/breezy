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

import re
import sys

from ... import urlutils
from ...directory_service import directories
from ...errors import DependencyNotPresent
from ...trace import note, warning

from debian.deb822 import Deb822
from debian.changelog import Version

from debmutate.vcs import source_package_vcs, split_vcs_url


def fixup_broken_git_url(url):
    """Attempt to fix up broken Git URLs.

    A common misspelling is to add an extra ":" after the hostname
    """
    (scheme, netloc, path, params,
     query, fragment) = urlutils.urlparse.urlparse(url, allow_fragments=False)
    if '@' in netloc:
        credentials, host = netloc.rsplit('@', 1)
    else:
        credentials = None
        host = netloc

    if ':' in host and not (host[0] == '[' and host[-1] == ']'):
        # there *is* port
        host, port = host.rsplit(':', 1)
        if not port or port.isdigit():
            return url
    else:
        port = None

    if host in ('salsa.debian.org', 'github.com'):
        if '/' not in path[1:] and port:
            path = '%s/%s' % (port, path.lstrip('/'))
        netloc = host
        if ":" in netloc:
            netloc = "[%s]" % netloc
        if (credentials is not None and
            not (credentials == 'git' and
                 scheme not in ('git', 'http', 'https'))):
            netloc = '%s@%s' % (credentials, netloc)
        if host == 'salsa.debian.org':
            scheme = 'https'
        if host == 'salsa.debian.org' and path.startswith('/cgit/'):
            path = path[5:]
        new_url = urlutils.urlparse.urlunparse(
            (scheme, netloc, path, params, query, fragment))
        if url != new_url:
            warning('Fixing up URL: %s -> %s', url, new_url)
        return new_url
    return url


def vcs_git_url_to_bzr_url(url):
    """Convert a Vcs-Git string to a Breezy URL."""
    (url, branch, subpath) = split_vcs_url(url)

    from breezy.git.urls import git_url_to_bzr_url

    url = fixup_broken_git_url(url)
    url = git_url_to_bzr_url(url)
    if branch:
        branch = urlutils.quote(branch, '')
        url = urlutils.join_segment_parameters(
            url, {'branch': branch})
    if subpath:
        url = urlutils.join(url, subpath)
    return url


def vcs_bzr_url_to_bzr_url(url):
    return directories.dereference(url)


def vcs_darcs_url_to_bzr_url(url):
    return url


def vcs_mtn_url_to_bzr_url(url):
    return url


def vcs_arch_url_to_bzr_url(url):
    return url


def vcs_cvs_url_to_bzr_url(location):
    from breezy.location import cvs_to_url
    try:
        (loc, module) = location.split(' ', 1)
    except ValueError:
        loc = location
        module = None
    url = cvs_to_url(loc)
    if module is not None:
        url = url + '?module=' + urlutils.quote(module)
    return url


def vcs_hg_url_to_bzr_url(url):
    (url, branch, subpath) = split_vcs_url(url)

    if branch:
        branch = urlutils.quote(branch, '')
        url = urlutils.join_segment_parameters(
            url, {'branch': branch})
    if subpath:
        url = urlutils.join(url, subpath)
    return url


def vcs_svn_url_to_bzr_url(url):
    return url


vcs_field_to_bzr_url_converters = [
    ("Bzr", vcs_bzr_url_to_bzr_url),
    ("Darcs", vcs_darcs_url_to_bzr_url),
    ("Svn", vcs_svn_url_to_bzr_url),
    ("Git", vcs_git_url_to_bzr_url),
    ("Hg", vcs_hg_url_to_bzr_url),
    ("Cvs", vcs_cvs_url_to_bzr_url),
    ("Mtn", vcs_mtn_url_to_bzr_url),
    ("Arch", vcs_arch_url_to_bzr_url),
]


def source_package_vcs_url(control):
    """Extract a Breezy-compatible URL from a source package.
    """
    (vcs_type, vcs_url) = source_package_vcs(control)
    return vcs_type, dict(vcs_field_to_bzr_url_converters)[vcs_type](vcs_url)


class AptDirectory(object):
    """Simple Bazaar directory service which uses dpkg Vcs-* fields."""

    def look_up(self, name, url, purpose=None):
        if "/" in name:
            (name, version) = name.split("/", 1)
        else:
            version = None

        try:
            import apt_pkg
        except ImportError as e:
            raise DependencyNotPresent('apt_pkg', e)
        apt_pkg.init()

        sources = apt_pkg.SourceRecords()

        by_version = {}
        while sources.lookup(name):
            by_version[sources.version] = sources.record

        if len(by_version) == 0:
            raise urlutils.InvalidURL(path=url, extra='package not found')

        if version is None:
            # Try the latest version
            version = sorted(by_version, key=Version)[-1]

        if version not in by_version:
            raise urlutils.InvalidURL(
                path=url, extra='version %s not found' % version)

        control = Deb822(by_version[version])

        try:
            vcs, url = source_package_vcs_url(control)
        except KeyError:
            note("Retrieving Vcs locating from %s Debian version %s", name,
                 version)
            raise urlutils.InvalidURL(path=url, extra='no VCS URL found')

        note("Resolved package URL from Debian package %s/%s: %s",
             name, version, url)
        return url


class DgitDirectory(object):
    """Directory that looks up the URL according to a Dgit control field."""

    def look_up(self, name, url, purpose=None):
        if "/" in name:
            (name, version) = name.split("/", 1)
        else:
            version = None

        try:
            import apt_pkg
        except ImportError as e:
            raise DependencyNotPresent('apt_pkg', e)

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
            version = sorted(urls, key=Version)[-1]

        if version not in urls:
            raise urlutils.InvalidURL(
                path=url, extra='version %s not found' % version)

        if len(urls[version]) < 3:
            raise urlutils.InvalidURL(
                path=url,
                extra='dgit header does not have location information')

        url = urlutils.join_segment_parameters(
                urls[version][3],
                {"tag": urlutils.quote(urls[version][2], '')})

        note("Resolved package URL from Debian package %s/%s: %s",
             name, version, url)
        return url


class VcsDirectory(object):
    """Use local Vcs Directory."""

    def look_up(self, name, url, purpose=None):
        from debian.deb822 import Deb822
        with open('debian/control', 'r') as f:
            source = Deb822(f)
            vcs, url = source_package_vcs_url(source)
            return url


def upstream_branch_alias(b):
    from .util import debuild_config
    with b.lock_read():
        tree = b.basis_tree()
        config = debuild_config(tree, subpath='.')
        return directories.dereference(config.upstream_branch)
