# Copyright (C) 2005-2014, 2016 Canonical Ltd
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

import os
import sys
import threading
from io import BytesIO
from textwrap import dedent

import configobj
from testtools import matchers

from .. import (
    bedding,
    branch,
    config,
    controldir,
    diff,
    errors,
    lock,
    mail_client,
    osutils,
    tests,
    trace,
    ui,
    urlutils,
)
from .. import registry as _mod_registry
from .. import transport as _mod_transport
from ..bzr import remote
from ..transport import remote as transport_remote
from . import features, scenarios, test_server


def lockable_config_scenarios():
    return [
        (
            "global",
            {
                "config_class": config.GlobalConfig,
                "config_args": [],
                "config_section": "DEFAULT",
            },
        ),
        (
            "locations",
            {
                "config_class": config.LocationConfig,
                "config_args": ["."],
                "config_section": ".",
            },
        ),
    ]


load_tests = scenarios.load_tests_apply_scenarios

# Register helpers to build stores
config.test_store_builder_registry.register(
    "configobj",
    lambda test: config.TransportIniFileStore(test.get_transport(), "configobj.conf"),
)
config.test_store_builder_registry.register("breezy", lambda test: config.GlobalStore())
config.test_store_builder_registry.register(
    "location", lambda test: config.LocationStore()
)


def build_backing_branch(test, relpath, transport_class=None, server_class=None):
    """Test helper to create a backing branch only once.

    Some tests needs multiple stores/stacks to check concurrent update
    behaviours. As such, they need to build different branch *objects* even if
    they share the branch on disk.

    :param relpath: The relative path to the branch. (Note that the helper
        should always specify the same relpath).

    :param transport_class: The Transport class the test needs to use.

    :param server_class: The server associated with the ``transport_class``
        above.

    Either both or neither of ``transport_class`` and ``server_class`` should
    be specified.
    """
    if transport_class is not None and server_class is not None:
        test.transport_class = transport_class
        test.transport_server = server_class
    elif not (transport_class is None and server_class is None):
        raise AssertionError(
            "Specify both ``transport_class`` and ``server_class`` or neither of them"
        )
    if getattr(test, "backing_branch", None) is None:
        # First call, let's build the branch on disk
        test.backing_branch = test.make_branch(relpath)


def build_branch_store(test):
    build_backing_branch(test, "branch")
    b = branch.Branch.open("branch")
    return config.BranchStore(b)


config.test_store_builder_registry.register("branch", build_branch_store)


def build_control_store(test):
    build_backing_branch(test, "branch")
    b = controldir.ControlDir.open("branch")
    return config.ControlStore(b)


config.test_store_builder_registry.register("control", build_control_store)


def build_remote_branch_store(test):
    # There is only one permutation (but we won't be able to handle more with
    # this design anyway)
    (transport_class, server_class) = transport_remote.get_test_permutations()[0]
    build_backing_branch(test, "branch", transport_class, server_class)
    b = branch.Branch.open(test.get_url("branch"))
    return config.BranchStore(b)


config.test_store_builder_registry.register("remote_branch", build_remote_branch_store)


config.test_stack_builder_registry.register("breezy", lambda test: config.GlobalStack())
config.test_stack_builder_registry.register(
    "location", lambda test: config.LocationStack(".")
)


def build_branch_stack(test):
    build_backing_branch(test, "branch")
    b = branch.Branch.open("branch")
    return config.BranchStack(b)


config.test_stack_builder_registry.register("branch", build_branch_stack)


def build_branch_only_stack(test):
    # There is only one permutation (but we won't be able to handle more with
    # this design anyway)
    (transport_class, server_class) = transport_remote.get_test_permutations()[0]
    build_backing_branch(test, "branch", transport_class, server_class)
    b = branch.Branch.open(test.get_url("branch"))
    return config.BranchOnlyStack(b)


config.test_stack_builder_registry.register("branch_only", build_branch_only_stack)


def build_remote_control_stack(test):
    # There is only one permutation (but we won't be able to handle more with
    # this design anyway)
    (transport_class, server_class) = transport_remote.get_test_permutations()[0]
    # We need only a bzrdir for this, not a full branch, but it's not worth
    # creating a dedicated helper to create only the bzrdir
    build_backing_branch(test, "branch", transport_class, server_class)
    b = branch.Branch.open(test.get_url("branch"))
    return config.RemoteControlStack(b.controldir)


config.test_stack_builder_registry.register(
    "remote_control", build_remote_control_stack
)


sample_long_alias = "log -r-15..-1 --line"
sample_config_text = (
    """
[DEFAULT]
email=Erik B\u00e5gfors <erik@bagfors.nu>
editor=vim
change_editor=vimdiff -of {new_path} {old_path}
gpg_signing_key=DD4D5088
log_format=short
validate_signatures_in_log=true
acceptable_keys=amy
user_global_option=something
bzr.mergetool.sometool=sometool {base} {this} {other} -o {result}
bzr.mergetool.funkytool=funkytool "arg with spaces" {this_temp}
bzr.mergetool.newtool='"newtool with spaces" {this_temp}'
bzr.default_mergetool=sometool
[ALIASES]
h=help
ll=""".encode()
    + sample_long_alias.encode("utf-8")
    + b"\n"
)


sample_always_signatures = b"""
[DEFAULT]
check_signatures=ignore
create_signatures=always
"""

sample_ignore_signatures = b"""
[DEFAULT]
check_signatures=require
create_signatures=never
"""

sample_maybe_signatures = b"""
[DEFAULT]
check_signatures=ignore
create_signatures=when-required
"""

sample_branches_text = b"""
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
gpg_signing_key=default
user_local_option=local
# test trailing / matching
[/a/*]
#subdirs will match but not the parent
[/a/c]
check_signatures=ignore
post_commit=breezy.tests.test_config.post_commit
#testing explicit beats globs
"""


def create_configs(test):
    """Create configuration files for a given test.

    This requires creating a tree (and populate the ``test.tree`` attribute)
    and its associated branch and will populate the following attributes:

    - branch_config: A BranchConfig for the associated branch.

    - locations_config : A LocationConfig for the associated branch

    - breezy_config: A GlobalConfig.

    The tree and branch are created in a 'tree' subdirectory so the tests can
    still use the test directory to stay outside of the branch.
    """
    tree = test.make_branch_and_tree("tree")
    test.tree = tree
    test.branch_config = config.BranchConfig(tree.branch)
    test.locations_config = config.LocationConfig(tree.basedir)
    test.breezy_config = config.GlobalConfig()


def create_configs_with_file_option(test):
    """Create configuration files with a ``file`` option set in each.

    This builds on ``create_configs`` and add one ``file`` option in each
    configuration with a value which allows identifying the configuration file.
    """
    create_configs(test)
    test.breezy_config.set_user_option("file", "breezy")
    test.locations_config.set_user_option("file", "locations")
    test.branch_config.set_user_option("file", "branch")


class TestOptionsMixin:
    def assertOptions(self, expected, conf):
        # We don't care about the parser (as it will make tests hard to write
        # and error-prone anyway)
        self.assertThat(
            [opt[:4] for opt in conf._get_options()], matchers.Equals(expected)
        )


class InstrumentedConfigObj:
    """A config obj look-enough-alike to record calls made to it."""

    def __contains__(self, thing):
        self._calls.append(("__contains__", thing))
        return False

    def __getitem__(self, key):
        self._calls.append(("__getitem__", key))
        return self

    def __init__(self, input, encoding=None):
        self._calls = [("__init__", input, encoding)]

    def __setitem__(self, key, value):
        self._calls.append(("__setitem__", key, value))

    def __delitem__(self, key):
        self._calls.append(("__delitem__", key))

    def keys(self):
        self._calls.append(("keys",))
        return []

    def reload(self):
        self._calls.append(("reload",))

    def write(self, arg):
        self._calls.append(("write",))

    def as_bool(self, value):
        self._calls.append(("as_bool", value))
        return False

    def get_value(self, section, name):
        self._calls.append(("get_value", section, name))
        return None


class FakeBranch:
    def __init__(self, base=None):
        if base is None:
            self.base = "http://example.com/branches/demo"
        else:
            self.base = base
        self._transport = self.control_files = FakeControlFilesAndTransport()

    def _get_config(self):
        return config.TransportConfig(self._transport, "branch.conf")

    def lock_write(self):
        return lock.LogicalLockResult(self.unlock)

    def unlock(self):
        pass


class FakeControlFilesAndTransport:
    def __init__(self):
        self.files = {}
        self._transport = self

    def get(self, filename):
        # from Transport
        try:
            return BytesIO(self.files[filename])
        except KeyError as e:
            raise _mod_transport.NoSuchFile(filename) from e

    def get_bytes(self, filename):
        # from Transport
        try:
            return self.files[filename]
        except KeyError as e:
            raise _mod_transport.NoSuchFile(filename) from e

    def put(self, filename, fileobj):
        self.files[filename] = fileobj.read()

    def put_file(self, filename, fileobj):
        return self.put(filename, fileobj)


class InstrumentedConfig(config.Config):
    """An instrumented config that supplies stubs for template methods."""

    def __init__(self):
        super().__init__()
        self._calls = []
        self._signatures = config.CHECK_NEVER
        self._change_editor = "vimdiff -fo {new_path} {old_path}"

    def _get_user_id(self):
        self._calls.append("_get_user_id")
        return "Robert Collins <robert.collins@example.org>"

    def _get_signature_checking(self):
        self._calls.append("_get_signature_checking")
        return self._signatures

    def _get_change_editor(self):
        self._calls.append("_get_change_editor")
        return self._change_editor


bool_config = b"""[DEFAULT]
active = true
inactive = false
[UPPERCASE]
active = True
nonactive = False
"""


class TestConfigObj(tests.TestCase):
    def test_get_bool(self):
        co = config.ConfigObj(BytesIO(bool_config))
        self.assertTrue(co.get_bool("DEFAULT", "active"))
        self.assertFalse(co.get_bool("DEFAULT", "inactive"))
        self.assertTrue(co.get_bool("UPPERCASE", "active"))
        self.assertFalse(co.get_bool("UPPERCASE", "nonactive"))

    def test_hash_sign_in_value(self):
        """Before 4.5.0, ConfigObj did not quote # signs in values, so they'd be
        treated as comments when read in again. (#86838).
        """
        co = config.ConfigObj()
        co["test"] = "foo#bar"
        outfile = BytesIO()
        co.write(outfile=outfile)
        lines = outfile.getvalue().splitlines()
        self.assertEqual(lines, [b'test = "foo#bar"'])
        co2 = config.ConfigObj(lines)
        self.assertEqual(co2["test"], "foo#bar")

    def test_triple_quotes(self):
        # Bug #710410: if the value string has triple quotes
        # then ConfigObj versions up to 4.7.2 will quote them wrong
        # and won't able to read them back
        triple_quotes_value = '''spam
""" that's my spam """
eggs'''
        co = config.ConfigObj()
        co["test"] = triple_quotes_value
        # While writing this test another bug in ConfigObj has been found:
        # method co.write() without arguments produces list of lines
        # one option per line, and multiline values are not split
        # across multiple lines,
        # and that breaks the parsing these lines back by ConfigObj.
        # This issue only affects test, but it's better to avoid
        # `co.write()` construct at all.
        # [bialix 20110222] bug report sent to ConfigObj's author
        outfile = BytesIO()
        co.write(outfile=outfile)
        output = outfile.getvalue()
        # now we're trying to read it back
        co2 = config.ConfigObj(BytesIO(output))
        self.assertEqual(triple_quotes_value, co2["test"])


erroneous_config = b"""[section] # line 1
good=good # line 2
[section] # line 3
whocares=notme # line 4
"""


class TestConfigObjErrors(tests.TestCase):
    def test_duplicate_section_name_error_line(self):
        try:
            configobj.ConfigObj(BytesIO(erroneous_config), raise_errors=True)
        except config.configobj.DuplicateError as e:
            self.assertEqual(3, e.line_number)
        else:
            self.fail("Error in config file not detected")


class TestConfig(tests.TestCase):
    def test_constructs(self):
        config.Config()

    def test_user_email(self):
        my_config = InstrumentedConfig()
        self.assertEqual("robert.collins@example.org", my_config.user_email())
        self.assertEqual(["_get_user_id"], my_config._calls)

    def test_username(self):
        my_config = InstrumentedConfig()
        self.assertEqual(
            "Robert Collins <robert.collins@example.org>", my_config.username()
        )
        self.assertEqual(["_get_user_id"], my_config._calls)

    def test_get_user_option_default(self):
        my_config = config.Config()
        self.assertEqual(None, my_config.get_user_option("no_option"))

    def test_validate_signatures_in_log_default(self):
        my_config = config.Config()
        self.assertEqual(False, my_config.validate_signatures_in_log())

    def test_get_change_editor(self):
        my_config = InstrumentedConfig()
        change_editor = my_config.get_change_editor("old_tree", "new_tree")
        self.assertEqual(["_get_change_editor"], my_config._calls)
        self.assertIs(diff.DiffFromTool, change_editor.__class__)
        self.assertEqual(
            ["vimdiff", "-fo", "{new_path}", "{old_path}"],
            change_editor.command_template,
        )

    def test_get_change_editor_implicit_args(self):
        # If there are no substitution variables, then assume the
        # old and new path are the last arguments.
        my_config = InstrumentedConfig()
        my_config._change_editor = "vimdiff -o"
        change_editor = my_config.get_change_editor("old_tree", "new_tree")
        self.assertEqual(["_get_change_editor"], my_config._calls)
        self.assertIs(diff.DiffFromTool, change_editor.__class__)
        self.assertEqual(
            ["vimdiff", "-o", "{old_path}", "{new_path}"],
            change_editor.command_template,
        )

    def test_get_change_editor_old_style(self):
        # Test the old style format for the change_editor setting.
        my_config = InstrumentedConfig()
        my_config._change_editor = "vimdiff -o @old_path @new_path"
        change_editor = my_config.get_change_editor("old_tree", "new_tree")
        self.assertEqual(["_get_change_editor"], my_config._calls)
        self.assertIs(diff.DiffFromTool, change_editor.__class__)
        self.assertEqual(
            ["vimdiff", "-o", "{old_path}", "{new_path}"],
            change_editor.command_template,
        )


class TestIniConfig(tests.TestCaseInTempDir):
    def make_config_parser(self, s):
        conf = config.IniBasedConfig.from_string(s)
        return conf, conf._get_parser()


class TestIniConfigBuilding(TestIniConfig):
    def test_contructs(self):
        config.IniBasedConfig()

    def test_from_fp(self):
        my_config = config.IniBasedConfig.from_string(sample_config_text)
        self.assertIsInstance(my_config._get_parser(), configobj.ConfigObj)

    def test_cached(self):
        my_config = config.IniBasedConfig.from_string(sample_config_text)
        parser = my_config._get_parser()
        self.assertIs(my_config._get_parser(), parser)

    def test_ini_config_ownership(self):
        """Ensure that chown is happening during _write_config_file."""
        self.requireFeature(features.chown_feature)
        conf = config.IniBasedConfig(file_name="./foo.conf")
        conf._write_config_file()
        got = os.stat("foo.conf")
        expected = os.stat(".")
        self.assertEqual(expected.st_uid, got.st_uid)
        self.assertEqual(expected.st_gid, got.st_gid)


class TestIniConfigSaving(tests.TestCaseInTempDir):
    def test_cant_save_without_a_file_name(self):
        conf = config.IniBasedConfig()
        self.assertRaises(AssertionError, conf._write_config_file)

    def test_saved_with_content(self):
        content = b"foo = bar\n"
        config.IniBasedConfig.from_string(content, file_name="./test.conf", save=True)
        self.assertFileEqual(content, "test.conf")


class TestIniConfigOptionExpansion(tests.TestCase):
    """Test option expansion from the IniConfig level.

    What we really want here is to test the Config level, but the class being
    abstract as far as storing values is concerned, this can't be done
    properly (yet).
    """

    # FIXME: This should be rewritten when all configs share a storage
    # implementation -- vila 2011-02-18

    def get_config(self, string=None):
        if string is None:
            string = b""
        c = config.IniBasedConfig.from_string(string)
        return c

    def assertExpansion(self, expected, conf, string, env=None):
        self.assertEqual(expected, conf.expand_options(string, env))

    def test_no_expansion(self):
        c = self.get_config("")
        self.assertExpansion("foo", c, "foo")

    def test_env_adding_options(self):
        c = self.get_config("")
        self.assertExpansion("bar", c, "{foo}", {"foo": "bar"})

    def test_env_overriding_options(self):
        c = self.get_config("foo=baz")
        self.assertExpansion("bar", c, "{foo}", {"foo": "bar"})

    def test_simple_ref(self):
        c = self.get_config("foo=xxx")
        self.assertExpansion("xxx", c, "{foo}")

    def test_unknown_ref(self):
        c = self.get_config("")
        self.assertRaises(config.ExpandingUnknownOption, c.expand_options, "{foo}")

    def test_indirect_ref(self):
        c = self.get_config(
            """
foo=xxx
bar={foo}
"""
        )
        self.assertExpansion("xxx", c, "{bar}")

    def test_embedded_ref(self):
        c = self.get_config(
            """
foo=xxx
bar=foo
"""
        )
        self.assertExpansion("xxx", c, "{{bar}}")

    def test_simple_loop(self):
        c = self.get_config("foo={foo}")
        self.assertRaises(config.OptionExpansionLoop, c.expand_options, "{foo}")

    def test_indirect_loop(self):
        c = self.get_config(
            """
foo={bar}
bar={baz}
baz={foo}"""
        )
        e = self.assertRaises(config.OptionExpansionLoop, c.expand_options, "{foo}")
        self.assertEqual("foo->bar->baz", e.refs)
        self.assertEqual("{foo}", e.string)

    def test_list(self):
        conf = self.get_config(
            """
foo=start
bar=middle
baz=end
list={foo},{bar},{baz}
"""
        )
        self.assertEqual(
            ["start", "middle", "end"], conf.get_user_option("list", expand=True)
        )

    def test_cascading_list(self):
        conf = self.get_config(
            """
foo=start,{bar}
bar=middle,{baz}
baz=end
list={foo}
"""
        )
        self.assertEqual(
            ["start", "middle", "end"], conf.get_user_option("list", expand=True)
        )

    def test_pathological_hidden_list(self):
        conf = self.get_config(
            """
foo=bin
bar=go
start={foo
middle=},{
end=bar}
hidden={start}{middle}{end}
"""
        )
        # Nope, it's either a string or a list, and the list wins as soon as a
        # ',' appears, so the string concatenation never occur.
        self.assertEqual(
            ["{foo", "}", "{", "bar}"], conf.get_user_option("hidden", expand=True)
        )


class TestLocationConfigOptionExpansion(tests.TestCaseInTempDir):
    def get_config(self, location, string=None):
        if string is None:
            string = ""
        # Since we don't save the config we won't strictly require to inherit
        # from TestCaseInTempDir, but an error occurs so quickly...
        c = config.LocationConfig.from_string(string, location)
        return c

    def test_dont_cross_unrelated_section(self):
        c = self.get_config(
            "/another/branch/path",
            """
[/one/branch/path]
foo = hello
bar = {foo}/2

[/another/branch/path]
bar = {foo}/2
""",
        )
        self.assertRaises(
            config.ExpandingUnknownOption, c.get_user_option, "bar", expand=True
        )

    def test_cross_related_sections(self):
        c = self.get_config(
            "/project/branch/path",
            """
[/project]
foo = qu

[/project/branch/path]
bar = {foo}ux
""",
        )
        self.assertEqual("quux", c.get_user_option("bar", expand=True))


