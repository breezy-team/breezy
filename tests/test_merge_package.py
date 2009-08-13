#!/usr/bin/env python
# -*- coding: iso-8859-15 -*-
#    test_merge_package.py -- Merge packaging branches, fix ancestry as needed.
#    Copyright (C) 2008 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import os
import unittest

from debian_bundle.changelog import Version
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree

_Debian_changelog = ['''\
ipsec-tools (1:0.7.1-1.5) unstable; urgency=high

  * Non-maintainer upload by the Security Team.
  * Fix multiple memory leaks in NAT traversal and RSA authentication
    code of racoon leading to DoS because (CVE-2009-1632; Closes: #528933).

 -- Nico Golde <nion@debian.org>  Tue, 19 May 2009 13:26:14 +0200
'''
,
'''
ipsec-tools (1:0.7.1-1.3) unstable; urgency=low

  * Non-maintainer upload
  * Racoon should depend on at least the current version of ipsec-tools
    (Closes: #507071)

 -- Evan Broder <broder@mit.edu>  Sat, 13 Dec 2008 15:40:55 -0500
'''
,
'''
ipsec-tools (1:0.5-5) unstable; urgency=high

  * Fix ISAKMP Header Parsing DoS bug (closes: #299716). 
  * Quote URL in README.Debian to avoid confusion (closes: #297179).

 -- Ganesan Rajagopal <rganesan@debian.org>  Wed, 16 Mar 2005 09:31:30 +0530
'''
,
'''
ipsec-tools (0.3.3-1) unstable; urgency=high

  * Security upload.  Updated to vesion 0.3.3 which fixes a "authentication
    bug in KAME's racoon" in eay_check_x509cert() (Bugtraq
    http://seclists.org/lists/bugtraq/2004/Jun/0219.html) (closes: #254663).
  * Fix for "racooninit" in racoon-tool.conf.  Applied patch submitted by
    Teddy Hogeborn <teddy@fukt.bth.se>. (closes: #249222)
  * Stopped patching racoon.conf.5 manpage as the "Japlish" fix is now in the
    source tree.

 -- Matthew Grant <grantma@anathoth.gen.nz>  Thu, 17 Jun 2004 09:05:50 +1200
'''
,
'''
ipsec-tools (0.3.3) unstable; urgency=high

  * Import upstream version 0.3.3

 -- Matthew Grant <grantma@anathoth.gen.nz>  Thu, 17 Jun 2004 09:05:50 +1200
''']

_Ubuntu_changelog = ['''
ipsec-tools (1:0.7.1-1.5ubuntu1) karmic; urgency=low

  * Merge from debian unstable, remaining changes:
    - debian/control:
      - Set Ubuntu maintainer address.
      - Depend on lsb-base.
    - debian/ipsec-tools.setkey.init: LSB init script.
    - debian/rules: build with -fno-strict-aliasing, required with gcc 4.4.
    - Enable build with hardened options:
      - src/setkey/setkey.c: stop scanning stdin if fgets fails.
  * Dropped
    - src/libipsec/policy_token.c: don't check return code of fwrite.

 -- Jamie Strandboge <jamie@ubuntu.com>  Fri, 24 Jul 2009 13:24:17 -0500

'''
,
'''
ipsec-tools (1:0.7.1-1.3ubuntu1) karmic; urgency=low

  * debian/rules: build with -fno-strict-aliasing, required with gcc 4.4.

 -- Steve Langasek <steve.langasek@ubuntu.com>  Tue, 21 Jul 2009 18:33:13 +0000

'''
,
'''
ipsec-tools (1:0.6.5-0ubuntu1) dapper; urgency=low

  * New upstream release.
  * Added debconf-updatepo in clean target (closes: #372910).
  * Compiled with PAM support (closes: #299806, #371053).
  * Fixed typo in racoon.templates and corresponding po files.
  * Updated Brazilian Portugese, Vietnamese, Swedish, French and Czech 
    translations for debconf templates (closes: #370148, #369409).

 -- Martin Pitt <martin.pitt@ubuntu.com>  Tue,  9 May 2006 11:33:01 +0200

'''
,
'''
ipsec-tools (1:0.5-5ubuntu1) breezy; urgency=low

  * No-change rebuild against libkrb5-3.

 -- LaMont Jones <lamont@ubuntu.com>  Wed, 28 Sep 2005 18:33:52 -0600

''']


