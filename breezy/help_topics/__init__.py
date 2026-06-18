# Copyright (C) 2006-2011 Canonical Ltd
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

"""A collection of extra help information for using brz.

Help topics are meant to be help for items that aren't commands, but will
help brz become fully learnable without referring to a tutorial.

Limited formatting of help text is permitted to make the text useful
both within the reference manual (reStructuredText) and on the screen.
The help text should be reStructuredText with formatting kept to a
minimum and, in particular, no headings. The onscreen renderer applies
the following simple rules before rendering the text:

    1. A '::' appearing on the end of a line is replaced with ':'.
    2. Lines starting with a ':' have it stripped.

These rules mean that literal blocks and field lists respectively can
be used in the help text, producing sensible input to a manual while
rendering on the screen naturally.
"""

__all__ = ["_format_see_also", "help_as_plain_text"]

from breezy import config
from breezy._cmd_rs import format_see_also as _format_see_also
from breezy._cmd_rs import help as _help_rs
from breezy._cmd_rs import help_as_plain_text

known_env_variables = _help_rs.known_env_variables
HelpTopicRegistry = _help_rs.HelpTopicRegistry

# Section identifiers (map topics to the right place in the manual)
SECT_COMMAND = "command"
SECT_CONCEPT = "concept"
SECT_HIDDEN = "hidden"
SECT_LIST = "list"
SECT_PLUGIN = "plugin"


topic_registry = HelpTopicRegistry()


# ----------------------------------------------------


def _help_on_topics(dummy):
    """Write out the help for topics to outfile."""
    topics = topic_registry.keys()
    lmax = max(len(topic) for topic in topics)

    out = []
    for topic in topics:
        summary = topic_registry.get_summary(topic)
        out.append("%-*s %s\n" % (lmax, topic, summary))
    return "".join(out)


def _help_on_revisionspec(name):
    """Generate the help for revision specs."""
    import re

    import breezy.revisionspec

    out = []
    out.append(
        """Revision Identifiers

A revision identifier refers to a specific state of a branch's history.  It
can be expressed in several ways.  It can begin with a keyword to
unambiguously specify a given lookup type; some examples are 'last:1',
'before:yesterday' and 'submit:'.

Alternately, it can be given without a keyword, in which case it will be
checked as a revision number, a tag, a revision id, a date specification, or a
branch specification, in that order.  For example, 'date:today' could be
written as simply 'today', though if you have a tag called 'today' that will
be found first.

If 'REV1' and 'REV2' are revision identifiers, then 'REV1..REV2' denotes a
revision range. Examples: '3647..3649', 'date:yesterday..-1' and
'branch:/path/to/branch1/..branch:/branch2' (note that there are no quotes or
spaces around the '..').

Ranges are interpreted differently by different commands. To the "log" command,
a range is a sequence of log messages, but to the "diff" command, the range
denotes a change between revisions (and not a sequence of changes).  In
addition, "log" considers a closed range whereas "diff" and "merge" consider it
to be open-ended, that is, they include one end but not the other.  For example:
"brz log -r 3647..3649" shows the messages of revisions 3647, 3648 and 3649,
while "brz diff -r 3647..3649" includes the changes done in revisions 3648 and
3649, but not 3647.

The keywords used as revision selection methods are the following:
"""
    )
    details = []
    details.append("\nIn addition, plugins can provide other keywords.")
    details.append("\nA detailed description of each keyword is given below.\n")

    # The help text is indented 4 spaces - this re cleans that up below
    re.compile(r"^    ", re.MULTILINE)
    for _prefix, i in breezy.revisionspec.revspec_registry.iteritems():
        doc = i.help_txt
        if doc == breezy.revisionspec.RevisionSpec.help_txt:
            summary = "N/A"
            doc = summary + "\n"
        else:
            # Extract out the top line summary from the body and
            # clean-up the unwanted whitespace
            summary, doc = doc.split("\n", 1)
            # doc = indent_re.sub('', doc)
            while doc[-2:] == "\n\n" or doc[-1:] == " ":
                doc = doc[:-1]

        # Note: The leading : here are HACKs to get reStructuredText
        # 'field' formatting - we know that the prefix ends in a ':'.
        out.append(f":{i.prefix}\n\t{summary}")
        details.append(f":{i.prefix}\n{doc}")

    return "\n".join(out + details)


