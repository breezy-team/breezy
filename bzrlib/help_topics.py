# Copyright (C) 2004, 2005, 2006 by Canonical Ltd
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

"""A collection of extra help information for using bzr.

Help topics are meant to be help for items that aren't commands, but will
help bzr become fully learnable without referring to a tutorial.
"""

import sys


HELP_TOPICS={}
HELP_TOPICS_COMMENT={}


def add_topic(name, obj, comment):
    """add a new topic, obj can be a function or a text; comment
       is a text"""
    HELP_TOPICS[name]=obj
    HELP_TOPICS_COMMENT[name]=comment


def write_topic(name, outfile=sys.stdout):
    """write to outfile the topic named "name"""
    obj = HELP_TOPICS[name]
    if callable(obj):
        obj(name, outfile)
    else:
        outfile.write(obj)


def is_topic(name):
    """is "name" a topic ?"""
    return name in HELP_TOPICS


def get_topics_list( ):
    """return a dict like {topic_name:topi_comment}"""
    return HELP_TOPICS_COMMENT


#----------------------------------------------------

def _help_on_topics(name, outfile):
    """Write out the help for topics to outfile"""

    topics = get_topics_list()
    for i in topics:
        outfile.write("%s\n        %s\n" % (i, topics[i]))


def _help_on_revisionspec(name, outfile):
    """Write out the help for revison spec information"""
    import bzrlib.revisionspec

    outfile.write("\nRevision prefix specifier:\n--------------------------\n")

    for i in bzrlib.revisionspec.SPEC_TYPES:
        doc = i.__doc__
        if doc == bzrlib.revisionspec.RevisionSpec.__doc__:
            doc = "N/A\n"
        while (len(doc) > 2 and doc[-2:]=='\n\n') or (len(doc)>1 and doc[-1]==' '):
            doc = doc[:-1]

        outfile.write("  %s%s" % (i.prefix, doc))


_basic_help= \
"""Bazaar -- a free distributed version-control tool
http://bazaar-vcs.org/

Basic commands:

  bzr init           makes this directory a versioned branch
  bzr branch         make a copy of another branch

  bzr add            make files or directories versioned
  bzr ignore         ignore a file or pattern
  bzr mv             move or rename a versioned file

  bzr status         summarize changes in working copy
  bzr diff           show detailed diffs

  bzr merge          pull in changes from another branch
  bzr commit         save some or all changes

  bzr log            show history of changes
  bzr check          validate storage

  bzr help init      more help on e.g. init command
  bzr help commands  list all commands
  bzr help topics    list all help topics
"""


add_topic("revisionspec", _help_on_revisionspec, "Revisions specifier")
add_topic("basic", _basic_help, "Basic commands")
add_topic("topics", _help_on_topics, "Topics list")


