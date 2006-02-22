# Copyright (C) 2005 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Tests for finding and reading the bzr config file[s]."""
# import system imports here
from bzrlib.util.configobj.configobj import ConfigObj, ConfigObjError
from cStringIO import StringIO
import os
import sys

#import bzrlib specific imports here
import bzrlib.config as config
import bzrlib.errors as errors
from bzrlib.tests import TestCase, TestCaseInTempDir


sample_long_alias="log -r-15..-1 --line"
sample_config_text = ("[DEFAULT]\n"
                      "email=Robert Collins <robertc@example.com>\n"
                      "editor=vim\n"
                      "gpg_signing_command=gnome-gpg\n"
                      "log_format=short\n"
                      "user_global_option=something\n"
                      "[ALIASES]\n"
                      "h=help\n"
                      "ll=" + sample_long_alias + "\n")


sample_always_signatures = ("[DEFAULT]\n"
                            "check_signatures=require\n")


sample_ignore_signatures = ("[DEFAULT]\n"
                            "check_signatures=ignore\n")


sample_maybe_signatures = ("[DEFAULT]\n"
                            "check_signatures=check-available\n")


sample_branches_text = ("[http://www.example.com]\n"
                        "# Top level policy\n"
                        "email=Robert Collins <robertc@example.org>\n"
                        "[http://www.example.com/useglobal]\n"
                        "# different project, forces global lookup\n"
                        "recurse=false\n"
                        "[/b/]\n"
                        "check_signatures=require\n"
                        "# test trailing / matching with no children\n"
                        "[/a/]\n"
                        "check_signatures=check-available\n"
                        "gpg_signing_command=false\n"
                        "user_local_option=local\n"
                        "# test trailing / matching\n"
                        "[/a/*]\n"
                        "#subdirs will match but not the parent\n"
                        "recurse=False\n"
                        "[/a/c]\n"
                        "check_signatures=ignore\n"
                        "post_commit=bzrlib.tests.test_config.post_commit\n"
                        "#testing explicit beats globs\n")



class InstrumentedConfigObj(object):
    """A config obj look-enough-alike to record calls made to it."""

    def __contains__(self, thing):
        self._calls.append(('__contains__', thing))
        return False

    def __getitem__(self, key):
        self._calls.append(('__getitem__', key))
        return self

    def __init__(self, input):
        self._calls = [('__init__', input)]

    def __setitem__(self, key, value):
        self._calls.append(('__setitem__', key, value))

    def write(self):
        self._calls.append(('write',))


class FakeBranch(object):

    def __init__(self):
        self.base = "http://example.com/branches/demo"
        self.control_files = FakeControlFiles()


class FakeControlFiles(object):

    def __init__(self):
        self.email = 'Robert Collins <robertc@example.net>\n'

    def get_utf8(self, filename):
        if filename != 'email':
            raise NotImplementedError
        if self.email is not None:
            return StringIO(self.email)
        raise errors.NoSuchFile(filename)


class InstrumentedConfig(config.Config):
    """An instrumented config that supplies stubs for template methods."""
    
    def __init__(self):
        super(InstrumentedConfig, self).__init__()
        self._calls = []
        self._signatures = config.CHECK_NEVER

    def _get_user_id(self):
        self._calls.append('_get_user_id')
        return "Robert Collins <robert.collins@example.org>"

    def _get_signature_checking(self):
        self._calls.append('_get_signature_checking')
        return self._signatures


