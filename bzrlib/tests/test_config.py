# Copyright (C) 2005-2010 Canonical Ltd
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

"""Tests for finding and reading the bzr config file[s]."""
# import system imports here
from cStringIO import StringIO
import os
import sys
import threading

#import bzrlib specific imports here
from bzrlib import (
    branch,
    bzrdir,
    config,
    diff,
    errors,
    osutils,
    mail_client,
    mergetools,
    ui,
    urlutils,
    tests,
    trace,
    transport,
    )
from bzrlib.tests import (
    features,
    scenarios,
    )
from bzrlib.util.configobj import configobj


def lockable_config_scenarios():
    return [
        ('global',
         {'config_class': config.GlobalConfig,
          'config_args': [],
          'config_section': 'DEFAULT'}),
        ('locations',
         {'config_class': config.LocationConfig,
          'config_args': ['.'],
          'config_section': '.'}),]


load_tests = scenarios.load_tests_apply_scenarios


sample_long_alias="log -r-15..-1 --line"
sample_config_text = u"""
[DEFAULT]
email=Erik B\u00e5gfors <erik@bagfors.nu>
editor=vim
change_editor=vimdiff -of @new_path @old_path
gpg_signing_command=gnome-gpg
log_format=short
user_global_option=something
mergetools.kdiff3=kdiff3 {base} {this} {other} -o {result}
mergetools.winmergeu=winmergeu {result}
mergetools.funkytool=funkytool "arg with spaces" {this_temp}
default_mergetool=kdiff3
[ALIASES]
h=help
ll=""" + sample_long_alias + "\n"


sample_always_signatures = """
[DEFAULT]
check_signatures=ignore
create_signatures=always
"""

sample_ignore_signatures = """
[DEFAULT]
check_signatures=require
create_signatures=never
"""

sample_maybe_signatures = """
[DEFAULT]
check_signatures=ignore
create_signatures=when-required
"""

sample_branches_text = """
[http://www.example.com]
# Top level policy
email=Robert Collins <robertc@example.org>
normal_option = normal
appendpath_option = append
appendpath_option:policy = appendpath
norecurse_option = norecurse
norecurse_option:policy = norecurse
[http://www.example.com/ignoreparent]
# different project: ignore parent dir config
ignore_parents=true
[http://www.example.com/norecurse]
# configuration items that only apply to this dir
recurse=false
normal_option = norecurse
[http://www.example.com/dir]
appendpath_option = normal
[/b/]
check_signatures=require
# test trailing / matching with no children
[/a/]
check_signatures=check-available
gpg_signing_command=false
user_local_option=local
# test trailing / matching
[/a/*]
#subdirs will match but not the parent
[/a/c]
check_signatures=ignore
post_commit=bzrlib.tests.test_config.post_commit
#testing explicit beats globs
"""


class InstrumentedConfigObj(object):
    """A config obj look-enough-alike to record calls made to it."""

    def __contains__(self, thing):
        self._calls.append(('__contains__', thing))
        return False

    def __getitem__(self, key):
        self._calls.append(('__getitem__', key))
        return self

    def __init__(self, input, encoding=None):
        self._calls = [('__init__', input, encoding)]

    def __setitem__(self, key, value):
        self._calls.append(('__setitem__', key, value))

    def __delitem__(self, key):
        self._calls.append(('__delitem__', key))

    def keys(self):
        self._calls.append(('keys',))
        return []

    def reload(self):
        self._calls.append(('reload',))

    def write(self, arg):
        self._calls.append(('write',))

    def as_bool(self, value):
        self._calls.append(('as_bool', value))
        return False

    def get_value(self, section, name):
        self._calls.append(('get_value', section, name))
        return None


class FakeBranch(object):

    def __init__(self, base=None, user_id=None):
        if base is None:
            self.base = "http://example.com/branches/demo"
        else:
            self.base = base
        self._transport = self.control_files = \
            FakeControlFilesAndTransport(user_id=user_id)

    def _get_config(self):
        return config.TransportConfig(self._transport, 'branch.conf')

    def lock_write(self):
        pass

    def unlock(self):
        pass


class FakeControlFilesAndTransport(object):

    def __init__(self, user_id=None):
        self.files = {}
        if user_id:
            self.files['email'] = user_id
        self._transport = self

    def get_utf8(self, filename):
        # from LockableFiles
        raise AssertionError("get_utf8 should no longer be used")

    def get(self, filename):
        # from Transport
        try:
            return StringIO(self.files[filename])
        except KeyError:
            raise errors.NoSuchFile(filename)

    def get_bytes(self, filename):
        # from Transport
        try:
            return self.files[filename]
        except KeyError:
            raise errors.NoSuchFile(filename)

    def put(self, filename, fileobj):
        self.files[filename] = fileobj.read()

    def put_file(self, filename, fileobj):
        return self.put(filename, fileobj)


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

    def _get_change_editor(self):
        self._calls.append('_get_change_editor')
        return 'vimdiff -fo @new_path @old_path'


bool_config = """[DEFAULT]
active = true
inactive = false
[UPPERCASE]
active = True
nonactive = False
"""


class TestConfigObj(tests.TestCase):

    def test_get_bool(self):
        co = config.ConfigObj(StringIO(bool_config))
        self.assertIs(co.get_bool('DEFAULT', 'active'), True)
        self.assertIs(co.get_bool('DEFAULT', 'inactive'), False)
        self.assertIs(co.get_bool('UPPERCASE', 'active'), True)
        self.assertIs(co.get_bool('UPPERCASE', 'nonactive'), False)

    def test_hash_sign_in_value(self):
        """
        Before 4.5.0, ConfigObj did not quote # signs in values, so they'd be
        treated as comments when read in again. (#86838)
        """
        co = config.ConfigObj()
        co['test'] = 'foo#bar'
        lines = co.write()
        self.assertEqual(lines, ['test = "foo#bar"'])
        co2 = config.ConfigObj(lines)
        self.assertEqual(co2['test'], 'foo#bar')


erroneous_config = """[section] # line 1
good=good # line 2
[section] # line 3
whocares=notme # line 4
"""


class TestConfigObjErrors(tests.TestCase):

    def test_duplicate_section_name_error_line(self):
        try:
            co = configobj.ConfigObj(StringIO(erroneous_config),
                                     raise_errors=True)
        except config.configobj.DuplicateError, e:
            self.assertEqual(3, e.line_number)
        else:
            self.fail('Error in config file not detected')


class TestConfig(tests.TestCase):

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
        self.assertFalse(my_config.signature_needed())
        self.assertEqual(config.CHECK_IF_POSSIBLE,
                         my_config.signature_checking())
        self.assertEqual(config.SIGN_WHEN_REQUIRED,
                         my_config.signing_policy())

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

    def test_get_change_editor(self):
        my_config = InstrumentedConfig()
        change_editor = my_config.get_change_editor('old_tree', 'new_tree')
        self.assertEqual(['_get_change_editor'], my_config._calls)
        self.assertIs(diff.DiffFromTool, change_editor.__class__)
        self.assertEqual(['vimdiff', '-fo', '@new_path', '@old_path'],
                         change_editor.command_template)


class TestConfigPath(tests.TestCase):

    def setUp(self):
        super(TestConfigPath, self).setUp()
        os.environ['HOME'] = '/home/bogus'
        os.environ['XDG_CACHE_DIR'] = ''
        if sys.platform == 'win32':
            os.environ['BZR_HOME'] = \
                r'C:\Documents and Settings\bogus\Application Data'
            self.bzr_home = \
                'C:/Documents and Settings/bogus/Application Data/bazaar/2.0'
        else:
            self.bzr_home = '/home/bogus/.bazaar'

    def test_config_dir(self):
        self.assertEqual(config.config_dir(), self.bzr_home)

    def test_config_filename(self):
        self.assertEqual(config.config_filename(),
                         self.bzr_home + '/bazaar.conf')

    def test_locations_config_filename(self):
        self.assertEqual(config.locations_config_filename(),
                         self.bzr_home + '/locations.conf')

    def test_authentication_config_filename(self):
        self.assertEqual(config.authentication_config_filename(),
                         self.bzr_home + '/authentication.conf')

    def test_xdg_cache_dir(self):
        self.assertEqual(config.xdg_cache_dir(),
            '/home/bogus/.cache')


class TestIniConfig(tests.TestCaseInTempDir):

    def make_config_parser(self, s):
        conf = config.IniBasedConfig.from_string(s)
        return conf, conf._get_parser()


class TestIniConfigBuilding(TestIniConfig):

    def test_contructs(self):
        my_config = config.IniBasedConfig()

    def test_from_fp(self):
        my_config = config.IniBasedConfig.from_string(sample_config_text)
        self.assertIsInstance(my_config._get_parser(), configobj.ConfigObj)

    def test_cached(self):
        my_config = config.IniBasedConfig.from_string(sample_config_text)
        parser = my_config._get_parser()
        self.failUnless(my_config._get_parser() is parser)

    def _dummy_chown(self, path, uid, gid):
        self.path, self.uid, self.gid = path, uid, gid

    def test_ini_config_ownership(self):
        """Ensure that chown is happening during _write_config_file"""
        self.requireFeature(features.chown_feature)
        self.overrideAttr(os, 'chown', self._dummy_chown)
        self.path = self.uid = self.gid = None
        conf = config.IniBasedConfig(file_name='./foo.conf')
        conf._write_config_file()
        self.assertEquals(self.path, './foo.conf')
        self.assertTrue(isinstance(self.uid, int))
        self.assertTrue(isinstance(self.gid, int))

    def test_get_filename_parameter_is_deprecated_(self):
        conf = self.callDeprecated([
            'IniBasedConfig.__init__(get_filename) was deprecated in 2.3.'
            ' Use file_name instead.'],
            config.IniBasedConfig, lambda: 'ini.conf')
        self.assertEqual('ini.conf', conf.file_name)

    def test_get_parser_file_parameter_is_deprecated_(self):
        config_file = StringIO(sample_config_text.encode('utf-8'))
        conf = config.IniBasedConfig.from_string(sample_config_text)
        conf = self.callDeprecated([
            'IniBasedConfig._get_parser(file=xxx) was deprecated in 2.3.'
            ' Use IniBasedConfig(_content=xxx) instead.'],
            conf._get_parser, file=config_file)

