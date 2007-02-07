# Copyright (C) 2006 Canonical Ltd
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

"""A collection of extra help information for using bzr.

Help topics are meant to be help for items that aren't commands, but will
help bzr become fully learnable without referring to a tutorial.
"""

from bzrlib import registry


class HelpTopicRegistry(registry.Registry):
    """A Registry customized for handling help topics."""

    def register(self, topic, detail, summary):
        """Register a new help topic.

        :param topic: Name of documentation entry
        :param detail: Function or string object providing detailed
            documentation for topic.  Function interface is detail(topic).
            This should return a text string of the detailed information.
        :param summary: String providing single-line documentation for topic.
        """
        # The detail is stored as the 'object' and the 
        super(HelpTopicRegistry, self).register(topic, detail, info=summary)

    def register_lazy(self, topic, module_name, member_name, summary):
        """Register a new help topic, and import the details on demand.

        :param topic: Name of documentation entry
        :param module_name: The module to find the detailed help.
        :param member_name: The member of the module to use for detailed help.
        :param summary: String providing single-line documentation for topic.
        """
        super(HelpTopicRegistry, self).register_lazy(topic, module_name,
                                                     member_name, info=summary)

    def get_detail(self, topic):
        """Get the detailed help on a given topic."""
        obj = self.get(topic)
        if callable(obj):
            return obj(topic)
        else:
            return obj

    def get_summary(self, topic):
        """Get the single line summary for the topic."""
        return self.get_info(topic)


topic_registry = HelpTopicRegistry()


#----------------------------------------------------

def _help_on_topics(dummy):
    """Write out the help for topics to outfile"""

    topics = topic_registry.keys()
    lmax = max(len(topic) for topic in topics)
        
    out = []
    for topic in topics:
        summary = topic_registry.get_summary(topic)
        out.append("%-*s %s\n" % (lmax, topic, summary))
    return ''.join(out)


def _help_on_revisionspec(name):
    """"Write the summary help for all documented topics to outfile."""
    import bzrlib.revisionspec

    out = []
    out.append("\nRevision prefix specifier:"
               "\n--------------------------\n")

    for i in bzrlib.revisionspec.SPEC_TYPES:
        doc = i.help_txt
        if doc == bzrlib.revisionspec.RevisionSpec.help_txt:
            doc = "N/A\n"
        while (doc[-2:] == '\n\n' or doc[-1:] == ' '):
            doc = doc[:-1]

        out.append("  %s %s\n\n" % (i.prefix, doc))

    return ''.join(out)


def _help_on_transport(name):
    from bzrlib.transport import (
        transport_list_registry,
    )
    import textwrap

    def add_string(proto, help, maxl, prefix_width=20):
       help_lines = textwrap.wrap(help, maxl - prefix_width)
       line_with_indent = '\n' + ' ' * prefix_width
       help_text = line_with_indent.join(help_lines)
       return "%-20s%s\n" % (proto, help_text)

    def sort_func(a,b):
        a1 = a[:a.rfind("://")]
        b1 = b[:b.rfind("://")]
        if a1>b1:
            return +1
        elif a1<b1:
            return -1
        else:
            return 0

    out = []
    protl = []
    decl = []
    protos = transport_list_registry.keys( )
    protos.sort(sort_func)
    for proto in protos:
        shorthelp = transport_list_registry.get_help(proto)
        if not shorthelp:
            continue
        if proto.endswith("://"):
            protl.extend(add_string(proto, shorthelp, 79))
        else:
            decl.extend(add_string(proto, shorthelp, 79))


    out = "\nSupported URL prefix\n--------------------\n" + \
            ''.join(protl)

    if len(decl):
        out += "\nSupported modifiers\n-------------------\n" + \
            ''.join(decl)

    return out


_basic_help= \
"""Bazaar -- a free distributed version-control tool
http://bazaar-vcs.org/

Basic commands:
  bzr init           makes this directory a versioned branch
  bzr branch         make a copy of another branch

  bzr add            make files or directories versioned
  bzr ignore         ignore a file or pattern
  bzr mv             move or rename a versioned file

  bzr status         summarize changes in working copy
  bzr diff           show detailed diffs

  bzr merge          pull in changes from another branch
  bzr commit         save some or all changes

  bzr log            show history of changes
  bzr check          validate storage

  bzr help init      more help on e.g. init command
  bzr help commands  list all commands
  bzr help topics    list all help topics
"""


_global_options =\
"""Global Options

These options may be used with any command, and may appear in front of any
command.  (e.g. "bzr --quiet help").

--quiet        Suppress informational output; only print errors and warnings
--version      Print the version number

--no-aliases   Do not process command aliases when running this command
--builtin      Use the built-in version of a command, not the plugin version.
               This does not suppress other plugin effects
--no-plugins   Do not process any plugins

-Derror        Instead of normal error handling, always print a traceback on
               error.
--profile      Profile execution using the hotshot profiler
--lsprof       Profile execution using the lsprof profiler
--lsprof-file  Profile execution using the lsprof profiler, and write the
               results to a specified file.

Note: --version must be supplied before any command.
"""


topic_registry.register("revisionspec", _help_on_revisionspec,
                        "Explain how to use --revision")
topic_registry.register('basic', _basic_help, "Basic commands")
topic_registry.register('topics', _help_on_topics, "Topics list")
def get_format_topic(topic):
    from bzrlib import bzrdir
    return bzrdir.format_registry.help_topic(topic)
topic_registry.register('formats', get_format_topic, 'Directory formats')
topic_registry.register('global-options', _global_options,
                        'Options that can be used with any command')
topic_registry.register('urlspec', _help_on_transport,
                        "Supported transport protocols")