def _merge_log(strings):
    result = ""
    for s in strings:
        result += s
    return result


class MergePackageTests(TestCaseWithTransport):

    def set_file_content(self, path, content):
        f = open(path, 'wb')
        try:
            f.write(content)
        finally:
            f.close()

    def test_debian_upstream_newer(self):
        # Set up debian upstream branch.
        debu_tree = self.make_branch_and_tree('debu')
        self.build_tree(['debu/a'])
        debu_tree.add(['a'], ['a-id'])
        revid_debu_A = debu_tree.commit('add a', rev_id='du-1')
        debu_tree.branch.tags.set_tag('upstream-0.3.3', revid_debu_A)

        self.build_tree(['debu/b'])
        debu_tree.add(['b'], ['b-id'])
        revid_debu_B = debu_tree.commit('add b', rev_id='du-2')
        debu_tree.branch.tags.set_tag('upstream-0.5', revid_debu_B)

        self.build_tree(['debu/c'])
        debu_tree.add(['c'], ['c-id'])
        self.build_tree_contents(
            [('debu/b', 'Debian upstream contents for b\n')])
        revid_debu_C = debu_tree.commit('add h', rev_id='du-3')
        debu_tree.branch.tags.set_tag('upstream-0.7.1', revid_debu_C)

        # Set up ubuntu upstream branch.
        ubuu_tree = debu_tree.bzrdir.sprout(
            'ubuu', revision_id=revid_debu_B).open_workingtree()

        self.build_tree_contents(
            [('ubuu/b', 'Ubuntu upstream contents for b\n')])
        revid_ubuu_A = ubuu_tree.commit('modifying b', rev_id='uu-1')
        ubuu_tree.branch.tags.set_tag('upstream-0.6.5', revid_ubuu_A)

        # Set up debian packaging branch.
        debp_tree = self.make_branch_and_tree('debp')
        debp_tree.pull(debu_tree.branch, stop_revision=revid_debu_A)

        self.build_tree(['debp/debian/', 'debp/debian/changelog'])
        debp_tree.add(['debian/', 'debian/changelog'])
        self.build_tree_contents(
            [('debp/debian/changelog', _merge_log(_Debian_changelog[-2:]))])
        revid_debp_A = debp_tree.commit('add debian/changelog', rev_id='dp-1')
        debp_tree.branch.tags.set_tag('0.3.3-1', revid_debp_A)

        debp_tree.merge_from_branch(
            debu_tree.branch, to_revision=revid_debu_B)
        self.build_tree_contents(
            [('debp/debian/changelog', _merge_log(_Debian_changelog[-3:]))])
        revid_debp_B = debp_tree.commit(
            'modify debian/changelog', rev_id='dp-2')
        debp_tree.branch.tags.set_tag('1:0.5-5', revid_debp_B)

        debp_tree.merge_from_branch(
            debu_tree.branch, to_revision=revid_debu_C)
        self.build_tree_contents(
            [('debp/debian/changelog', _merge_log(_Debian_changelog[-4:]))])
        revid_debp_C = debp_tree.commit(
            'modify debian/changelog', rev_id='dp-3')
        debp_tree.branch.tags.set_tag('1:0.7.1-1.3', revid_debp_C)

        self.build_tree_contents(
            [('debp/debian/changelog', _merge_log(_Debian_changelog))])
        revid_debp_D = debp_tree.commit(
            'modify debian/changelog', rev_id='dp-4')
        debp_tree.branch.tags.set_tag('1:0.7.1-1.5', revid_debp_D)

        # Set up ubuntu packaging branch.
        ubup_tree = self.make_branch_and_tree('ubup')
        ubup_tree.pull(ubuu_tree.branch, stop_revision=revid_debu_A)
        conflicts = ubup_tree.merge_from_branch(
            debp_tree.branch, to_revision=revid_debp_A)
        print("\n-> conflicts = %s\n" % conflicts)
        revid_ubup_A = ubup_tree.commit(
            'merged from debian (0.3.3-1)', rev_id='up-1')
        ubup_tree.branch.tags.set_tag('0.3.3-1ubuntu1', revid_ubup_A)

        import pdb
        pdb.set_trace()
        import sys
        sys.exit(1)


if __name__ == '__main__':
    unittest.main()