class TestIniConfigSaving(tests.TestCaseInTempDir):

    def test_cant_save_without_a_file_name(self):
        conf = config.IniBasedConfig()
        self.assertRaises(AssertionError, conf._write_config_file)

    def test_saved_with_content(self):
        content = 'foo = bar\n'
        conf = config.IniBasedConfig.from_string(
            content, file_name='./test.conf', save=True)
        self.assertFileEqual(content, 'test.conf')


class TestIniBaseConfigOnDisk(tests.TestCaseInTempDir):

    def test_cannot_reload_without_name(self):
        conf = config.IniBasedConfig.from_string(sample_config_text)
        self.assertRaises(AssertionError, conf.reload)

    def test_reload_see_new_value(self):
        c1 = config.IniBasedConfig.from_string('editor=vim\n',
                                               file_name='./test/conf')
        c1._write_config_file()
        c2 = config.IniBasedConfig.from_string('editor=emacs\n',
                                               file_name='./test/conf')
        c2._write_config_file()
        self.assertEqual('vim', c1.get_user_option('editor'))
        self.assertEqual('emacs', c2.get_user_option('editor'))
        # Make sure we get the Right value
        c1.reload()
        self.assertEqual('emacs', c1.get_user_option('editor'))


class TestLockableConfig(tests.TestCaseInTempDir):

    scenarios = lockable_config_scenarios()

    # Set by load_tests
    config_class = None
    config_args = None
    config_section = None

    def setUp(self):
        super(TestLockableConfig, self).setUp()
        self._content = '[%s]\none=1\ntwo=2\n' % (self.config_section,)
        self.config = self.create_config(self._content)

    def get_existing_config(self):
        return self.config_class(*self.config_args)

    def create_config(self, content):
        kwargs = dict(save=True)
        c = self.config_class.from_string(content, *self.config_args, **kwargs)
        return c

    def test_simple_read_access(self):
        self.assertEquals('1', self.config.get_user_option('one'))

    def test_simple_write_access(self):
        self.config.set_user_option('one', 'one')
        self.assertEquals('one', self.config.get_user_option('one'))

    def test_listen_to_the_last_speaker(self):
        c1 = self.config
        c2 = self.get_existing_config()
        c1.set_user_option('one', 'ONE')
        c2.set_user_option('two', 'TWO')
        self.assertEquals('ONE', c1.get_user_option('one'))
        self.assertEquals('TWO', c2.get_user_option('two'))
        # The second update respect the first one
        self.assertEquals('ONE', c2.get_user_option('one'))

    def test_last_speaker_wins(self):
        # If the same config is not shared, the same variable modified twice
        # can only see a single result.
        c1 = self.config
        c2 = self.get_existing_config()
        c1.set_user_option('one', 'c1')
        c2.set_user_option('one', 'c2')
        self.assertEquals('c2', c2._get_user_option('one'))
        # The first modification is still available until another refresh
        # occur
        self.assertEquals('c1', c1._get_user_option('one'))
        c1.set_user_option('two', 'done')
        self.assertEquals('c2', c1._get_user_option('one'))

    def test_writes_are_serialized(self):
        c1 = self.config
        c2 = self.get_existing_config()

        # We spawn a thread that will pause *during* the write
        before_writing = threading.Event()
        after_writing = threading.Event()
        writing_done = threading.Event()
        c1_orig = c1._write_config_file
        def c1_write_config_file():
            before_writing.set()
            c1_orig()
            # The lock is held we wait for the main thread to decide when to
            # continue
            after_writing.wait()
        c1._write_config_file = c1_write_config_file
        def c1_set_option():
            c1.set_user_option('one', 'c1')
            writing_done.set()
        t1 = threading.Thread(target=c1_set_option)
        # Collect the thread after the test
        self.addCleanup(t1.join)
        # Be ready to unblock the thread if the test goes wrong
        self.addCleanup(after_writing.set)
        t1.start()
        before_writing.wait()
        self.assertTrue(c1._lock.is_held)
        self.assertRaises(errors.LockContention,
                          c2.set_user_option, 'one', 'c2')
        self.assertEquals('c1', c1.get_user_option('one'))
        # Let the lock be released
        after_writing.set()
        writing_done.wait()
        c2.set_user_option('one', 'c2')
        self.assertEquals('c2', c2.get_user_option('one'))

    def test_read_while_writing(self):
       c1 = self.config
       # We spawn a thread that will pause *during* the write
       ready_to_write = threading.Event()
       do_writing = threading.Event()
       writing_done = threading.Event()
       c1_orig = c1._write_config_file
       def c1_write_config_file():
           ready_to_write.set()
           # The lock is held we wait for the main thread to decide when to
           # continue
           do_writing.wait()
           c1_orig()
           writing_done.set()
       c1._write_config_file = c1_write_config_file
       def c1_set_option():
           c1.set_user_option('one', 'c1')
       t1 = threading.Thread(target=c1_set_option)
       # Collect the thread after the test
       self.addCleanup(t1.join)
       # Be ready to unblock the thread if the test goes wrong
       self.addCleanup(do_writing.set)
       t1.start()
       # Ensure the thread is ready to write
       ready_to_write.wait()
       self.assertTrue(c1._lock.is_held)
       self.assertEquals('c1', c1.get_user_option('one'))
       # If we read during the write, we get the old value
       c2 = self.get_existing_config()
       self.assertEquals('1', c2.get_user_option('one'))
       # Let the writing occur and ensure it occurred
       do_writing.set()
       writing_done.wait()
       # Now we get the updated value
       c3 = self.get_existing_config()
       self.assertEquals('c1', c3.get_user_option('one'))


class TestGetUserOptionAs(TestIniConfig):

    def test_get_user_option_as_bool(self):
        conf, parser = self.make_config_parser("""
a_true_bool = true
a_false_bool = 0
an_invalid_bool = maybe
a_list = hmm, who knows ? # This is interpreted as a list !
""")
        get_bool = conf.get_user_option_as_bool
        self.assertEqual(True, get_bool('a_true_bool'))
        self.assertEqual(False, get_bool('a_false_bool'))
        warnings = []
        def warning(*args):
            warnings.append(args[0] % args[1:])
        self.overrideAttr(trace, 'warning', warning)
        msg = 'Value "%s" is not a boolean for "%s"'
        self.assertIs(None, get_bool('an_invalid_bool'))
        self.assertEquals(msg % ('maybe', 'an_invalid_bool'), warnings[0])
        warnings = []
        self.assertIs(None, get_bool('not_defined_in_this_config'))
        self.assertEquals([], warnings)

    def test_get_user_option_as_list(self):
        conf, parser = self.make_config_parser("""
a_list = a,b,c
length_1 = 1,
one_item = x
""")
        get_list = conf.get_user_option_as_list
        self.assertEqual(['a', 'b', 'c'], get_list('a_list'))
        self.assertEqual(['1'], get_list('length_1'))
        self.assertEqual('x', conf.get_user_option('one_item'))
        # automatically cast to list
        self.assertEqual(['x'], get_list('one_item'))


class TestSupressWarning(TestIniConfig):

    def make_warnings_config(self, s):
        conf, parser = self.make_config_parser(s)
        return conf.suppress_warning

    def test_suppress_warning_unknown(self):
        suppress_warning = self.make_warnings_config('')
        self.assertEqual(False, suppress_warning('unknown_warning'))

    def test_suppress_warning_known(self):
        suppress_warning = self.make_warnings_config('suppress_warnings=a,b')
        self.assertEqual(False, suppress_warning('c'))
        self.assertEqual(True, suppress_warning('a'))
        self.assertEqual(True, suppress_warning('b'))


class TestGetConfig(tests.TestCase):

    def test_constructs(self):
        my_config = config.GlobalConfig()

    def test_calls_read_filenames(self):
        # replace the class that is constructed, to check its parameters
        oldparserclass = config.ConfigObj
        config.ConfigObj = InstrumentedConfigObj
        my_config = config.GlobalConfig()
        try:
            parser = my_config._get_parser()
        finally:
            config.ConfigObj = oldparserclass
        self.failUnless(isinstance(parser, InstrumentedConfigObj))
        self.assertEqual(parser._calls, [('__init__', config.config_filename(),
                                          'utf-8')])


