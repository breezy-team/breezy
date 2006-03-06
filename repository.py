# Foreign branch support for Subversion
# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL

from bzrlib.repository import Repository
import bzrlib

"""
Provides a simplified interface to a Subversion repository 
by using the RA (remote access) API from subversion
"""
class SvnRepository(Repository):
	pass
