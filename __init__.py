#!/usr/bin/python
# Simple SVN pull / push functionality for bzr
# Copyright (C) 2005 Jelmer Vernooij <jelmer@samba.org>
# Published under the GNU GPL

"""
Push to and pull from SVN repositories
"""
from bzrlib.branch import register_branch_type
import sys
import os.path

sys.path.append(os.path.dirname(__file__))

from svnbranch import SvnBranch, SvnBranch

register_branch_type(SvnBranch)
