# Copyright (C) 2011, 2016 Canonical Ltd
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

import re
import textwrap
from io import StringIO

from .. import commands, export_pot, option, registry, tests


class TestEscape(tests.TestCase):
    def test_simple_escape(self):
        self.assertEqual(export_pot._escape("foobar"), "foobar")

        s = '''foo\nbar\r\tbaz\\"spam"'''
        e = '''foo\\nbar\\r\\tbaz\\\\\\"spam\\"'''
        self.assertEqual(export_pot._escape(s), e)

    def test_complex_escape(self):
        s = """\\r \\\n"""
        e = """\\\\r \\\\\\n"""
        self.assertEqual(export_pot._escape(s), e)


class TestNormalize(tests.TestCase):
    def test_single_line(self):
        s = "foobar"
        e = '"foobar"'
        self.assertEqual(export_pot._normalize(s), e)

        s = 'foo"bar'
        e = '"foo\\"bar"'
        self.assertEqual(export_pot._normalize(s), e)

    def test_multi_lines(self):
        s = "foo\nbar\n"
        e = '""\n"foo\\n"\n"bar\\n"'
        self.assertEqual(export_pot._normalize(s), e)

        s = "\nfoo\nbar\n"
        e = '""\n"\\n"\n"foo\\n"\n"bar\\n"'
        self.assertEqual(export_pot._normalize(s), e)


class TestParseSource(tests.TestCase):
    """Check mappings to line numbers generated from python source"""

    def test_classes(self):
        src = '''
class Ancient:
    """Old style class"""

class Modern(object):
    """New style class"""
'''
        cls_lines, _ = export_pot._parse_source(src)
        self.assertEqual(cls_lines, {"Ancient": 2, "Modern": 5})

    def test_classes_nested(self):
        src = """
class Matroska(object):
    class Smaller(object):
        class Smallest(object):
            pass
"""
        cls_lines, _ = export_pot._parse_source(src)
        self.assertEqual(cls_lines, {"Matroska": 2, "Smaller": 3, "Smallest": 4})

    def test_strings_docstrings(self):
        src = '''\
"""Module"""

def function():
    """Function"""

class Class(object):
    """Class"""

    def method(self):
        """Method"""
'''
        _, str_lines = export_pot._parse_source(src)
        self.assertEqual(
            str_lines, {"Module": 1, "Function": 4, "Class": 7, "Method": 10}
        )

    def test_strings_literals(self):
        src = """\
s = "One"
t = (2, "Two")
f = dict(key="Three")
"""
        _, str_lines = export_pot._parse_source(src)
        self.assertEqual(str_lines, {"One": 1, "Two": 2, "Three": 3})

    def test_strings_multiline(self):
        src = '''\
"""Start

End
"""
t = (
    "A"
    "B"
    "C"
    )
'''
        _, str_lines = export_pot._parse_source(src)
        self.assertEqual(str_lines, {"Start\n\nEnd\n": 1, "ABC": 6})

    def test_strings_multiline_escapes(self):
        src = """\
s = "Escaped\\n"
r = r"Raw\\n"
t = (
    "A\\n\\n"
    "B\\n\\n"
    "C\\n\\n"
    )
"""
        _, str_lines = export_pot._parse_source(src)
        self.assertEqual(str_lines, {"Escaped\n": 1, "Raw\\n": 2, "A\n\nB\n\nC\n\n": 4})


