#!/usr/bin/python
# Simple SVN pull / push functionality for bzr
# Copyright (C) 2005 Jelmer Vernooij <jelmer@samba.org>

"""
Push to and pull from SVN repositories
"""
import tempfile
import bzrlib.commands
from bzrlib.branch import Branch
import sys
import os.path
sys.path.append(os.path.dirname(__file__))
from svnbranch import SvnBranch

# Based on set_push_data and get_push_data from bzrtools

def set_svn_location(br, location):
    push_file = file (br.controlfilename("x-svn-repository"), "wb")
    push_file.write("%s\n" % location)

def get_svn_location(br):
    filename = br.controlfilename("x-svn-repository")
    if not os.path.exists(filename):
        return None
    push_file = file (filename, "rb")
    (location,) = [f.rstrip('\n') for f in push_file]
    return location

REVISIONMAP_FILENAME='x-svn-revisionmap'

def save_revisionmap(branch, map):
    import cPickle
    cPickle.dump(map, open(branch.controlfilename(REVISIONMAP_FILENAME), 'wb'))

def load_revisionmap(branch):
    import cPickle
    try:
        return cPickle.load(open(branch.controlfilename(REVISIOMAP_FILENAME), 'rb'))
    except IOError:
        return []

class cmd_svnpush(bzrlib.commands.Command):
    """Push to a SVN repository
    """
    takes_args = ['repository?']
    def run(self, repository=None):
        br = Branch.open_containing(".")

        if not repository:
            repository = get_svn_location(br)
        
        if repository is None:
            print "No svn location saved.  Please specify one on the command line."
            sys.exit(1)

        svnbr = SvnBranch.open(repository)

        # FIXME

        # - for all local revisions that don't have svn:revision set:
        #  - send to remote server
        #  - set bzr:revision as SVN revision property

        pass #FIXME

class cmd_svnpull(bzrlib.commands.Command):
    """Pull from a SVN repository
    """
    takes_args = ['repository?']
    def run(self, repository=None):
        br = Branch.open_containing(".")

        if not repository:
            repository = get_svn_location(br)

        if repository is None:
            print "No svn location saved.  Please specify one on the command line."
            sys.exit(1)

        svnbr = SvnBranch.open(repository)

        tempdir = tempfile.mkdtemp(prefix="bzr-")
        try:
            # FIXME: eliminate None
            merge_inner(br, svnbr, None, tempdir)
        finally:
            shutil.rmtree(tempdir)

commands = [cmd_svnpush, cmd_svnpull]

if hasattr(bzrlib.commands, 'register_command'):
    for command in commands:
        bzrlib.commands.register_command(command)