class TestBranchConfig(tests.TestCaseWithTransport):

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

    def test_get_config(self):
        """The Branch.get_config method works properly"""
        b = bzrdir.BzrDir.create_standalone_workingtree('.').branch
        my_config = b.get_config()
        self.assertIs(my_config.get_user_option('wacky'), None)
        my_config.set_user_option('wacky', 'unlikely')
        self.assertEqual(my_config.get_user_option('wacky'), 'unlikely')

        # Ensure we get the same thing if we start again
        b2 = branch.Branch.open('.')
        my_config2 = b2.get_config()
        self.assertEqual(my_config2.get_user_option('wacky'), 'unlikely')

    def test_has_explicit_nickname(self):
        b = self.make_branch('.')
        self.assertFalse(b.get_config().has_explicit_nickname())
        b.nick = 'foo'
        self.assertTrue(b.get_config().has_explicit_nickname())

    def test_config_url(self):
        """The Branch.get_config will use section that uses a local url"""
        branch = self.make_branch('branch')
        self.assertEqual('branch', branch.nick)

        local_url = urlutils.local_path_to_url('branch')
        conf = config.LocationConfig.from_string(
            '[%s]\nnickname = foobar' % (local_url,),
            local_url, save=True)
        self.assertEqual('foobar', branch.nick)

    def test_config_local_path(self):
        """The Branch.get_config will use a local system path"""
        branch = self.make_branch('branch')
        self.assertEqual('branch', branch.nick)

        local_path = osutils.getcwd().encode('utf8')
        conf = config.LocationConfig.from_string(
            '[%s/branch]\nnickname = barry' % (local_path,),
            'branch',  save=True)
        self.assertEqual('barry', branch.nick)

    def test_config_creates_local(self):
        """Creating a new entry in config uses a local path."""
        branch = self.make_branch('branch', format='knit')
        branch.set_push_location('http://foobar')
        local_path = osutils.getcwd().encode('utf8')
        # Surprisingly ConfigObj doesn't create a trailing newline
        self.check_file_contents(config.locations_config_filename(),
                                 '[%s/branch]\n'
                                 'push_location = http://foobar\n'
                                 'push_location:policy = norecurse\n'
                                 % (local_path,))

    def test_autonick_urlencoded(self):
        b = self.make_branch('!repo')
        self.assertEqual('!repo', b.get_config().get_nickname())

    def test_warn_if_masked(self):
        warnings = []
        def warning(*args):
            warnings.append(args[0] % args[1:])
        self.overrideAttr(trace, 'warning', warning)

        def set_option(store, warn_masked=True):
            warnings[:] = []
            conf.set_user_option('example_option', repr(store), store=store,
                                 warn_masked=warn_masked)
        def assertWarning(warning):
            if warning is None:
                self.assertEqual(0, len(warnings))
            else:
                self.assertEqual(1, len(warnings))
                self.assertEqual(warning, warnings[0])
        branch = self.make_branch('.')
        conf = branch.get_config()
        set_option(config.STORE_GLOBAL)
        assertWarning(None)
        set_option(config.STORE_BRANCH)
        assertWarning(None)
        set_option(config.STORE_GLOBAL)
        assertWarning('Value "4" is masked by "3" from branch.conf')
        set_option(config.STORE_GLOBAL, warn_masked=False)
        assertWarning(None)
        set_option(config.STORE_LOCATION)
        assertWarning(None)
        set_option(config.STORE_BRANCH)
        assertWarning('Value "3" is masked by "0" from locations.conf')
        set_option(config.STORE_BRANCH, warn_masked=False)
        assertWarning(None)


class TestGlobalConfigItems(tests.TestCaseInTempDir):

    def test_user_id(self):
        my_config = config.GlobalConfig.from_string(sample_config_text)
        self.assertEqual(u"Erik B\u00e5gfors <erik@bagfors.nu>",
                         my_config._get_user_id())

    def test_absent_user_id(self):
        my_config = config.GlobalConfig()
        self.assertEqual(None, my_config._get_user_id())

    def test_configured_editor(self):
        my_config = config.GlobalConfig.from_string(sample_config_text)
        self.assertEqual("vim", my_config.get_editor())

    def test_signatures_always(self):
        my_config = config.GlobalConfig.from_string(sample_always_signatures)
        self.assertEqual(config.CHECK_NEVER,
                         my_config.signature_checking())
        self.assertEqual(config.SIGN_ALWAYS,
                         my_config.signing_policy())
        self.assertEqual(True, my_config.signature_needed())

    def test_signatures_if_possible(self):
        my_config = config.GlobalConfig.from_string(sample_maybe_signatures)
        self.assertEqual(config.CHECK_NEVER,
                         my_config.signature_checking())
        self.assertEqual(config.SIGN_WHEN_REQUIRED,
                         my_config.signing_policy())
        self.assertEqual(False, my_config.signature_needed())

    def test_signatures_ignore(self):
        my_config = config.GlobalConfig.from_string(sample_ignore_signatures)
        self.assertEqual(config.CHECK_ALWAYS,
                         my_config.signature_checking())
        self.assertEqual(config.SIGN_NEVER,
                         my_config.signing_policy())
        self.assertEqual(False, my_config.signature_needed())

    def _get_sample_config(self):
        my_config = config.GlobalConfig.from_string(sample_config_text)
        return my_config

    def test_gpg_signing_command(self):
        my_config = self._get_sample_config()
        self.assertEqual("gnome-gpg", my_config.gpg_signing_command())
        self.assertEqual(False, my_config.signature_needed())

    def _get_empty_config(self):
        my_config = config.GlobalConfig()
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

    def test_get_aliases(self):
        my_config = self._get_sample_config()
        aliases = my_config.get_aliases()
        self.assertEqual(2, len(aliases))
        sorted_keys = sorted(aliases)
        self.assertEqual('help', aliases[sorted_keys[0]])
        self.assertEqual(sample_long_alias, aliases[sorted_keys[1]])

    def test_get_no_alias(self):
        my_config = self._get_sample_config()
        self.assertEqual(None, my_config.get_alias('foo'))

    def test_get_long_alias(self):
        my_config = self._get_sample_config()
        self.assertEqual(sample_long_alias, my_config.get_alias('ll'))

    def test_get_change_editor(self):
        my_config = self._get_sample_config()
        change_editor = my_config.get_change_editor('old', 'new')
        self.assertIs(diff.DiffFromTool, change_editor.__class__)
        self.assertEqual('vimdiff -of @new_path @old_path',
                         ' '.join(change_editor.command_template))

    def test_get_no_change_editor(self):
        my_config = self._get_empty_config()
        change_editor = my_config.get_change_editor('old', 'new')
        self.assertIs(None, change_editor)

    def test_get_merge_tools(self):
        conf = self._get_sample_config()
        tools = conf.get_merge_tools()
        self.log(repr(tools))
        self.assertEqual(3, len(tools))
        self.assertEqual('kdiff3', tools[0].get_name())
        self.assertEqual('kdiff3 {base} {this} {other} -o {result}',
                         tools[0].get_commandline())
        self.assertEqual('winmergeu', tools[1].get_name())
        self.assertEqual('winmergeu {result}', tools[1].get_commandline())
        self.assertEqual('funkytool', tools[2].get_name())
        self.assertEqual('funkytool "arg with spaces" {this_temp}',
                          tools[2].get_commandline())

    def test_get_default_merge_tool(self):
        conf = self._get_sample_config()
        tool = conf.get_default_merge_tool()
        self.log(repr(tool))
        self.assertEqual('kdiff3', tool.get_name())
        self.assertEqual('kdiff3 {base} {this} {other} -o {result}',
                         tool.get_commandline())

    def test_get_default_merge_tool_empty(self):
        conf = self._get_empty_config()
        tool = conf.get_default_merge_tool()
        self.assertEqual(None, tool)


class TestGlobalConfigSavingOptions(tests.TestCaseInTempDir):

    def test_empty(self):
        my_config = config.GlobalConfig()
        self.assertEqual(0, len(my_config.get_aliases()))

    def test_set_alias(self):
        my_config = config.GlobalConfig()
        alias_value = 'commit --strict'
        my_config.set_alias('commit', alias_value)
        new_config = config.GlobalConfig()
        self.assertEqual(alias_value, new_config.get_alias('commit'))

    def test_remove_alias(self):
        my_config = config.GlobalConfig()
        my_config.set_alias('commit', 'commit --strict')
        # Now remove the alias again.
        my_config.unset_alias('commit')
        new_config = config.GlobalConfig()
        self.assertIs(None, new_config.get_alias('commit'))

    def test_set_merge_tools(self):
        conf = config.GlobalConfig()
        conf.set_merge_tools([
            mergetools.MergeTool('kdiff3',
                                 'kdiff3 {base} {this} {other} -o {result}'),
            mergetools.MergeTool('winmergeu',
                                 'winmergeu {result}'),
            mergetools.MergeTool('funkytool',
                                 'funkytool "arg with spaces" {this_temp}')
            ])
        self.assertEqual('funkytool "arg with spaces" {this_temp}',
                          conf.get_user_option('mergetools.funkytool'))
        self.assertEqual('kdiff3 {base} {this} {other} -o {result}',
                          conf.get_user_option('mergetools.kdiff3'))
        self.assertEqual('winmergeu {result}',
                          conf.get_user_option('mergetools.winmergeu'))

    def test_set_merge_tools_duplicates(self):
        conf = config.GlobalConfig()
        conf.set_merge_tools([
            mergetools.MergeTool('kdiff3',
                                 'kdiff3 {base} {this} {other} -o {result}'),
            mergetools.MergeTool('kdiff3',
                                 'kdiff3 {base} {this} {other} -o {result}')
            ])
        tools = conf.get_merge_tools()
        self.assertEqual(1, len(tools))
        self.assertEqual('kdiff3', tools[0].get_name())
        self.assertEqual('kdiff3 {base} {this} {other} -o {result}',
                         tools[0].get_commandline())

    def test_set_merge_tools_empty_tool(self):
        conf = config.GlobalConfig()
        conf.set_merge_tools([
            mergetools.MergeTool('kdiff3',
                                 'kdiff3 {base} {this} {other} -o {result}'),
            mergetools.MergeTool('',''),
            mergetools.MergeTool('blah','')
            ])
        tools = conf.get_merge_tools()
        self.assertEqual(1, len(tools))
        self.assertEqual('kdiff3', tools[0].get_name())
        self.assertEqual('kdiff3 {base} {this} {other} -o {result}',
                         tools[0].get_commandline())

    def test_set_merge_tools_remove_one(self):
        conf = config.GlobalConfig()
        tools = [
            mergetools.MergeTool('kdiff3',
                                 'kdiff3 {base} {this} {other} -o {result}'),
            mergetools.MergeTool('winmergeu',
                                 'winmergeu {result}'),
            mergetools.MergeTool('funkytool',
                                 'funkytool "arg with spaces" {this_temp}')
            ]
        conf.set_merge_tools(tools)
        del tools[0]
        conf.set_merge_tools(tools)
        self.assertEqual(sorted([
            ('mergetools.funkytool',
             'funkytool "arg with spaces" {this_temp}', 'DEFAULT', 'bazaar'),
            ('mergetools.winmergeu',
             'winmergeu {result}', 'DEFAULT', 'bazaar'),
            ]),
            sorted(conf._get_options()))

    def test_set_default_merge_tool(self):
        conf = config.GlobalConfig()
        tools = [
            mergetools.MergeTool('kdiff3',
                                 'kdiff3 {base} {this} {other} -o {result}'),
            mergetools.MergeTool('winmergeu',
                                 'winmergeu {result}'),
            mergetools.MergeTool('funkytool',
                                 'funkytool "arg with spaces" {this_temp}')
            ]
        conf.set_merge_tools(tools)
        conf.set_default_merge_tool('winmergeu')
        self.assertEqual('winmergeu', conf.get_user_option('default_mergetool'))

    def test_set_default_merge_tool_none(self):
        conf = config.GlobalConfig.from_string(sample_config_text)
        conf.set_default_merge_tool(None)
        self.assertEqual(None, conf.get_user_option('default_mergetool'))

    def test_set_invalid_default_merge_tool(self):
        conf = config.GlobalConfig()
        tools = [
            mergetools.MergeTool('kdiff3',
                                 'kdiff3 {base} {this} {other} -o {result}'),
            mergetools.MergeTool('winmergeu',
                                 'winmergeu {result}'),
            mergetools.MergeTool('funkytool',
                                 'funkytool "arg with spaces" {this_temp}')
            ]
        conf.set_merge_tools(tools)
        self.failUnlessRaises(errors.BzrError, conf.set_default_merge_tool,
                              'DOES NOT EXIST')


