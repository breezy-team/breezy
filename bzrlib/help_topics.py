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

import textwrap
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

def help_topics(name, outfile):
    topics=get_topics_list( )
    for i in topics:
        outfile.write("%s\n        %s\n"%(i,topics[i]))

def help_revisions(name, outfile):
    import revisionspec
    outfile.write("\nRevision prefix specifier:\n--------------------------\n")

    for i in revisionspec.SPEC_TYPES:
        doc = i.__doc__
        if doc == revisionspec.RevisionSpec.__doc__:
            doc = "N/A\n"
        while (len(doc) > 2 and doc[-2:]=='\n\n') or ( len(doc)>1 and doc[-1]==' '):
            doc = doc[:-1]

        outfile.write("  %s%s"%(i.prefix,doc))

global_help = \
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
"""

add_topic("revisionspec",help_revisions,"Revisions specifier")
add_topic("global_help", global_help, "Basic commands")
add_topic("topics", help_topics, "Topics list")


