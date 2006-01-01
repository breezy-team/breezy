# (C) 2005 Canonical Development Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Serializer factory for reading and writing changesets.
"""

import re

import bzrlib.errors as errors

# New changesets should try to use this header format
CHANGESET_HEADER = '# Bazaar changeset v'
CHANGESET_HEADER_RE = re.compile(r'^# Bazaar changeset v(?P<version>\d+[\w.]*)\n$')
CHANGESET_OLD_HEADER_RE = re.compile(r'^# Bazaar-NG changeset v(?P<version>\d+[\w.]*)\n$')


_serializers = {} 


def _get_filename(f):
    if hasattr(f, 'name'):
        return f.name
    return '<unknown>'


def read(f):
    """Read in a changeset from a filelike object.

    :param f: A file-like object
    :return: A list of Changeset objects
    """
    version = None
    for line in f:
        m = CHANGESET_HEADER_RE.match(line)
        if m:
            version = m.group('version')
            break
        m = CHANGESET_OLD_HEADER_RE.match(line)
        if m:
            version = m.group('version')
            raise errors.ChangesetNotSupported(version, 'old format changesets not supported')

    if version is None:
        raise errors.NoChangesetFound(_get_filename(f))

    # Now we have a version, to figure out how to read the changeset
    if not _serializers.has_key(version):
        raise errors.ChangesetNotSupported(version, 'version not listed in known versions')

    serializer = _serializers[version](version)

    return serializer.read(f)


def write(source, revision_ids, f, version=None):
    """Serialize a list of changesets to a filelike object.

    :param source: A source for revision information
    :param revision_ids: The list of revision ids to serialize
    :param f: The file to output to
    :param version: [optional] target serialization version
    """

    if not _serializers.has_key(version):
        raise errors.ChangesetNotSupported(version, 'unknown changeset format')

    serializer = _serializers[version](version)
    return serializer.write(source, revision_ids, f) 


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
    """
    import time
    assert isinstance(t, float)
    
    # This has to be formatted for "original" date, so that the
    # revision XML entry will be reproduced faithfully.
    if offset == None:
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
        raise ValueError('Date string does not contain high-precision seconds: %r' % date)
    base_time = time.strptime(date[:dot_loc], "%a %Y-%m-%d %H:%M:%S")
    fract_seconds, offset = date[dot_loc:].split()
    fract_seconds = float(fract_seconds)
    offset = int(offset)
    offset = int(offset / 100) * 3600 + offset % 100
    
    # time.mktime returns localtime, but calendar.timegm returns UTC time
    timestamp = calendar.timegm(base_time)
    timestamp -= offset
    # Add back in the fractional seconds
    timestamp += fract_seconds
    return (timestamp, offset)


class ChangesetSerializer(object):
    """The base class for Serializers.

    Common functionality should be included here.
    """
    def __init__(self, version):
        self.version = version

    def read(self, f):
        """Read the rest of the changesets from the supplied file.

        :param f: The file to read from
        :return: A list of changeset trees
        """
        raise NotImplementedError

    def write(self, source, revision_ids, f):
        """Write the changesets to the supplied files.

        :param source: A source for revision information
        :param revision_ids: The list of revision ids to serialize
        :param f: The file to output to
        """
        raise NotImplementedError


def register(version, klass, overwrite=False):
    """Register a ChangesetSerializer version.

    :param version: The version associated with this format
    :param klass: The class to instantiate, which must take a version argument
    """
    global _serializers
    if overwrite:
        _serializers[version] = klass
        return

    if not _serializers.has_key(version):
        _serializers[version] = klass


def register_lazy(version, module, classname, overwrite=False):
    """Register lazy-loaded changeset serializer.

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


register_lazy('0.6', 'bzrlib.changeset.serializer.v06', 'ChangesetSerializerV06')
register_lazy(None, 'bzrlib.changeset.serializer.v06', 'ChangesetSerializerV06')