class TestLocationConfig(tests.TestCaseInTempDir):

    def test_constructs(self):
        my_config = config.LocationConfig('http://example.com')
        self.assertRaises(TypeError, config.LocationConfig)

    def test_branch_calls_read_filenames(self):
        # This is testing the correct file names are provided.
        # TODO: consolidate with the test for GlobalConfigs filename checks.
        #
        # replace the class that is constructed, to check its parameters
        oldparserclass = config.ConfigObj
        config.ConfigObj = InstrumentedConfigObj
        try:
            my_config = config.LocationConfig('http://www.example.com')
            parser = my_config._get_parser()
        finally:
            config.ConfigObj = oldparserclass
        self.failUnless(isinstance(parser, InstrumentedConfigObj))
        self.assertEqual(parser._calls,
                         [('__init__', config.locations_config_filename(),
                           'utf-8')])

    def test_get_global_config(self):
        my_config = config.BranchConfig(FakeBranch('http://example.com'))
        global_config = my_config._get_global_config()
        self.failUnless(isinstance(global_config, config.GlobalConfig))
        self.failUnless(global_config is my_config._get_global_config())

    def test__get_matching_sections_no_match(self):
        self.get_branch_config('/')
        self.assertEqual([], self.my_location_config._get_matching_sections())

    def test__get_matching_sections_exact(self):
        self.get_branch_config('http://www.example.com')
        self.assertEqual([('http://www.example.com', '')],
                         self.my_location_config._get_matching_sections())

    def test__get_matching_sections_suffix_does_not(self):
        self.get_branch_config('http://www.example.com-com')
        self.assertEqual([], self.my_location_config._get_matching_sections())

    def test__get_matching_sections_subdir_recursive(self):
        self.get_branch_config('http://www.example.com/com')
        self.assertEqual([('http://www.example.com', 'com')],
                         self.my_location_config._get_matching_sections())

    def test__get_matching_sections_ignoreparent(self):
        self.get_branch_config('http://www.example.com/ignoreparent')
        self.assertEqual([('http://www.example.com/ignoreparent', '')],
                         self.my_location_config._get_matching_sections())

    def test__get_matching_sections_ignoreparent_subdir(self):
        self.get_branch_config(
            'http://www.example.com/ignoreparent/childbranch')
        self.assertEqual([('http://www.example.com/ignoreparent',
                           'childbranch')],
                         self.my_location_config._get_matching_sections())

    def test__get_matching_sections_subdir_trailing_slash(self):
        self.get_branch_config('/b')
        self.assertEqual([('/b/', '')],
                         self.my_location_config._get_matching_sections())

    def test__get_matching_sections_subdir_child(self):
        self.get_branch_config('/a/foo')
        self.assertEqual([('/a/*', ''), ('/a/', 'foo')],
                         self.my_location_config._get_matching_sections())

    def test__get_matching_sections_subdir_child_child(self):
        self.get_branch_config('/a/foo/bar')
        self.assertEqual([('/a/*', 'bar'), ('/a/', 'foo/bar')],
                         self.my_location_config._get_matching_sections())

    def test__get_matching_sections_trailing_slash_with_children(self):
        self.get_branch_config('/a/')
        self.assertEqual([('/a/', '')],
                         self.my_location_config._get_matching_sections())

    def test__get_matching_sections_explicit_over_glob(self):
        # XXX: 2006-09-08 jamesh
        # This test only passes because ord('c') > ord('*').  If there
        # was a config section for '/a/?', it would get precedence
        # over '/a/c'.
        self.get_branch_config('/a/c')
        self.assertEqual([('/a/c', ''), ('/a/*', ''), ('/a/', 'c')],
                         self.my_location_config._get_matching_sections())

    def test__get_option_policy_normal(self):
        self.get_branch_config('http://www.example.com')
        self.assertEqual(
            self.my_location_config._get_config_policy(
            'http://www.example.com', 'normal_option'),
            config.POLICY_NONE)

    def test__get_option_policy_norecurse(self):
        self.get_branch_config('http://www.example.com')
        self.assertEqual(
            self.my_location_config._get_option_policy(
            'http://www.example.com', 'norecurse_option'),
            config.POLICY_NORECURSE)
        # Test old recurse=False setting:
        self.assertEqual(
            self.my_location_config._get_option_policy(
            'http://www.example.com/norecurse', 'normal_option'),
            config.POLICY_NORECURSE)

    def test__get_option_policy_normal(self):
        self.get_branch_config('http://www.example.com')
        self.assertEqual(
            self.my_location_config._get_option_policy(
            'http://www.example.com', 'appendpath_option'),
            config.POLICY_APPENDPATH)

    def test_location_without_username(self):
        self.get_branch_config('http://www.example.com/ignoreparent')
        self.assertEqual(u'Erik B\u00e5gfors <erik@bagfors.nu>',
                         self.my_config.username())

    def test_location_not_listed(self):
        """Test that the global username is used when no location matches"""
        self.get_branch_config('/home/robertc/sources')
        self.assertEqual(u'Erik B\u00e5gfors <erik@bagfors.nu>',
                         self.my_config.username())

    def test_overriding_location(self):
        self.get_branch_config('http://www.example.com/foo')
        self.assertEqual('Robert Collins <robertc@example.org>',
                         self.my_config.username())

    def test_signatures_not_set(self):
        self.get_branch_config('http://www.example.com',
                                 global_config=sample_ignore_signatures)
        self.assertEqual(config.CHECK_ALWAYS,
                         self.my_config.signature_checking())
        self.assertEqual(config.SIGN_NEVER,
                         self.my_config.signing_policy())

    def test_signatures_never(self):
        self.get_branch_config('/a/c')
        self.assertEqual(config.CHECK_NEVER,
                         self.my_config.signature_checking())

    def test_signatures_when_available(self):
        self.get_branch_config('/a/', global_config=sample_ignore_signatures)
        self.assertEqual(config.CHECK_IF_POSSIBLE,
                         self.my_config.signature_checking())

    def test_signatures_always(self):
        self.get_branch_config('/b')
        self.assertEqual(config.CHECK_ALWAYS,
                         self.my_config.signature_checking())

    def test_gpg_signing_command(self):
        self.get_branch_config('/b')
        self.assertEqual("gnome-gpg", self.my_config.gpg_signing_command())

    def test_gpg_signing_command_missing(self):
        self.get_branch_config('/a')
        self.assertEqual("false", self.my_config.gpg_signing_command())

    def test_get_user_option_global(self):
        self.get_branch_config('/a')
        self.assertEqual('something',
                         self.my_config.get_user_option('user_global_option'))

    def test_get_user_option_local(self):
        self.get_branch_config('/a')
        self.assertEqual('local',
                         self.my_config.get_user_option('user_local_option'))

    def test_get_user_option_appendpath(self):
        # returned as is for the base path:
        self.get_branch_config('http://www.example.com')
        self.assertEqual('append',
                         self.my_config.get_user_option('appendpath_option'))
        # Extra path components get appended:
        self.get_branch_config('http://www.example.com/a/b/c')
        self.assertEqual('append/a/b/c',
                         self.my_config.get_user_option('appendpath_option'))
        # Overriden for http://www.example.com/dir, where it is a
        # normal option:
        self.get_branch_config('http://www.example.com/dir/a/b/c')
        self.assertEqual('normal',
                         self.my_config.get_user_option('appendpath_option'))

    def test_get_user_option_norecurse(self):
        self.get_branch_config('http://www.example.com')
        self.assertEqual('norecurse',
                         self.my_config.get_user_option('norecurse_option'))
        self.get_branch_config('http://www.example.com/dir')
        self.assertEqual(None,
                         self.my_config.get_user_option('norecurse_option'))
        # http://www.example.com/norecurse is a recurse=False section
        # that redefines normal_option.  Subdirectories do not pick up
        # this redefinition.
        self.get_branch_config('http://www.example.com/norecurse')
        self.assertEqual('norecurse',
                         self.my_config.get_user_option('normal_option'))
        self.get_branch_config('http://www.example.com/norecurse/subdir')
        self.assertEqual('normal',
                         self.my_config.get_user_option('normal_option'))

    def test_set_user_option_norecurse(self):
        self.get_branch_config('http://www.example.com')
        self.my_config.set_user_option('foo', 'bar',
                                       store=config.STORE_LOCATION_NORECURSE)
        self.assertEqual(
            self.my_location_config._get_option_policy(
            'http://www.example.com', 'foo'),
            config.POLICY_NORECURSE)

    def test_set_user_option_appendpath(self):
        self.get_branch_config('http://www.example.com')
        self.my_config.set_user_option('foo', 'bar',
                                       store=config.STORE_LOCATION_APPENDPATH)
        self.assertEqual(
            self.my_location_config._get_option_policy(
            'http://www.example.com', 'foo'),
            config.POLICY_APPENDPATH)

    def test_set_user_option_change_policy(self):
        self.get_branch_config('http://www.example.com')
        self.my_config.set_user_option('norecurse_option', 'normal',
                                       store=config.STORE_LOCATION)
        self.assertEqual(
            self.my_location_config._get_option_policy(
            'http://www.example.com', 'norecurse_option'),
            config.POLICY_NONE)

    def test_set_user_option_recurse_false_section(self):
        # The following section has recurse=False set.  The test is to
        # make sure that a normal option can be added to the section,
        # converting recurse=False to the norecurse policy.
        self.get_branch_config('http://www.example.com/norecurse')
        self.callDeprecated(['The recurse option is deprecated as of 0.14.  '
                             'The section "http://www.example.com/norecurse" '
                             'has been converted to use policies.'],
                            self.my_config.set_user_option,
                            'foo', 'bar', store=config.STORE_LOCATION)
        self.assertEqual(
            self.my_location_config._get_option_policy(
            'http://www.example.com/norecurse', 'foo'),
            config.POLICY_NONE)
        # The previously existing option is still norecurse:
        self.assertEqual(
            self.my_location_config._get_option_policy(
            'http://www.example.com/norecurse', 'normal_option'),
            config.POLICY_NORECURSE)

    def test_post_commit_default(self):
        self.get_branch_config('/a/c')
        self.assertEqual('bzrlib.tests.test_config.post_commit',
                         self.my_config.post_commit())

    def get_branch_config(self, location, global_config=None):
        my_branch = FakeBranch(location)
        if global_config is None:
            global_config = sample_config_text

        my_global_config = config.GlobalConfig.from_string(global_config,
                                                           save=True)
        my_location_config = config.LocationConfig.from_string(
            sample_branches_text, my_branch.base, save=True)
        my_config = config.BranchConfig(my_branch)
        self.my_config = my_config
        self.my_location_config = my_config._get_location_config()

    def test_set_user_setting_sets_and_saves(self):
        self.get_branch_config('/a/c')
        record = InstrumentedConfigObj("foo")
        self.my_location_config._parser = record

        self.callDeprecated(['The recurse option is deprecated as of '
                             '0.14.  The section "/a/c" has been '
                             'converted to use policies.'],
                            self.my_config.set_user_option,
                            'foo', 'bar', store=config.STORE_LOCATION)
        self.assertEqual([('reload',),
                          ('__contains__', '/a/c'),
                          ('__contains__', '/a/c/'),
                          ('__setitem__', '/a/c', {}),
                          ('__getitem__', '/a/c'),
                          ('__setitem__', 'foo', 'bar'),
                          ('__getitem__', '/a/c'),
                          ('as_bool', 'recurse'),
                          ('__getitem__', '/a/c'),
                          ('__delitem__', 'recurse'),
                          ('__getitem__', '/a/c'),
                          ('keys',),
                          ('__getitem__', '/a/c'),
                          ('__contains__', 'foo:policy'),
                          ('write',)],
                         record._calls[1:])

    def test_set_user_setting_sets_and_saves2(self):
        self.get_branch_config('/a/c')
        self.assertIs(self.my_config.get_user_option('foo'), None)
        self.my_config.set_user_option('foo', 'bar')
        self.assertEqual(
            self.my_config.branch.control_files.files['branch.conf'].strip(),
            'foo = bar')
        self.assertEqual(self.my_config.get_user_option('foo'), 'bar')
        self.my_config.set_user_option('foo', 'baz',
                                       store=config.STORE_LOCATION)
        self.assertEqual(self.my_config.get_user_option('foo'), 'baz')
        self.my_config.set_user_option('foo', 'qux')
        self.assertEqual(self.my_config.get_user_option('foo'), 'baz')

    def test_get_bzr_remote_path(self):
        my_config = config.LocationConfig('/a/c')
        self.assertEqual('bzr', my_config.get_bzr_remote_path())
        my_config.set_user_option('bzr_remote_path', '/path-bzr')
        self.assertEqual('/path-bzr', my_config.get_bzr_remote_path())
        os.environ['BZR_REMOTE_PATH'] = '/environ-bzr'
        self.assertEqual('/environ-bzr', my_config.get_bzr_remote_path())