class TestConfig(TestCase):

    def test_constructs(self):
        config.Config()
 
    def test_no_default_editor(self):
        self.assertRaises(NotImplementedError, config.Config().get_editor)

    def test_user_email(self):
        my_config = InstrumentedConfig()
        self.assertEqual('robert.collins@example.org', my_config.user_email())
        self.assertEqual(['_get_user_id'], my_config._calls)

    def test_username(self):
        my_config = InstrumentedConfig()
        self.assertEqual('Robert Collins <robert.collins@example.org>',
                         my_config.username())
        self.assertEqual(['_get_user_id'], my_config._calls)

    def test_signatures_default(self):
        my_config = config.Config()
        self.assertEqual(config.CHECK_IF_POSSIBLE,
                         my_config.signature_checking())

    def test_signatures_template_method(self):
        my_config = InstrumentedConfig()
        self.assertEqual(config.CHECK_NEVER, my_config.signature_checking())
        self.assertEqual(['_get_signature_checking'], my_config._calls)

    def test_signatures_template_method_none(self):
        my_config = InstrumentedConfig()
        my_config._signatures = None
        self.assertEqual(config.CHECK_IF_POSSIBLE,
                         my_config.signature_checking())
        self.assertEqual(['_get_signature_checking'], my_config._calls)

    def test_gpg_signing_command_default(self):
        my_config = config.Config()
        self.assertEqual('gpg', my_config.gpg_signing_command())

    def test_get_user_option_default(self):
        my_config = config.Config()
        self.assertEqual(None, my_config.get_user_option('no_option'))

    def test_post_commit_default(self):
        my_config = config.Config()
        self.assertEqual(None, my_config.post_commit())

    def test_log_format_default(self):
        my_config = config.Config()
        self.assertEqual('long', my_config.log_format())


class TestConfigPath(TestCase):

    def setUp(self):
        super(TestConfigPath, self).setUp()
        self.old_home = os.environ.get('HOME', None)
        self.old_appdata = os.environ.get('APPDATA', None)
        os.environ['HOME'] = '/home/bogus'
        os.environ['APPDATA'] = \
            r'C:\Documents and Settings\bogus\Application Data'

    def tearDown(self):
        if self.old_home is None:
            del os.environ['HOME']
        else:
            os.environ['HOME'] = self.old_home
        if self.old_appdata is None:
            del os.environ['APPDATA']
        else:
            os.environ['APPDATA'] = self.old_appdata
        super(TestConfigPath, self).tearDown()
    
    def test_config_dir(self):
        if sys.platform == 'win32':
            self.assertEqual(config.config_dir(), 
                'C:/Documents and Settings/bogus/Application Data/bazaar/2.0')
        else:
            self.assertEqual(config.config_dir(), '/home/bogus/.bazaar')

    def test_config_filename(self):
        if sys.platform == 'win32':
            self.assertEqual(config.config_filename(), 
                'C:/Documents and Settings/bogus/Application Data/bazaar/2.0/bazaar.conf')
        else:
            self.assertEqual(config.config_filename(),
                             '/home/bogus/.bazaar/bazaar.conf')

    def test_branches_config_filename(self):
        if sys.platform == 'win32':
            self.assertEqual(config.branches_config_filename(), 
                'C:/Documents and Settings/bogus/Application Data/bazaar/2.0/branches.conf')
        else:
            self.assertEqual(config.branches_config_filename(),
                             '/home/bogus/.bazaar/branches.conf')

class TestIniConfig(TestCase):

    def test_contructs(self):
        my_config = config.IniBasedConfig("nothing")

    def test_from_fp(self):
        config_file = StringIO(sample_config_text)
        my_config = config.IniBasedConfig(None)
        self.failUnless(
            isinstance(my_config._get_parser(file=config_file),
                        ConfigObj))

    def test_cached(self):
        config_file = StringIO(sample_config_text)
        my_config = config.IniBasedConfig(None)
        parser = my_config._get_parser(file=config_file)
        self.failUnless(my_config._get_parser() is parser)


class TestGetConfig(TestCase):

    def test_constructs(self):
        my_config = config.GlobalConfig()

    def test_calls_read_filenames(self):
        # replace the class that is constructured, to check its parameters
        oldparserclass = config.ConfigObj
        config.ConfigObj = InstrumentedConfigObj
        my_config = config.GlobalConfig()
        try:
            parser = my_config._get_parser()
        finally:
            config.ConfigObj = oldparserclass
        self.failUnless(isinstance(parser, InstrumentedConfigObj))
        self.assertEqual(parser._calls, [('__init__', config.config_filename())])


