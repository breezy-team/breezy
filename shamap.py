# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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

"""Map from Git sha's to Bazaar objects."""

import bzrlib

from bzrlib.errors import NoSuchRevision

import os


def check_pysqlite_version(sqlite3):
    """Check that sqlite library is compatible.

    """
    if (sqlite3.sqlite_version_info[0] < 3 or 
            (sqlite3.sqlite_version_info[0] == 3 and 
             sqlite3.sqlite_version_info[1] < 3)):
        warning('Needs at least sqlite 3.3.x')
        raise bzrlib.errors.BzrError("incompatible sqlite library")

try:
    try:
        import sqlite3
        check_pysqlite_version(sqlite3)
    except (ImportError, bzrlib.errors.BzrError), e: 
        from pysqlite2 import dbapi2 as sqlite3
        check_pysqlite_version(sqlite3)
except:
    warning('Needs at least Python2.5 or Python2.4 with the pysqlite2 '
            'module')
    raise bzrlib.errors.BzrError("missing sqlite library")


class GitShaMap(object):
    """Git<->Bzr revision id mapping database."""

    def add_entry(self, sha, type, type_data):
        """Add a new entry to the database.
        """
        raise NotImplementedError(self.add_entry)

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            revision: revid, tree sha
        """
        raise NotImplementedError(self.lookup_git_sha)

    def revids(self):
        """List the revision ids known."""
        raise NotImplementedError(self.revids)

    def commit(self):
        """Commit any pending changes."""


class DictGitShaMap(GitShaMap):

    def __init__(self):
        self.dict = {}

    def add_entry(self, sha, type, type_data):
        self.dict[sha] = (type, type_data)

    def lookup_git_sha(self, sha):
        return self.dict[sha]

    def revids(self):
        for key, (type, type_data) in self.dict.iteritems():
            if type == "commit":
                yield type_data[0]


class SqliteGitShaMap(GitShaMap):

    def __init__(self, transport=None):
        self.transport = transport
        if transport is None:
            self.db = sqlite3.connect(":memory:")
        else:
            self.db = sqlite3.connect(
                os.path.join(self.transport.local_abspath("."), "git.db"))
        self.db.executescript("""
        create table if not exists commits(sha1 text, revid text, tree_sha text);
        create index if not exists commit_sha1 on commits(sha1);
        create table if not exists blobs(sha1 text, fileid text, revid text);
        create index if not exists blobs_sha1 on blobs(sha1);
        create table if not exists trees(sha1 text, path text, revid text);
        create index if not exists trees_sha1 on trees(sha1);
""")

    def _parent_lookup(self, revid):
        return self.db.execute("select sha1 from commits where revid = ?", (revid,)).fetchone()[0].encode("utf-8")

    def commit(self):
        self.db.commit()

    def add_entry(self, sha, type, type_data):
        """Add a new entry to the database.
        """
        assert isinstance(type_data, tuple)
        assert isinstance(sha, str), "type was %r" % sha
        if type == "commit":
            self.db.execute("replace into commits (sha1, revid, tree_sha) values (?, ?, ?)", (sha, type_data[0], type_data[1]))
        elif type == "blob":
            self.db.execute("replace into blobs (sha1, fileid, revid) values (?, ?, ?)", (sha, type_data[0], type_data[1]))
        elif type == "tree":
            self.db.execute("replace into trees (sha1, path, revid) values (?, ?, ?)", (sha, type_data[0], type_data[1]))
        else:
            raise AssertionError("Unknown type %s" % type)

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            revision: revid, tree sha
        """
        row = self.db.execute("select revid, tree_sha from commits where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return ("commit", row)
        row = self.db.execute("select fileid, revid from blobs where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return ("blob", row)
        row = self.db.execute("select path, revid from trees where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return ("tree", row)
        raise KeyError(sha)

    def revids(self):
        """List the revision ids known."""
        for row in self.db.execute("select revid from commits").fetchall():
            yield row[0]