precedence_global = 'option = global'
precedence_branch = 'option = branch'
precedence_location = """
[http://]
recurse = true
option = recurse
[http://example.com/specific]
option = exact
"""

class TestBranchConfigItems(tests.TestCaseInTempDir):

    def get_branch_config(self, global_config=None, location=None,
                          location_config=None, branch_data_config=None):
        my_branch = FakeBranch(location)
        if global_config is not None:
            my_global_config = config.GlobalConfig.from_string(global_config,
                                                               save=True)
        if location_config is not None:
            my_location_config = config.LocationConfig.from_string(
                location_config, my_branch.base, save=True)
        my_config = config.BranchConfig(my_branch)
        if branch_data_config is not None:
            my_config.branch.control_files.files['branch.conf'] = \
                branch_data_config
        return my_config

    def test_user_id(self):
        branch = FakeBranch(user_id='Robert Collins <robertc@example.net>')
        my_config = config.BranchConfig(branch)
        self.assertEqual("Robert Collins <robertc@example.net>",
                         my_config.username())
        my_config.branch.control_files.files['email'] = "John"
        my_config.set_user_option('email',
                                  "Robert Collins <robertc@example.org>")
        self.assertEqual("John", my_config.username())
        del my_config.branch.control_files.files['email']
        self.assertEqual("Robert Collins <robertc@example.org>",
                         my_config.username())

    def test_not_set_in_branch(self):
        my_config = self.get_branch_config(global_config=sample_config_text)
        self.assertEqual(u"Erik B\u00e5gfors <erik@bagfors.nu>",
                         my_config._get_user_id())
        my_config.branch.control_files.files['email'] = "John"
        self.assertEqual("John", my_config._get_user_id())

    def test_BZR_EMAIL_OVERRIDES(self):
        os.environ['BZR_EMAIL'] = "Robert Collins <robertc@example.org>"
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        self.assertEqual("Robert Collins <robertc@example.org>",
                         my_config.username())

    def test_signatures_forced(self):
        my_config = self.get_branch_config(
            global_config=sample_always_signatures)
        self.assertEqual(config.CHECK_NEVER, my_config.signature_checking())
        self.assertEqual(config.SIGN_ALWAYS, my_config.signing_policy())
        self.assertTrue(my_config.signature_needed())

    def test_signatures_forced_branch(self):
        my_config = self.get_branch_config(
            global_config=sample_ignore_signatures,
            branch_data_config=sample_always_signatures)
        self.assertEqual(config.CHECK_NEVER, my_config.signature_checking())
        self.assertEqual(config.SIGN_ALWAYS, my_config.signing_policy())
        self.assertTrue(my_config.signature_needed())

    def test_gpg_signing_command(self):
        my_config = self.get_branch_config(
            global_config=sample_config_text,
            # branch data cannot set gpg_signing_command
            branch_data_config="gpg_signing_command=pgp")
        self.assertEqual('gnome-gpg', my_config.gpg_signing_command())

    def test_get_user_option_global(self):
        my_config = self.get_branch_config(global_config=sample_config_text)
        self.assertEqual('something',
                         my_config.get_user_option('user_global_option'))

    def test_post_commit_default(self):
        my_config = self.get_branch_config(global_config=sample_config_text,
                                      location='/a/c',
                                      location_config=sample_branches_text)
        self.assertEqual(my_config.branch.base, '/a/c')
        self.assertEqual('bzrlib.tests.test_config.post_commit',
                         my_config.post_commit())
        my_config.set_user_option('post_commit', 'rmtree_root')
        # post-commit is ignored when present in branch data
        self.assertEqual('bzrlib.tests.test_config.post_commit',
                         my_config.post_commit())
        my_config.set_user_option('post_commit', 'rmtree_root',
                                  store=config.STORE_LOCATION)
        self.assertEqual('rmtree_root', my_config.post_commit())

    def test_config_precedence(self):
        # FIXME: eager test, luckily no persitent config file makes it fail
        # -- vila 20100716
        my_config = self.get_branch_config(global_config=precedence_global)
        self.assertEqual(my_config.get_user_option('option'), 'global')
        my_config = self.get_branch_config(global_config=precedence_global,
                                           branch_data_config=precedence_branch)
        self.assertEqual(my_config.get_user_option('option'), 'branch')
        my_config = self.get_branch_config(
            global_config=precedence_global,
            branch_data_config=precedence_branch,
            location_config=precedence_location)
        self.assertEqual(my_config.get_user_option('option'), 'recurse')
        my_config = self.get_branch_config(
            global_config=precedence_global,
            branch_data_config=precedence_branch,
            location_config=precedence_location,
            location='http://example.com/specific')
        self.assertEqual(my_config.get_user_option('option'), 'exact')

    def test_get_mail_client(self):
        config = self.get_branch_config()
        client = config.get_mail_client()
        self.assertIsInstance(client, mail_client.DefaultMail)

        # Specific clients
        config.set_user_option('mail_client', 'evolution')
        client = config.get_mail_client()
        self.assertIsInstance(client, mail_client.Evolution)

        config.set_user_option('mail_client', 'kmail')
        client = config.get_mail_client()
        self.assertIsInstance(client, mail_client.KMail)

        config.set_user_option('mail_client', 'mutt')
        client = config.get_mail_client()
        self.assertIsInstance(client, mail_client.Mutt)

        config.set_user_option('mail_client', 'thunderbird')
        client = config.get_mail_client()
        self.assertIsInstance(client, mail_client.Thunderbird)

        # Generic options
        config.set_user_option('mail_client', 'default')
        client = config.get_mail_client()
        self.assertIsInstance(client, mail_client.DefaultMail)

        config.set_user_option('mail_client', 'editor')
        client = config.get_mail_client()
        self.assertIsInstance(client, mail_client.Editor)

        config.set_user_option('mail_client', 'mapi')
        client = config.get_mail_client()
        self.assertIsInstance(client, mail_client.MAPIClient)

        config.set_user_option('mail_client', 'xdg-email')
        client = config.get_mail_client()
        self.assertIsInstance(client, mail_client.XDGEmail)

        config.set_user_option('mail_client', 'firebird')
        self.assertRaises(errors.UnknownMailClient, config.get_mail_client)