class TestModuleContext(tests.TestCase):
    """Checks for source context tracking objects"""

    def check_context(self, context, path, lineno):
        self.assertEqual((context.path, context.lineno), (path, lineno))

    def test___init__(self):
        context = export_pot._ModuleContext("one.py")
        self.check_context(context, "one.py", 1)
        context = export_pot._ModuleContext("two.py", 5)
        self.check_context(context, "two.py", 5)

    def test_from_class(self):
        """New context returned with lineno updated from class"""
        path = "cls.py"

        class A:
            pass

        class B:
            pass

        cls_lines = {"A": 5, "B": 7}
        context = export_pot._ModuleContext(path, _source_info=(cls_lines, {}))
        contextA = context.from_class(A)
        self.check_context(contextA, path, 5)
        contextB1 = context.from_class(B)
        self.check_context(contextB1, path, 7)
        contextB2 = contextA.from_class(B)
        self.check_context(contextB2, path, 7)
        self.check_context(context, path, 1)
        self.assertEqual("", self.get_log())

    def test_from_class_missing(self):
        """When class has no lineno the old context details are returned"""
        path = "cls_missing.py"

        class A:
            pass

        class M:
            pass

        context = export_pot._ModuleContext(path, 3, ({"A": 15}, {}))
        contextA = context.from_class(A)
        contextM1 = context.from_class(M)
        self.check_context(contextM1, path, 3)
        contextM2 = contextA.from_class(M)
        self.check_context(contextM2, path, 15)
        self.assertContainsRe(self.get_log(), "Definition of <.*M'> not found")

    def test_from_string(self):
        """New context returned with lineno updated from string"""
        path = "str.py"
        str_lines = {"one": 14, "two": 42}
        context = export_pot._ModuleContext(path, _source_info=({}, str_lines))
        context1 = context.from_string("one")
        self.check_context(context1, path, 14)
        context2A = context.from_string("two")
        self.check_context(context2A, path, 42)
        context2B = context1.from_string("two")
        self.check_context(context2B, path, 42)
        self.check_context(context, path, 1)
        self.assertEqual("", self.get_log())

    def test_from_string_missing(self):
        """When string has no lineno the old context details are returned"""
        path = "str_missing.py"
        context = export_pot._ModuleContext(path, 4, ({}, {"line\n": 21}))
        context1 = context.from_string("line\n")
        context2A = context.from_string("not there")
        self.check_context(context2A, path, 4)
        context2B = context1.from_string("not there")
        self.check_context(context2B, path, 21)
        self.assertContainsRe(self.get_log(), "String b?'not there' not found")


class TestWriteOption(tests.TestCase):
    """Tests for writing texts extracted from options in pot format"""

    def pot_from_option(self, opt, context=None, note="test"):
        sio = StringIO()
        exporter = export_pot._PotExporter(sio)
        if context is None:
            context = export_pot._ModuleContext("nowhere", 0)
        export_pot._write_option(exporter, context, opt, note)
        return sio.getvalue()

    def test_option_without_help(self):
        opt = option.Option("helpless")
        self.assertEqual("", self.pot_from_option(opt))

    def test_option_with_help(self):
        opt = option.Option("helpful", help="Info.")
        self.assertContainsString(
            self.pot_from_option(opt),
            "\n# help of 'helpful' test\nmsgid \"Info.\"\n",
        )

    def test_option_hidden(self):
        opt = option.Option("hidden", help="Unseen.", hidden=True)
        self.assertEqual("", self.pot_from_option(opt))

    def test_option_context_missing(self):
        context = export_pot._ModuleContext("remote.py", 3)
        opt = option.Option("metaphor", help="Not a literal in the source.")
        self.assertContainsString(
            self.pot_from_option(opt, context),
            "#: remote.py:3\n# help of 'metaphor' test\n",
        )

    def test_option_context_string(self):
        s = "Literally."
        context = export_pot._ModuleContext("local.py", 3, ({}, {s: 17}))
        opt = option.Option("example", help=s)
        self.assertContainsString(
            self.pot_from_option(opt, context),
            "#: local.py:17\n# help of 'example' test\n",
        )

    def test_registry_option_title(self):
        opt = option.RegistryOption.from_kwargs(
            "group", help="Pick one.", title="Choose!"
        )
        pot = self.pot_from_option(opt)
        self.assertContainsString(pot, "\n# title of 'group' test\nmsgid \"Choose!\"\n")
        self.assertContainsString(
            pot, "\n# help of 'group' test\nmsgid \"Pick one.\"\n"
        )

    def test_registry_option_title_context_missing(self):
        context = export_pot._ModuleContext("theory.py", 3)
        opt = option.RegistryOption.from_kwargs("abstract", title="Unfounded!")
        self.assertContainsString(
            self.pot_from_option(opt, context),
            "#: theory.py:3\n# title of 'abstract' test\n",
        )

    def test_registry_option_title_context_string(self):
        s = "Grounded!"
        context = export_pot._ModuleContext("practice.py", 3, ({}, {s: 144}))
        opt = option.RegistryOption.from_kwargs("concrete", title=s)
        self.assertContainsString(
            self.pot_from_option(opt, context),
            "#: practice.py:144\n# title of 'concrete' test\n",
        )

    def test_registry_option_value_switches(self):
        opt = option.RegistryOption.from_kwargs(
            "switch",
            help="Flip one.",
            value_switches=True,
            enum_switch=False,
            red="Big.",
            green="Small.",
        )
        pot = self.pot_from_option(opt)
        self.assertContainsString(
            pot, "\n# help of 'switch' test\nmsgid \"Flip one.\"\n"
        )
        self.assertContainsString(
            pot, "\n# help of 'switch=red' test\nmsgid \"Big.\"\n"
        )
        self.assertContainsString(
            pot, "\n# help of 'switch=green' test\nmsgid \"Small.\"\n"
        )

    def test_registry_option_value_switches_hidden(self):
        reg = registry.Registry()

        class Hider:
            hidden = True

        reg.register("new", 1, "Current.")
        reg.register("old", 0, "Legacy.", info=Hider())
        opt = option.RegistryOption(
            "protocol", "Talking.", reg, value_switches=True, enum_switch=False
        )
        pot = self.pot_from_option(opt)
        self.assertContainsString(
            pot, "\n# help of 'protocol' test\nmsgid \"Talking.\"\n"
        )
        self.assertContainsString(
            pot, "\n# help of 'protocol=new' test\nmsgid \"Current.\"\n"
        )
        self.assertNotContainsString(pot, "'protocol=old'")