class TestIniBaseConfigOnDisk(tests.TestCaseInTempDir):
    def test_cannot_reload_without_name(self):
        conf = config.IniBasedConfig.from_string(sample_config_text)
        self.assertRaises(AssertionError, conf.reload)

    def test_reload_see_new_value(self):
        c1 = config.IniBasedConfig.from_string("editor=vim\n", file_name="./test/conf")
        c1._write_config_file()
        c2 = config.IniBasedConfig.from_string(
            "editor=emacs\n", file_name="./test/conf"
        )
        c2._write_config_file()
        self.assertEqual("vim", c1.get_user_option("editor"))
        self.assertEqual("emacs", c2.get_user_option("editor"))
        # Make sure we get the Right value
        c1.reload()
        self.assertEqual("emacs", c1.get_user_option("editor"))


class TestLockableConfig(tests.TestCaseInTempDir):
    scenarios = lockable_config_scenarios()

    # Set by load_tests
    config_class = None
    config_args = None
    config_section = None

    def setUp(self):
        super().setUp()
        self._content = f"[{self.config_section}]\none=1\ntwo=2\n"
        self.config = self.create_config(self._content)

    def get_existing_config(self):
        return self.config_class(*self.config_args)

    def create_config(self, content):
        kwargs = {"save": True}
        c = self.config_class.from_string(content, *self.config_args, **kwargs)
        return c

    def test_simple_read_access(self):
        self.assertEqual("1", self.config.get_user_option("one"))

    def test_simple_write_access(self):
        self.config.set_user_option("one", "one")
        self.assertEqual("one", self.config.get_user_option("one"))

    def test_listen_to_the_last_speaker(self):
        c1 = self.config
        c2 = self.get_existing_config()
        c1.set_user_option("one", "ONE")
        c2.set_user_option("two", "TWO")
        self.assertEqual("ONE", c1.get_user_option("one"))
        self.assertEqual("TWO", c2.get_user_option("two"))
        # The second update respect the first one
        self.assertEqual("ONE", c2.get_user_option("one"))

    def test_last_speaker_wins(self):
        # If the same config is not shared, the same variable modified twice
        # can only see a single result.
        c1 = self.config
        c2 = self.get_existing_config()
        c1.set_user_option("one", "c1")
        c2.set_user_option("one", "c2")
        self.assertEqual("c2", c2._get_user_option("one"))
        # The first modification is still available until another refresh
        # occur
        self.assertEqual("c1", c1._get_user_option("one"))
        c1.set_user_option("two", "done")
        self.assertEqual("c2", c1._get_user_option("one"))

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
            # The lock is held. We wait for the main thread to decide when to
            # continue
            after_writing.wait()

        c1._write_config_file = c1_write_config_file

        def c1_set_option():
            c1.set_user_option("one", "c1")
            writing_done.set()

        t1 = threading.Thread(target=c1_set_option)
        # Collect the thread after the test
        self.addCleanup(t1.join)
        # Be ready to unblock the thread if the test goes wrong
        self.addCleanup(after_writing.set)
        t1.start()
        before_writing.wait()
        self.assertTrue(c1._lock.is_held)
        self.assertRaises(errors.LockContention, c2.set_user_option, "one", "c2")
        self.assertEqual("c1", c1.get_user_option("one"))
        # Let the lock be released
        after_writing.set()
        writing_done.wait()
        c2.set_user_option("one", "c2")
        self.assertEqual("c2", c2.get_user_option("one"))

    def test_read_while_writing(self):
        c1 = self.config
        # We spawn a thread that will pause *during* the write
        ready_to_write = threading.Event()
        do_writing = threading.Event()
        writing_done = threading.Event()
        c1_orig = c1._write_config_file

        def c1_write_config_file():
            ready_to_write.set()
            # The lock is held. We wait for the main thread to decide when to
            # continue
            do_writing.wait()
            c1_orig()
            writing_done.set()

        c1._write_config_file = c1_write_config_file

        def c1_set_option():
            c1.set_user_option("one", "c1")

        t1 = threading.Thread(target=c1_set_option)
        # Collect the thread after the test
        self.addCleanup(t1.join)
        # Be ready to unblock the thread if the test goes wrong
        self.addCleanup(do_writing.set)
        t1.start()
        # Ensure the thread is ready to write
        ready_to_write.wait()
        self.assertTrue(c1._lock.is_held)
        self.assertEqual("c1", c1.get_user_option("one"))
        # If we read during the write, we get the old value
        c2 = self.get_existing_config()
        self.assertEqual("1", c2.get_user_option("one"))
        # Let the writing occur and ensure it occurred
        do_writing.set()
        writing_done.wait()
        # Now we get the updated value
        c3 = self.get_existing_config()
        self.assertEqual("c1", c3.get_user_option("one"))


class TestGetUserOptionAs(TestIniConfig):
    def test_get_user_option_as_bool(self):
        conf, parser = self.make_config_parser(
            """
a_true_bool = true
a_false_bool = 0
an_invalid_bool = maybe
a_list = hmm, who knows ? # This is interpreted as a list !
"""
        )
        get_bool = conf.get_user_option_as_bool
        self.assertEqual(True, get_bool("a_true_bool"))
        self.assertEqual(False, get_bool("a_false_bool"))
        warnings = []

        def warning(*args):
            warnings.append(args[0] % args[1:])

        self.overrideAttr(trace, "warning", warning)
        msg = 'Value "%s" is not a boolean for "%s"'
        self.assertIs(None, get_bool("an_invalid_bool"))
        self.assertEqual(msg % ("maybe", "an_invalid_bool"), warnings[0])
        warnings = []
        self.assertIs(None, get_bool("not_defined_in_this_config"))
        self.assertEqual([], warnings)

    def test_get_user_option_as_list(self):
        conf, parser = self.make_config_parser(
            """
a_list = a,b,c
length_1 = 1,
one_item = x
"""
        )
        get_list = conf.get_user_option_as_list
        self.assertEqual(["a", "b", "c"], get_list("a_list"))
        self.assertEqual(["1"], get_list("length_1"))
        self.assertEqual("x", conf.get_user_option("one_item"))
        # automatically cast to list
        self.assertEqual(["x"], get_list("one_item"))


class TestSupressWarning(TestIniConfig):
    def make_warnings_config(self, s):
        conf, parser = self.make_config_parser(s)
        return conf.suppress_warning

    def test_suppress_warning_unknown(self):
        suppress_warning = self.make_warnings_config("")
        self.assertEqual(False, suppress_warning("unknown_warning"))

    def test_suppress_warning_known(self):
        suppress_warning = self.make_warnings_config("suppress_warnings=a,b")
        self.assertEqual(False, suppress_warning("c"))
        self.assertEqual(True, suppress_warning("a"))
        self.assertEqual(True, suppress_warning("b"))


class TestGetConfig(tests.TestCaseInTempDir):
    def test_constructs(self):
        config.GlobalConfig()

    def test_calls_read_filenames(self):
        # replace the class that is constructed, to check its parameters
        oldparserclass = config.ConfigObj
        config.ConfigObj = InstrumentedConfigObj
        my_config = config.GlobalConfig()
        try:
            parser = my_config._get_parser()
        finally:
            config.ConfigObj = oldparserclass
        self.assertIsInstance(parser, InstrumentedConfigObj)
        self.assertEqual(parser._calls, [("__init__", bedding.config_path(), "utf-8")])


