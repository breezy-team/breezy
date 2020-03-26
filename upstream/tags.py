#    tags.py -- Providers of upstream source - tag names
#    Copyright (C) 2016-2020 Jelmer Vernooij <jelmer@debian.org>
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

import re

from ....errors import BzrError


class GbpTagFormatError(BzrError):
    _fmt = 'Unknown variable %(variable)s in tag %(tag_name)s.'

    def __init__(self, tag_name, variable):
        self.variable = variable
        self.tag_name = tag_name


def gbp_expand_tag_name(tag_format, version):
    # See gbp/pkg/pkgpolicy.py in gbp-buildpackage
    version_mangle_re = (
        r'%\(version'
        r'%(?P<M>[^%])'
        r'%(?P<R>([^%]|\\%))+'
        r'\)s')

    ret = tag_format
    m = re.search(version_mangle_re, tag_format)
    if m:
        ret = re.sub(version_mangle_re, "%(version)s", tag_format)
        version = version.replace(
            m.group('M'), m.group('R').replace(r'\%', '%'))

    vars = {
        'version': version,
        'hversion': version.replace('.', '-'),
        }
    try:
        return ret % vars
    except KeyError as e:
        raise GbpTagFormatError(tag_format, e.args[0])


def upstream_tag_name(version, component=None, distro=None, git_style=False):
    if git_style:
        # In git, the convention is to use a slash
        if distro is None:
            name = "upstream/" + version.replace('~', '_')
        else:
            name = "upstream-%s/%s" % (distro, version.replace('~', '_'))
    else:
        if distro is None:
            name = "upstream-" + version
        else:
            name = "upstream-%s-%s" % (distro, version)
    if component is not None:
        name += "/%s" % component
    return name


def possible_upstream_tag_names(version, component=None):
    tags = []
    if component is None:
        # compatibility with git-buildpackage
        tags.append("upstream/%s" % version)
        tags.append("upstream-%s" % version)
        if "~" in version:
            tags.append("upstream/%s" % version.replace("~", "_"))
        # compatibility with svn-buildpackage
        tags.append("upstream_%s" % version)
    else:
        tags.append(upstream_tag_name(version, component))
    return tags


def is_upstream_tag(tag):
    """Return true if tag is an upstream tag.

    :param tag: The string name of the tag.
    :return: True if the tag name is one generated by upstream tag operations.
    """
    return (tag.startswith('upstream-') or tag.startswith('upstream/') or
            tag.startswith('upstream_'))


def upstream_tag_version(tag):
    """Return the upstream version portion of an upstream tag name.

    :param tag: The string name of the tag.
    :return: tuple with version portion of the tag and component name
    """
    assert is_upstream_tag(tag), "Not an upstream tag: %s" % tag
    if tag.startswith('upstream/'):
        tag = tag[len('upstream/'):]
    elif tag.startswith('upstream_'):
        tag = tag[len('upstream_'):]
    elif tag.startswith('upstream-'):
        tag = tag[len('upstream-'):]
        if tag.startswith('debian-'):
            tag = tag[len('debian-'):]
        elif tag.startswith('ubuntu-'):
            tag = tag[len('ubuntu-'):]
    tag = tag.replace('_', '~')
    if '/' not in tag:
        return (None, tag)
    (version, component) = tag.rsplit('/', 1)
    if component == "":
        component = None
    return (component, version)