class TestPotExporter(tests.TestCase):
    """Test for logic specific to the _PotExporter class"""

    # This test duplicates test_duplicates below
    def test_duplicates(self):
        exporter = export_pot._PotExporter(StringIO())
        context = export_pot._ModuleContext("mod.py", 1)
        exporter.poentry_in_context(context, "Common line.")
        context.lineno = 3
        exporter.poentry_in_context(context, "Common line.")
        self.assertEqual(1, exporter.outf.getvalue().count("Common line."))

    def test_duplicates_included(self):
        exporter = export_pot._PotExporter(StringIO(), True)
        context = export_pot._ModuleContext("mod.py", 1)
        exporter.poentry_in_context(context, "Common line.")
        context.lineno = 3
        exporter.poentry_in_context(context, "Common line.")
        self.assertEqual(2, exporter.outf.getvalue().count("Common line."))


class PoEntryTestCase(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.exporter = export_pot._PotExporter(StringIO())

    def check_output(self, expected):
        self.assertEqual(self.exporter.outf.getvalue(), textwrap.dedent(expected))


class TestPoEntry(PoEntryTestCase):
    def test_simple(self):
        self.exporter.poentry("dummy", 1, "spam")
        self.exporter.poentry("dummy", 2, "ham", "EGG")
        self.check_output("""\
                #: dummy:1
                msgid "spam"
                msgstr ""

                #: dummy:2
                # EGG
                msgid "ham"
                msgstr ""

                """)

    def test_duplicate(self):
        self.exporter.poentry("dummy", 1, "spam")
        # This should be ignored.
        self.exporter.poentry("dummy", 2, "spam", "EGG")

        self.check_output("""\
                #: dummy:1
                msgid "spam"
                msgstr ""\n
                """)


class TestPoentryPerPergraph(PoEntryTestCase):
    def test_single(self):
        self.exporter.poentry_per_paragraph("dummy", 10, """foo\nbar\nbaz\n""")
        self.check_output("""\
                #: dummy:10
                msgid ""
                "foo\\n"
                "bar\\n"
                "baz\\n"
                msgstr ""\n
                """)

    def test_multi(self):
        self.exporter.poentry_per_paragraph(
            "dummy", 10, """spam\nham\negg\n\nSPAM\nHAM\nEGG\n"""
        )
        self.check_output("""\
                #: dummy:10
                msgid ""
                "spam\\n"
                "ham\\n"
                "egg"
                msgstr ""

                #: dummy:14
                msgid ""
                "SPAM\\n"
                "HAM\\n"
                "EGG\\n"
                msgstr ""\n
                """)


class TestExportCommandHelp(PoEntryTestCase):
    def test_command_help(self):
        class cmd_Demo(commands.Command):
            __doc__ = """A sample command.

            :Usage:
                bzr demo

            :Examples:
                Example 1::

                    cmd arg1

            Blah Blah Blah
            """

        export_pot._write_command_help(self.exporter, cmd_Demo())
        result = self.exporter.outf.getvalue()
        # We don't care about filename and lineno here.
        result = re.sub(r"(?m)^#: [^\n]+\n", "", result)

        self.assertEqualDiff(
            'msgid "A sample command."\n'
            'msgstr ""\n'
            "\n"  # :Usage: should not be translated.
            'msgid ""\n'
            '":Examples:\\n"\n'
            '"    Example 1::"\n'
            'msgstr ""\n'
            "\n"
            'msgid "        cmd arg1"\n'
            'msgstr ""\n'
            "\n"
            'msgid "Blah Blah Blah"\n'
            'msgstr ""\n'
            "\n",
            result,
        )
