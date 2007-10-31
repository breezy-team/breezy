#    test_hooks.py -- Tests for builddeb hooks.
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
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
#

import os

from bzrlib.tests import TestCaseInTempDir

from config import DebBuildConfig
from errors import HookFailedError
from hooks import run_hook


class HookTests(TestCaseInTempDir):

  default_conf = 'default.conf'
  local_conf = 'local.conf'

  def test_run_hook_allows_no_hook_defined(self):
    f = open(self.default_conf, 'wb')
    f.close()
    config = DebBuildConfig([(self.default_conf, False)])
    run_hook('pre-build', config)

  def test_run_hook_raises_when_hook_fails(self):
    f = open(self.default_conf, 'wb')
    try:
      f.write('[HOOKS]\npre-build = false\n')
    finally:
      f.close()
    config = DebBuildConfig([(self.default_conf, False)])
    self.assertRaises(HookFailedError, run_hook, 'pre-build', config)

  def test_run_hook_when_hook_passes(self):
    f = open(self.default_conf, 'wb')
    try:
      f.write('[HOOKS]\npre-build = true\n')
    finally:
      f.close()
    config = DebBuildConfig([(self.default_conf, False)])
    run_hook('pre-build', config)

  def test_run_hook_uses_cwd_by_default(self):
    f = open(self.default_conf, 'wb')
    try:
      f.write('[HOOKS]\npre-build = touch a\n')
    finally:
      f.close()
    config = DebBuildConfig([(self.default_conf, False)])
    run_hook('pre-build', config)
    self.failUnlessExists('a')

  def test_run_hook_uses_passed_wd(self):
    os.mkdir('dir')
    f = open(self.default_conf, 'wb')
    try:
      f.write('[HOOKS]\npre-build = touch a\n')
    finally:
      f.close()
    config = DebBuildConfig([(self.default_conf, False)])
    run_hook('pre-build', config, wd='dir')
    self.failUnlessExists('dir/a')

  def test_run_hook_uses_shell(self):
    f = open(self.default_conf, 'wb')
    try:
      f.write('[HOOKS]\npost-build = touch a && touch b\n')
    finally:
      f.close()
    config = DebBuildConfig([(self.default_conf, False)])
    run_hook('post-build', config)
    self.failUnlessExists('a')
    self.failUnlessExists('b')

  def test_run_hook_uses_local_over_global(self):
    f = open(self.default_conf, 'wb')
    try:
      f.write('[HOOKS]\npost-build = touch a\n')
    finally:
      f.close()
    f = open(self.local_conf, 'wb')
    try:
      f.write('[HOOKS]\npost-build = touch b\n')
    finally:
      f.close()
    config = DebBuildConfig([(self.local_conf, False),
                             (self.default_conf, False)])
    run_hook('post-build', config)
    self.failIfExists('a')
    self.failUnlessExists('b')

# vim: ts=2 sts=2 sw=2
