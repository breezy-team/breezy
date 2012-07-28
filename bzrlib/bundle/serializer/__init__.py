# Copyright (C) 2005, 2006, 2007, 2009, 2010 Canonical Ltd
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

"""Serializer factory for reading and writing bundles.
"""

from __future__ import absolute_import

import base64
from StringIO import StringIO
import re

from bzrlib import (
    errors,
    pyutils,
    )
from bzrlib.diff import internal_diff
from bzrlib.revision import NULL_REVISION
# For backwards-compatibility
from bzrlib.timestamp import unpack_highres_date, format_highres_date


# New bundles should try to use this header format
BUNDLE_HEADER = '# Bazaar revision bundle v'
BUNDLE_HEADER_RE = re.compile(
    r'^# Bazaar revision bundle v(?P<version>\d+[\w.]*)(?P<lineending>\r?)\n$')
CHANGESET_OLD_HEADER_RE = re.compile(
    r'^# Bazaar-NG changeset v(?P<version>\d+[\w.]*)(?P<lineending>\r?)\n$')


_serializers = {}

v4_string = '4'

def _get_bundle_header(version):
    return '%s%s\n' % (BUNDLE_HEADER, version)

def _get_filename(f):
    return getattr(f, 'name', '<unknown>')


def read_bundle(f):
    """Read in a bundle from a filelike object.

    :param f: A file-like object
    :return: A list of Bundle objects
    """
    version = None
    for line in f:
        m = BUNDLE_HEADER_RE.match(line)
        if m:
            if m.group('lineending') != '':
                raise errors.UnsupportedEOLMarker()
            version = m.group('version')
            break
        elif line.startswith(BUNDLE_HEADER):
            raise errors.MalformedHeader(
                'Extra characters after version number')
        m = CHANGESET_OLD_HEADER_RE.match(line)
        if m:
            version = m.group('version')
            raise errors.BundleNotSupported(version,
                'old format bundles not supported')

    if version is None:
        raise errors.NotABundle('Did not find an opening header')

    # Now we have a version, to figure out how to read the bundle
    if version not in _serializers:
        raise errors.BundleNotSupported(version,
            'version not listed in known versions')

    serializer = _serializers[version](version)

    return serializer.read(f)


def get_serializer(version):
    try:
        return _serializers[version](version)
    except KeyError:
        raise errors.BundleNotSupported(version, 'unknown bundle format')


def write(source, revision_ids, f, version=None, forced_bases={}):
    """Serialize a list of bundles to a filelike object.

    :param source: A source for revision information
    :param revision_ids: The list of revision ids to serialize
    :param f: The file to output to
    :param version: [optional] target serialization version
    """

    source.lock_read()
    try:
        return get_serializer(version).write(source, revision_ids,
                                             forced_bases, f)
    finally:
        source.unlock()


def write_bundle(repository, revision_id, base_revision_id, out, format=None):
    """Write a bundle of revisions.

    :param repository: Repository containing revisions to serialize.
    :param revision_id: Head revision_id of the bundle.
    :param base_revision_id: Revision assumed to be present in repositories
         applying the bundle.
    :param out: Output file.
    """
    repository.lock_read()
    try:
        return get_serializer(format).write_bundle(repository, revision_id,
                                                   base_revision_id, out)
    finally:
        repository.unlock()


class BundleSerializer(object):
    """The base class for Serializers.

    Common functionality should be included here.
    """
    def __init__(self, version):
        self.version = version

    def read(self, f):
        """Read the rest of the bundles from the supplied file.

        :param f: The file to read from
        :return: A list of bundle trees
        """
        raise NotImplementedError

    def write_bundle(self, repository, target, base, fileobj):
        """Write the bundle to the supplied file.

        :param repository: The repository to retrieve revision data from
        :param target: The revision to provide data for
        :param base: The most recent of ancestor of the revision that does not
            need to be included in the bundle
        :param fileobj: The file to output to
        """
        raise NotImplementedError

    def _write_bundle(self, repository, revision_id, base_revision_id, out):
        """Helper function for translating write_bundle to write"""
        forced_bases = {revision_id:base_revision_id}
        if base_revision_id is NULL_REVISION:
            base_revision_id = None
        graph = repository.get_graph()
        revision_ids = graph.find_unique_ancestors(revision_id,
            [base_revision_id])
        revision_ids = list(repository.get_graph().iter_topo_order(
            revision_ids))
        revision_ids.reverse()
        self.write(repository, revision_ids, forced_bases, out)
        return revision_ids


def register(version, klass, overwrite=False):
    """Register a BundleSerializer version.

    :param version: The version associated with this format
    :param klass: The class to instantiate, which must take a version argument
    """
    global _serializers
    if overwrite:
        _serializers[version] = klass
        return

    if version not in _serializers:
        _serializers[version] = klass


def register_lazy(version, module, classname, overwrite=False):
    """Register lazy-loaded bundle serializer.

    :param version: The version associated with this reader
    :param module: String indicating what module should be loaded
    :param classname: Name of the class that will be instantiated
    :param overwrite: Should this version override a default
    """
    def _loader(version):
        klass = pyutils.get_named_object(module, classname)
        return klass(version)
    register(version, _loader, overwrite=overwrite)


def binary_diff(old_filename, old_lines, new_filename, new_lines, to_file):
    temp = StringIO()
    internal_diff(old_filename, old_lines, new_filename, new_lines, temp,
                  allow_binary=True)
    temp.seek(0)
    base64.encode(temp, to_file)
    to_file.write('\n')

register_lazy('0.8', 'bzrlib.bundle.serializer.v08', 'BundleSerializerV08')
register_lazy('0.9', 'bzrlib.bundle.serializer.v09', 'BundleSerializerV09')
register_lazy(v4_string, 'bzrlib.bundle.serializer.v4',
              'BundleSerializerV4')
register_lazy(None, 'bzrlib.bundle.serializer.v4', 'BundleSerializerV4')