class TestMailAddressExtraction(tests.TestCase):

    def test_extract_email_address(self):
        self.assertEqual('jane@test.com',
                         config.extract_email_address('Jane <jane@test.com>'))
        self.assertRaises(errors.NoEmailInUsername,
                          config.extract_email_address, 'Jane Tester')

    def test_parse_username(self):
        self.assertEqual(('', 'jdoe@example.com'),
                         config.parse_username('jdoe@example.com'))
        self.assertEqual(('', 'jdoe@example.com'),
                         config.parse_username('<jdoe@example.com>'))
        self.assertEqual(('John Doe', 'jdoe@example.com'),
                         config.parse_username('John Doe <jdoe@example.com>'))
        self.assertEqual(('John Doe', ''),
                         config.parse_username('John Doe'))
        self.assertEqual(('John Doe', 'jdoe@example.com'),
                         config.parse_username('John Doe jdoe@example.com'))

class TestTreeConfig(tests.TestCaseWithTransport):

    def test_get_value(self):
        """Test that retreiving a value from a section is possible"""
        branch = self.make_branch('.')
        tree_config = config.TreeConfig(branch)
        tree_config.set_option('value', 'key', 'SECTION')
        tree_config.set_option('value2', 'key2')
        tree_config.set_option('value3-top', 'key3')
        tree_config.set_option('value3-section', 'key3', 'SECTION')
        value = tree_config.get_option('key', 'SECTION')
        self.assertEqual(value, 'value')
        value = tree_config.get_option('key2')
        self.assertEqual(value, 'value2')
        self.assertEqual(tree_config.get_option('non-existant'), None)
        value = tree_config.get_option('non-existant', 'SECTION')
        self.assertEqual(value, None)
        value = tree_config.get_option('non-existant', default='default')
        self.assertEqual(value, 'default')
        self.assertEqual(tree_config.get_option('key2', 'NOSECTION'), None)
        value = tree_config.get_option('key2', 'NOSECTION', default='default')
        self.assertEqual(value, 'default')
        value = tree_config.get_option('key3')
        self.assertEqual(value, 'value3-top')
        value = tree_config.get_option('key3', 'SECTION')
        self.assertEqual(value, 'value3-section')


class TestTransportConfig(tests.TestCaseWithTransport):

    def test_get_value(self):
        """Test that retreiving a value from a section is possible"""
        bzrdir_config = config.TransportConfig(transport.get_transport('.'),
                                               'control.conf')
        bzrdir_config.set_option('value', 'key', 'SECTION')
        bzrdir_config.set_option('value2', 'key2')
        bzrdir_config.set_option('value3-top', 'key3')
        bzrdir_config.set_option('value3-section', 'key3', 'SECTION')
        value = bzrdir_config.get_option('key', 'SECTION')
        self.assertEqual(value, 'value')
        value = bzrdir_config.get_option('key2')
        self.assertEqual(value, 'value2')
        self.assertEqual(bzrdir_config.get_option('non-existant'), None)
        value = bzrdir_config.get_option('non-existant', 'SECTION')
        self.assertEqual(value, None)
        value = bzrdir_config.get_option('non-existant', default='default')
        self.assertEqual(value, 'default')
        self.assertEqual(bzrdir_config.get_option('key2', 'NOSECTION'), None)
        value = bzrdir_config.get_option('key2', 'NOSECTION',
                                         default='default')
        self.assertEqual(value, 'default')
        value = bzrdir_config.get_option('key3')
        self.assertEqual(value, 'value3-top')
        value = bzrdir_config.get_option('key3', 'SECTION')
        self.assertEqual(value, 'value3-section')

    def test_set_unset_default_stack_on(self):
        my_dir = self.make_bzrdir('.')
        bzrdir_config = config.BzrDirConfig(my_dir)
        self.assertIs(None, bzrdir_config.get_default_stack_on())
        bzrdir_config.set_default_stack_on('Foo')
        self.assertEqual('Foo', bzrdir_config._config.get_option(
                         'default_stack_on'))
        self.assertEqual('Foo', bzrdir_config.get_default_stack_on())
        bzrdir_config.set_default_stack_on(None)
        self.assertIs(None, bzrdir_config.get_default_stack_on())


def create_configs(test):
    """Create configuration files for a given test.

    This requires creating a tree (and populate the ``test.tree`` attribute)
    and its associated branch and will populate the following attributes:

    - branch_config: A BranchConfig for the associated branch.

    - locations_config : A LocationConfig for the associated branch

    - bazaar_config: A GlobalConfig.

    The tree and branch are created in a 'tree' subdirectory so the tests can
    still use the test directory to stay outside of the branch.
    """
    tree = test.make_branch_and_tree('tree')
    test.tree = tree
    test.branch_config = config.BranchConfig(tree.branch)
    test.locations_config = config.LocationConfig(tree.basedir)
    test.bazaar_config = config.GlobalConfig()


def create_configs_with_file_option(test):
    """Create configuration files with a ``file`` option set in each.

    This builds on ``create_configs`` and add one ``file`` option in each
    configuration with a value which allows identifying the configuration file.
    """
    create_configs(test)
    test.bazaar_config.set_user_option('file', 'bazaar')
    test.locations_config.set_user_option('file', 'locations')
    test.branch_config.set_user_option('file', 'branch')


class TestConfigGetOptions(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestConfigGetOptions, self).setUp()
        create_configs(self)

    def assertOptions(self, expected, conf):
        actual = list(conf._get_options())
        self.assertEqual(expected, actual)

    # One variable in none of the above
    def test_no_variable(self):
        # Using branch should query branch, locations and bazaar
        self.assertOptions([], self.branch_config)

    def test_option_in_bazaar(self):
        self.bazaar_config.set_user_option('file', 'bazaar')
        self.assertOptions([('file', 'bazaar', 'DEFAULT', 'bazaar')],
                           self.bazaar_config)

    def test_option_in_locations(self):
        self.locations_config.set_user_option('file', 'locations')
        self.assertOptions(
            [('file', 'locations', self.tree.basedir, 'locations')],
            self.locations_config)

    def test_option_in_branch(self):
        self.branch_config.set_user_option('file', 'branch')
        self.assertOptions([('file', 'branch', 'DEFAULT', 'branch')],
                           self.branch_config)

    def test_option_in_bazaar_and_branch(self):
        self.bazaar_config.set_user_option('file', 'bazaar')
        self.branch_config.set_user_option('file', 'branch')
        self.assertOptions([('file', 'branch', 'DEFAULT', 'branch'),
                            ('file', 'bazaar', 'DEFAULT', 'bazaar'),],
                           self.branch_config)

    def test_option_in_branch_and_locations(self):
        # Hmm, locations override branch :-/
        self.locations_config.set_user_option('file', 'locations')
        self.branch_config.set_user_option('file', 'branch')
        self.assertOptions(
            [('file', 'locations', self.tree.basedir, 'locations'),
             ('file', 'branch', 'DEFAULT', 'branch'),],
            self.branch_config)

    def test_option_in_bazaar_locations_and_branch(self):
        self.bazaar_config.set_user_option('file', 'bazaar')
        self.locations_config.set_user_option('file', 'locations')
        self.branch_config.set_user_option('file', 'branch')
        self.assertOptions(
            [('file', 'locations', self.tree.basedir, 'locations'),
             ('file', 'branch', 'DEFAULT', 'branch'),
             ('file', 'bazaar', 'DEFAULT', 'bazaar'),],
            self.branch_config)


