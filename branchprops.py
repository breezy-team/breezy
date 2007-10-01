# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

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

"""Branch property access and caching."""

from bzrlib.errors import NoSuchRevision
from bzrlib.trace import mutter

from svn.core import SubversionException, Pool
import svn.core

class BranchPropertyList:
    """Simple class that retrieves file properties set on branches."""
    def __init__(self, log, cachedb):
        self.log = log
        self.cachedb = cachedb

        self.cachedb.executescript("""
            create table if not exists branchprop (name text, value text, branchpath text, revnum integer);
            create index if not exists branch_path_revnum on branchprop (branchpath, revnum);
            create index if not exists branch_path_revnum_name on branchprop (branchpath, revnum, name);
        """)

        self.pool = Pool()

    def _get_dir_props(self, path, revnum):
        """Obtain all the directory properties set on a path/revnum pair.

        :param path: Subversion path
        :param revnum: Subversion revision number
        :return: Dictionary with properties
        """
        assert isinstance(path, str)
        path = path.lstrip("/")

        try:
            (_, _, props) = self.log._get_transport().get_dir(path, 
                revnum, pool=self.pool)
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(self, revnum)
            raise

        return props

    def get_properties(self, path, origrevnum):
        """Obtain the file properties set on a path/revnum pair.

        Will use the cache.

        :param path: Subversion path.
        :param origrevnum: Subversion revision number.
        :return: Dictionary with properties
        """
        assert path is not None
        assert isinstance(path, str)
        assert isinstance(origrevnum, int) and origrevnum >= 0
        revnum = self.log.find_latest_change(path, origrevnum, 
                                             include_parents=True)
        assert revnum is not None, \
                "can't find latest change for %r:%r" % (path, origrevnum)

        if revnum == 0: # no properties are set in revision 0
            return {}

        proplist = {}
        for (name, value) in self.cachedb.execute("select name, value from branchprop where revnum=%d and branchpath='%s'" % (revnum, path)):
            proplist[name] = value.encode("utf-8")

        if proplist != {}:
            return proplist

        proplist = self._get_dir_props(path, revnum)
        for name in proplist:
            self.cachedb.execute("insert into branchprop (name, value, revnum, branchpath) values (?,?,?,?)", (name, proplist[name], revnum, path))
        self.cachedb.commit()

        return proplist

    def get_property(self, path, revnum, name, default=None):
        """Get the contents of a Subversion file property.

        Will use the cache.

        :param path: Subversion path.
        :param revnum: Subversion revision number.
        :param default: Default value to return if property wasn't found.
        :return: Contents of property or default if property didn't exist.
        """
        assert isinstance(revnum, int)
        assert isinstance(path, str)
        props = self.get_properties(path, revnum)
        if props.has_key(name):
            return props[name]
        return default

    def touches_property(self, path, revnum, name):
        """Check whether a property was modified in a revision."""
        assert isinstance(path, str)
        assert isinstance(revnum, int)
        assert isinstance(name, str)
        # If the path this property is set on didn't change, then 
        # the property can't have changed.
        if not self.log.touches_path(path, revnum):
            return ""

        current = self.get_property(path, revnum, name, None)
        (prev_path, prev_revnum) = self.log.get_previous(path, revnum)
        if prev_path is None and prev_revnum == -1:
            return (current is not None)
        previous = self.get_property(prev_path.encode("utf-8"), 
                                     prev_revnum, name, None)
        return (previous != current)

    def get_property_diff(self, path, revnum, name):
        """Returns the new lines that were added to a particular property."""
        assert isinstance(path, str)
        # If the path this property is set on didn't change, then 
        # the property can't have changed.
        if not self.log.touches_path(path, revnum):
            return ""

        current = self.get_property(path, revnum, name, "")
        (prev_path, prev_revnum) = self.log.get_previous(path, revnum)
        if prev_path is None and prev_revnum == -1:
            previous = ""
        else:
            previous = self.get_property(prev_path.encode("utf-8"), 
                                         prev_revnum, name, "")
        if len(previous) > len(current) or current[0:len(previous)] != previous:
            mutter('original part changed for %r between %s:%d -> %s:%d' % (name, prev_path, prev_revnum, path, revnum))
            return ""
        return current[len(previous):] 
