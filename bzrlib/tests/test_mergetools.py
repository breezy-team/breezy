# Copyright (C) 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import os
import re
import sys

from bzrlib import (
    config,
    mergetools,
    tests
)
from bzrlib.tests.features import backslashdir_feature


class TestMergeTool(tests.TestCaseInTempDir):
    def test_basics(self):
        mt = mergetools.MergeTool('tool', '/path/to/tool --opt %b -x %t %o --stuff %r')
        self.assertEquals('/path/to/tool --opt %b -x %t %o --stuff %r', mt.get_commandline())
        self.assertEquals(['/path/to/tool', '--opt', '%b', '-x', '%t', '%o',
                           '--stuff', '%r'], mt.get_commandline_as_list())
        self.assertEquals('/path/to/tool', mt.get_executable())
        self.assertEquals('--opt %b -x %t %o --stuff %r', mt.get_arguments())
        self.assertEquals('tool', mt.get_name())
        mt.set_name('bettertool')
        mt.set_commandline('/new/path/to/bettertool %b %t %o %r')
        self.assertEquals('/new/path/to/bettertool %b %t %o %r', mt.get_commandline())
        self.assertEquals(['/new/path/to/bettertool', '%b', '%t', '%o', '%r'],
            mt.get_commandline_as_list())
        self.assertEquals('/new/path/to/bettertool', mt.get_executable())
        self.assertEquals('%b %t %o %r', mt.get_arguments())
        self.assertEquals('bettertool', mt.get_name())
        mt.set_executable('othertool')
        self.assertEquals('othertool', mt.get_executable())
        self.assertEquals('othertool %b %t %o %r', mt.get_commandline())
        self.assertEquals(['othertool', '%b', '%t', '%o', '%r'],
            mt.get_commandline_as_list())
        mt.set_arguments('%r %b %t %o')
        self.assertEquals('%r %b %t %o', mt.get_arguments())
        self.assertEquals('othertool %r %b %t %o', mt.get_commandline())
        self.assertEquals(['othertool', '%r', '%b', '%t', '%o'],
            mt.get_commandline_as_list())
        mt = mergetools.MergeTool(None, '/path/to/tool blah stuff etc')
        self.assertEquals('tool', mt.get_name())
        
    def test_unicode(self):
        mt = mergetools.MergeTool(u'b\u0414r', u'/path/to/b\u0414r --opt %b -x %t %o --stuff %r')
        self.assertEquals(u'/path/to/b\u0414r --opt %b -x %t %o --stuff %r', mt.get_commandline())
        self.assertEquals([u'/path/to/b\u0414r', u'--opt', u'%b', u'-x', u'%t', u'%o',
                           u'--stuff', u'%r'], mt.get_commandline_as_list())
        self.assertEquals(u'/path/to/b\u0414r', mt.get_executable())
        self.assertEquals(u'--opt %b -x %t %o --stuff %r', mt.get_arguments())
        self.assertEquals(u'b\u0414r', mt.get_name())
        mt.set_name(u'b\u0414rs')
        mt.set_commandline(u'/new/path/to/b\u0414rs %b %t %o %r')
        self.assertEquals(u'/new/path/to/b\u0414rs %b %t %o %r', mt.get_commandline())
        self.assertEquals([u'/new/path/to/b\u0414rs', u'%b', u'%t', u'%o', u'%r'],
            mt.get_commandline_as_list())
        self.assertEquals(u'/new/path/to/b\u0414rs', mt.get_executable())
        self.assertEquals(u'%b %t %o %r', mt.get_arguments())
        self.assertEquals(u'b\u0414rs', mt.get_name())
        mt.set_executable(u'b\u0414rst')
        self.assertEquals(u'b\u0414rst', mt.get_executable())
        self.assertEquals(u'b\u0414rst %b %t %o %r', mt.get_commandline())
        self.assertEquals([u'b\u0414rst', u'%b', u'%t', u'%o', u'%r'],
            mt.get_commandline_as_list())
        mt.set_arguments(u'%r %b %t %o')
        self.assertEquals(u'%r %b %t %o', mt.get_arguments())
        self.assertEquals(u'b\u0414rst %r %b %t %o', mt.get_commandline())
        self.assertEquals([u'b\u0414rst', u'%r', u'%b', u'%t', u'%o'],
            mt.get_commandline_as_list())
        mt = mergetools.MergeTool(None, u'/path/to/b\u0414r blah stuff etc')
        self.assertEquals(u'b\u0414r', mt.get_name())
        
    def test_quoted_executable(self):
        self.requireFeature(backslashdir_feature)
        mt = mergetools.MergeTool('kdiff3', '"C:\\Program Files\\KDiff3\\kdiff3.exe" %b %t %o -o %r')
        self.assertEquals('kdiff3', mt.get_name())

    def test_filename_substitution(self):
        def dummy_invoker(executable, args, cleanup):
            self._commandline = [executable] + args
            cleanup(0)
        mt = mergetools.MergeTool('kdiff3', 'kdiff3 %b %t %o -o %r')
        mt.invoke('test.txt', dummy_invoker)
        self.assertEquals(
            ['kdiff3',
             'test.txt.BASE',
             'test.txt.THIS',
             'test.txt.OTHER',
             '-o',
             'test.txt'],
            self._commandline)
        mt.invoke('file with space.txt', dummy_invoker)
        self.assertEquals(
            ['kdiff3',
             "file with space.txt.BASE",
             "file with space.txt.THIS",
             "file with space.txt.OTHER",
             '-o',
             "file with space.txt"],
            self._commandline)
        mt.invoke('file with "space and quotes".txt', dummy_invoker)
        self.assertEquals(
            ['kdiff3',
             "file with \"space and quotes\".txt.BASE",
             "file with \"space and quotes\".txt.THIS",
             "file with \"space and quotes\".txt.OTHER",
             '-o',
             "file with \"space and quotes\".txt"],
            self._commandline)
        
    def test_expand_commandline_tempfile(self):
        def dummy_invoker(executable, args, cleanup):
            self.assertEquals('some_tool', executable)
            self.failUnlessExists(args[0])
            cleanup(0)
            self._tmp_file = args[0]
        self.build_tree(('test.txt', 'test.txt.BASE', 'test.txt.THIS',
                         'test.txt.OTHER'))
        mt = mergetools.MergeTool('some_tool', 'some_tool %T')
        mt.invoke('test.txt', dummy_invoker)
        self.failIfExists(self._tmp_file)
        
    def test_is_available(self):
        mt = mergetools.MergeTool(sys.executable, sys.executable)
        self.assertTrue(mt.is_available())
        mt.set_executable(os.path.basename(sys.executable))
        self.assertTrue(mt.is_available())
        mt.set_executable("ThisExecutableShouldReallyNotExist")
        self.assertFalse(mt.is_available())
        
    def test_empty_commandline(self):
        mt = mergetools.MergeTool('', '')
        self.assertEquals('', mt.get_executable())
        self.assertEquals('', mt.get_arguments())
        
    def test_no_arguments(self):
        mt = mergetools.MergeTool('tool', 'tool')
        self.assertEquals('tool', mt.get_executable())
        self.assertEquals('', mt.get_arguments())
        
    def test_get_merge_tools(self):
        conf = FakeConfig()
        conf.set_user_option('mergetools', 'kdiff3,winmergeu,funkytool')
        conf.set_user_option('mergetools.kdiff3', 'kdiff3 %b %t %o -o %r')
        conf.set_user_option('mergetools.winmergeu', 'winmergeu %r')
        conf.set_user_option('mergetools.funkytool', 'funkytool "arg with spaces" %T')
        tools = mergetools.get_merge_tools(conf)
        self.assertEquals(3, len(tools))
        self.assertEquals('kdiff3', tools[0].get_name())
        self.assertEquals('kdiff3 %b %t %o -o %r', tools[0].get_commandline())
        self.assertEquals('winmergeu', tools[1].get_name())
        self.assertEquals('winmergeu %r', tools[1].get_commandline())
        self.assertEquals('funkytool', tools[2].get_name())
        self.assertEquals('funkytool "arg with spaces" %T',
                          tools[2].get_commandline(quote=True))
        
    def test_set_merge_tools(self):
        conf = FakeConfig()
        tools = [mergetools.MergeTool('kdiff3', 'kdiff3 %b %t %o -o %r'),
                 mergetools.MergeTool('winmergeu', 'winmergeu %r'),
                 mergetools.MergeTool('funkytool',
                                      'funkytool "arg with spaces" %T')
                 ]
        mergetools.set_merge_tools(tools, conf)
        self.assertEquals(['funkytool', 'kdiff3', 'winmergeu'],
            conf.get_user_option_as_list('mergetools'))
        self.assertEquals('funkytool "arg with spaces" %T',
                          conf.get_user_option('mergetools.funkytool'))
        self.assertEquals('kdiff3 %b %t %o -o %r',
                          conf.get_user_option('mergetools.kdiff3'))
        self.assertEquals('winmergeu %r',
                          conf.get_user_option('mergetools.winmergeu'))
    
    def test_set_merge_tools_duplicates(self):
        conf = FakeConfig()
        mergetools.set_merge_tools(
            [mergetools.MergeTool('kdiff3', 'kdiff3 %b %t %o -o %r'),
             mergetools.MergeTool('kdiff3', 'kdiff3 %b %t %o -o %r')],
            conf)
        tools = mergetools.get_merge_tools(conf)
        self.assertEquals(1, len(tools))
        self.assertEquals('kdiff3', tools[0].get_name())
        self.assertEquals('kdiff3 %b %t %o -o %r', tools[0].get_commandline())
        
    def test_set_merge_tools_empty_tool(self):
        conf = FakeConfig()
        mergetools.set_merge_tools(
            [mergetools.MergeTool('kdiff3', 'kdiff3 %b %t %o -o %r'),
             mergetools.MergeTool('',''),
             mergetools.MergeTool('blah','')],
            conf)
        tools = mergetools.get_merge_tools(conf)
        self.assertEquals(1, len(tools))
        self.assertEquals('kdiff3', tools[0].get_name())
        self.assertEquals('kdiff3 %b %t %o -o %r', tools[0].get_commandline())

    def test_detect(self):
        # only way to reliably test detection is to add a known existing
        # executable to the list used for detection
        old_kmt = mergetools._KNOWN_MERGE_TOOLS
        mergetools._KNOWN_MERGE_TOOLS = ['sh', 'cmd']
        tools = mergetools.detect_merge_tools()
        tools_commandlines = [mt.get_commandline() for mt in tools]
        self.assertTrue('sh' in tools_commandlines or
                        'cmd' in tools_commandlines)
        mergetools._KNOWN_MERGE_TOOLS = old_kmt


class FakeConfig(object):
    """
    Just enough of the Config interface to fool the mergetools module.
    """
    def __init__(self):
        self.options = {}
        
    def get_user_option(self, option):
        return self.options[option]
        
    def get_user_option_as_list(self, option):
        return self.options[option].split(',')
    
    def set_user_option(self, option, value):
        if isinstance(value, tuple) or isinstance(value, list):
            self.options[option] = ','.join(value)
        else:
            self.options[option] = value