def _help_on_transport(name):
    import textwrap

    from breezy.transport import transport_list_registry

    def add_string(proto, help, maxl, prefix_width=20):
        help_lines = textwrap.wrap(help, maxl - prefix_width, break_long_words=False)
        line_with_indent = "\n" + " " * prefix_width
        help_text = line_with_indent.join(help_lines)
        return "%-20s%s\n" % (proto, help_text)

    def key_func(a):
        return a[: a.rfind("://")]

    protl = []
    decl = []
    protos = transport_list_registry.keys()
    protos.sort(key=key_func)
    for proto in protos:
        shorthelp = transport_list_registry.get_help(proto)
        if not shorthelp:
            continue
        if proto.endswith("://"):
            protl.append(add_string(proto, shorthelp, 79))
        else:
            decl.append(add_string(proto, shorthelp, 79))

    out = "URL Identifiers\n\n" + "Supported URL prefixes::\n\n  " + "  ".join(protl)

    if len(decl):
        out += "\nSupported modifiers::\n\n  " + "  ".join(decl)

    out += """\
\nBreezy supports all of the standard parts within the URL::

  <protocol>://[user[:password]@]host[:port]/[path]

allowing URLs such as::

  http://brzuser:BadPass@brz.example.com:8080/brz/trunk

For brz+ssh:// and sftp:// URLs, Breezy also supports paths that begin
with '~' as meaning that the rest of the path should be interpreted
relative to the remote user's home directory.  For example if the user
``remote`` has a  home directory of ``/home/remote`` on the server
shell.example.com, then::

  brz+ssh://remote@shell.example.com/~/myproject/trunk

would refer to ``/home/remote/myproject/trunk``.

Many commands that accept URLs also accept location aliases too.
See :doc:`location-alias-help` and :doc:`url-special-chars-help`.
"""

    return out


# Register help topics
topic_registry.register(
    "revisionspec", _help_on_revisionspec, "Explain how to use --revision"
)
topic_registry.register("topics", _help_on_topics, "Topics list", SECT_HIDDEN)


def get_current_formats_topic(topic):
    from breezy import controldir

    return "Current Storage Formats\n\n" + controldir.format_registry.help_topic(topic)


def get_other_formats_topic(topic):
    from breezy import controldir

    return "Other Storage Formats\n\n" + controldir.format_registry.help_topic(topic)


topic_registry.register(
    "current-formats", get_current_formats_topic, "Current storage formats"
)
topic_registry.register(
    "other-formats",
    get_other_formats_topic,
    "Experimental and deprecated storage formats",
)
topic_registry.register("urlspec", _help_on_transport, "Supported transport protocols")

topic_registry.register_lazy(
    "hooks",
    "breezy.hooks",
    "hooks_help_text",
    "Points at which custom processing can be added",
)
topic_registry.register_lazy(
    "location-alias",
    "breezy.directory_service",
    "AliasDirectory.help_text",
    "Aliases for remembered locations",
)


# Register concept topics.
# Note that we might choose to remove these from the online help in the
# future or implement them via loading content from files. In the meantime,
# please keep them concise.


class HelpTopicIndex:
    """A index for brz help that returns topics."""

    def __init__(self):
        self.prefix = ""

    def get_topics(self, topic):
        """Search for topic in the HelpTopicRegistry.

        :param topic: A topic to search for. None is treated as 'basic'.
        :return: A list which is either empty or contains a single
            RegisteredTopic entry.
        """
        if topic is None:
            topic = "basic"
        topic = topic_registry.get(topic)
        if topic:
            return [topic]
        else:
            return []


class ConfigOptionHelpIndex:
    """A help index that returns help topics for config options."""

    def __init__(self):
        self.prefix = "configuration/"

    def get_topics(self, topic):
        """Search for topic in the registered config options.

        :param topic: A topic to search for.
        :return: A list which is either empty or contains a single
            config.Option entry.
        """
        if topic is None:
            return []
        elif topic.startswith(self.prefix):
            topic = topic[len(self.prefix) :]
        if topic in config.option_registry:
            return [config.option_registry.get(topic)]
        else:
            return []
