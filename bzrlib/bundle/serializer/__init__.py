# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Serializer factory for reading and writing bundles.
"""

import base64
from StringIO import StringIO
import re

import bzrlib.errors as errors
from bzrlib.diff import internal_diff
from bzrlib.revision import NULL_REVISION

# New bundles should try to use this header format
BUNDLE_HEADER = '# Bazaar revision bundle v'
BUNDLE_HEADER_RE = re.compile(
    r'^# Bazaar revision bundle v(?P<version>\d+[\w.]*)(?P<lineending>\r?)\n$')
CHANGESET_OLD_HEADER_RE = re.compile(
    r'^# Bazaar-NG changeset v(?P<version>\d+[\w.]*)(?P<lineending>\r?)\n$')


_serializers = {}


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


def write(source, revision_ids, f, version=None, forced_bases={}):
    """Serialize a list of bundles to a filelike object.

    :param source: A source for revision information
    :param revision_ids: The list of revision ids to serialize
    :param f: The file to output to
    :param version: [optional] target serialization version
    """

    if version not in _serializers:
        raise errors.BundleNotSupported(version, 'unknown bundle format')

    serializer = _serializers[version](version)
    source.lock_read()
    try:
        return serializer.write(source, revision_ids, forced_bases, f)
    finally:
        source.unlock()


def write_bundle(repository, revision_id, base_revision_id, out, format=None):
    """"""
    repository.lock_read()
    try:
        return _write_bundle(repository, revision_id, base_revision_id, out,
                             format)
    finally:
        repository.unlock()


def _write_bundle(repository, revision_id, base_revision_id, out, format):
    """Write a bundle of revisions.

    :param repository: Repository containing revisions to serialize.
    :param revision_id: Head revision_id of the bundle.
    :param base_revision_id: Revision assumed to be present in repositories
         applying the bundle.
    :param out: Output file.
    """
    if base_revision_id is NULL_REVISION:
        base_revision_id = None
    base_ancestry = set(repository.get_ancestry(base_revision_id))
    revision_ids = [r for r in repository.get_ancestry(revision_id) if r
                    not in base_ancestry]
    revision_ids = list(reversed(revision_ids))
    write(repository, revision_ids, out, format,
          forced_bases = {revision_id:base_revision_id})
    return revision_ids


def format_highres_date(t, offset=0):
    """Format a date, such that it includes higher precision in the
    seconds field.

    :param t:   The local time in fractional seconds since the epoch
    :type t: float
    :param offset:  The timezone offset in integer seconds
    :type offset: int

    Example: format_highres_date(time.time(), -time.timezone)
    this will return a date stamp for right now,
    formatted for the local timezone.

    >>> from bzrlib.osutils import format_date
    >>> format_date(1120153132.350850105, 0)
    'Thu 2005-06-30 17:38:52 +0000'
    >>> format_highres_date(1120153132.350850105, 0)
    'Thu 2005-06-30 17:38:52.350850105 +0000'
    >>> format_date(1120153132.350850105, -5*3600)
    'Thu 2005-06-30 12:38:52 -0500'
    >>> format_highres_date(1120153132.350850105, -5*3600)
    'Thu 2005-06-30 12:38:52.350850105 -0500'
    >>> format_highres_date(1120153132.350850105, 7200)
    'Thu 2005-06-30 19:38:52.350850105 +0200'
    >>> format_highres_date(1152428738.867522, 19800)
    'Sun 2006-07-09 12:35:38.867522001 +0530'
    """
    import time
    assert isinstance(t, float)
    
    # This has to be formatted for "original" date, so that the
    # revision XML entry will be reproduced faithfully.
    if offset is None:
        offset = 0
    tt = time.gmtime(t + offset)

    return (time.strftime("%a %Y-%m-%d %H:%M:%S", tt)
            + ('%.9f' % (t - int(t)))[1:] # Get the high-res seconds, but ignore the 0
            + ' %+03d%02d' % (offset / 3600, (offset / 60) % 60))


def unpack_highres_date(date):
    """This takes the high-resolution date stamp, and
    converts it back into the tuple (timestamp, timezone)
    Where timestamp is in real UTC since epoch seconds, and timezone is an integer
    number of seconds offset.

    :param date: A date formated by format_highres_date
    :type date: string

    >>> import time, random
    >>> unpack_highres_date('Thu 2005-06-30 12:38:52.350850105 -0500')
    (1120153132.3508501, -18000)
    >>> unpack_highres_date('Thu 2005-06-30 17:38:52.350850105 +0000')
    (1120153132.3508501, 0)
    >>> unpack_highres_date('Thu 2005-06-30 19:38:52.350850105 +0200')
    (1120153132.3508501, 7200)
    >>> unpack_highres_date('Sun 2006-07-09 12:35:38.867522001 +0530')
    (1152428738.867522, 19800)
    >>> from bzrlib.osutils import local_time_offset
    >>> t = time.time()
    >>> o = local_time_offset()
    >>> t2, o2 = unpack_highres_date(format_highres_date(t, o))
    >>> t == t2
    True
    >>> o == o2
    True
    >>> t -= 24*3600*365*2 # Start 2 years ago
    >>> o = -12*3600
    >>> for count in xrange(500):
    ...   t += random.random()*24*3600*30
    ...   o = ((o/3600 + 13) % 25 - 12)*3600 # Add 1 wrap around from [-12, 12]
    ...   date = format_highres_date(t, o)
    ...   t2, o2 = unpack_highres_date(date)
    ...   if t != t2 or o != o2:
    ...      print 'Failed on date %r, %s,%s diff:%s' % (date, t, o, t2-t)
    ...      break

    """
    import time, calendar
    # Up until the first period is a datestamp that is generated
    # as normal from time.strftime, so use time.strptime to
    # parse it
    dot_loc = date.find('.')
    if dot_loc == -1:
        raise ValueError(
            'Date string does not contain high-precision seconds: %r' % date)
    base_time = time.strptime(date[:dot_loc], "%a %Y-%m-%d %H:%M:%S")
    fract_seconds, offset = date[dot_loc:].split()
    fract_seconds = float(fract_seconds)

    offset = int(offset)

    hours = int(offset / 100)
    minutes = (offset % 100)
    seconds_offset = (hours * 3600) + (minutes * 60)
    
    # time.mktime returns localtime, but calendar.timegm returns UTC time
    timestamp = calendar.timegm(base_time)
    timestamp -= seconds_offset
    # Add back in the fractional seconds
    timestamp += fract_seconds
    return (timestamp, seconds_offset)


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

    def write(self, source, revision_ids, forced_bases, f):
        """Write the bundle to the supplied file.

        :param source: A source for revision information
        :param revision_ids: The list of revision ids to serialize
        :param forced_bases: A dict of revision -> base that overrides default
        :param f: The file to output to
        """
        raise NotImplementedError


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
        mod = __import__(module, globals(), locals(), [classname])
        klass = getattr(mod, classname)
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
register_lazy(None, 'bzrlib.bundle.serializer.v08', 'BundleSerializerV08')