class TestConfigRemoveOption(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestConfigRemoveOption, self).setUp()
        create_configs_with_file_option(self)

    def assertOptions(self, expected, conf):
        actual = list(conf._get_options())
        self.assertEqual(expected, actual)

    def test_remove_in_locations(self):
        self.locations_config.remove_user_option('file', self.tree.basedir)
        self.assertOptions(
            [('file', 'branch', 'DEFAULT', 'branch'),
             ('file', 'bazaar', 'DEFAULT', 'bazaar'),],
            self.branch_config)

    def test_remove_in_branch(self):
        self.branch_config.remove_user_option('file')
        self.assertOptions(
            [('file', 'locations', self.tree.basedir, 'locations'),
             ('file', 'bazaar', 'DEFAULT', 'bazaar'),],
            self.branch_config)

    def test_remove_in_bazaar(self):
        self.bazaar_config.remove_user_option('file')
        self.assertOptions(
            [('file', 'locations', self.tree.basedir, 'locations'),
             ('file', 'branch', 'DEFAULT', 'branch'),],
            self.branch_config)


class TestConfigGetSections(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestConfigGetSections, self).setUp()
        create_configs(self)

    def assertSectionNames(self, expected, conf, name=None):
        """Check which sections are returned for a given config.

        If fallback configurations exist their sections can be included.

        :param expected: A list of section names.

        :param conf: The configuration that will be queried.

        :param name: An optional section name that will be passed to
            get_sections().
        """
        sections = list(conf._get_sections(name))
        self.assertLength(len(expected), sections)
        self.assertEqual(expected, [name for name, _, _ in sections])

    def test_bazaar_default_section(self):
        self.assertSectionNames(['DEFAULT'], self.bazaar_config)

    def test_locations_default_section(self):
        # No sections are defined in an empty file
        self.assertSectionNames([], self.locations_config)

    def test_locations_named_section(self):
        self.locations_config.set_user_option('file', 'locations')
        self.assertSectionNames([self.tree.basedir], self.locations_config)

    def test_locations_matching_sections(self):
        loc_config = self.locations_config
        loc_config.set_user_option('file', 'locations')
        # We need to cheat a bit here to create an option in sections above and
        # below the 'location' one.
        parser = loc_config._get_parser()
        # locations.cong deals with '/' ignoring native os.sep
        location_names = self.tree.basedir.split('/')
        parent = '/'.join(location_names[:-1])
        child = '/'.join(location_names + ['child'])
        parser[parent] = {}
        parser[parent]['file'] = 'parent'
        parser[child] = {}
        parser[child]['file'] = 'child'
        self.assertSectionNames([self.tree.basedir, parent], loc_config)

    def test_branch_data_default_section(self):
        self.assertSectionNames([None],
                                self.branch_config._get_branch_data_config())

    def test_branch_default_sections(self):
        # No sections are defined in an empty locations file
        self.assertSectionNames([None, 'DEFAULT'],
                                self.branch_config)
        # Unless we define an option
        self.branch_config._get_location_config().set_user_option(
            'file', 'locations')
        self.assertSectionNames([self.tree.basedir, None, 'DEFAULT'],
                                self.branch_config)

    def test_bazaar_named_section(self):
        # We need to cheat as the API doesn't give direct access to sections
        # other than DEFAULT.
        self.bazaar_config.set_alias('bazaar', 'bzr')
        self.assertSectionNames(['ALIASES'], self.bazaar_config, 'ALIASES')


class TestAuthenticationConfigFile(tests.TestCase):
    """Test the authentication.conf file matching"""

    def _got_user_passwd(self, expected_user, expected_password,
                         config, *args, **kwargs):
        credentials = config.get_credentials(*args, **kwargs)
        if credentials is None:
            user = None
            password = None
        else:
            user = credentials['user']
            password = credentials['password']
        self.assertEquals(expected_user, user)
        self.assertEquals(expected_password, password)

    def test_empty_config(self):
        conf = config.AuthenticationConfig(_file=StringIO())
        self.assertEquals({}, conf._get_config())
        self._got_user_passwd(None, None, conf, 'http', 'foo.net')

    def test_missing_auth_section_header(self):
        conf = config.AuthenticationConfig(_file=StringIO('foo = bar'))
        self.assertRaises(ValueError, conf.get_credentials, 'ftp', 'foo.net')

    def test_auth_section_header_not_closed(self):
        conf = config.AuthenticationConfig(_file=StringIO('[DEF'))
        self.assertRaises(errors.ParseConfigError, conf._get_config)

    def test_auth_value_not_boolean(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """[broken]
scheme=ftp
user=joe
verify_certificates=askme # Error: Not a boolean
"""))
        self.assertRaises(ValueError, conf.get_credentials, 'ftp', 'foo.net')

    def test_auth_value_not_int(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """[broken]
scheme=ftp
user=joe
port=port # Error: Not an int
"""))
        self.assertRaises(ValueError, conf.get_credentials, 'ftp', 'foo.net')

    def test_unknown_password_encoding(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """[broken]
scheme=ftp
user=joe
password_encoding=unknown
"""))
        self.assertRaises(ValueError, conf.get_password,
                          'ftp', 'foo.net', 'joe')

    def test_credentials_for_scheme_host(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """# Identity on foo.net
[ftp definition]
scheme=ftp
host=foo.net
user=joe
password=secret-pass
"""))
        # Basic matching
        self._got_user_passwd('joe', 'secret-pass', conf, 'ftp', 'foo.net')
        # different scheme
        self._got_user_passwd(None, None, conf, 'http', 'foo.net')
        # different host
        self._got_user_passwd(None, None, conf, 'ftp', 'bar.net')

    def test_credentials_for_host_port(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """# Identity on foo.net
[ftp definition]
scheme=ftp
port=10021
host=foo.net
user=joe
password=secret-pass
"""))
        # No port
        self._got_user_passwd('joe', 'secret-pass',
                              conf, 'ftp', 'foo.net', port=10021)
        # different port
        self._got_user_passwd(None, None, conf, 'ftp', 'foo.net')

    def test_for_matching_host(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """# Identity on foo.net
[sourceforge]
scheme=bzr
host=bzr.sf.net
user=joe
password=joepass
[sourceforge domain]
scheme=bzr
host=.bzr.sf.net
user=georges
password=bendover
"""))
        # matching domain
        self._got_user_passwd('georges', 'bendover',
                              conf, 'bzr', 'foo.bzr.sf.net')
        # phishing attempt
        self._got_user_passwd(None, None,
                              conf, 'bzr', 'bbzr.sf.net')

    def test_for_matching_host_None(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """# Identity on foo.net
[catchup bzr]
scheme=bzr
user=joe
password=joepass
[DEFAULT]
user=georges
password=bendover
"""))
        # match no host
        self._got_user_passwd('joe', 'joepass',
                              conf, 'bzr', 'quux.net')
        # no host but different scheme
        self._got_user_passwd('georges', 'bendover',
                              conf, 'ftp', 'quux.net')

    def test_credentials_for_path(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """
[http dir1]
scheme=http
host=bar.org
path=/dir1
user=jim
password=jimpass
[http dir2]
scheme=http
host=bar.org
path=/dir2
user=georges
password=bendover
"""))
        # no path no dice
        self._got_user_passwd(None, None,
                              conf, 'http', host='bar.org', path='/dir3')
        # matching path
        self._got_user_passwd('georges', 'bendover',
                              conf, 'http', host='bar.org', path='/dir2')
        # matching subdir
        self._got_user_passwd('jim', 'jimpass',
                              conf, 'http', host='bar.org',path='/dir1/subdir')

    def test_credentials_for_user(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """
[with user]
scheme=http
host=bar.org
user=jim
password=jimpass
"""))
        # Get user
        self._got_user_passwd('jim', 'jimpass',
                              conf, 'http', 'bar.org')
        # Get same user
        self._got_user_passwd('jim', 'jimpass',
                              conf, 'http', 'bar.org', user='jim')
        # Don't get a different user if one is specified
        self._got_user_passwd(None, None,
                              conf, 'http', 'bar.org', user='georges')

    def test_credentials_for_user_without_password(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """
[without password]
scheme=http
host=bar.org
user=jim
"""))
        # Get user but no password
        self._got_user_passwd('jim', None,
                              conf, 'http', 'bar.org')

    def test_verify_certificates(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """
[self-signed]
scheme=https
host=bar.org
user=jim
password=jimpass
verify_certificates=False
[normal]
scheme=https
host=foo.net
user=georges
password=bendover
"""))
        credentials = conf.get_credentials('https', 'bar.org')
        self.assertEquals(False, credentials.get('verify_certificates'))
        credentials = conf.get_credentials('https', 'foo.net')
        self.assertEquals(True, credentials.get('verify_certificates'))


class TestAuthenticationStorage(tests.TestCaseInTempDir):

    def test_set_credentials(self):
        conf = config.AuthenticationConfig()
        conf.set_credentials('name', 'host', 'user', 'scheme', 'password',
        99, path='/foo', verify_certificates=False, realm='realm')
        credentials = conf.get_credentials(host='host', scheme='scheme',
                                           port=99, path='/foo',
                                           realm='realm')
        CREDENTIALS = {'name': 'name', 'user': 'user', 'password': 'password',
                       'verify_certificates': False, 'scheme': 'scheme', 
                       'host': 'host', 'port': 99, 'path': '/foo', 
                       'realm': 'realm'}
        self.assertEqual(CREDENTIALS, credentials)
        credentials_from_disk = config.AuthenticationConfig().get_credentials(
            host='host', scheme='scheme', port=99, path='/foo', realm='realm')
        self.assertEqual(CREDENTIALS, credentials_from_disk)

    def test_reset_credentials_different_name(self):
        conf = config.AuthenticationConfig()
        conf.set_credentials('name', 'host', 'user', 'scheme', 'password'),
        conf.set_credentials('name2', 'host', 'user2', 'scheme', 'password'),
        self.assertIs(None, conf._get_config().get('name'))
        credentials = conf.get_credentials(host='host', scheme='scheme')
        CREDENTIALS = {'name': 'name2', 'user': 'user2', 'password':
                       'password', 'verify_certificates': True, 
                       'scheme': 'scheme', 'host': 'host', 'port': None, 
                       'path': None, 'realm': None}
        self.assertEqual(CREDENTIALS, credentials)