class TestBranchConfig(TestCaseInTempDir):

    def test_constructs(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        self.assertRaises(TypeError, config.BranchConfig)

    def test_get_location_config(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        location_config = my_config._get_location_config()
        self.assertEqual(branch.base, location_config.location)
        self.failUnless(location_config is my_config._get_location_config())


class TestGlobalConfigItems(TestCase):

    def test_user_id(self):
        config_file = StringIO(sample_config_text)
        my_config = config.GlobalConfig()
        my_config._parser = my_config._get_parser(file=config_file)
        self.assertEqual("Robert Collins <robertc@example.com>",
                         my_config._get_user_id())

    def test_absent_user_id(self):
        config_file = StringIO("")
        my_config = config.GlobalConfig()
        my_config._parser = my_config._get_parser(file=config_file)
        self.assertEqual(None, my_config._get_user_id())

    def test_configured_editor(self):
        config_file = StringIO(sample_config_text)
        my_config = config.GlobalConfig()
        my_config._parser = my_config._get_parser(file=config_file)
        self.assertEqual("vim", my_config.get_editor())

    def test_signatures_always(self):
        config_file = StringIO(sample_always_signatures)
        my_config = config.GlobalConfig()
        my_config._parser = my_config._get_parser(file=config_file)
        self.assertEqual(config.CHECK_ALWAYS,
                         my_config.signature_checking())
        self.assertEqual(True, my_config.signature_needed())

    def test_signatures_if_possible(self):
        config_file = StringIO(sample_maybe_signatures)
        my_config = config.GlobalConfig()
        my_config._parser = my_config._get_parser(file=config_file)
        self.assertEqual(config.CHECK_IF_POSSIBLE,
                         my_config.signature_checking())
        self.assertEqual(False, my_config.signature_needed())

    def test_signatures_ignore(self):
        config_file = StringIO(sample_ignore_signatures)
        my_config = config.GlobalConfig()
        my_config._parser = my_config._get_parser(file=config_file)
        self.assertEqual(config.CHECK_NEVER,
                         my_config.signature_checking())
        self.assertEqual(False, my_config.signature_needed())

    def _get_sample_config(self):
        config_file = StringIO(sample_config_text)
        my_config = config.GlobalConfig()
        my_config._parser = my_config._get_parser(file=config_file)
        return my_config

    def test_gpg_signing_command(self):
        my_config = self._get_sample_config()
        self.assertEqual("gnome-gpg", my_config.gpg_signing_command())
        self.assertEqual(False, my_config.signature_needed())

    def _get_empty_config(self):
        config_file = StringIO("")
        my_config = config.GlobalConfig()
        my_config._parser = my_config._get_parser(file=config_file)
        return my_config

    def test_gpg_signing_command_unset(self):
        my_config = self._get_empty_config()
        self.assertEqual("gpg", my_config.gpg_signing_command())

    def test_get_user_option_default(self):
        my_config = self._get_empty_config()
        self.assertEqual(None, my_config.get_user_option('no_option'))

    def test_get_user_option_global(self):
        my_config = self._get_sample_config()
        self.assertEqual("something",
                         my_config.get_user_option('user_global_option'))
        
    def test_post_commit_default(self):
        my_config = self._get_sample_config()
        self.assertEqual(None, my_config.post_commit())

    def test_configured_logformat(self):
        my_config = self._get_sample_config()
        self.assertEqual("short", my_config.log_format())

    def test_get_alias(self):
        my_config = self._get_sample_config()
        self.assertEqual('help', my_config.get_alias('h'))

    def test_get_no_alias(self):
        my_config = self._get_sample_config()
        self.assertEqual(None, my_config.get_alias('foo'))

    def test_get_long_alias(self):
        my_config = self._get_sample_config()
        self.assertEqual(sample_long_alias, my_config.get_alias('ll'))

class TestLocationConfig(TestCase):

    def test_constructs(self):
        my_config = config.LocationConfig('http://example.com')
        self.assertRaises(TypeError, config.LocationConfig)

    def test_branch_calls_read_filenames(self):
        # This is testing the correct file names are provided.
        # TODO: consolidate with the test for GlobalConfigs filename checks.
        #
        # replace the class that is constructured, to check its parameters
        oldparserclass = config.ConfigObj
        config.ConfigObj = InstrumentedConfigObj
        my_config = config.LocationConfig('http://www.example.com')
        try:
            parser = my_config._get_parser()
        finally:
            config.ConfigObj = oldparserclass
        self.failUnless(isinstance(parser, InstrumentedConfigObj))
        self.assertEqual(parser._calls,
                         [('__init__', config.branches_config_filename())])

    def test_get_global_config(self):
        my_config = config.LocationConfig('http://example.com')
        global_config = my_config._get_global_config()
        self.failUnless(isinstance(global_config, config.GlobalConfig))
        self.failUnless(global_config is my_config._get_global_config())

    def test__get_section_no_match(self):
        self.get_location_config('/')
        self.assertEqual(None, self.my_config._get_section())
        
    def test__get_section_exact(self):
        self.get_location_config('http://www.example.com')
        self.assertEqual('http://www.example.com',
                         self.my_config._get_section())
   
    def test__get_section_suffix_does_not(self):
        self.get_location_config('http://www.example.com-com')
        self.assertEqual(None, self.my_config._get_section())

    def test__get_section_subdir_recursive(self):
        self.get_location_config('http://www.example.com/com')
        self.assertEqual('http://www.example.com',
                         self.my_config._get_section())

    def test__get_section_subdir_matches(self):
        self.get_location_config('http://www.example.com/useglobal')
        self.assertEqual('http://www.example.com/useglobal',
                         self.my_config._get_section())

    def test__get_section_subdir_nonrecursive(self):
        self.get_location_config(
            'http://www.example.com/useglobal/childbranch')
        self.assertEqual('http://www.example.com',
                         self.my_config._get_section())

    def test__get_section_subdir_trailing_slash(self):
        self.get_location_config('/b')
        self.assertEqual('/b/', self.my_config._get_section())

    def test__get_section_subdir_child(self):
        self.get_location_config('/a/foo')
        self.assertEqual('/a/*', self.my_config._get_section())

    def test__get_section_subdir_child_child(self):
        self.get_location_config('/a/foo/bar')
        self.assertEqual('/a/', self.my_config._get_section())

    def test__get_section_trailing_slash_with_children(self):
        self.get_location_config('/a/')
        self.assertEqual('/a/', self.my_config._get_section())

    def test__get_section_explicit_over_glob(self):
        self.get_location_config('/a/c')
        self.assertEqual('/a/c', self.my_config._get_section())

    def get_location_config(self, location, global_config=None):
        if global_config is None:
            global_file = StringIO(sample_config_text)
        else:
            global_file = StringIO(global_config)
        branches_file = StringIO(sample_branches_text)
        self.my_config = config.LocationConfig(location)
        self.my_config._get_parser(branches_file)
        self.my_config._get_global_config()._get_parser(global_file)

    def test_location_without_username(self):
        self.get_location_config('http://www.example.com/useglobal')
        self.assertEqual('Robert Collins <robertc@example.com>',
                         self.my_config.username())

    def test_location_not_listed(self):
        self.get_location_config('/home/robertc/sources')
        self.assertEqual('Robert Collins <robertc@example.com>',
                         self.my_config.username())

    def test_overriding_location(self):
        self.get_location_config('http://www.example.com/foo')
        self.assertEqual('Robert Collins <robertc@example.org>',
                         self.my_config.username())

    def test_signatures_not_set(self):
        self.get_location_config('http://www.example.com',
                                 global_config=sample_ignore_signatures)
        self.assertEqual(config.CHECK_NEVER,
                         self.my_config.signature_checking())

    def test_signatures_never(self):
        self.get_location_config('/a/c')
        self.assertEqual(config.CHECK_NEVER,
                         self.my_config.signature_checking())
        
    def test_signatures_when_available(self):
        self.get_location_config('/a/', global_config=sample_ignore_signatures)
        self.assertEqual(config.CHECK_IF_POSSIBLE,
                         self.my_config.signature_checking())
        
    def test_signatures_always(self):
        self.get_location_config('/b')
        self.assertEqual(config.CHECK_ALWAYS,
                         self.my_config.signature_checking())
        
    def test_gpg_signing_command(self):
        self.get_location_config('/b')
        self.assertEqual("gnome-gpg", self.my_config.gpg_signing_command())

    def test_gpg_signing_command_missing(self):
        self.get_location_config('/a')
        self.assertEqual("false", self.my_config.gpg_signing_command())

    def test_get_user_option_global(self):
        self.get_location_config('/a')
        self.assertEqual('something',
                         self.my_config.get_user_option('user_global_option'))

    def test_get_user_option_local(self):
        self.get_location_config('/a')
        self.assertEqual('local',
                         self.my_config.get_user_option('user_local_option'))
        
    def test_post_commit_default(self):
        self.get_location_config('/a/c')
        self.assertEqual('bzrlib.tests.test_config.post_commit',
                         self.my_config.post_commit())


class TestLocationConfig(TestCaseInTempDir):

    def get_location_config(self, location, global_config=None):
        if global_config is None:
            global_file = StringIO(sample_config_text)
        else:
            global_file = StringIO(global_config)
        branches_file = StringIO(sample_branches_text)
        self.my_config = config.LocationConfig(location)
        self.my_config._get_parser(branches_file)
        self.my_config._get_global_config()._get_parser(global_file)

    def test_set_user_setting_sets_and_saves(self):
        self.get_location_config('/a/c')
        record = InstrumentedConfigObj("foo")
        self.my_config._parser = record

        real_mkdir = os.mkdir
        self.created = False
        def checked_mkdir(path, mode=0777):
            self.log('making directory: %s', path)
            real_mkdir(path, mode)
            self.created = True

        os.mkdir = checked_mkdir
        try:
            self.my_config.set_user_option('foo', 'bar')
        finally:
            os.mkdir = real_mkdir

        self.failUnless(self.created, 'Failed to create ~/.bazaar')
        self.assertEqual([('__contains__', '/a/c'),
                          ('__contains__', '/a/c/'),
                          ('__setitem__', '/a/c', {}),
                          ('__getitem__', '/a/c'),
                          ('__setitem__', 'foo', 'bar'),
                          ('write',)],
                         record._calls[1:])


class TestBranchConfigItems(TestCase):

    def test_user_id(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        self.assertEqual("Robert Collins <robertc@example.net>",
                         my_config._get_user_id())
        branch.control_files.email = "John"
        self.assertEqual("John", my_config._get_user_id())

    def test_not_set_in_branch(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        branch.control_files.email = None
        config_file = StringIO(sample_config_text)
        (my_config._get_location_config().
            _get_global_config()._get_parser(config_file))
        self.assertEqual("Robert Collins <robertc@example.com>",
                         my_config._get_user_id())
        branch.control_files.email = "John"
        self.assertEqual("John", my_config._get_user_id())

    def test_BZREMAIL_OVERRIDES(self):
        os.environ['BZREMAIL'] = "Robert Collins <robertc@example.org>"
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        self.assertEqual("Robert Collins <robertc@example.org>",
                         my_config.username())
    
    def test_signatures_forced(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        config_file = StringIO(sample_always_signatures)
        (my_config._get_location_config().
            _get_global_config()._get_parser(config_file))
        self.assertEqual(config.CHECK_ALWAYS, my_config.signature_checking())

    def test_gpg_signing_command(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        config_file = StringIO(sample_config_text)
        (my_config._get_location_config().
            _get_global_config()._get_parser(config_file))
        self.assertEqual('gnome-gpg', my_config.gpg_signing_command())

    def test_get_user_option_global(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        config_file = StringIO(sample_config_text)
        (my_config._get_location_config().
            _get_global_config()._get_parser(config_file))
        self.assertEqual('something',
                         my_config.get_user_option('user_global_option'))

    def test_post_commit_default(self):
        branch = FakeBranch()
        branch.base='/a/c'
        my_config = config.BranchConfig(branch)
        config_file = StringIO(sample_config_text)
        (my_config._get_location_config().
            _get_global_config()._get_parser(config_file))
        branch_file = StringIO(sample_branches_text)
        my_config._get_location_config()._get_parser(branch_file)
        self.assertEqual('bzrlib.tests.test_config.post_commit',
                         my_config.post_commit())


class TestMailAddressExtraction(TestCase):

    def test_extract_email_address(self):
        self.assertEqual('jane@test.com',
                         config.extract_email_address('Jane <jane@test.com>'))
        self.assertRaises(errors.BzrError,
                          config.extract_email_address, 'Jane Tester')