class TestBranchConfig(tests.TestCaseWithTransport):
    def test_constructs_valid(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        self.assertIsNot(None, my_config)

    def test_constructs_error(self):
        self.assertRaises(TypeError, config.BranchConfig)

    def test_get_location_config(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        location_config = my_config._get_location_config()
        self.assertEqual(branch.base, location_config.location)
        self.assertIs(location_config, my_config._get_location_config())

    def test_get_config(self):
        """The Branch.get_config method works properly."""
        b = controldir.ControlDir.create_standalone_workingtree(".").branch
        my_config = b.get_config()
        self.assertIsNone(my_config.get_user_option("wacky"))
        my_config.set_user_option("wacky", "unlikely")
        self.assertEqual(my_config.get_user_option("wacky"), "unlikely")

        # Ensure we get the same thing if we start again
        b2 = branch.Branch.open(".")
        my_config2 = b2.get_config()
        self.assertEqual(my_config2.get_user_option("wacky"), "unlikely")

    def test_has_explicit_nickname(self):
        b = self.make_branch(".")
        self.assertFalse(b.get_config().has_explicit_nickname())
        b.nick = "foo"
        self.assertTrue(b.get_config().has_explicit_nickname())

    def test_config_url(self):
        """The Branch.get_config will use section that uses a local url."""
        branch = self.make_branch("branch")
        self.assertEqual("branch", branch.nick)

        local_url = urlutils.local_path_to_url("branch")
        conf = config.LocationConfig.from_string(
            f"[{local_url}]\nnickname = foobar", local_url, save=True
        )
        self.assertIsNot(None, conf)
        self.assertEqual("foobar", branch.nick)

    def test_config_local_path(self):
        """The Branch.get_config will use a local system path."""
        branch = self.make_branch("branch")
        self.assertEqual("branch", branch.nick)

        local_path = osutils.getcwd().encode("utf8")
        config.LocationConfig.from_string(
            b"[%s/branch]\nnickname = barry" % (local_path,), "branch", save=True
        )
        # Now the branch will find its nick via the location config
        self.assertEqual("barry", branch.nick)

    def test_config_creates_local(self):
        """Creating a new entry in config uses a local path."""
        branch = self.make_branch("branch", format="knit")
        branch.set_push_location("http://foobar")
        local_path = osutils.getcwd().encode("utf8")
        # Surprisingly ConfigObj doesn't create a trailing newline
        self.check_file_contents(
            bedding.locations_config_path(),
            b"[%s/branch]\n"
            b"push_location = http://foobar\n"
            b"push_location:policy = norecurse\n" % (local_path,),
        )

    def test_autonick_urlencoded(self):
        b = self.make_branch("!repo")
        self.assertEqual("!repo", b.get_config().get_nickname())

    def test_autonick_uses_branch_name(self):
        b = self.make_branch("foo", name="bar")
        self.assertEqual("bar", b.get_config().get_nickname())

    def test_warn_if_masked(self):
        warnings = []

        def warning(*args):
            warnings.append(args[0] % args[1:])

        self.overrideAttr(trace, "warning", warning)

        def set_option(store, warn_masked=True):
            warnings[:] = []
            conf.set_user_option(
                "example_option", repr(store), store=store, warn_masked=warn_masked
            )

        def assertWarning(warning):
            if warning is None:
                self.assertEqual(0, len(warnings))
            else:
                self.assertEqual(1, len(warnings))
                self.assertEqual(warning, warnings[0])

        branch = self.make_branch(".")
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
    def _get_empty_config(self):
        my_config = config.GlobalConfig()
        return my_config

    def _get_sample_config(self):
        my_config = config.GlobalConfig.from_string(sample_config_text)
        return my_config

    def test_user_id(self):
        my_config = config.GlobalConfig.from_string(sample_config_text)
        self.assertEqual(
            "Erik B\u00e5gfors <erik@bagfors.nu>", my_config._get_user_id()
        )

    def test_absent_user_id(self):
        my_config = config.GlobalConfig()
        self.assertEqual(None, my_config._get_user_id())

    def test_get_user_option_default(self):
        my_config = self._get_empty_config()
        self.assertEqual(None, my_config.get_user_option("no_option"))

    def test_get_user_option_global(self):
        my_config = self._get_sample_config()
        self.assertEqual("something", my_config.get_user_option("user_global_option"))

    def test_configured_validate_signatures_in_log(self):
        my_config = self._get_sample_config()
        self.assertEqual(True, my_config.validate_signatures_in_log())

    def test_get_alias(self):
        my_config = self._get_sample_config()
        self.assertEqual("help", my_config.get_alias("h"))

    def test_get_aliases(self):
        my_config = self._get_sample_config()
        aliases = my_config.get_aliases()
        self.assertEqual(2, len(aliases))
        sorted_keys = sorted(aliases)
        self.assertEqual("help", aliases[sorted_keys[0]])
        self.assertEqual(sample_long_alias, aliases[sorted_keys[1]])

    def test_get_no_alias(self):
        my_config = self._get_sample_config()
        self.assertEqual(None, my_config.get_alias("foo"))

    def test_get_long_alias(self):
        my_config = self._get_sample_config()
        self.assertEqual(sample_long_alias, my_config.get_alias("ll"))

    def test_get_change_editor(self):
        my_config = self._get_sample_config()
        change_editor = my_config.get_change_editor("old", "new")
        self.assertIs(diff.DiffFromTool, change_editor.__class__)
        self.assertEqual(
            "vimdiff -of {new_path} {old_path}",
            " ".join(change_editor.command_template),
        )

    def test_get_no_change_editor(self):
        my_config = self._get_empty_config()
        change_editor = my_config.get_change_editor("old", "new")
        self.assertIs(None, change_editor)

    def test_get_merge_tools(self):
        conf = self._get_sample_config()
        tools = conf.get_merge_tools()
        self.log(repr(tools))
        self.assertEqual(
            {
                "funkytool": 'funkytool "arg with spaces" {this_temp}',
                "sometool": "sometool {base} {this} {other} -o {result}",
                "newtool": '"newtool with spaces" {this_temp}',
            },
            tools,
        )

    def test_get_merge_tools_empty(self):
        conf = self._get_empty_config()
        tools = conf.get_merge_tools()
        self.assertEqual({}, tools)

    def test_find_merge_tool(self):
        conf = self._get_sample_config()
        cmdline = conf.find_merge_tool("sometool")
        self.assertEqual("sometool {base} {this} {other} -o {result}", cmdline)

    def test_find_merge_tool_not_found(self):
        conf = self._get_sample_config()
        cmdline = conf.find_merge_tool("DOES NOT EXIST")
        self.assertIsNone(cmdline)

    def test_find_merge_tool_known(self):
        conf = self._get_empty_config()
        cmdline = conf.find_merge_tool("kdiff3")
        self.assertEqual("kdiff3 {base} {this} {other} -o {result}", cmdline)

    def test_find_merge_tool_override_known(self):
        conf = self._get_empty_config()
        conf.set_user_option("bzr.mergetool.kdiff3", "kdiff3 blah")
        cmdline = conf.find_merge_tool("kdiff3")
        self.assertEqual("kdiff3 blah", cmdline)


class TestGlobalConfigSavingOptions(tests.TestCaseInTempDir):
    def test_empty(self):
        my_config = config.GlobalConfig()
        self.assertEqual(0, len(my_config.get_aliases()))

    def test_set_alias(self):
        my_config = config.GlobalConfig()
        alias_value = "commit --strict"
        my_config.set_alias("commit", alias_value)
        new_config = config.GlobalConfig()
        self.assertEqual(alias_value, new_config.get_alias("commit"))

    def test_remove_alias(self):
        my_config = config.GlobalConfig()
        my_config.set_alias("commit", "commit --strict")
        # Now remove the alias again.
        my_config.unset_alias("commit")
        new_config = config.GlobalConfig()
        self.assertIs(None, new_config.get_alias("commit"))


class TestLocationConfig(tests.TestCaseInTempDir, TestOptionsMixin):
    def test_constructs_valid(self):
        config.LocationConfig("http://example.com")

    def test_constructs_error(self):
        self.assertRaises(TypeError, config.LocationConfig)

    def test_branch_calls_read_filenames(self):
        # This is testing the correct file names are provided.
        # TODO: consolidate with the test for GlobalConfigs filename checks.
        #
        # replace the class that is constructed, to check its parameters
        oldparserclass = config.ConfigObj
        config.ConfigObj = InstrumentedConfigObj
        try:
            my_config = config.LocationConfig("http://www.example.com")
            parser = my_config._get_parser()
        finally:
            config.ConfigObj = oldparserclass
        self.assertIsInstance(parser, InstrumentedConfigObj)
        self.assertEqual(
            parser._calls, [("__init__", bedding.locations_config_path(), "utf-8")]
        )

    def test_get_global_config(self):
        my_config = config.BranchConfig(FakeBranch("http://example.com"))
        global_config = my_config._get_global_config()
        self.assertIsInstance(global_config, config.GlobalConfig)
        self.assertIs(global_config, my_config._get_global_config())

    def assertLocationMatching(self, expected):
        self.assertEqual(
            expected, list(self.my_location_config._get_matching_sections())
        )

    def test__get_matching_sections_no_match(self):
        self.get_branch_config("/")
        self.assertLocationMatching([])

    def test__get_matching_sections_exact(self):
        self.get_branch_config("http://www.example.com")
        self.assertLocationMatching([("http://www.example.com", "")])

    def test__get_matching_sections_suffix_does_not(self):
        self.get_branch_config("http://www.example.com-com")
        self.assertLocationMatching([])

    def test__get_matching_sections_subdir_recursive(self):
        self.get_branch_config("http://www.example.com/com")
        self.assertLocationMatching([("http://www.example.com", "com")])

    def test__get_matching_sections_ignoreparent(self):
        self.get_branch_config("http://www.example.com/ignoreparent")
        self.assertLocationMatching([("http://www.example.com/ignoreparent", "")])

    def test__get_matching_sections_ignoreparent_subdir(self):
        self.get_branch_config("http://www.example.com/ignoreparent/childbranch")
        self.assertLocationMatching(
            [("http://www.example.com/ignoreparent", "childbranch")]
        )

    def test__get_matching_sections_subdir_trailing_slash(self):
        self.get_branch_config("/b")
        self.assertLocationMatching([("/b/", "")])

    def test__get_matching_sections_subdir_child(self):
        self.get_branch_config("/a/foo")
        self.assertLocationMatching([("/a/*", ""), ("/a/", "foo")])

    def test__get_matching_sections_subdir_child_child(self):
        self.get_branch_config("/a/foo/bar")
        self.assertLocationMatching([("/a/*", "bar"), ("/a/", "foo/bar")])

    def test__get_matching_sections_trailing_slash_with_children(self):
        self.get_branch_config("/a/")
        self.assertLocationMatching([("/a/", "")])

    def test__get_matching_sections_explicit_over_glob(self):
        # XXX: 2006-09-08 jamesh
        # This test only passes because ord('c') > ord('*').  If there
        # was a config section for '/a/?', it would get precedence
        # over '/a/c'.
        self.get_branch_config("/a/c")
        self.assertLocationMatching([("/a/c", ""), ("/a/*", ""), ("/a/", "c")])

    def test__get_option_policy_normal(self):
        self.get_branch_config("http://www.example.com")
        self.assertEqual(
            self.my_location_config._get_option_policy(
                "http://www.example.com", "normal_option"
            ),
            config.POLICY_NONE,
        )

    def test__get_option_policy_norecurse(self):
        self.get_branch_config("http://www.example.com")
        self.assertEqual(
            self.my_location_config._get_option_policy(
                "http://www.example.com", "norecurse_option"
            ),
            config.POLICY_NORECURSE,
        )
        # Test old recurse=False setting:
        self.assertEqual(
            self.my_location_config._get_option_policy(
                "http://www.example.com/norecurse", "normal_option"
            ),
            config.POLICY_NORECURSE,
        )

    def test__get_option_policy_normal_appendpath(self):
        self.get_branch_config("http://www.example.com")
        self.assertEqual(
            self.my_location_config._get_option_policy(
                "http://www.example.com", "appendpath_option"
            ),
            config.POLICY_APPENDPATH,
        )

    def test__get_options_with_policy(self):
        self.get_branch_config(
            "/dir/subdir",
            location_config="""\
[/dir]
other_url = /other-dir
other_url:policy = appendpath
[/dir/subdir]
other_url = /other-subdir
""",
        )
        self.assertOptions(
            [
                ("other_url", "/other-subdir", "/dir/subdir", "locations"),
                ("other_url", "/other-dir", "/dir", "locations"),
                ("other_url:policy", "appendpath", "/dir", "locations"),
            ],
            self.my_location_config,
        )

    def test_location_without_username(self):
        self.get_branch_config("http://www.example.com/ignoreparent")
        self.assertEqual(
            "Erik B\u00e5gfors <erik@bagfors.nu>", self.my_config.username()
        )

    def test_location_not_listed(self):
        """Test that the global username is used when no location matches."""
        self.get_branch_config("/home/robertc/sources")
        self.assertEqual(
            "Erik B\u00e5gfors <erik@bagfors.nu>", self.my_config.username()
        )

    def test_overriding_location(self):
        self.get_branch_config("http://www.example.com/foo")
        self.assertEqual(
            "Robert Collins <robertc@example.org>", self.my_config.username()
        )

    def test_get_user_option_global(self):
        self.get_branch_config("/a")
        self.assertEqual(
            "something", self.my_config.get_user_option("user_global_option")
        )

    def test_get_user_option_local(self):
        self.get_branch_config("/a")
        self.assertEqual("local", self.my_config.get_user_option("user_local_option"))

    def test_get_user_option_appendpath(self):
        # returned as is for the base path:
        self.get_branch_config("http://www.example.com")
        self.assertEqual("append", self.my_config.get_user_option("appendpath_option"))
        # Extra path components get appended:
        self.get_branch_config("http://www.example.com/a/b/c")
        self.assertEqual(
            "append/a/b/c", self.my_config.get_user_option("appendpath_option")
        )
        # Overriden for http://www.example.com/dir, where it is a
        # normal option:
        self.get_branch_config("http://www.example.com/dir/a/b/c")
        self.assertEqual("normal", self.my_config.get_user_option("appendpath_option"))

    def test_get_user_option_norecurse(self):
        self.get_branch_config("http://www.example.com")
        self.assertEqual(
            "norecurse", self.my_config.get_user_option("norecurse_option")
        )
        self.get_branch_config("http://www.example.com/dir")
        self.assertEqual(None, self.my_config.get_user_option("norecurse_option"))
        # http://www.example.com/norecurse is a recurse=False section
        # that redefines normal_option.  Subdirectories do not pick up
        # this redefinition.
        self.get_branch_config("http://www.example.com/norecurse")
        self.assertEqual("norecurse", self.my_config.get_user_option("normal_option"))
        self.get_branch_config("http://www.example.com/norecurse/subdir")
        self.assertEqual("normal", self.my_config.get_user_option("normal_option"))

    def test_set_user_option_norecurse(self):
        self.get_branch_config("http://www.example.com")
        self.my_config.set_user_option(
            "foo", "bar", store=config.STORE_LOCATION_NORECURSE
        )
        self.assertEqual(
            self.my_location_config._get_option_policy("http://www.example.com", "foo"),
            config.POLICY_NORECURSE,
        )

    def test_set_user_option_appendpath(self):
        self.get_branch_config("http://www.example.com")
        self.my_config.set_user_option(
            "foo", "bar", store=config.STORE_LOCATION_APPENDPATH
        )
        self.assertEqual(
            self.my_location_config._get_option_policy("http://www.example.com", "foo"),
            config.POLICY_APPENDPATH,
        )

    def test_set_user_option_change_policy(self):
        self.get_branch_config("http://www.example.com")
        self.my_config.set_user_option(
            "norecurse_option", "normal", store=config.STORE_LOCATION
        )
        self.assertEqual(
            self.my_location_config._get_option_policy(
                "http://www.example.com", "norecurse_option"
            ),
            config.POLICY_NONE,
        )

    def get_branch_config(self, location, global_config=None, location_config=None):
        my_branch = FakeBranch(location)
        if global_config is None:
            global_config = sample_config_text
        if location_config is None:
            location_config = sample_branches_text

        config.GlobalConfig.from_string(global_config, save=True)
        config.LocationConfig.from_string(location_config, my_branch.base, save=True)
        my_config = config.BranchConfig(my_branch)
        self.my_config = my_config
        self.my_location_config = my_config._get_location_config()

    def test_set_user_setting_sets_and_saves2(self):
        self.get_branch_config("/a/c")
        self.assertIsNone(self.my_config.get_user_option("foo"))
        self.my_config.set_user_option("foo", "bar")
        self.assertEqual(
            self.my_config.branch.control_files.files["branch.conf"].strip(),
            b"foo = bar",
        )
        self.assertEqual(self.my_config.get_user_option("foo"), "bar")
        self.my_config.set_user_option("foo", "baz", store=config.STORE_LOCATION)
        self.assertEqual(self.my_config.get_user_option("foo"), "baz")
        self.my_config.set_user_option("foo", "qux")
        self.assertEqual(self.my_config.get_user_option("foo"), "baz")

    def test_get_bzr_remote_path(self):
        my_config = config.LocationConfig("/a/c")
        self.assertEqual("bzr", my_config.get_bzr_remote_path())
        my_config.set_user_option("bzr_remote_path", "/path-bzr")
        self.assertEqual("/path-bzr", my_config.get_bzr_remote_path())
        self.overrideEnv("BZR_REMOTE_PATH", "/environ-bzr")
        self.assertEqual("/environ-bzr", my_config.get_bzr_remote_path())


precedence_global = b"option = global"
precedence_branch = b"option = branch"
precedence_location = b"""
[http://]
recurse = true
option = recurse
[http://example.com/specific]
option = exact
"""


class TestBranchConfigItems(tests.TestCaseInTempDir):
    def get_branch_config(
        self,
        global_config=None,
        location=None,
        location_config=None,
        branch_data_config=None,
    ):
        my_branch = FakeBranch(location)
        if global_config is not None:
            config.GlobalConfig.from_string(global_config, save=True)
        if location_config is not None:
            config.LocationConfig.from_string(
                location_config, my_branch.base, save=True
            )
        my_config = config.BranchConfig(my_branch)
        if branch_data_config is not None:
            my_config.branch.control_files.files["branch.conf"] = branch_data_config
        return my_config

    def test_user_id(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        self.assertIsNot(None, my_config.username())
        my_config.branch.control_files.files["email"] = "John"
        my_config.set_user_option("email", "Robert Collins <robertc@example.org>")
        self.assertEqual("Robert Collins <robertc@example.org>", my_config.username())

    def test_BRZ_EMAIL_OVERRIDES(self):
        self.overrideEnv("BRZ_EMAIL", "Robert Collins <robertc@example.org>")
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        self.assertEqual("Robert Collins <robertc@example.org>", my_config.username())

    def test_get_user_option_global(self):
        my_config = self.get_branch_config(global_config=sample_config_text)
        self.assertEqual("something", my_config.get_user_option("user_global_option"))

    def test_config_precedence(self):
        # FIXME: eager test, luckily no persitent config file makes it fail
        # -- vila 20100716
        my_config = self.get_branch_config(global_config=precedence_global)
        self.assertEqual(my_config.get_user_option("option"), "global")
        my_config = self.get_branch_config(
            global_config=precedence_global, branch_data_config=precedence_branch
        )
        self.assertEqual(my_config.get_user_option("option"), "branch")
        my_config = self.get_branch_config(
            global_config=precedence_global,
            branch_data_config=precedence_branch,
            location_config=precedence_location,
        )
        self.assertEqual(my_config.get_user_option("option"), "recurse")
        my_config = self.get_branch_config(
            global_config=precedence_global,
            branch_data_config=precedence_branch,
            location_config=precedence_location,
            location="http://example.com/specific",
        )
        self.assertEqual(my_config.get_user_option("option"), "exact")


class TestMailAddressExtraction(tests.TestCase):
    def test_extract_email_address(self):
        self.assertEqual(
            "jane@test.com", config.extract_email_address("Jane <jane@test.com>")
        )
        self.assertRaises(
            config.NoEmailInUsername, config.extract_email_address, "Jane Tester"
        )

    def test_parse_username(self):
        self.assertEqual(
            ("", "jdoe@example.com"), config.parse_username("jdoe@example.com")
        )
        self.assertEqual(
            ("", "jdoe@example.com"), config.parse_username("<jdoe@example.com>")
        )
        self.assertEqual(
            ("John Doe", "jdoe@example.com"),
            config.parse_username("John Doe <jdoe@example.com>"),
        )
        self.assertEqual(("John Doe", ""), config.parse_username("John Doe"))
        self.assertEqual(
            ("John Doe", "jdoe@example.com"),
            config.parse_username("John Doe jdoe@example.com"),
        )
        self.assertEqual(
            ("John Doe", "jdoe[bot]@example.com"),
            config.parse_username("John Doe <jdoe[bot]@example.com>"),
        )


class TestTreeConfig(tests.TestCaseWithTransport):
    def test_get_value(self):
        """Test that retreiving a value from a section is possible."""
        branch = self.make_branch(".")
        tree_config = config.TreeConfig(branch)
        tree_config.set_option("value", "key", "SECTION")
        tree_config.set_option("value2", "key2")
        tree_config.set_option("value3-top", "key3")
        tree_config.set_option("value3-section", "key3", "SECTION")
        value = tree_config.get_option("key", "SECTION")
        self.assertEqual(value, "value")
        value = tree_config.get_option("key2")
        self.assertEqual(value, "value2")
        self.assertEqual(tree_config.get_option("non-existant"), None)
        value = tree_config.get_option("non-existant", "SECTION")
        self.assertEqual(value, None)
        value = tree_config.get_option("non-existant", default="default")
        self.assertEqual(value, "default")
        self.assertEqual(tree_config.get_option("key2", "NOSECTION"), None)
        value = tree_config.get_option("key2", "NOSECTION", default="default")
        self.assertEqual(value, "default")
        value = tree_config.get_option("key3")
        self.assertEqual(value, "value3-top")
        value = tree_config.get_option("key3", "SECTION")
        self.assertEqual(value, "value3-section")


class TestTransportConfig(tests.TestCaseWithTransport):
    def test_load_utf8(self):
        """Ensure we can load an utf8-encoded file."""
        t = self.get_transport()
        unicode_user = "b\N{EURO SIGN}ar"
        unicode_content = f"user={unicode_user}"
        utf8_content = unicode_content.encode("utf8")
        # Store the raw content in the config file
        t.put_bytes("foo.conf", utf8_content)
        conf = config.TransportConfig(t, "foo.conf")
        self.assertEqual(unicode_user, conf.get_option("user"))

    def test_load_non_ascii(self):
        """Ensure we display a proper error on non-ascii, non utf-8 content."""
        t = self.get_transport()
        t.put_bytes("foo.conf", b"user=foo\n#\xff\n")
        conf = config.TransportConfig(t, "foo.conf")
        self.assertRaises(config.ConfigContentError, conf._get_configobj)

    def test_load_erroneous_content(self):
        """Ensure we display a proper error on content that can't be parsed."""
        t = self.get_transport()
        t.put_bytes("foo.conf", b"[open_section\n")
        conf = config.TransportConfig(t, "foo.conf")
        self.assertRaises(config.ParseConfigError, conf._get_configobj)

    def test_load_permission_denied(self):
        """Ensure we get an empty config file if the file is inaccessible."""
        warnings = []

        def warning(*args):
            warnings.append(args[0] % args[1:])

        self.overrideAttr(trace, "warning", warning)

        class DenyingTransport:
            def __init__(self, base):
                self.base = base

            def get_bytes(self, relpath):
                raise errors.PermissionDenied(relpath, "")

        cfg = config.TransportConfig(DenyingTransport("nonexisting://"), "control.conf")
        self.assertIs(None, cfg.get_option("non-existant", "SECTION"))
        self.assertEqual(
            warnings,
            [
                "Permission denied while trying to open configuration file "
                "nonexisting:///control.conf."
            ],
        )

    def test_get_value(self):
        """Test that retreiving a value from a section is possible."""
        bzrdir_config = config.TransportConfig(self.get_transport("."), "control.conf")
        bzrdir_config.set_option("value", "key", "SECTION")
        bzrdir_config.set_option("value2", "key2")
        bzrdir_config.set_option("value3-top", "key3")
        bzrdir_config.set_option("value3-section", "key3", "SECTION")
        value = bzrdir_config.get_option("key", "SECTION")
        self.assertEqual(value, "value")
        value = bzrdir_config.get_option("key2")
        self.assertEqual(value, "value2")
        self.assertEqual(bzrdir_config.get_option("non-existant"), None)
        value = bzrdir_config.get_option("non-existant", "SECTION")
        self.assertEqual(value, None)
        value = bzrdir_config.get_option("non-existant", default="default")
        self.assertEqual(value, "default")
        self.assertEqual(bzrdir_config.get_option("key2", "NOSECTION"), None)
        value = bzrdir_config.get_option("key2", "NOSECTION", default="default")
        self.assertEqual(value, "default")
        value = bzrdir_config.get_option("key3")
        self.assertEqual(value, "value3-top")
        value = bzrdir_config.get_option("key3", "SECTION")
        self.assertEqual(value, "value3-section")

    def test_set_unset_default_stack_on(self):
        my_dir = self.make_controldir(".")
        bzrdir_config = config.BzrDirConfig(my_dir)
        self.assertIs(None, bzrdir_config.get_default_stack_on())
        bzrdir_config.set_default_stack_on("Foo")
        self.assertEqual("Foo", bzrdir_config._config.get_option("default_stack_on"))
        self.assertEqual("Foo", bzrdir_config.get_default_stack_on())
        bzrdir_config.set_default_stack_on(None)
        self.assertIs(None, bzrdir_config.get_default_stack_on())


class TestOldConfigHooks(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        create_configs_with_file_option(self)

    def assertGetHook(self, conf, name, value):
        calls = []

        def hook(*args):
            calls.append(args)

        config.OldConfigHooks.install_named_hook("get", hook, None)
        self.addCleanup(config.OldConfigHooks.uninstall_named_hook, "get", None)
        self.assertLength(0, calls)
        actual_value = conf.get_user_option(name)
        self.assertEqual(value, actual_value)
        self.assertLength(1, calls)
        self.assertEqual((conf, name, value), calls[0])

    def test_get_hook_breezy(self):
        self.assertGetHook(self.breezy_config, "file", "breezy")

    def test_get_hook_locations(self):
        self.assertGetHook(self.locations_config, "file", "locations")

    def test_get_hook_branch(self):
        # Since locations masks branch, we define a different option
        self.branch_config.set_user_option("file2", "branch")
        self.assertGetHook(self.branch_config, "file2", "branch")

    def assertSetHook(self, conf, name, value):
        calls = []

        def hook(*args):
            calls.append(args)

        config.OldConfigHooks.install_named_hook("set", hook, None)
        self.addCleanup(config.OldConfigHooks.uninstall_named_hook, "set", None)
        self.assertLength(0, calls)
        conf.set_user_option(name, value)
        self.assertLength(1, calls)
        # We can't assert the conf object below as different configs use
        # different means to implement set_user_option and we care only about
        # coverage here.
        self.assertEqual((name, value), calls[0][1:])

    def test_set_hook_breezy(self):
        self.assertSetHook(self.breezy_config, "foo", "breezy")

    def test_set_hook_locations(self):
        self.assertSetHook(self.locations_config, "foo", "locations")

    def test_set_hook_branch(self):
        self.assertSetHook(self.branch_config, "foo", "branch")

    def assertRemoveHook(self, conf, name, section_name=None):
        calls = []

        def hook(*args):
            calls.append(args)

        config.OldConfigHooks.install_named_hook("remove", hook, None)
        self.addCleanup(config.OldConfigHooks.uninstall_named_hook, "remove", None)
        self.assertLength(0, calls)
        conf.remove_user_option(name, section_name)
        self.assertLength(1, calls)
        # We can't assert the conf object below as different configs use
        # different means to implement remove_user_option and we care only about
        # coverage here.
        self.assertEqual((name,), calls[0][1:])

    def test_remove_hook_breezy(self):
        self.assertRemoveHook(self.breezy_config, "file")

    def test_remove_hook_locations(self):
        self.assertRemoveHook(
            self.locations_config, "file", self.locations_config.location
        )

    def test_remove_hook_branch(self):
        self.assertRemoveHook(self.branch_config, "file")

    def assertLoadHook(self, name, conf_class, *conf_args):
        calls = []

        def hook(*args):
            calls.append(args)

        config.OldConfigHooks.install_named_hook("load", hook, None)
        self.addCleanup(config.OldConfigHooks.uninstall_named_hook, "load", None)
        self.assertLength(0, calls)
        # Build a config
        conf = conf_class(*conf_args)
        # Access an option to trigger a load
        conf.get_user_option(name)
        self.assertLength(1, calls)
        # Since we can't assert about conf, we just use the number of calls ;-/

    def test_load_hook_breezy(self):
        self.assertLoadHook("file", config.GlobalConfig)

    def test_load_hook_locations(self):
        self.assertLoadHook("file", config.LocationConfig, self.tree.basedir)

    def test_load_hook_branch(self):
        self.assertLoadHook("file", config.BranchConfig, self.tree.branch)

    def assertSaveHook(self, conf):
        calls = []

        def hook(*args):
            calls.append(args)

        config.OldConfigHooks.install_named_hook("save", hook, None)
        self.addCleanup(config.OldConfigHooks.uninstall_named_hook, "save", None)
        self.assertLength(0, calls)
        # Setting an option triggers a save
        conf.set_user_option("foo", "bar")
        self.assertLength(1, calls)
        # Since we can't assert about conf, we just use the number of calls ;-/

    def test_save_hook_breezy(self):
        self.assertSaveHook(self.breezy_config)

    def test_save_hook_locations(self):
        self.assertSaveHook(self.locations_config)

    def test_save_hook_branch(self):
        self.assertSaveHook(self.branch_config)


class TestOldConfigHooksForRemote(tests.TestCaseWithTransport):
    """Tests config hooks for remote configs.

    No tests for the remove hook as this is not implemented there.
    """

    def setUp(self):
        super().setUp()
        self.transport_server = test_server.SmartTCPServer_for_testing
        create_configs_with_file_option(self)

    def assertGetHook(self, conf, name, value):
        calls = []

        def hook(*args):
            calls.append(args)

        config.OldConfigHooks.install_named_hook("get", hook, None)
        self.addCleanup(config.OldConfigHooks.uninstall_named_hook, "get", None)
        self.assertLength(0, calls)
        actual_value = conf.get_option(name)
        self.assertEqual(value, actual_value)
        self.assertLength(1, calls)
        self.assertEqual((conf, name, value), calls[0])

    def test_get_hook_remote_branch(self):
        remote_branch = branch.Branch.open(self.get_url("tree"))
        self.assertGetHook(remote_branch._get_config(), "file", "branch")

    def test_get_hook_remote_bzrdir(self):
        remote_bzrdir = controldir.ControlDir.open(self.get_url("tree"))
        conf = remote_bzrdir._get_config()
        conf.set_option("remotedir", "file")
        self.assertGetHook(conf, "file", "remotedir")

    def assertSetHook(self, conf, name, value):
        calls = []

        def hook(*args):
            calls.append(args)

        config.OldConfigHooks.install_named_hook("set", hook, None)
        self.addCleanup(config.OldConfigHooks.uninstall_named_hook, "set", None)
        self.assertLength(0, calls)
        conf.set_option(value, name)
        self.assertLength(1, calls)
        # We can't assert the conf object below as different configs use
        # different means to implement set_user_option and we care only about
        # coverage here.
        self.assertEqual((name, value), calls[0][1:])

    def test_set_hook_remote_branch(self):
        remote_branch = branch.Branch.open(self.get_url("tree"))
        self.addCleanup(remote_branch.lock_write().unlock)
        self.assertSetHook(remote_branch._get_config(), "file", "remote")

    def test_set_hook_remote_bzrdir(self):
        remote_branch = branch.Branch.open(self.get_url("tree"))
        self.addCleanup(remote_branch.lock_write().unlock)
        remote_bzrdir = controldir.ControlDir.open(self.get_url("tree"))
        self.assertSetHook(remote_bzrdir._get_config(), "file", "remotedir")

    def assertLoadHook(self, expected_nb_calls, name, conf_class, *conf_args):
        calls = []

        def hook(*args):
            calls.append(args)

        config.OldConfigHooks.install_named_hook("load", hook, None)
        self.addCleanup(config.OldConfigHooks.uninstall_named_hook, "load", None)
        self.assertLength(0, calls)
        # Build a config
        conf = conf_class(*conf_args)
        # Access an option to trigger a load
        conf.get_option(name)
        self.assertLength(expected_nb_calls, calls)
        # Since we can't assert about conf, we just use the number of calls ;-/

    def test_load_hook_remote_branch(self):
        remote_branch = branch.Branch.open(self.get_url("tree"))
        self.assertLoadHook(1, "file", remote.RemoteBranchConfig, remote_branch)

    def test_load_hook_remote_bzrdir(self):
        remote_bzrdir = controldir.ControlDir.open(self.get_url("tree"))
        # The config file doesn't exist, set an option to force its creation
        conf = remote_bzrdir._get_config()
        conf.set_option("remotedir", "file")
        # We get one call for the server and one call for the client, this is
        # caused by the differences in implementations betwen
        # SmartServerBzrDirRequestConfigFile (in smart/bzrdir.py) and
        # SmartServerBranchGetConfigFile (in smart/branch.py)
        self.assertLoadHook(2, "file", remote.RemoteBzrDirConfig, remote_bzrdir)

    def assertSaveHook(self, conf):
        calls = []

        def hook(*args):
            calls.append(args)

        config.OldConfigHooks.install_named_hook("save", hook, None)
        self.addCleanup(config.OldConfigHooks.uninstall_named_hook, "save", None)
        self.assertLength(0, calls)
        # Setting an option triggers a save
        conf.set_option("foo", "bar")
        self.assertLength(1, calls)
        # Since we can't assert about conf, we just use the number of calls ;-/

    def test_save_hook_remote_branch(self):
        remote_branch = branch.Branch.open(self.get_url("tree"))
        self.addCleanup(remote_branch.lock_write().unlock)
        self.assertSaveHook(remote_branch._get_config())

    def test_save_hook_remote_bzrdir(self):
        remote_branch = branch.Branch.open(self.get_url("tree"))
        self.addCleanup(remote_branch.lock_write().unlock)
        remote_bzrdir = controldir.ControlDir.open(self.get_url("tree"))
        self.assertSaveHook(remote_bzrdir._get_config())


class TestOptionNames(tests.TestCase):
    def is_valid(self, name):
        return config._option_ref_re.match("{{{}}}".format(name)) is not None

    def test_valid_names(self):
        self.assertTrue(self.is_valid("foo"))
        self.assertTrue(self.is_valid("foo.bar"))
        self.assertTrue(self.is_valid("f1"))
        self.assertTrue(self.is_valid("_"))
        self.assertTrue(self.is_valid("__bar__"))
        self.assertTrue(self.is_valid("a_"))
        self.assertTrue(self.is_valid("a1"))
        # Don't break bzr-svn for no good reason
        self.assertTrue(self.is_valid("guessed-layout"))

    def test_invalid_names(self):
        self.assertFalse(self.is_valid(" foo"))
        self.assertFalse(self.is_valid("foo "))
        self.assertFalse(self.is_valid("1"))
        self.assertFalse(self.is_valid("1,2"))
        self.assertFalse(self.is_valid("foo$"))
        self.assertFalse(self.is_valid("!foo"))
        self.assertFalse(self.is_valid("foo."))
        self.assertFalse(self.is_valid("foo..bar"))
        self.assertFalse(self.is_valid("{}"))
        self.assertFalse(self.is_valid("{a}"))
        self.assertFalse(self.is_valid("a\n"))
        self.assertFalse(self.is_valid("-"))
        self.assertFalse(self.is_valid("-a"))
        self.assertFalse(self.is_valid("a-"))
        self.assertFalse(self.is_valid("a--a"))

    def assertSingleGroup(self, reference):
        # the regexp is used with split and as such should match the reference
        # *only*, if more groups needs to be defined, (?:...) should be used.
        m = config._option_ref_re.match("{a}")
        self.assertLength(1, m.groups())

    def test_valid_references(self):
        self.assertSingleGroup("{a}")
        self.assertSingleGroup("{{a}}")


class TestOption(tests.TestCase):
    def test_default_value(self):
        opt = config.Option("foo", default="bar")
        self.assertEqual("bar", opt.get_default())

    def test_callable_default_value(self):
        def bar_as_unicode():
            return "bar"

        opt = config.Option("foo", default=bar_as_unicode)
        self.assertEqual("bar", opt.get_default())

    def test_default_value_from_env(self):
        opt = config.Option("foo", default="bar", default_from_env=["FOO"])
        self.overrideEnv("FOO", "quux")
        # Env variable provides a default taking over the option one
        self.assertEqual("quux", opt.get_default())

    def test_first_default_value_from_env_wins(self):
        opt = config.Option(
            "foo", default="bar", default_from_env=["NO_VALUE", "FOO", "BAZ"]
        )
        self.overrideEnv("FOO", "foo")
        self.overrideEnv("BAZ", "baz")
        # The first env var set wins
        self.assertEqual("foo", opt.get_default())

    def test_not_supported_list_default_value(self):
        self.assertRaises(AssertionError, config.Option, "foo", default=[1])

    def test_not_supported_object_default_value(self):
        self.assertRaises(AssertionError, config.Option, "foo", default=object())

    def test_not_supported_callable_default_value_not_unicode(self):
        def bar_not_unicode():
            return b"bar"

        opt = config.Option("foo", default=bar_not_unicode)
        self.assertRaises(AssertionError, opt.get_default)

    def test_get_help_topic(self):
        opt = config.Option("foo")
        self.assertEqual("foo", opt.get_help_topic())


class TestOptionConverter(tests.TestCase):
    def assertConverted(self, expected, opt, value):
        self.assertEqual(expected, opt.convert_from_unicode(None, value))

    def assertCallsWarning(self, opt, value):
        warnings = []

        def warning(*args):
            warnings.append(args[0] % args[1:])

        self.overrideAttr(trace, "warning", warning)
        self.assertEqual(None, opt.convert_from_unicode(None, value))
        self.assertLength(1, warnings)
        self.assertEqual(f'Value "{value}" is not valid for "{opt.name}"', warnings[0])

    def assertCallsError(self, opt, value):
        self.assertRaises(
            config.ConfigOptionValueError, opt.convert_from_unicode, None, value
        )

    def assertConvertInvalid(self, opt, invalid_value):
        opt.invalid = None
        self.assertEqual(None, opt.convert_from_unicode(None, invalid_value))
        opt.invalid = "warning"
        self.assertCallsWarning(opt, invalid_value)
        opt.invalid = "error"
        self.assertCallsError(opt, invalid_value)


class TestOptionWithBooleanConverter(TestOptionConverter):
    def get_option(self):
        return config.Option(
            "foo", help="A boolean.", from_unicode=config.bool_from_store
        )

    def test_convert_invalid(self):
        opt = self.get_option()
        # A string that is not recognized as a boolean
        self.assertConvertInvalid(opt, "invalid-boolean")
        # A list of strings is never recognized as a boolean
        self.assertConvertInvalid(opt, ["not", "a", "boolean"])

    def test_convert_valid(self):
        opt = self.get_option()
        self.assertConverted(True, opt, "True")
        self.assertConverted(True, opt, "1")
        self.assertConverted(False, opt, "False")


class TestOptionWithIntegerConverter(TestOptionConverter):
    def get_option(self):
        return config.Option(
            "foo", help="An integer.", from_unicode=config.int_from_store
        )

    def test_convert_invalid(self):
        opt = self.get_option()
        # A string that is not recognized as an integer
        self.assertConvertInvalid(opt, "forty-two")
        # A list of strings is never recognized as an integer
        self.assertConvertInvalid(opt, ["a", "list"])

    def test_convert_valid(self):
        opt = self.get_option()
        self.assertConverted(16, opt, "16")


class TestOptionWithSIUnitConverter(TestOptionConverter):
    def get_option(self):
        return config.Option(
            "foo", help="An integer in SI units.", from_unicode=config.int_SI_from_store
        )

    def test_convert_invalid(self):
        opt = self.get_option()
        self.assertConvertInvalid(opt, "not-a-unit")
        self.assertConvertInvalid(opt, "Gb")  # Forgot the value
        self.assertConvertInvalid(opt, "1b")  # Forgot the unit
        self.assertConvertInvalid(opt, "1GG")
        self.assertConvertInvalid(opt, "1Mbb")
        self.assertConvertInvalid(opt, "1MM")

    def test_convert_valid(self):
        opt = self.get_option()
        self.assertConverted(int(5e3), opt, "5kb")
        self.assertConverted(int(5e6), opt, "5M")
        self.assertConverted(int(5e6), opt, "5MB")
        self.assertConverted(int(5e9), opt, "5g")
        self.assertConverted(int(5e9), opt, "5gB")
        self.assertConverted(100, opt, "100")


class TestListOption(TestOptionConverter):
    def get_option(self):
        return config.ListOption("foo", help="A list.")

    def test_convert_invalid(self):
        opt = self.get_option()
        # We don't even try to convert a list into a list, we only expect
        # strings
        self.assertConvertInvalid(opt, [1])
        # No string is invalid as all forms can be converted to a list

    def test_convert_valid(self):
        opt = self.get_option()
        # An empty string is an empty list
        self.assertConverted([], opt, "")  # Using a bare str() just in case
        self.assertConverted([], opt, "")
        # A boolean
        self.assertConverted(["True"], opt, "True")
        # An integer
        self.assertConverted(["42"], opt, "42")
        # A single string
        self.assertConverted(["bar"], opt, "bar")


class TestRegistryOption(TestOptionConverter):
    def get_option(self, registry):
        return config.RegistryOption("foo", registry, help="A registry option.")

    def test_convert_invalid(self):
        registry = _mod_registry.Registry()
        opt = self.get_option(registry)
        self.assertConvertInvalid(opt, [1])
        self.assertConvertInvalid(opt, "notregistered")

    def test_convert_valid(self):
        registry = _mod_registry.Registry()
        registry.register("someval", 1234)
        opt = self.get_option(registry)
        # Using a bare str() just in case
        self.assertConverted(1234, opt, "someval")
        self.assertConverted(1234, opt, "someval")
        self.assertConverted(None, opt, None)

    def test_help(self):
        registry = _mod_registry.Registry()
        registry.register("someval", 1234, help="some option")
        registry.register("dunno", 1234, help="some other option")
        opt = self.get_option(registry)
        self.assertEqual(
            "A registry option.\n"
            "\n"
            "The following values are supported:\n"
            " dunno - some other option\n"
            " someval - some option\n",
            opt.help,
        )

    def test_get_help_text(self):
        registry = _mod_registry.Registry()
        registry.register("someval", 1234, help="some option")
        registry.register("dunno", 1234, help="some other option")
        opt = self.get_option(registry)
        self.assertEqual(
            "A registry option.\n"
            "\n"
            "The following values are supported:\n"
            " dunno - some other option\n"
            " someval - some option\n",
            opt.get_help_text(),
        )


class TestOptionRegistry(tests.TestCase):
    def setUp(self):
        super().setUp()
        # Always start with an empty registry
        self.overrideAttr(config, "option_registry", config.OptionRegistry())
        self.registry = config.option_registry

    def test_register(self):
        opt = config.Option("foo")
        self.registry.register(opt)
        self.assertIs(opt, self.registry.get("foo"))

    def test_registered_help(self):
        opt = config.Option("foo", help="A simple option")
        self.registry.register(opt)
        self.assertEqual("A simple option", self.registry.get_help("foo"))

    def test_dont_register_illegal_name(self):
        self.assertRaises(
            config.IllegalOptionName, self.registry.register, config.Option(" foo")
        )
        self.assertRaises(
            config.IllegalOptionName, self.registry.register, config.Option("bar,")
        )

    lazy_option = config.Option("lazy_foo", help="Lazy help")

    def test_register_lazy(self):
        self.registry.register_lazy(
            "lazy_foo", self.__module__, "TestOptionRegistry.lazy_option"
        )
        self.assertIs(self.lazy_option, self.registry.get("lazy_foo"))

    def test_registered_lazy_help(self):
        self.registry.register_lazy(
            "lazy_foo", self.__module__, "TestOptionRegistry.lazy_option"
        )
        self.assertEqual("Lazy help", self.registry.get_help("lazy_foo"))

    def test_dont_lazy_register_illegal_name(self):
        # This is where the root cause of http://pad.lv/1235099 is better
        # understood: 'register_lazy' doc string mentions that key should match
        # the option name which indirectly requires that the option name is a
        # valid python identifier. We violate that rule here (using a key that
        # doesn't match the option name) to test the option name checking.
        self.assertRaises(
            config.IllegalOptionName,
            self.registry.register_lazy,
            " foo",
            self.__module__,
            "TestOptionRegistry.lazy_option",
        )
        self.assertRaises(
            config.IllegalOptionName,
            self.registry.register_lazy,
            "1,2",
            self.__module__,
            "TestOptionRegistry.lazy_option",
        )


class TestRegisteredOptions(tests.TestCase):
    """All registered options should verify some constraints."""

    scenarios = [
        (key, {"option_name": key, "option": option})
        for key, option in config.option_registry.iteritems()
    ]

    def setUp(self):
        super().setUp()
        self.registry = config.option_registry

    def test_proper_name(self):
        # An option should be registered under its own name, this can't be
        # checked at registration time for the lazy ones.
        self.assertEqual(self.option_name, self.option.name)

    def test_help_is_set(self):
        option_help = self.registry.get_help(self.option_name)
        # Come on, think about the user, he really wants to know what the
        # option is about
        self.assertIsNot(None, option_help)
        self.assertNotEqual("", option_help)


class TestSection(tests.TestCase):
    # FIXME: Parametrize so that all sections produced by Stores run these
    # tests -- vila 2011-04-01

    def test_get_a_value(self):
        a_dict = {"foo": "bar"}
        section = config.Section("myID", a_dict)
        self.assertEqual("bar", section.get("foo"))

    def test_get_unknown_option(self):
        a_dict = {}
        section = config.Section(None, a_dict)
        self.assertEqual("out of thin air", section.get("foo", "out of thin air"))

    def test_options_is_shared(self):
        a_dict = {}
        section = config.Section(None, a_dict)
        self.assertIs(a_dict, section.options)


class TestMutableSection(tests.TestCase):
    scenarios = [
        (
            "mutable",
            {"get_section": lambda opts: config.MutableSection("myID", opts)},
        ),
    ]

    def test_set(self):
        a_dict = {"foo": "bar"}
        section = self.get_section(a_dict)
        section.set("foo", "new_value")
        self.assertEqual("new_value", section.get("foo"))
        # The change appears in the shared section
        self.assertEqual("new_value", a_dict.get("foo"))
        # We keep track of the change
        self.assertIn("foo", section.orig)
        self.assertEqual("bar", section.orig.get("foo"))

    def test_set_preserve_original_once(self):
        a_dict = {"foo": "bar"}
        section = self.get_section(a_dict)
        section.set("foo", "first_value")
        section.set("foo", "second_value")
        # We keep track of the original value
        self.assertIn("foo", section.orig)
        self.assertEqual("bar", section.orig.get("foo"))

    def test_remove(self):
        a_dict = {"foo": "bar"}
        section = self.get_section(a_dict)
        section.remove("foo")
        # We get None for unknown options via the default value
        self.assertEqual(None, section.get("foo"))
        # Or we just get the default value
        self.assertEqual("unknown", section.get("foo", "unknown"))
        self.assertNotIn("foo", section.options)
        # We keep track of the deletion
        self.assertIn("foo", section.orig)
        self.assertEqual("bar", section.orig.get("foo"))

    def test_remove_new_option(self):
        a_dict = {}
        section = self.get_section(a_dict)
        section.set("foo", "bar")
        section.remove("foo")
        self.assertNotIn("foo", section.options)
        # The option didn't exist initially so it we need to keep track of it
        # with a special value
        self.assertIn("foo", section.orig)
        self.assertEqual(config._NewlyCreatedOption, section.orig["foo"])


class TestCommandLineStore(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.store = config.CommandLineStore()
        self.overrideAttr(config, "option_registry", config.OptionRegistry())

    def get_section(self):
        """Get the unique section for the command line overrides."""
        sections = list(self.store.get_sections())
        self.assertLength(1, sections)
        store, section = sections[0]
        self.assertEqual(self.store, store)
        return section

    def test_no_override(self):
        self.store._from_cmdline([])
        section = self.get_section()
        self.assertLength(0, list(section.iter_option_names()))

    def test_simple_override(self):
        self.store._from_cmdline(["a=b"])
        section = self.get_section()
        self.assertEqual("b", section.get("a"))

    def test_list_override(self):
        opt = config.ListOption("l")
        config.option_registry.register(opt)
        self.store._from_cmdline(["l=1,2,3"])
        val = self.get_section().get("l")
        self.assertEqual("1,2,3", val)
        # Reminder: lists should be registered as such explicitely, otherwise
        # the conversion needs to be done afterwards.
        self.assertEqual(["1", "2", "3"], opt.convert_from_unicode(self.store, val))

    def test_multiple_overrides(self):
        self.store._from_cmdline(["a=b", "x=y"])
        section = self.get_section()
        self.assertEqual("b", section.get("a"))
        self.assertEqual("y", section.get("x"))

    def test_wrong_syntax(self):
        self.assertRaises(errors.CommandError, self.store._from_cmdline, ["a=b", "c"])


class TestStoreMinimalAPI(tests.TestCaseWithTransport):
    scenarios = [
        (key, {"get_store": builder})
        for key, builder in config.test_store_builder_registry.iteritems()
    ] + [("cmdline", {"get_store": lambda test: config.CommandLineStore()})]

    def test_id(self):
        store = self.get_store(self)
        if isinstance(store, config.TransportIniFileStore):
            raise tests.TestNotApplicable(
                f"{store.__class__.__name__} is not a concrete Store implementation"
                " so it doesn't need an id"
            )
        self.assertIsNot(None, store.id)


class TestStore(tests.TestCaseWithTransport):
    def assertSectionContent(self, expected, store_and_section):
        """Assert that some options have the proper values in a section."""
        _, section = store_and_section
        expected_name, expected_options = expected
        self.assertEqual(expected_name, section.id)
        self.assertEqual(
            expected_options, {k: section.get(k) for k in expected_options.keys()}
        )


class TestReadonlyStore(TestStore):
    scenarios = [
        (key, {"get_store": builder})
        for key, builder in config.test_store_builder_registry.iteritems()
    ]

    def test_building_delays_load(self):
        store = self.get_store(self)
        self.assertEqual(False, store.is_loaded())
        store._load_from_string(b"")
        self.assertEqual(True, store.is_loaded())

    def test_get_no_sections_for_empty(self):
        store = self.get_store(self)
        store._load_from_string(b"")
        self.assertEqual([], list(store.get_sections()))

    def test_get_default_section(self):
        store = self.get_store(self)
        store._load_from_string(b"foo=bar")
        sections = list(store.get_sections())
        self.assertLength(1, sections)
        self.assertSectionContent((None, {"foo": "bar"}), sections[0])

    def test_get_named_section(self):
        store = self.get_store(self)
        store._load_from_string(b"[baz]\nfoo=bar")
        sections = list(store.get_sections())
        self.assertLength(1, sections)
        self.assertSectionContent(("baz", {"foo": "bar"}), sections[0])

    def test_load_from_string_fails_for_non_empty_store(self):
        store = self.get_store(self)
        store._load_from_string(b"foo=bar")
        self.assertRaises(AssertionError, store._load_from_string, b"bar=baz")


class TestStoreQuoting(TestStore):
    scenarios = [
        (key, {"get_store": builder})
        for key, builder in config.test_store_builder_registry.iteritems()
    ]

    def setUp(self):
        super().setUp()
        self.store = self.get_store(self)
        # We need a loaded store but any content will do
        self.store._load_from_string(b"")

    def assertIdempotent(self, s):
        """Assert that quoting an unquoted string is a no-op and vice-versa.

        What matters here is that option values, as they appear in a store, can
        be safely round-tripped out of the store and back.

        :param s: A string, quoted if required.
        """
        self.assertEqual(s, self.store.quote(self.store.unquote(s)))
        self.assertEqual(s, self.store.unquote(self.store.quote(s)))

    def test_empty_string(self):
        if isinstance(self.store, config.IniFileStore):
            # configobj._quote doesn't handle empty values
            self.assertRaises(AssertionError, self.assertIdempotent, "")
        else:
            self.assertIdempotent("")
        # But quoted empty strings are ok
        self.assertIdempotent('""')

    def test_embedded_spaces(self):
        self.assertIdempotent('" a b c "')

    def test_embedded_commas(self):
        self.assertIdempotent('" a , b c "')

    def test_simple_comma(self):
        if isinstance(self.store, config.IniFileStore):
            # configobj requires that lists are special-cased
            self.assertRaises(AssertionError, self.assertIdempotent, ",")
        else:
            self.assertIdempotent(",")
        # When a single comma is required, quoting is also required
        self.assertIdempotent('","')

    def test_list(self):
        if isinstance(self.store, config.IniFileStore):
            # configobj requires that lists are special-cased
            self.assertRaises(AssertionError, self.assertIdempotent, "a,b")
        else:
            self.assertIdempotent("a,b")


class TestDictFromStore(tests.TestCase):
    def test_unquote_not_string(self):
        conf = config.MemoryStack(b"x=2\n[a_section]\na=1\n")
        value = conf.get("a_section")
        # Urgh, despite 'conf' asking for the no-name section, we get the
        # content of another section as a dict o_O
        self.assertEqual({"a": "1"}, value)
        unquoted = conf.store.unquote(value)
        # Which cannot be unquoted but shouldn't crash either (the use cases
        # are getting the value or displaying it. In the later case, '%s' will
        # do).
        self.assertEqual({"a": "1"}, unquoted)
        self.assertIn(f"{unquoted}", ("{u'a': u'1'}", "{'a': '1'}"))


class TestIniFileStoreContent(tests.TestCaseWithTransport):
    """Simulate loading a config store with content of various encodings.

    All files produced by bzr are in utf8 content.

    Users may modify them manually and end up with a file that can't be
    loaded. We need to issue proper error messages in this case.
    """

    invalid_utf8_char = b"\xff"

    def test_load_utf8(self):
        """Ensure we can load an utf8-encoded file."""
        t = self.get_transport()
        # From http://pad.lv/799212
        unicode_user = "b\N{EURO SIGN}ar"
        unicode_content = f"user={unicode_user}"
        utf8_content = unicode_content.encode("utf8")
        # Store the raw content in the config file
        t.put_bytes("foo.conf", utf8_content)
        store = config.TransportIniFileStore(t, "foo.conf")
        store.load()
        stack = config.Stack([store.get_sections], store)
        self.assertEqual(unicode_user, stack.get("user"))

    def test_load_non_ascii(self):
        """Ensure we display a proper error on non-ascii, non utf-8 content."""
        t = self.get_transport()
        t.put_bytes("foo.conf", b"user=foo\n#%s\n" % (self.invalid_utf8_char,))
        store = config.TransportIniFileStore(t, "foo.conf")
        self.assertRaises(config.ConfigContentError, store.load)

    def test_load_erroneous_content(self):
        """Ensure we display a proper error on content that can't be parsed."""
        t = self.get_transport()
        t.put_bytes("foo.conf", b"[open_section\n")
        store = config.TransportIniFileStore(t, "foo.conf")
        self.assertRaises(config.ParseConfigError, store.load)

    def test_load_permission_denied(self):
        """Ensure we get warned when trying to load an inaccessible file."""
        warnings = []

        def warning(*args):
            warnings.append(args[0] % args[1:])

        self.overrideAttr(trace, "warning", warning)

        t = self.get_transport()

        def get_bytes(relpath):
            raise errors.PermissionDenied(relpath, "")

        try:
            t.get_bytes = get_bytes
        except AttributeError as e:
            raise tests.TestSkipped("unable to override Transport.get_bytes") from e
        store = config.TransportIniFileStore(t, "foo.conf")
        self.assertRaises(errors.PermissionDenied, store.load)
        self.assertEqual(
            warnings,
            [
                "Permission denied while trying to load configuration store {}.".format(
                    store.external_url()
                )
            ],
        )


class TestIniConfigContent(tests.TestCaseWithTransport):
    """Simulate loading a IniBasedConfig with content of various encodings.

    All files produced by bzr are in utf8 content.

    Users may modify them manually and end up with a file that can't be
    loaded. We need to issue proper error messages in this case.
    """

    invalid_utf8_char = b"\xff"

    def test_load_utf8(self):
        """Ensure we can load an utf8-encoded file."""
        # From http://pad.lv/799212
        unicode_user = "b\N{EURO SIGN}ar"
        unicode_content = f"user={unicode_user}"
        utf8_content = unicode_content.encode("utf8")
        # Store the raw content in the config file
        with open("foo.conf", "wb") as f:
            f.write(utf8_content)
        conf = config.IniBasedConfig(file_name="foo.conf")
        self.assertEqual(unicode_user, conf.get_user_option("user"))

    def test_load_badly_encoded_content(self):
        """Ensure we display a proper error on non-ascii, non utf-8 content."""
        with open("foo.conf", "wb") as f:
            f.write(b"user=foo\n#%s\n" % (self.invalid_utf8_char,))
        conf = config.IniBasedConfig(file_name="foo.conf")
        self.assertRaises(config.ConfigContentError, conf._get_parser)

    def test_load_erroneous_content(self):
        """Ensure we display a proper error on content that can't be parsed."""
        with open("foo.conf", "wb") as f:
            f.write(b"[open_section\n")
        conf = config.IniBasedConfig(file_name="foo.conf")
        self.assertRaises(config.ParseConfigError, conf._get_parser)


class TestMutableStore(TestStore):
    scenarios = [
        (key, {"store_id": key, "get_store": builder})
        for key, builder in config.test_store_builder_registry.iteritems()
    ]

    def setUp(self):
        super().setUp()
        self.transport = self.get_transport()

    def has_store(self, store):
        store_basename = urlutils.relative_url(
            self.transport.external_url(), store.external_url()
        )
        return self.transport.has(store_basename)

    def test_save_empty_creates_no_file(self):
        # FIXME: There should be a better way than relying on the test
        # parametrization to identify branch.conf -- vila 2011-0526
        if self.store_id in ("branch", "remote_branch"):
            raise tests.TestNotApplicable(
                "branch.conf is *always* created when a branch is initialized"
            )
        store = self.get_store(self)
        store.save()
        self.assertEqual(False, self.has_store(store))

    def test_mutable_section_shared(self):
        store = self.get_store(self)
        store._load_from_string(b"foo=bar\n")
        # FIXME: There should be a better way than relying on the test
        # parametrization to identify branch.conf -- vila 2011-0526
        if self.store_id in ("branch", "remote_branch"):
            # branch stores requires write locked branches
            self.addCleanup(store.branch.lock_write().unlock)
        section1 = store.get_mutable_section(None)
        section2 = store.get_mutable_section(None)
        # If we get different sections, different callers won't share the
        # modification
        self.assertIs(section1, section2)

    def test_save_emptied_succeeds(self):
        store = self.get_store(self)
        store._load_from_string(b"foo=bar\n")
        # FIXME: There should be a better way than relying on the test
        # parametrization to identify branch.conf -- vila 2011-0526
        if self.store_id in ("branch", "remote_branch"):
            # branch stores requires write locked branches
            self.addCleanup(store.branch.lock_write().unlock)
        section = store.get_mutable_section(None)
        section.remove("foo")
        store.save()
        self.assertEqual(True, self.has_store(store))
        modified_store = self.get_store(self)
        sections = list(modified_store.get_sections())
        self.assertLength(0, sections)

    def test_save_with_content_succeeds(self):
        # FIXME: There should be a better way than relying on the test
        # parametrization to identify branch.conf -- vila 2011-0526
        if self.store_id in ("branch", "remote_branch"):
            raise tests.TestNotApplicable(
                "branch.conf is *always* created when a branch is initialized"
            )
        store = self.get_store(self)
        store._load_from_string(b"foo=bar\n")
        self.assertEqual(False, self.has_store(store))
        store.save()
        self.assertEqual(True, self.has_store(store))
        modified_store = self.get_store(self)
        sections = list(modified_store.get_sections())
        self.assertLength(1, sections)
        self.assertSectionContent((None, {"foo": "bar"}), sections[0])

    def test_set_option_in_empty_store(self):
        store = self.get_store(self)
        # FIXME: There should be a better way than relying on the test
        # parametrization to identify branch.conf -- vila 2011-0526
        if self.store_id in ("branch", "remote_branch"):
            # branch stores requires write locked branches
            self.addCleanup(store.branch.lock_write().unlock)
        section = store.get_mutable_section(None)
        section.set("foo", "bar")
        store.save()
        modified_store = self.get_store(self)
        sections = list(modified_store.get_sections())
        self.assertLength(1, sections)
        self.assertSectionContent((None, {"foo": "bar"}), sections[0])

    def test_set_option_in_default_section(self):
        store = self.get_store(self)
        store._load_from_string(b"")
        # FIXME: There should be a better way than relying on the test
        # parametrization to identify branch.conf -- vila 2011-0526
        if self.store_id in ("branch", "remote_branch"):
            # branch stores requires write locked branches
            self.addCleanup(store.branch.lock_write().unlock)
        section = store.get_mutable_section(None)
        section.set("foo", "bar")
        store.save()
        modified_store = self.get_store(self)
        sections = list(modified_store.get_sections())
        self.assertLength(1, sections)
        self.assertSectionContent((None, {"foo": "bar"}), sections[0])

    def test_set_option_in_named_section(self):
        store = self.get_store(self)
        store._load_from_string(b"")
        # FIXME: There should be a better way than relying on the test
        # parametrization to identify branch.conf -- vila 2011-0526
        if self.store_id in ("branch", "remote_branch"):
            # branch stores requires write locked branches
            self.addCleanup(store.branch.lock_write().unlock)
        section = store.get_mutable_section("baz")
        section.set("foo", "bar")
        store.save()
        modified_store = self.get_store(self)
        sections = list(modified_store.get_sections())
        self.assertLength(1, sections)
        self.assertSectionContent(("baz", {"foo": "bar"}), sections[0])

    def test_load_hook(self):
        # First, we need to ensure that the store exists
        store = self.get_store(self)
        # FIXME: There should be a better way than relying on the test
        # parametrization to identify branch.conf -- vila 2011-0526
        if self.store_id in ("branch", "remote_branch"):
            # branch stores requires write locked branches
            self.addCleanup(store.branch.lock_write().unlock)
        section = store.get_mutable_section("baz")
        section.set("foo", "bar")
        store.save()
        # Now we can try to load it
        store = self.get_store(self)
        calls = []

        def hook(*args):
            calls.append(args)

        config.ConfigHooks.install_named_hook("load", hook, None)
        self.assertLength(0, calls)
        store.load()
        self.assertLength(1, calls)
        self.assertEqual((store,), calls[0])

    def test_save_hook(self):
        calls = []

        def hook(*args):
            calls.append(args)

        config.ConfigHooks.install_named_hook("save", hook, None)
        self.assertLength(0, calls)
        store = self.get_store(self)
        # FIXME: There should be a better way than relying on the test
        # parametrization to identify branch.conf -- vila 2011-0526
        if self.store_id in ("branch", "remote_branch"):
            # branch stores requires write locked branches
            self.addCleanup(store.branch.lock_write().unlock)
        section = store.get_mutable_section("baz")
        section.set("foo", "bar")
        store.save()
        self.assertLength(1, calls)
        self.assertEqual((store,), calls[0])

    def test_set_mark_dirty(self):
        stack = config.MemoryStack(b"")
        self.assertLength(0, stack.store.dirty_sections)
        stack.set("foo", "baz")
        self.assertLength(1, stack.store.dirty_sections)
        self.assertTrue(stack.store._need_saving())

    def test_remove_mark_dirty(self):
        stack = config.MemoryStack(b"foo=bar")
        self.assertLength(0, stack.store.dirty_sections)
        stack.remove("foo")
        self.assertLength(1, stack.store.dirty_sections)
        self.assertTrue(stack.store._need_saving())


class TestStoreSaveChanges(tests.TestCaseWithTransport):
    """Tests that config changes are kept in memory and saved on-demand."""

    def setUp(self):
        super().setUp()
        self.transport = self.get_transport()
        # Most of the tests involve two stores pointing to the same persistent
        # storage to observe the effects of concurrent changes
        self.st1 = config.TransportIniFileStore(self.transport, "foo.conf")
        self.st2 = config.TransportIniFileStore(self.transport, "foo.conf")
        self.warnings = []

        def warning(*args):
            self.warnings.append(args[0] % args[1:])

        self.overrideAttr(trace, "warning", warning)

    def has_store(self, store):
        store_basename = urlutils.relative_url(
            self.transport.external_url(), store.external_url()
        )
        return self.transport.has(store_basename)

    def get_stack(self, store):
        # Any stack will do as long as it uses the right store, just a single
        # no-name section is enough
        return config.Stack([store.get_sections], store)

    def test_no_changes_no_save(self):
        s = self.get_stack(self.st1)
        s.store.save_changes()
        self.assertEqual(False, self.has_store(self.st1))

    def test_unrelated_concurrent_update(self):
        s1 = self.get_stack(self.st1)
        s2 = self.get_stack(self.st2)
        s1.set("foo", "bar")
        s2.set("baz", "quux")
        s1.store.save()
        # Changes don't propagate magically
        self.assertEqual(None, s1.get("baz"))
        s2.store.save_changes()
        self.assertEqual("quux", s2.get("baz"))
        # Changes are acquired when saving
        self.assertEqual("bar", s2.get("foo"))
        # Since there is no overlap, no warnings are emitted
        self.assertLength(0, self.warnings)

    def test_concurrent_update_modified(self):
        s1 = self.get_stack(self.st1)
        s2 = self.get_stack(self.st2)
        s1.set("foo", "bar")
        s2.set("foo", "baz")
        s1.store.save()
        # Last speaker wins
        s2.store.save_changes()
        self.assertEqual("baz", s2.get("foo"))
        # But the user get a warning
        self.assertLength(1, self.warnings)
        warning = self.warnings[0]
        self.assertStartsWith(warning, "Option foo in section None")
        self.assertEndsWith(
            warning,
            "was changed from <CREATED> to bar. The baz value will be saved.",
        )

    def test_concurrent_deletion(self):
        self.st1._load_from_string(b"foo=bar")
        self.st1.save()
        s1 = self.get_stack(self.st1)
        s2 = self.get_stack(self.st2)
        s1.remove("foo")
        s2.remove("foo")
        s1.store.save_changes()
        # No warning yet
        self.assertLength(0, self.warnings)
        s2.store.save_changes()
        # Now we get one
        self.assertLength(1, self.warnings)
        warning = self.warnings[0]
        self.assertStartsWith(warning, "Option foo in section None")
        self.assertEndsWith(
            warning,
            "was changed from bar to <CREATED>. The <DELETED> value will be saved.",
        )


class TestQuotingIniFileStore(tests.TestCaseWithTransport):
    def get_store(self):
        return config.TransportIniFileStore(self.get_transport(), "foo.conf")

    def test_get_quoted_string(self):
        store = self.get_store()
        store._load_from_string(b'foo= " abc "')
        stack = config.Stack([store.get_sections])
        self.assertEqual(" abc ", stack.get("foo"))

    def test_set_quoted_string(self):
        store = self.get_store()
        stack = config.Stack([store.get_sections], store)
        stack.set("foo", " a b c ")
        store.save()
        self.assertFileEqual(
            b'foo = " a b c "' + os.linesep.encode("ascii"), "foo.conf"
        )


class TestTransportIniFileStore(TestStore):
    def test_loading_unknown_file_fails(self):
        store = config.TransportIniFileStore(self.get_transport(), "I-do-not-exist")
        self.assertRaises(_mod_transport.NoSuchFile, store.load)

    def test_invalid_content(self):
        store = config.TransportIniFileStore(self.get_transport(), "foo.conf")
        self.assertEqual(False, store.is_loaded())
        exc = self.assertRaises(
            config.ParseConfigError, store._load_from_string, b"this is invalid !"
        )
        self.assertEndsWith(exc.filename, "foo.conf")
        # And the load failed
        self.assertEqual(False, store.is_loaded())

    def test_get_embedded_sections(self):
        # A more complicated example (which also shows that section names and
        # option names share the same name space...)
        # FIXME: This should be fixed by forbidding dicts as values ?
        # -- vila 2011-04-05
        store = config.TransportIniFileStore(self.get_transport(), "foo.conf")
        store._load_from_string(
            b"""
foo=bar
l=1,2
[DEFAULT]
foo_in_DEFAULT=foo_DEFAULT
[bar]
foo_in_bar=barbar
[baz]
foo_in_baz=barbaz
[[qux]]
foo_in_qux=quux
"""
        )
        sections = list(store.get_sections())
        self.assertLength(4, sections)
        # The default section has no name.
        # List values are provided as strings and need to be explicitly
        # converted by specifying from_unicode=list_from_store at option
        # registration
        self.assertSectionContent((None, {"foo": "bar", "l": "1,2"}), sections[0])
        self.assertSectionContent(
            ("DEFAULT", {"foo_in_DEFAULT": "foo_DEFAULT"}), sections[1]
        )
        self.assertSectionContent(("bar", {"foo_in_bar": "barbar"}), sections[2])
        # sub sections are provided as embedded dicts.
        self.assertSectionContent(
            ("baz", {"foo_in_baz": "barbaz", "qux": {"foo_in_qux": "quux"}}),
            sections[3],
        )


class TestLockableIniFileStore(TestStore):
    def test_create_store_in_created_dir(self):
        self.assertPathDoesNotExist("dir")
        t = self.get_transport("dir/subdir")
        store = config.LockableIniFileStore(t, "foo.conf")
        store.get_mutable_section(None).set("foo", "bar")
        store.save()
        self.assertPathExists("dir/subdir")


class TestConcurrentStoreUpdates(TestStore):
    """Test that Stores properly handle conccurent updates.

    New Store implementation may fail some of these tests but until such
    implementations exist it's hard to properly filter them from the scenarios
    applied here. If you encounter such a case, contact the bzr devs.
    """

    scenarios = [
        (key, {"get_stack": builder})
        for key, builder in config.test_stack_builder_registry.iteritems()
    ]

    def setUp(self):
        super().setUp()
        self.stack = self.get_stack(self)
        if not isinstance(self.stack, config._CompatibleStack):
            raise tests.TestNotApplicable(
                f"{self.stack} is not meant to be compatible with the old config design"
            )
        self.stack.set("one", "1")
        self.stack.set("two", "2")
        # Flush the store
        self.stack.store.save()

    def test_simple_read_access(self):
        self.assertEqual("1", self.stack.get("one"))

    def test_simple_write_access(self):
        self.stack.set("one", "one")
        self.assertEqual("one", self.stack.get("one"))

    def test_listen_to_the_last_speaker(self):
        c1 = self.stack
        c2 = self.get_stack(self)
        c1.set("one", "ONE")
        c2.set("two", "TWO")
        self.assertEqual("ONE", c1.get("one"))
        self.assertEqual("TWO", c2.get("two"))
        # The second update respect the first one
        self.assertEqual("ONE", c2.get("one"))

    def test_last_speaker_wins(self):
        # If the same config is not shared, the same variable modified twice
        # can only see a single result.
        c1 = self.stack
        c2 = self.get_stack(self)
        c1.set("one", "c1")
        c2.set("one", "c2")
        self.assertEqual("c2", c2.get("one"))
        # The first modification is still available until another refresh
        # occur
        self.assertEqual("c1", c1.get("one"))
        c1.set("two", "done")
        self.assertEqual("c2", c1.get("one"))

    def test_writes_are_serialized(self):
        c1 = self.stack
        c2 = self.get_stack(self)

        # We spawn a thread that will pause *during* the config saving.
        before_writing = threading.Event()
        after_writing = threading.Event()
        writing_done = threading.Event()
        c1_save_without_locking_orig = c1.store.save_without_locking

        def c1_save_without_locking():
            before_writing.set()
            c1_save_without_locking_orig()
            # The lock is held. We wait for the main thread to decide when to
            # continue
            after_writing.wait()

        c1.store.save_without_locking = c1_save_without_locking

        def c1_set():
            c1.set("one", "c1")
            writing_done.set()

        t1 = threading.Thread(target=c1_set)
        # Collect the thread after the test
        self.addCleanup(t1.join)
        # Be ready to unblock the thread if the test goes wrong
        self.addCleanup(after_writing.set)
        t1.start()
        before_writing.wait()
        self.assertRaises(errors.LockContention, c2.set, "one", "c2")
        self.assertEqual("c1", c1.get("one"))
        # Let the lock be released
        after_writing.set()
        writing_done.wait()
        c2.set("one", "c2")
        self.assertEqual("c2", c2.get("one"))

    def test_read_while_writing(self):
        c1 = self.stack
        # We spawn a thread that will pause *during* the write
        ready_to_write = threading.Event()
        do_writing = threading.Event()
        writing_done = threading.Event()
        # We override the _save implementation so we know the store is locked
        c1_save_without_locking_orig = c1.store.save_without_locking

        def c1_save_without_locking():
            ready_to_write.set()
            # The lock is held. We wait for the main thread to decide when to
            # continue
            do_writing.wait()
            c1_save_without_locking_orig()
            writing_done.set()

        c1.store.save_without_locking = c1_save_without_locking

        def c1_set():
            c1.set("one", "c1")

        t1 = threading.Thread(target=c1_set)
        # Collect the thread after the test
        self.addCleanup(t1.join)
        # Be ready to unblock the thread if the test goes wrong
        self.addCleanup(do_writing.set)
        t1.start()
        # Ensure the thread is ready to write
        ready_to_write.wait()
        self.assertEqual("c1", c1.get("one"))
        # If we read during the write, we get the old value
        c2 = self.get_stack(self)
        self.assertEqual("1", c2.get("one"))
        # Let the writing occur and ensure it occurred
        do_writing.set()
        writing_done.wait()
        # Now we get the updated value
        c3 = self.get_stack(self)
        self.assertEqual("c1", c3.get("one"))

    # FIXME: It may be worth looking into removing the lock dir when it's not
    # needed anymore and look at possible fallouts for concurrent lockers. This
    # will matter if/when we use config files outside of breezy directories
    # (.config/breezy or .bzr) -- vila 20110-04-111


class TestSectionMatcher(TestStore):
    scenarios = [
        ("location", {"matcher": config.LocationMatcher}),
        ("id", {"matcher": config.NameMatcher}),
    ]

    def setUp(self):
        super().setUp()
        # Any simple store is good enough
        self.get_store = config.test_store_builder_registry.get("configobj")

    def test_no_matches_for_empty_stores(self):
        store = self.get_store(self)
        store._load_from_string(b"")
        matcher = self.matcher(store, "/bar")
        self.assertEqual([], list(matcher.get_sections()))

    def test_build_doesnt_load_store(self):
        store = self.get_store(self)
        self.matcher(store, "/bar")
        self.assertFalse(store.is_loaded())


class TestLocationSection(tests.TestCase):
    def get_section(self, options, extra_path):
        section = config.Section("foo", options)
        return config.LocationSection(section, extra_path)

    def test_simple_option(self):
        section = self.get_section({"foo": "bar"}, "")
        self.assertEqual("bar", section.get("foo"))

    def test_option_with_extra_path(self):
        section = self.get_section({"foo": "bar", "foo:policy": "appendpath"}, "baz")
        self.assertEqual("bar/baz", section.get("foo"))

    def test_invalid_policy(self):
        section = self.get_section({"foo": "bar", "foo:policy": "die"}, "baz")
        # invalid policies are ignored
        self.assertEqual("bar", section.get("foo"))


class TestLocationMatcher(TestStore):
    def setUp(self):
        super().setUp()
        # Any simple store is good enough
        self.get_store = config.test_store_builder_registry.get("configobj")

    def test_unrelated_section_excluded(self):
        store = self.get_store(self)
        store._load_from_string(
            b"""
[/foo]
section=/foo
[/foo/baz]
section=/foo/baz
[/foo/bar]
section=/foo/bar
[/foo/bar/baz]
section=/foo/bar/baz
[/quux/quux]
section=/quux/quux
"""
        )
        self.assertEqual(
            ["/foo", "/foo/baz", "/foo/bar", "/foo/bar/baz", "/quux/quux"],
            [section.id for _, section in store.get_sections()],
        )
        matcher = config.LocationMatcher(store, "/foo/bar/quux")
        sections = [section for _, section in matcher.get_sections()]
        self.assertEqual(["/foo/bar", "/foo"], [section.id for section in sections])
        self.assertEqual(
            ["quux", "bar/quux"], [section.extra_path for section in sections]
        )

    def test_more_specific_sections_first(self):
        store = self.get_store(self)
        store._load_from_string(
            b"""
[/foo]
section=/foo
[/foo/bar]
section=/foo/bar
"""
        )
        self.assertEqual(
            ["/foo", "/foo/bar"], [section.id for _, section in store.get_sections()]
        )
        matcher = config.LocationMatcher(store, "/foo/bar/baz")
        sections = [section for _, section in matcher.get_sections()]
        self.assertEqual(["/foo/bar", "/foo"], [section.id for section in sections])
        self.assertEqual(
            ["baz", "bar/baz"], [section.extra_path for section in sections]
        )

    def test_appendpath_in_no_name_section(self):
        # It's a bit weird to allow appendpath in a no-name section, but
        # someone may found a use for it
        store = self.get_store(self)
        store._load_from_string(
            b"""
foo=bar
foo:policy = appendpath
"""
        )
        matcher = config.LocationMatcher(store, "dir/subdir")
        sections = list(matcher.get_sections())
        self.assertLength(1, sections)
        self.assertEqual("bar/dir/subdir", sections[0][1].get("foo"))

    def test_file_urls_are_normalized(self):
        store = self.get_store(self)
        if sys.platform == "win32":
            expected_url = "file:///C:/dir/subdir"
            expected_location = "C:/dir/subdir"
        else:
            expected_url = "file:///dir/subdir"
            expected_location = "/dir/subdir"
        matcher = config.LocationMatcher(store, expected_url)
        self.assertEqual(expected_location, matcher.location)

    def test_branch_name_colo(self):
        store = self.get_store(self)
        store._load_from_string(
            dedent(
                """\
            [/]
            push_location=my{branchname}
        """
            ).encode("ascii")
        )
        matcher = config.LocationMatcher(store, "file:///,branch=example%3c")
        self.assertEqual("example<", matcher.branch_name)
        ((_, section),) = matcher.get_sections()
        self.assertEqual("example<", section.locals["branchname"])

    def test_branch_name_basename(self):
        store = self.get_store(self)
        store._load_from_string(
            dedent(
                """\
            [/]
            push_location=my{branchname}
        """
            ).encode("ascii")
        )
        matcher = config.LocationMatcher(store, "file:///parent/example%3c")
        self.assertEqual("example<", matcher.branch_name)
        ((_, section),) = matcher.get_sections()
        self.assertEqual("example<", section.locals["branchname"])


class TestStartingPathMatcher(TestStore):
    def setUp(self):
        super().setUp()
        # Any simple store is good enough
        self.store = config.IniFileStore()

    def assertSectionIDs(self, expected, location, content):
        self.store._load_from_string(content)
        matcher = config.StartingPathMatcher(self.store, location)
        sections = list(matcher.get_sections())
        self.assertLength(len(expected), sections)
        self.assertEqual(expected, [section.id for _, section in sections])
        return sections

    def test_empty(self):
        self.assertSectionIDs([], self.get_url(), b"")

    def test_url_vs_local_paths(self):
        # The matcher location is an url and the section names are local paths
        self.assertSectionIDs(
            ["/foo/bar", "/foo"],
            "file:///foo/bar/baz",
            b"""\
[/foo]
[/foo/bar]
""",
        )

    def test_local_path_vs_url(self):
        # The matcher location is a local path and the section names are urls
        self.assertSectionIDs(
            ["file:///foo/bar", "file:///foo"],
            "/foo/bar/baz",
            b"""\
[file:///foo]
[file:///foo/bar]
""",
        )

    def test_no_name_section_included_when_present(self):
        # Note that other tests will cover the case where the no-name section
        # is empty and as such, not included.
        sections = self.assertSectionIDs(
            ["/foo/bar", "/foo", None],
            "/foo/bar/baz",
            b"""\
option = defined so the no-name section exists
[/foo]
[/foo/bar]
""",
        )
        self.assertEqual(
            ["baz", "bar/baz", "/foo/bar/baz"],
            [s.locals["relpath"] for _, s in sections],
        )

    def test_order_reversed(self):
        self.assertSectionIDs(
            ["/foo/bar", "/foo"],
            "/foo/bar/baz",
            b"""\
[/foo]
[/foo/bar]
""",
        )

    def test_unrelated_section_excluded(self):
        self.assertSectionIDs(
            ["/foo/bar", "/foo"],
            "/foo/bar/baz",
            b"""\
[/foo]
[/foo/qux]
[/foo/bar]
""",
        )

    def test_glob_included(self):
        sections = self.assertSectionIDs(
            ["/foo/*/baz", "/foo/b*", "/foo"],
            "/foo/bar/baz",
            b"""\
[/foo]
[/foo/qux]
[/foo/b*]
[/foo/*/baz]
""",
        )
        # Note that 'baz' as a relpath for /foo/b* is not fully correct, but
        # nothing really is... as far using {relpath} to append it to something
        # else, this seems good enough though.
        self.assertEqual(
            ["", "baz", "bar/baz"], [s.locals["relpath"] for _, s in sections]
        )

    def test_respect_order(self):
        self.assertSectionIDs(
            ["/foo", "/foo/b*", "/foo/*/baz"],
            "/foo/bar/baz",
            b"""\
[/foo/*/baz]
[/foo/qux]
[/foo/b*]
[/foo]
""",
        )


class TestNameMatcher(TestStore):
    def setUp(self):
        super().setUp()
        self.matcher = config.NameMatcher
        # Any simple store is good enough
        self.get_store = config.test_store_builder_registry.get("configobj")

    def get_matching_sections(self, name):
        store = self.get_store(self)
        store._load_from_string(
            b"""
[foo]
option=foo
[foo/baz]
option=foo/baz
[bar]
option=bar
"""
        )
        matcher = self.matcher(store, name)
        return list(matcher.get_sections())

    def test_matching(self):
        sections = self.get_matching_sections("foo")
        self.assertLength(1, sections)
        self.assertSectionContent(("foo", {"option": "foo"}), sections[0])

    def test_not_matching(self):
        sections = self.get_matching_sections("baz")
        self.assertLength(0, sections)


class TestBaseStackGet(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.overrideAttr(config, "option_registry", config.OptionRegistry())

    def test_get_first_definition(self):
        store1 = config.IniFileStore()
        store1._load_from_string(b"foo=bar")
        store2 = config.IniFileStore()
        store2._load_from_string(b"foo=baz")
        conf = config.Stack([store1.get_sections, store2.get_sections])
        self.assertEqual("bar", conf.get("foo"))

    def test_get_with_registered_default_value(self):
        config.option_registry.register(config.Option("foo", default="bar"))
        conf_stack = config.Stack([])
        self.assertEqual("bar", conf_stack.get("foo"))

    def test_get_without_registered_default_value(self):
        config.option_registry.register(config.Option("foo"))
        conf_stack = config.Stack([])
        self.assertEqual(None, conf_stack.get("foo"))

    def test_get_without_default_value_for_not_registered(self):
        conf_stack = config.Stack([])
        self.assertEqual(None, conf_stack.get("foo"))

    def test_get_for_empty_section_callable(self):
        conf_stack = config.Stack([lambda: []])
        self.assertEqual(None, conf_stack.get("foo"))

    def test_get_for_broken_callable(self):
        # Trying to use and invalid callable raises an exception on first use
        conf_stack = config.Stack([object])
        self.assertRaises(TypeError, conf_stack.get, "foo")


class TestStackWithSimpleStore(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.overrideAttr(config, "option_registry", config.OptionRegistry())
        self.registry = config.option_registry

    def get_conf(self, content=None):
        return config.MemoryStack(content)

    def test_override_value_from_env(self):
        self.overrideEnv("FOO", None)
        self.registry.register(
            config.Option("foo", default="bar", override_from_env=["FOO"])
        )
        self.overrideEnv("FOO", "quux")
        # Env variable provides a default taking over the option one
        conf = self.get_conf(b"foo=store")
        self.assertEqual("quux", conf.get("foo"))

    def test_first_override_value_from_env_wins(self):
        self.overrideEnv("NO_VALUE", None)
        self.overrideEnv("FOO", None)
        self.overrideEnv("BAZ", None)
        self.registry.register(
            config.Option(
                "foo", default="bar", override_from_env=["NO_VALUE", "FOO", "BAZ"]
            )
        )
        self.overrideEnv("FOO", "foo")
        self.overrideEnv("BAZ", "baz")
        # The first env var set wins
        conf = self.get_conf(b"foo=store")
        self.assertEqual("foo", conf.get("foo"))


class TestMemoryStack(tests.TestCase):
    def test_get(self):
        conf = config.MemoryStack(b"foo=bar")
        self.assertEqual("bar", conf.get("foo"))

    def test_set(self):
        conf = config.MemoryStack(b"foo=bar")
        conf.set("foo", "baz")
        self.assertEqual("baz", conf.get("foo"))

    def test_no_content(self):
        conf = config.MemoryStack()
        # No content means no loading
        self.assertFalse(conf.store.is_loaded())
        self.assertRaises(NotImplementedError, conf.get, "foo")
        # But a content can still be provided
        conf.store._load_from_string(b"foo=bar")
        self.assertEqual("bar", conf.get("foo"))


class TestStackIterSections(tests.TestCase):
    def test_empty_stack(self):
        conf = config.Stack([])
        sections = list(conf.iter_sections())
        self.assertLength(0, sections)

    def test_empty_store(self):
        store = config.IniFileStore()
        store._load_from_string(b"")
        conf = config.Stack([store.get_sections])
        sections = list(conf.iter_sections())
        self.assertLength(0, sections)

    def test_simple_store(self):
        store = config.IniFileStore()
        store._load_from_string(b"foo=bar")
        conf = config.Stack([store.get_sections])
        tuples = list(conf.iter_sections())
        self.assertLength(1, tuples)
        (found_store, found_section) = tuples[0]
        self.assertIs(store, found_store)

    def test_two_stores(self):
        store1 = config.IniFileStore()
        store1._load_from_string(b"foo=bar")
        store2 = config.IniFileStore()
        store2._load_from_string(b"bar=qux")
        conf = config.Stack([store1.get_sections, store2.get_sections])
        tuples = list(conf.iter_sections())
        self.assertLength(2, tuples)
        self.assertIs(store1, tuples[0][0])
        self.assertIs(store2, tuples[1][0])


class TestStackWithTransport(tests.TestCaseWithTransport):
    scenarios = [
        (key, {"get_stack": builder})
        for key, builder in config.test_stack_builder_registry.iteritems()
    ]


class TestConcreteStacks(TestStackWithTransport):
    def test_build_stack(self):
        # Just a smoke test to help debug builders
        self.get_stack(self)


class TestStackGet(TestStackWithTransport):
    def setUp(self):
        super().setUp()
        self.conf = self.get_stack(self)

    def test_get_for_empty_stack(self):
        self.assertEqual(None, self.conf.get("foo"))

    def test_get_hook(self):
        self.conf.set("foo", "bar")
        calls = []

        def hook(*args):
            calls.append(args)

        config.ConfigHooks.install_named_hook("get", hook, None)
        self.assertLength(0, calls)
        value = self.conf.get("foo")
        self.assertEqual("bar", value)
        self.assertLength(1, calls)
        self.assertEqual((self.conf, "foo", "bar"), calls[0])


class TestStackGetWithConverter(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.overrideAttr(config, "option_registry", config.OptionRegistry())
        self.registry = config.option_registry

    def get_conf(self, content=None):
        return config.MemoryStack(content)

    def register_bool_option(self, name, default=None, default_from_env=None):
        b = config.Option(
            name,
            help="A boolean.",
            default=default,
            default_from_env=default_from_env,
            from_unicode=config.bool_from_store,
        )
        self.registry.register(b)

    def test_get_default_bool_None(self):
        self.register_bool_option("foo")
        conf = self.get_conf(b"")
        self.assertEqual(None, conf.get("foo"))

    def test_get_default_bool_True(self):
        self.register_bool_option("foo", "True")
        conf = self.get_conf(b"")
        self.assertEqual(True, conf.get("foo"))

    def test_get_default_bool_False(self):
        self.register_bool_option("foo", False)
        conf = self.get_conf(b"")
        self.assertEqual(False, conf.get("foo"))

    def test_get_default_bool_False_as_string(self):
        self.register_bool_option("foo", "False")
        conf = self.get_conf(b"")
        self.assertEqual(False, conf.get("foo"))

    def test_get_default_bool_from_env_converted(self):
        self.register_bool_option("foo", "True", default_from_env=["FOO"])
        self.overrideEnv("FOO", "False")
        conf = self.get_conf(b"")
        self.assertEqual(False, conf.get("foo"))

    def test_get_default_bool_when_conversion_fails(self):
        self.register_bool_option("foo", default="True")
        conf = self.get_conf(b"foo=invalid boolean")
        self.assertEqual(True, conf.get("foo"))

    def register_integer_option(self, name, default=None, default_from_env=None):
        i = config.Option(
            name,
            help="An integer.",
            default=default,
            default_from_env=default_from_env,
            from_unicode=config.int_from_store,
        )
        self.registry.register(i)

    def test_get_default_integer_None(self):
        self.register_integer_option("foo")
        conf = self.get_conf(b"")
        self.assertEqual(None, conf.get("foo"))

    def test_get_default_integer(self):
        self.register_integer_option("foo", 42)
        conf = self.get_conf(b"")
        self.assertEqual(42, conf.get("foo"))

    def test_get_default_integer_as_string(self):
        self.register_integer_option("foo", "42")
        conf = self.get_conf(b"")
        self.assertEqual(42, conf.get("foo"))

    def test_get_default_integer_from_env(self):
        self.register_integer_option("foo", default_from_env=["FOO"])
        self.overrideEnv("FOO", "18")
        conf = self.get_conf(b"")
        self.assertEqual(18, conf.get("foo"))

    def test_get_default_integer_when_conversion_fails(self):
        self.register_integer_option("foo", default="12")
        conf = self.get_conf(b"foo=invalid integer")
        self.assertEqual(12, conf.get("foo"))

    def register_list_option(self, name, default=None, default_from_env=None):
        l = config.ListOption(
            name, help="A list.", default=default, default_from_env=default_from_env
        )
        self.registry.register(l)

    def test_get_default_list_None(self):
        self.register_list_option("foo")
        conf = self.get_conf(b"")
        self.assertEqual(None, conf.get("foo"))

    def test_get_default_list_empty(self):
        self.register_list_option("foo", "")
        conf = self.get_conf(b"")
        self.assertEqual([], conf.get("foo"))

    def test_get_default_list_from_env(self):
        self.register_list_option("foo", default_from_env=["FOO"])
        self.overrideEnv("FOO", "")
        conf = self.get_conf(b"")
        self.assertEqual([], conf.get("foo"))

    def test_get_with_list_converter_no_item(self):
        self.register_list_option("foo", None)
        conf = self.get_conf(b"foo=,")
        self.assertEqual([], conf.get("foo"))

    def test_get_with_list_converter_many_items(self):
        self.register_list_option("foo", None)
        conf = self.get_conf(b"foo=m,o,r,e")
        self.assertEqual(["m", "o", "r", "e"], conf.get("foo"))

    def test_get_with_list_converter_embedded_spaces_many_items(self):
        self.register_list_option("foo", None)
        conf = self.get_conf(b'foo=" bar", "baz "')
        self.assertEqual([" bar", "baz "], conf.get("foo"))

    def test_get_with_list_converter_stripped_spaces_many_items(self):
        self.register_list_option("foo", None)
        conf = self.get_conf(b"foo= bar ,  baz ")
        self.assertEqual(["bar", "baz"], conf.get("foo"))


class TestIterOptionRefs(tests.TestCase):
    """iter_option_refs is a bit unusual, document some cases."""

    def assertRefs(self, expected, string):
        self.assertEqual(expected, list(config.iter_option_refs(string)))

    def test_empty(self):
        self.assertRefs([(False, "")], "")

    def test_no_refs(self):
        self.assertRefs([(False, "foo bar")], "foo bar")

    def test_single_ref(self):
        self.assertRefs([(False, ""), (True, "{foo}"), (False, "")], "{foo}")

    def test_broken_ref(self):
        self.assertRefs([(False, "{foo")], "{foo")

    def test_embedded_ref(self):
        self.assertRefs([(False, "{"), (True, "{foo}"), (False, "}")], "{{foo}}")

    def test_two_refs(self):
        self.assertRefs(
            [
                (False, ""),
                (True, "{foo}"),
                (False, ""),
                (True, "{bar}"),
                (False, ""),
            ],
            "{foo}{bar}",
        )

    def test_newline_in_refs_are_not_matched(self):
        self.assertRefs([(False, "{\nxx}{xx\n}{{\n}}")], "{\nxx}{xx\n}{{\n}}")


class TestStackExpandOptions(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.overrideAttr(config, "option_registry", config.OptionRegistry())
        self.registry = config.option_registry
        store = config.TransportIniFileStore(self.get_transport(), "foo.conf")
        self.conf = config.Stack([store.get_sections], store)

    def assertExpansion(self, expected, string, env=None):
        self.assertEqual(expected, self.conf.expand_options(string, env))

    def test_no_expansion(self):
        self.assertExpansion("foo", "foo")

    def test_expand_default_value(self):
        self.conf.store._load_from_string(b"bar=baz")
        self.registry.register(config.Option("foo", default="{bar}"))
        self.assertEqual("baz", self.conf.get("foo", expand=True))

    def test_expand_default_from_env(self):
        self.conf.store._load_from_string(b"bar=baz")
        self.registry.register(config.Option("foo", default_from_env=["FOO"]))
        self.overrideEnv("FOO", "{bar}")
        self.assertEqual("baz", self.conf.get("foo", expand=True))

    def test_expand_default_on_failed_conversion(self):
        self.conf.store._load_from_string(b"baz=bogus\nbar=42\nfoo={baz}")
        self.registry.register(
            config.Option("foo", default="{bar}", from_unicode=config.int_from_store)
        )
        self.assertEqual(42, self.conf.get("foo", expand=True))

    def test_env_adding_options(self):
        self.assertExpansion("bar", "{foo}", {"foo": "bar"})

    def test_env_overriding_options(self):
        self.conf.store._load_from_string(b"foo=baz")
        self.assertExpansion("bar", "{foo}", {"foo": "bar"})

    def test_simple_ref(self):
        self.conf.store._load_from_string(b"foo=xxx")
        self.assertExpansion("xxx", "{foo}")

    def test_unknown_ref(self):
        self.assertRaises(
            config.ExpandingUnknownOption, self.conf.expand_options, "{foo}"
        )

    def test_illegal_def_is_ignored(self):
        self.assertExpansion("{1,2}", "{1,2}")
        self.assertExpansion("{ }", "{ }")
        self.assertExpansion("${Foo,f}", "${Foo,f}")

    def test_indirect_ref(self):
        self.conf.store._load_from_string(
            b"""
foo=xxx
bar={foo}
"""
        )
        self.assertExpansion("xxx", "{bar}")

    def test_embedded_ref(self):
        self.conf.store._load_from_string(
            b"""
foo=xxx
bar=foo
"""
        )
        self.assertExpansion("xxx", "{{bar}}")

    def test_simple_loop(self):
        self.conf.store._load_from_string(b"foo={foo}")
        self.assertRaises(config.OptionExpansionLoop, self.conf.expand_options, "{foo}")

    def test_indirect_loop(self):
        self.conf.store._load_from_string(
            b"""
foo={bar}
bar={baz}
baz={foo}"""
        )
        e = self.assertRaises(
            config.OptionExpansionLoop, self.conf.expand_options, "{foo}"
        )
        self.assertEqual("foo->bar->baz", e.refs)
        self.assertEqual("{foo}", e.string)

    def test_list(self):
        self.conf.store._load_from_string(
            b"""
foo=start
bar=middle
baz=end
list={foo},{bar},{baz}
"""
        )
        self.registry.register(config.ListOption("list"))
        self.assertEqual(["start", "middle", "end"], self.conf.get("list", expand=True))

    def test_cascading_list(self):
        self.conf.store._load_from_string(
            b"""
foo=start,{bar}
bar=middle,{baz}
baz=end
list={foo}
"""
        )
        self.registry.register(config.ListOption("list"))
        # Register an intermediate option as a list to ensure no conversion
        # happen while expanding. Conversion should only occur for the original
        # option ('list' here).
        self.registry.register(config.ListOption("baz"))
        self.assertEqual(["start", "middle", "end"], self.conf.get("list", expand=True))

    def test_pathologically_hidden_list(self):
        self.conf.store._load_from_string(
            b"""
foo=bin
bar=go
start={foo
middle=},{
end=bar}
hidden={start}{middle}{end}
"""
        )
        # What matters is what the registration says, the conversion happens
        # only after all expansions have been performed
        self.registry.register(config.ListOption("hidden"))
        self.assertEqual(["bin", "go"], self.conf.get("hidden", expand=True))


class TestStackCrossSectionsExpand(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()

    def get_config(self, location, string):
        if string is None:
            string = b""
        # Since we don't save the config we won't strictly require to inherit
        # from TestCaseInTempDir, but an error occurs so quickly...
        c = config.LocationStack(location)
        c.store._load_from_string(string)
        return c

    def test_dont_cross_unrelated_section(self):
        c = self.get_config(
            "/another/branch/path",
            b"""
[/one/branch/path]
foo = hello
bar = {foo}/2

[/another/branch/path]
bar = {foo}/2
""",
        )
        self.assertRaises(config.ExpandingUnknownOption, c.get, "bar", expand=True)

    def test_cross_related_sections(self):
        c = self.get_config(
            "/project/branch/path",
            b"""
[/project]
foo = qu

[/project/branch/path]
bar = {foo}ux
""",
        )
        self.assertEqual("quux", c.get("bar", expand=True))


class TestStackCrossStoresExpand(tests.TestCaseWithTransport):
    def test_cross_global_locations(self):
        l_store = config.LocationStore()
        l_store._load_from_string(
            b"""
[/branch]
lfoo = loc-foo
lbar = {gbar}
"""
        )
        l_store.save()
        g_store = config.GlobalStore()
        g_store._load_from_string(
            b"""
[DEFAULT]
gfoo = {lfoo}
gbar = glob-bar
"""
        )
        g_store.save()
        stack = config.LocationStack("/branch")
        self.assertEqual("glob-bar", stack.get("lbar", expand=True))
        self.assertEqual("loc-foo", stack.get("gfoo", expand=True))


class TestStackExpandSectionLocals(tests.TestCaseWithTransport):
    def test_expand_locals_empty(self):
        l_store = config.LocationStore()
        l_store._load_from_string(
            b"""
[/home/user/project]
base = {basename}
rel = {relpath}
"""
        )
        l_store.save()
        stack = config.LocationStack("/home/user/project/")
        self.assertEqual("", stack.get("base", expand=True))
        self.assertEqual("", stack.get("rel", expand=True))

    def test_expand_basename_locally(self):
        l_store = config.LocationStore()
        l_store._load_from_string(
            b"""
[/home/user/project]
bfoo = {basename}
"""
        )
        l_store.save()
        stack = config.LocationStack("/home/user/project/branch")
        self.assertEqual("branch", stack.get("bfoo", expand=True))

    def test_expand_basename_locally_longer_path(self):
        l_store = config.LocationStore()
        l_store._load_from_string(
            b"""
[/home/user]
bfoo = {basename}
"""
        )
        l_store.save()
        stack = config.LocationStack("/home/user/project/dir/branch")
        self.assertEqual("branch", stack.get("bfoo", expand=True))

    def test_expand_relpath_locally(self):
        l_store = config.LocationStore()
        l_store._load_from_string(
            b"""
[/home/user/project]
lfoo = loc-foo/{relpath}
"""
        )
        l_store.save()
        stack = config.LocationStack("/home/user/project/branch")
        self.assertEqual("loc-foo/branch", stack.get("lfoo", expand=True))

    def test_expand_relpath_unknonw_in_global(self):
        g_store = config.GlobalStore()
        g_store._load_from_string(
            b"""
[DEFAULT]
gfoo = {relpath}
"""
        )
        g_store.save()
        stack = config.LocationStack("/home/user/project/branch")
        self.assertRaises(config.ExpandingUnknownOption, stack.get, "gfoo", expand=True)

    def test_expand_local_option_locally(self):
        l_store = config.LocationStore()
        l_store._load_from_string(
            b"""
[/home/user/project]
lfoo = loc-foo/{relpath}
lbar = {gbar}
"""
        )
        l_store.save()
        g_store = config.GlobalStore()
        g_store._load_from_string(
            b"""
[DEFAULT]
gfoo = {lfoo}
gbar = glob-bar
"""
        )
        g_store.save()
        stack = config.LocationStack("/home/user/project/branch")
        self.assertEqual("glob-bar", stack.get("lbar", expand=True))
        self.assertEqual("loc-foo/branch", stack.get("gfoo", expand=True))

    def test_locals_dont_leak(self):
        """Make sure we chose the right local in presence of several sections."""
        l_store = config.LocationStore()
        l_store._load_from_string(
            b"""
[/home/user]
lfoo = loc-foo/{relpath}
[/home/user/project]
lfoo = loc-foo/{relpath}
"""
        )
        l_store.save()
        stack = config.LocationStack("/home/user/project/branch")
        self.assertEqual("loc-foo/branch", stack.get("lfoo", expand=True))
        stack = config.LocationStack("/home/user/bar/baz")
        self.assertEqual("loc-foo/bar/baz", stack.get("lfoo", expand=True))


class TestStackSet(TestStackWithTransport):
    def test_simple_set(self):
        conf = self.get_stack(self)
        self.assertEqual(None, conf.get("foo"))
        conf.set("foo", "baz")
        # Did we get it back ?
        self.assertEqual("baz", conf.get("foo"))

    def test_set_creates_a_new_section(self):
        conf = self.get_stack(self)
        conf.set("foo", "baz")
        self.assertEqual, "baz", conf.get("foo")

    def test_set_hook(self):
        calls = []

        def hook(*args):
            calls.append(args)

        config.ConfigHooks.install_named_hook("set", hook, None)
        self.assertLength(0, calls)
        conf = self.get_stack(self)
        conf.set("foo", "bar")
        self.assertLength(1, calls)
        self.assertEqual((conf, "foo", "bar"), calls[0])


class TestStackRemove(TestStackWithTransport):
    def test_remove_existing(self):
        conf = self.get_stack(self)
        conf.set("foo", "bar")
        self.assertEqual("bar", conf.get("foo"))
        conf.remove("foo")
        # Did we get it back ?
        self.assertEqual(None, conf.get("foo"))

    def test_remove_unknown(self):
        conf = self.get_stack(self)
        self.assertRaises(KeyError, conf.remove, "I_do_not_exist")

    def test_remove_hook(self):
        calls = []

        def hook(*args):
            calls.append(args)

        config.ConfigHooks.install_named_hook("remove", hook, None)
        self.assertLength(0, calls)
        conf = self.get_stack(self)
        conf.set("foo", "bar")
        conf.remove("foo")
        self.assertLength(1, calls)
        self.assertEqual((conf, "foo"), calls[0])


class TestConfigGetOptions(tests.TestCaseWithTransport, TestOptionsMixin):
    def setUp(self):
        super().setUp()
        create_configs(self)

    def test_no_variable(self):
        # Using branch should query branch, locations and breezy
        self.assertOptions([], self.branch_config)

    def test_option_in_breezy(self):
        self.breezy_config.set_user_option("file", "breezy")
        self.assertOptions(
            [("file", "breezy", "DEFAULT", "breezy")], self.breezy_config
        )

    def test_option_in_locations(self):
        self.locations_config.set_user_option("file", "locations")
        self.assertOptions(
            [("file", "locations", self.tree.basedir, "locations")],
            self.locations_config,
        )

    def test_option_in_branch(self):
        self.branch_config.set_user_option("file", "branch")
        self.assertOptions(
            [("file", "branch", "DEFAULT", "branch")], self.branch_config
        )

    def test_option_in_breezy_and_branch(self):
        self.breezy_config.set_user_option("file", "breezy")
        self.branch_config.set_user_option("file", "branch")
        self.assertOptions(
            [
                ("file", "branch", "DEFAULT", "branch"),
                ("file", "breezy", "DEFAULT", "breezy"),
            ],
            self.branch_config,
        )

    def test_option_in_branch_and_locations(self):
        # Hmm, locations override branch :-/
        self.locations_config.set_user_option("file", "locations")
        self.branch_config.set_user_option("file", "branch")
        self.assertOptions(
            [
                ("file", "locations", self.tree.basedir, "locations"),
                ("file", "branch", "DEFAULT", "branch"),
            ],
            self.branch_config,
        )

    def test_option_in_breezy_locations_and_branch(self):
        self.breezy_config.set_user_option("file", "breezy")
        self.locations_config.set_user_option("file", "locations")
        self.branch_config.set_user_option("file", "branch")
        self.assertOptions(
            [
                ("file", "locations", self.tree.basedir, "locations"),
                ("file", "branch", "DEFAULT", "branch"),
                ("file", "breezy", "DEFAULT", "breezy"),
            ],
            self.branch_config,
        )


class TestConfigRemoveOption(tests.TestCaseWithTransport, TestOptionsMixin):
    def setUp(self):
        super().setUp()
        create_configs_with_file_option(self)

    def test_remove_in_locations(self):
        self.locations_config.remove_user_option("file", self.tree.basedir)
        self.assertOptions(
            [
                ("file", "branch", "DEFAULT", "branch"),
                ("file", "breezy", "DEFAULT", "breezy"),
            ],
            self.branch_config,
        )

    def test_remove_in_branch(self):
        self.branch_config.remove_user_option("file")
        self.assertOptions(
            [
                ("file", "locations", self.tree.basedir, "locations"),
                ("file", "breezy", "DEFAULT", "breezy"),
            ],
            self.branch_config,
        )

    def test_remove_in_breezy(self):
        self.breezy_config.remove_user_option("file")
        self.assertOptions(
            [
                ("file", "locations", self.tree.basedir, "locations"),
                ("file", "branch", "DEFAULT", "branch"),
            ],
            self.branch_config,
        )


class TestConfigGetSections(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
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
        self.assertEqual(expected, [n for n, _, _ in sections])

    def test_breezy_default_section(self):
        self.assertSectionNames(["DEFAULT"], self.breezy_config)

    def test_locations_default_section(self):
        # No sections are defined in an empty file
        self.assertSectionNames([], self.locations_config)

    def test_locations_named_section(self):
        self.locations_config.set_user_option("file", "locations")
        self.assertSectionNames([self.tree.basedir], self.locations_config)

    def test_locations_matching_sections(self):
        loc_config = self.locations_config
        loc_config.set_user_option("file", "locations")
        # We need to cheat a bit here to create an option in sections above and
        # below the 'location' one.
        parser = loc_config._get_parser()
        # locations.cong deals with '/' ignoring native os.sep
        location_names = self.tree.basedir.split("/")
        parent = "/".join(location_names[:-1])
        child = "/".join(location_names + ["child"])
        parser[parent] = {}
        parser[parent]["file"] = "parent"
        parser[child] = {}
        parser[child]["file"] = "child"
        self.assertSectionNames([self.tree.basedir, parent], loc_config)

    def test_branch_data_default_section(self):
        self.assertSectionNames([None], self.branch_config._get_branch_data_config())

    def test_branch_default_sections(self):
        # No sections are defined in an empty locations file
        self.assertSectionNames([None, "DEFAULT"], self.branch_config)
        # Unless we define an option
        self.branch_config._get_location_config().set_user_option("file", "locations")
        self.assertSectionNames(
            [self.tree.basedir, None, "DEFAULT"], self.branch_config
        )

    def test_breezy_named_section(self):
        # We need to cheat as the API doesn't give direct access to sections
        # other than DEFAULT.
        self.breezy_config.set_alias("breezy", "bzr")
        self.assertSectionNames(["ALIASES"], self.breezy_config, "ALIASES")


class TestSharedStores(tests.TestCaseInTempDir):
    def test_breezy_conf_shared(self):
        g1 = config.GlobalStack()
        g2 = config.GlobalStack()
        # The two stacks share the same store
        self.assertIs(g1.store, g2.store)


class TestAuthenticationConfigFilePermissions(tests.TestCaseInTempDir):
    """Test warning for permissions of authentication.conf."""

    def setUp(self):
        super().setUp()
        self.path = osutils.pathjoin(self.test_dir, "authentication.conf")
        with open(self.path, "wb") as f:
            f.write(
                b"""[broken]
scheme=ftp
user=joe
port=port # Error: Not an int
"""
            )
        self.overrideAttr(bedding, "authentication_config_path", lambda: self.path)
        osutils.chmod_if_possible(self.path, 0o755)

    def test_check_warning(self):
        conf = config.AuthenticationConfig()
        self.assertEqual(conf._filename, self.path)
        self.assertContainsRe(
            self.get_log(), "Saved passwords may be accessible by other users."
        )

    def test_check_suppressed_warning(self):
        global_config = config.GlobalConfig()
        global_config.set_user_option("suppress_warnings", "insecure_permissions")
        conf = config.AuthenticationConfig()
        self.assertEqual(conf._filename, self.path)
        self.assertNotContainsRe(
            self.get_log(), "Saved passwords may be accessible by other users."
        )


class TestAuthenticationConfigFile(tests.TestCase):
    """Test the authentication.conf file matching."""

    def _got_user_passwd(
        self, expected_user, expected_password, config, *args, **kwargs
    ):
        credentials = config.get_credentials(*args, **kwargs)
        if credentials is None:
            user = None
            password = None
        else:
            user = credentials["user"]
            password = credentials["password"]
        self.assertEqual(expected_user, user)
        self.assertEqual(expected_password, password)

    def test_empty_config(self):
        conf = config.AuthenticationConfig(_file=BytesIO())
        self.assertEqual({}, conf._get_config())
        self._got_user_passwd(None, None, conf, "http", "foo.net")

    def test_non_utf8_config(self):
        conf = config.AuthenticationConfig(_file=BytesIO(b"foo = bar\xff"))
        self.assertRaises(config.ConfigContentError, conf._get_config)

    def test_missing_auth_section_header(self):
        conf = config.AuthenticationConfig(_file=BytesIO(b"foo = bar"))
        self.assertRaises(ValueError, conf.get_credentials, "ftp", "foo.net")

    def test_auth_section_header_not_closed(self):
        conf = config.AuthenticationConfig(_file=BytesIO(b"[DEF"))
        self.assertRaises(config.ParseConfigError, conf._get_config)

    def test_auth_value_not_boolean(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""\
[broken]
scheme=ftp
user=joe
verify_certificates=askme # Error: Not a boolean
"""
            )
        )
        self.assertRaises(ValueError, conf.get_credentials, "ftp", "foo.net")

    def test_auth_value_not_int(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""\
[broken]
scheme=ftp
user=joe
port=port # Error: Not an int
"""
            )
        )
        self.assertRaises(ValueError, conf.get_credentials, "ftp", "foo.net")

    def test_unknown_password_encoding(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""\
[broken]
scheme=ftp
user=joe
password_encoding=unknown
"""
            )
        )
        self.assertRaises(ValueError, conf.get_password, "ftp", "foo.net", "joe")

    def test_credentials_for_scheme_host(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""\
# Identity on foo.net
[ftp definition]
scheme=ftp
host=foo.net
user=joe
password=secret-pass
"""
            )
        )
        # Basic matching
        self._got_user_passwd("joe", "secret-pass", conf, "ftp", "foo.net")
        # different scheme
        self._got_user_passwd(None, None, conf, "http", "foo.net")
        # different host
        self._got_user_passwd(None, None, conf, "ftp", "bar.net")

    def test_credentials_for_host_port(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""\
# Identity on foo.net
[ftp definition]
scheme=ftp
port=10021
host=foo.net
user=joe
password=secret-pass
"""
            )
        )
        # No port
        self._got_user_passwd("joe", "secret-pass", conf, "ftp", "foo.net", port=10021)
        # different port
        self._got_user_passwd(None, None, conf, "ftp", "foo.net")

    def test_for_matching_host(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""\
# Identity on foo.net
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
"""
            )
        )
        # matching domain
        self._got_user_passwd("georges", "bendover", conf, "bzr", "foo.bzr.sf.net")
        # phishing attempt
        self._got_user_passwd(None, None, conf, "bzr", "bbzr.sf.net")

    def test_for_matching_host_None(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""\
# Identity on foo.net
[catchup bzr]
scheme=bzr
user=joe
password=joepass
[DEFAULT]
user=georges
password=bendover
"""
            )
        )
        # match no host
        self._got_user_passwd("joe", "joepass", conf, "bzr", "quux.net")
        # no host but different scheme
        self._got_user_passwd("georges", "bendover", conf, "ftp", "quux.net")

    def test_credentials_for_path(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""
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
"""
            )
        )
        # no path no dice
        self._got_user_passwd(None, None, conf, "http", host="bar.org", path="/dir3")
        # matching path
        self._got_user_passwd(
            "georges", "bendover", conf, "http", host="bar.org", path="/dir2"
        )
        # matching subdir
        self._got_user_passwd(
            "jim", "jimpass", conf, "http", host="bar.org", path="/dir1/subdir"
        )

    def test_credentials_for_user(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""
[with user]
scheme=http
host=bar.org
user=jim
password=jimpass
"""
            )
        )
        # Get user
        self._got_user_passwd("jim", "jimpass", conf, "http", "bar.org")
        # Get same user
        self._got_user_passwd("jim", "jimpass", conf, "http", "bar.org", user="jim")
        # Don't get a different user if one is specified
        self._got_user_passwd(None, None, conf, "http", "bar.org", user="georges")

    def test_credentials_for_user_without_password(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""
[without password]
scheme=http
host=bar.org
user=jim
"""
            )
        )
        # Get user but no password
        self._got_user_passwd("jim", None, conf, "http", "bar.org")

    def test_verify_certificates(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""
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
"""
            )
        )
        credentials = conf.get_credentials("https", "bar.org")
        self.assertEqual(False, credentials.get("verify_certificates"))
        credentials = conf.get_credentials("https", "foo.net")
        self.assertEqual(True, credentials.get("verify_certificates"))


class TestAuthenticationStorage(tests.TestCaseInTempDir):
    def test_set_credentials(self):
        conf = config.AuthenticationConfig()
        conf.set_credentials(
            "name",
            "host",
            "user",
            "scheme",
            "password",
            99,
            path="/foo",
            verify_certificates=False,
            realm="realm",
        )
        credentials = conf.get_credentials(
            host="host", scheme="scheme", port=99, path="/foo", realm="realm"
        )
        CREDENTIALS = {
            "name": "name",
            "user": "user",
            "password": "password",
            "verify_certificates": False,
            "scheme": "scheme",
            "host": "host",
            "port": 99,
            "path": "/foo",
            "realm": "realm",
        }
        self.assertEqual(CREDENTIALS, credentials)
        credentials_from_disk = config.AuthenticationConfig().get_credentials(
            host="host", scheme="scheme", port=99, path="/foo", realm="realm"
        )
        self.assertEqual(CREDENTIALS, credentials_from_disk)

    def test_reset_credentials_different_name(self):
        conf = config.AuthenticationConfig()
        (conf.set_credentials("name", "host", "user", "scheme", "password"),)
        (conf.set_credentials("name2", "host", "user2", "scheme", "password"),)
        self.assertIs(None, conf._get_config().get("name"))
        credentials = conf.get_credentials(host="host", scheme="scheme")
        CREDENTIALS = {
            "name": "name2",
            "user": "user2",
            "password": "password",
            "verify_certificates": True,
            "scheme": "scheme",
            "host": "host",
            "port": None,
            "path": None,
            "realm": None,
        }
        self.assertEqual(CREDENTIALS, credentials)


class TestAuthenticationConfig(tests.TestCaseInTempDir):
    """Test AuthenticationConfig behaviour."""

    def _check_default_password_prompt(
        self,
        expected_prompt_format,
        scheme,
        host=None,
        port=None,
        realm=None,
        path=None,
    ):
        if host is None:
            host = "bar.org"
        user, password = "jim", "precious"
        expected_prompt = expected_prompt_format % {
            "scheme": scheme,
            "host": host,
            "port": port,
            "user": user,
            "realm": realm,
        }

        ui.ui_factory = tests.TestUIFactory(stdin=password + "\n")
        # We use an empty conf so that the user is always prompted
        conf = config.AuthenticationConfig()
        self.assertEqual(
            password,
            conf.get_password(scheme, host, user, port=port, realm=realm, path=path),
        )
        self.assertEqual(expected_prompt, ui.ui_factory.stderr.getvalue())
        self.assertEqual("", ui.ui_factory.stdout.getvalue())

    def _check_default_username_prompt(
        self,
        expected_prompt_format,
        scheme,
        host=None,
        port=None,
        realm=None,
        path=None,
    ):
        if host is None:
            host = "bar.org"
        username = "jim"
        expected_prompt = expected_prompt_format % {
            "scheme": scheme,
            "host": host,
            "port": port,
            "realm": realm,
        }
        ui.ui_factory = tests.TestUIFactory(stdin=username + "\n")
        # We use an empty conf so that the user is always prompted
        conf = config.AuthenticationConfig()
        self.assertEqual(
            username,
            conf.get_user(scheme, host, port=port, realm=realm, path=path, ask=True),
        )
        self.assertEqual(expected_prompt, ui.ui_factory.stderr.getvalue())
        self.assertEqual("", ui.ui_factory.stdout.getvalue())

    def test_username_defaults_prompts(self):
        # HTTP prompts can't be tested here, see test_http.py
        self._check_default_username_prompt("FTP %(host)s username: ", "ftp")
        self._check_default_username_prompt(
            "FTP %(host)s:%(port)d username: ", "ftp", port=10020
        )
        self._check_default_username_prompt(
            "SSH %(host)s:%(port)d username: ", "ssh", port=12345
        )

    def test_username_default_no_prompt(self):
        conf = config.AuthenticationConfig()
        self.assertEqual(None, conf.get_user("ftp", "example.com"))
        self.assertEqual(
            "explicitdefault",
            conf.get_user("ftp", "example.com", default="explicitdefault"),
        )

    def test_password_default_prompts(self):
        # HTTP prompts can't be tested here, see test_http.py
        self._check_default_password_prompt("FTP %(user)s@%(host)s password: ", "ftp")
        self._check_default_password_prompt(
            "FTP %(user)s@%(host)s:%(port)d password: ", "ftp", port=10020
        )
        self._check_default_password_prompt(
            "SSH %(user)s@%(host)s:%(port)d password: ", "ssh", port=12345
        )
        # SMTP port handling is a bit special (it's handled if embedded in the
        # host too)
        # FIXME: should we: forbid that, extend it to other schemes, leave
        # things as they are that's fine thank you ?
        self._check_default_password_prompt("SMTP %(user)s@%(host)s password: ", "smtp")
        self._check_default_password_prompt(
            "SMTP %(user)s@%(host)s password: ", "smtp", host="bar.org:10025"
        )
        self._check_default_password_prompt(
            "SMTP %(user)s@%(host)s:%(port)d password: ", "smtp", port=10025
        )

    def test_ssh_password_emits_warning(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""
[ssh with password]
scheme=ssh
host=bar.org
user=jim
password=jimpass
"""
            )
        )
        entered_password = "typed-by-hand"
        ui.ui_factory = tests.TestUIFactory(stdin=entered_password + "\n")

        # Since the password defined in the authentication config is ignored,
        # the user is prompted
        self.assertEqual(
            entered_password, conf.get_password("ssh", "bar.org", user="jim")
        )
        self.assertContainsRe(
            self.get_log(), "password ignored in section \\[ssh with password\\]"
        )

    def test_ssh_without_password_doesnt_emit_warning(self):
        conf = config.AuthenticationConfig(
            _file=BytesIO(
                b"""
[ssh with password]
scheme=ssh
host=bar.org
user=jim
"""
            )
        )
        entered_password = "typed-by-hand"
        ui.ui_factory = tests.TestUIFactory(stdin=entered_password + "\n")

        # Since the password defined in the authentication config is ignored,
        # the user is prompted
        self.assertEqual(
            entered_password, conf.get_password("ssh", "bar.org", user="jim")
        )
        # No warning shoud be emitted since there is no password. We are only
        # providing "user".
        self.assertNotContainsRe(
            self.get_log(), "password ignored in section \\[ssh with password\\]"
        )

    def test_uses_fallback_stores(self):
        self.overrideAttr(
            config, "credential_store_registry", config.CredentialStoreRegistry()
        )
        store = StubCredentialStore()
        store.add_credentials("http", "example.com", "joe", "secret")
        config.credential_store_registry.register("stub", store, fallback=True)
        conf = config.AuthenticationConfig(_file=BytesIO())
        creds = conf.get_credentials("http", "example.com")
        self.assertEqual("joe", creds["user"])
        self.assertEqual("secret", creds["password"])


class StubCredentialStore(config.CredentialStore):
    def __init__(self):
        self._username = {}
        self._password = {}

    def add_credentials(self, scheme, host, user, password=None):
        self._username[(scheme, host)] = user
        self._password[(scheme, host)] = password

    def get_credentials(
        self, scheme, host, port=None, user=None, path=None, realm=None
    ):
        key = (scheme, host)
        if key not in self._username:
            return None
        return {
            "scheme": scheme,
            "host": host,
            "port": port,
            "user": self._username[key],
            "password": self._password[key],
        }


class CountingCredentialStore(config.CredentialStore):
    def __init__(self):
        self._calls = 0

    def get_credentials(
        self, scheme, host, port=None, user=None, path=None, realm=None
    ):
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
        self.assertRaises(KeyError, r.get_credential_store, "unknown")

    def test_fallback_none_registered(self):
        r = config.CredentialStoreRegistry()
        self.assertEqual(None, r.get_fallback_credentials("http", "example.com"))

    def test_register(self):
        r = config.CredentialStoreRegistry()
        r.register("stub", StubCredentialStore(), fallback=False)
        r.register("another", StubCredentialStore(), fallback=True)
        self.assertEqual(["another", "stub"], r.keys())

    def test_register_lazy(self):
        r = config.CredentialStoreRegistry()
        r.register_lazy(
            "stub", "breezy.tests.test_config", "StubCredentialStore", fallback=False
        )
        self.assertEqual(["stub"], r.keys())
        self.assertIsInstance(r.get_credential_store("stub"), StubCredentialStore)

    def test_is_fallback(self):
        r = config.CredentialStoreRegistry()
        r.register("stub1", None, fallback=False)
        r.register("stub2", None, fallback=True)
        self.assertEqual(False, r.is_fallback("stub1"))
        self.assertEqual(True, r.is_fallback("stub2"))

    def test_no_fallback(self):
        r = config.CredentialStoreRegistry()
        store = CountingCredentialStore()
        r.register("count", store, fallback=False)
        self.assertEqual(None, r.get_fallback_credentials("http", "example.com"))
        self.assertEqual(0, store._calls)

    def test_fallback_credentials(self):
        r = config.CredentialStoreRegistry()
        store = StubCredentialStore()
        store.add_credentials("http", "example.com", "somebody", "geheim")
        r.register("stub", store, fallback=True)
        creds = r.get_fallback_credentials("http", "example.com")
        self.assertEqual("somebody", creds["user"])
        self.assertEqual("geheim", creds["password"])

    def test_fallback_first_wins(self):
        r = config.CredentialStoreRegistry()
        stub1 = StubCredentialStore()
        stub1.add_credentials("http", "example.com", "somebody", "stub1")
        r.register("stub1", stub1, fallback=True)
        stub2 = StubCredentialStore()
        stub2.add_credentials("http", "example.com", "somebody", "stub2")
        r.register("stub2", stub1, fallback=True)
        creds = r.get_fallback_credentials("http", "example.com")
        self.assertEqual("somebody", creds["user"])
        self.assertEqual("stub1", creds["password"])


class TestPlainTextCredentialStore(tests.TestCase):
    def test_decode_password(self):
        r = config.credential_store_registry
        plain_text = r.get_credential_store()
        decoded = plain_text.decode_password({"password": "secret"})
        self.assertEqual("secret", decoded)


class TestBase64CredentialStore(tests.TestCase):
    def test_decode_password(self):
        r = config.credential_store_registry
        plain_text = r.get_credential_store("base64")
        decoded = plain_text.decode_password({"password": "c2VjcmV0"})
        self.assertEqual(b"secret", decoded)


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


class EmailOptionTests(tests.TestCase):
    def test_default_email_uses_BRZ_EMAIL(self):
        conf = config.MemoryStack(b"email=jelmer@debian.org")
        # BRZ_EMAIL takes precedence over BZR_EMAIL and EMAIL
        self.overrideEnv("BRZ_EMAIL", "jelmer@samba.org")
        self.overrideEnv("BZR_EMAIL", "jelmer@jelmer.uk")
        self.overrideEnv("EMAIL", "jelmer@apache.org")
        self.assertEqual("jelmer@samba.org", conf.get("email"))

    def test_default_email_uses_BZR_EMAIL(self):
        conf = config.MemoryStack(b"email=jelmer@debian.org")
        # BZR_EMAIL takes precedence over EMAIL
        self.overrideEnv("BZR_EMAIL", "jelmer@samba.org")
        self.overrideEnv("EMAIL", "jelmer@apache.org")
        self.assertEqual("jelmer@samba.org", conf.get("email"))

    def test_default_email_uses_EMAIL(self):
        conf = config.MemoryStack(b"")
        self.overrideEnv("BRZ_EMAIL", None)
        self.overrideEnv("EMAIL", "jelmer@apache.org")
        self.assertEqual("jelmer@apache.org", conf.get("email"))

    def test_BRZ_EMAIL_overrides(self):
        conf = config.MemoryStack(b"email=jelmer@debian.org")
        self.overrideEnv("BRZ_EMAIL", "jelmer@apache.org")
        self.assertEqual("jelmer@apache.org", conf.get("email"))
        self.overrideEnv("BRZ_EMAIL", None)
        self.overrideEnv("EMAIL", "jelmer@samba.org")
        self.assertEqual("jelmer@debian.org", conf.get("email"))


class MailClientOptionTests(tests.TestCase):
    def test_default(self):
        conf = config.MemoryStack(b"")
        client = conf.get("mail_client")
        self.assertIs(client, mail_client.DefaultMail)

    def test_evolution(self):
        conf = config.MemoryStack(b"mail_client=evolution")
        client = conf.get("mail_client")
        self.assertIs(client, mail_client.Evolution)

    def test_kmail(self):
        conf = config.MemoryStack(b"mail_client=kmail")
        client = conf.get("mail_client")
        self.assertIs(client, mail_client.KMail)

    def test_mutt(self):
        conf = config.MemoryStack(b"mail_client=mutt")
        client = conf.get("mail_client")
        self.assertIs(client, mail_client.Mutt)

    def test_thunderbird(self):
        conf = config.MemoryStack(b"mail_client=thunderbird")
        client = conf.get("mail_client")
        self.assertIs(client, mail_client.Thunderbird)

    def test_explicit_default(self):
        conf = config.MemoryStack(b"mail_client=default")
        client = conf.get("mail_client")
        self.assertIs(client, mail_client.DefaultMail)

    def test_editor(self):
        conf = config.MemoryStack(b"mail_client=editor")
        client = conf.get("mail_client")
        self.assertIs(client, mail_client.Editor)

    def test_mapi(self):
        conf = config.MemoryStack(b"mail_client=mapi")
        client = conf.get("mail_client")
        self.assertIs(client, mail_client.MAPIClient)

    def test_xdg_email(self):
        conf = config.MemoryStack(b"mail_client=xdg-email")
        client = conf.get("mail_client")
        self.assertIs(client, mail_client.XDGEmail)

    def test_unknown(self):
        conf = config.MemoryStack(b"mail_client=firebird")
        self.assertRaises(config.ConfigOptionValueError, conf.get, "mail_client")
