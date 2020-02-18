# Copyright (C) 2005-2011 Canonical Ltd
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

# TODO: Some way to get a list of external commands (defined by shell
# scripts) so that they can be included in the help listing as well.
# It should be enough to just list the plugin directory and look for
# executable files with reasonable names.

# TODO: `help commands --all` should show hidden commands

from . import (
    commands as _mod_commands,
    errors,
    help_topics,
    osutils,
    plugin,
    ui,
    utextwrap,
    )


class NoHelpTopic(errors.BzrError):

    _fmt = ("No help could be found for '%(topic)s'. "
            "Please use 'brz help topics' to obtain a list of topics.")

    def __init__(self, topic):
        self.topic = topic


def help(topic=None, outfile=None):
    """Write the help for the specific topic to outfile"""
    if outfile is None:
        outfile = ui.ui_factory.make_output_stream()

    indices = HelpIndices()

    alias = _mod_commands.get_alias(topic)
    try:
        topics = indices.search(topic)
        shadowed_terms = []
        for index, topic_obj in topics[1:]:
            shadowed_terms.append('%s%s' % (index.prefix,
                                            topic_obj.get_help_topic()))
        source = topics[0][1]
        outfile.write(source.get_help_text(shadowed_terms))
    except NoHelpTopic:
        if alias is None:
            raise

    if alias is not None:
        outfile.write("'brz %s' is an alias for 'brz %s'.\n" % (topic,
                                                                " ".join(alias)))


def help_commands(outfile=None):
    """List all commands"""
    if outfile is None:
        outfile = ui.ui_factory.make_output_stream()
    outfile.write(_help_commands_to_text('commands'))


def _help_commands_to_text(topic):
    """Generate the help text for the list of commands"""
    out = []
    if topic == 'hidden-commands':
        hidden = True
    else:
        hidden = False
    names = list(_mod_commands.all_command_names())
    commands = ((n, _mod_commands.get_cmd_object(n)) for n in names)
    shown_commands = [(n, o) for n, o in commands if o.hidden == hidden]
    max_name = max(len(n) for n, o in shown_commands)
    indent = ' ' * (max_name + 1)
    width = osutils.terminal_width()
    if width is None:
        width = osutils.default_terminal_width
    # we need one extra space for terminals that wrap on last char
    width = width - 1

    for cmd_name, cmd_object in sorted(shown_commands):
        plugin_name = cmd_object.plugin_name()
        if plugin_name is None:
            plugin_name = ''
        else:
            plugin_name = ' [%s]' % plugin_name

        cmd_help = cmd_object.help()
        if cmd_help:
            firstline = cmd_help.split('\n', 1)[0]
        else:
            firstline = ''
        helpstring = '%-*s %s%s' % (max_name, cmd_name, firstline, plugin_name)
        lines = utextwrap.wrap(
            helpstring, subsequent_indent=indent,
            width=width,
            break_long_words=False)
        for line in lines:
            out.append(line + '\n')
    return ''.join(out)


help_topics.topic_registry.register("commands",
                                    _help_commands_to_text,
                                    "Basic help for all commands",
                                    help_topics.SECT_HIDDEN)
help_topics.topic_registry.register("hidden-commands",
                                    _help_commands_to_text,
                                    "All hidden commands",
                                    help_topics.SECT_HIDDEN)


class HelpIndices(object):
    """Maintainer of help topics across multiple indices.

    It is currently separate to the HelpTopicRegistry because of its ordered
    nature, but possibly we should instead structure it as a search within the
    registry and add ordering and searching facilities to the registry. The
    registry would probably need to be restructured to support that cleanly
    which is why this has been implemented in parallel even though it does as a
    result permit searching for help in indices which are not discoverable via
    'help topics'.

    Each index has a unique prefix string, such as "commands", and contains
    help topics which can be listed or searched.
    """

    def __init__(self):
        self.search_path = [
            help_topics.HelpTopicIndex(),
            _mod_commands.HelpCommandIndex(),
            plugin.PluginsHelpIndex(),
            help_topics.ConfigOptionHelpIndex(),
            ]

    def _check_prefix_uniqueness(self):
        """Ensure that the index collection is able to differentiate safely."""
        prefixes = set()
        for index in self.search_path:
            prefix = index.prefix
            if prefix in prefixes:
                raise errors.DuplicateHelpPrefix(prefix)
            prefixes.add(prefix)

    def search(self, topic):
        """Search for topic across the help search path.

        :param topic: A string naming the help topic to search for.
        :raises: NoHelpTopic if none of the indexs in search_path have topic.
        :return: A list of HelpTopics which matched 'topic'.
        """
        self._check_prefix_uniqueness()
        result = []
        for index in self.search_path:
            result.extend([(index, _topic)
                           for _topic in index.get_topics(topic)])
        if not result:
            raise NoHelpTopic(topic)
        else:
            return result