class TestAuthenticationConfig(tests.TestCase):
    """Test AuthenticationConfig behaviour"""

    def _check_default_password_prompt(self, expected_prompt_format, scheme,
                                       host=None, port=None, realm=None,
                                       path=None):
        if host is None:
            host = 'bar.org'
        user, password = 'jim', 'precious'
        expected_prompt = expected_prompt_format % {
            'scheme': scheme, 'host': host, 'port': port,
            'user': user, 'realm': realm}

        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        ui.ui_factory = tests.TestUIFactory(stdin=password + '\n',
                                            stdout=stdout, stderr=stderr)
        # We use an empty conf so that the user is always prompted
        conf = config.AuthenticationConfig()
        self.assertEquals(password,
                          conf.get_password(scheme, host, user, port=port,
                                            realm=realm, path=path))
        self.assertEquals(expected_prompt, stderr.getvalue())
        self.assertEquals('', stdout.getvalue())

    def _check_default_username_prompt(self, expected_prompt_format, scheme,
                                       host=None, port=None, realm=None,
                                       path=None):
        if host is None:
            host = 'bar.org'
        username = 'jim'
        expected_prompt = expected_prompt_format % {
            'scheme': scheme, 'host': host, 'port': port,
            'realm': realm}
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        ui.ui_factory = tests.TestUIFactory(stdin=username+ '\n',
                                            stdout=stdout, stderr=stderr)
        # We use an empty conf so that the user is always prompted
        conf = config.AuthenticationConfig()
        self.assertEquals(username, conf.get_user(scheme, host, port=port,
                          realm=realm, path=path, ask=True))
        self.assertEquals(expected_prompt, stderr.getvalue())
        self.assertEquals('', stdout.getvalue())

    def test_username_defaults_prompts(self):
        # HTTP prompts can't be tested here, see test_http.py
        self._check_default_username_prompt('FTP %(host)s username: ', 'ftp')
        self._check_default_username_prompt(
            'FTP %(host)s:%(port)d username: ', 'ftp', port=10020)
        self._check_default_username_prompt(
            'SSH %(host)s:%(port)d username: ', 'ssh', port=12345)

    def test_username_default_no_prompt(self):
        conf = config.AuthenticationConfig()
        self.assertEquals(None,
            conf.get_user('ftp', 'example.com'))
        self.assertEquals("explicitdefault",
            conf.get_user('ftp', 'example.com', default="explicitdefault"))

    def test_password_default_prompts(self):
        # HTTP prompts can't be tested here, see test_http.py
        self._check_default_password_prompt(
            'FTP %(user)s@%(host)s password: ', 'ftp')
        self._check_default_password_prompt(
            'FTP %(user)s@%(host)s:%(port)d password: ', 'ftp', port=10020)
        self._check_default_password_prompt(
            'SSH %(user)s@%(host)s:%(port)d password: ', 'ssh', port=12345)
        # SMTP port handling is a bit special (it's handled if embedded in the
        # host too)
        # FIXME: should we: forbid that, extend it to other schemes, leave
        # things as they are that's fine thank you ?
        self._check_default_password_prompt('SMTP %(user)s@%(host)s password: ',
                                            'smtp')
        self._check_default_password_prompt('SMTP %(user)s@%(host)s password: ',
                                            'smtp', host='bar.org:10025')
        self._check_default_password_prompt(
            'SMTP %(user)s@%(host)s:%(port)d password: ',
            'smtp', port=10025)

    def test_ssh_password_emits_warning(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """
[ssh with password]
scheme=ssh
host=bar.org
user=jim
password=jimpass
"""))
        entered_password = 'typed-by-hand'
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        ui.ui_factory = tests.TestUIFactory(stdin=entered_password + '\n',
                                            stdout=stdout, stderr=stderr)

        # Since the password defined in the authentication config is ignored,
        # the user is prompted
        self.assertEquals(entered_password,
                          conf.get_password('ssh', 'bar.org', user='jim'))
        self.assertContainsRe(
            self.get_log(),
            'password ignored in section \[ssh with password\]')

    def test_ssh_without_password_doesnt_emit_warning(self):
        conf = config.AuthenticationConfig(_file=StringIO(
                """
[ssh with password]
scheme=ssh
host=bar.org
user=jim
"""))
        entered_password = 'typed-by-hand'
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        ui.ui_factory = tests.TestUIFactory(stdin=entered_password + '\n',
                                            stdout=stdout,
                                            stderr=stderr)

        # Since the password defined in the authentication config is ignored,
        # the user is prompted
        self.assertEquals(entered_password,
                          conf.get_password('ssh', 'bar.org', user='jim'))
        # No warning shoud be emitted since there is no password. We are only
        # providing "user".
        self.assertNotContainsRe(
            self.get_log(),
            'password ignored in section \[ssh with password\]')

    def test_uses_fallback_stores(self):
        self.overrideAttr(config, 'credential_store_registry',
                          config.CredentialStoreRegistry())
        store = StubCredentialStore()
        store.add_credentials("http", "example.com", "joe", "secret")
        config.credential_store_registry.register("stub", store, fallback=True)
        conf = config.AuthenticationConfig(_file=StringIO())
        creds = conf.get_credentials("http", "example.com")
        self.assertEquals("joe", creds["user"])
        self.assertEquals("secret", creds["password"])


class StubCredentialStore(config.CredentialStore):

    def __init__(self):
        self._username = {}
        self._password = {}

    def add_credentials(self, scheme, host, user, password=None):
        self._username[(scheme, host)] = user
        self._password[(scheme, host)] = password

    def get_credentials(self, scheme, host, port=None, user=None,
        path=None, realm=None):
        key = (scheme, host)
        if not key in self._username:
            return None
        return { "scheme": scheme, "host": host, "port": port,
                "user": self._username[key], "password": self._password[key]}


class CountingCredentialStore(config.CredentialStore):

    def __init__(self):
        self._calls = 0

    def get_credentials(self, scheme, host, port=None, user=None,
        path=None, realm=None):
        self._calls += 1
        return None


class TestCredentialStoreRegistry(tests.TestCase):

    def _get_cs_registry(self):
        return config.credential_store_registry

    def test_default_credential_store(self):
        r = self._get_cs_registry()
        default = r.get_credential_store(None)
        self.assertIsInstance(default, config.PlainTextCredentialStore)

    def test_unknown_credential_store(self):
        r = self._get_cs_registry()
        # It's hard to imagine someone creating a credential store named
        # 'unknown' so we use that as an never registered key.
        self.assertRaises(KeyError, r.get_credential_store, 'unknown')

    def test_fallback_none_registered(self):
        r = config.CredentialStoreRegistry()
        self.assertEquals(None,
                          r.get_fallback_credentials("http", "example.com"))

    def test_register(self):
        r = config.CredentialStoreRegistry()
        r.register("stub", StubCredentialStore(), fallback=False)
        r.register("another", StubCredentialStore(), fallback=True)
        self.assertEquals(["another", "stub"], r.keys())

    def test_register_lazy(self):
        r = config.CredentialStoreRegistry()
        r.register_lazy("stub", "bzrlib.tests.test_config",
                        "StubCredentialStore", fallback=False)
        self.assertEquals(["stub"], r.keys())
        self.assertIsInstance(r.get_credential_store("stub"),
                              StubCredentialStore)

    def test_is_fallback(self):
        r = config.CredentialStoreRegistry()
        r.register("stub1", None, fallback=False)
        r.register("stub2", None, fallback=True)
        self.assertEquals(False, r.is_fallback("stub1"))
        self.assertEquals(True, r.is_fallback("stub2"))

    def test_no_fallback(self):
        r = config.CredentialStoreRegistry()
        store = CountingCredentialStore()
        r.register("count", store, fallback=False)
        self.assertEquals(None,
                          r.get_fallback_credentials("http", "example.com"))
        self.assertEquals(0, store._calls)

    def test_fallback_credentials(self):
        r = config.CredentialStoreRegistry()
        store = StubCredentialStore()
        store.add_credentials("http", "example.com",
                              "somebody", "geheim")
        r.register("stub", store, fallback=True)
        creds = r.get_fallback_credentials("http", "example.com")
        self.assertEquals("somebody", creds["user"])
        self.assertEquals("geheim", creds["password"])

    def test_fallback_first_wins(self):
        r = config.CredentialStoreRegistry()
        stub1 = StubCredentialStore()
        stub1.add_credentials("http", "example.com",
                              "somebody", "stub1")
        r.register("stub1", stub1, fallback=True)
        stub2 = StubCredentialStore()
        stub2.add_credentials("http", "example.com",
                              "somebody", "stub2")
        r.register("stub2", stub1, fallback=True)
        creds = r.get_fallback_credentials("http", "example.com")
        self.assertEquals("somebody", creds["user"])
        self.assertEquals("stub1", creds["password"])


class TestPlainTextCredentialStore(tests.TestCase):

    def test_decode_password(self):
        r = config.credential_store_registry
        plain_text = r.get_credential_store()
        decoded = plain_text.decode_password(dict(password='secret'))
        self.assertEquals('secret', decoded)


# FIXME: Once we have a way to declare authentication to all test servers, we
# can implement generic tests.
# test_user_password_in_url
# test_user_in_url_password_from_config
# test_user_in_url_password_prompted
# test_user_in_config
# test_user_getpass.getuser
# test_user_prompted ?
class TestAuthenticationRing(tests.TestCaseWithTransport):
    pass
