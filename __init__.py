#!/usr/bin/python
# Simple SVN pull / push functionality for bzr
# Copyright (C) 2005 Jelmer Vernooij <jelmer@samba.org>

"""
Push to and pull from SVN repositories
"""
from bzrlib.branch import register_branch_type
import sys
import os.path

sys.path.append(os.path.dirname(__file__))

from svnbranch import SvnBranch

register_branch_type(SvnBranch)
