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

"""A sphinx/docutil writer producing texinfo output."""

from docutils import (
    nodes,
    writers,
    )

DEBUG = 0

class TexinfoWriter(writers.Writer):

    supported = ('texinfo',)
    settings_spec = ('No options here.', '', ())
    settings_defaults = {}

    output = None

    def __init__(self, builder):
        writers.Writer.__init__(self)
        self.builder = builder

    def translate(self):
        visitor = TexinfoTranslator(self.document, self.builder)
        self.document.walkabout(visitor)
        self.output = visitor.body


class TexinfoTranslator(nodes.NodeVisitor):

    section_names = ['chapter', 'section', 'subsection', 'subsubsection']
    """texinfo section names differ from the sphinx ones.

    Since this can be confusing, the correspondences are shown below
    (shpinx -> texinfo):
    part       -> chapter
    chapter    -> section
    section    -> subsection
    subsection -> subsubsection

    Additionally, sphinx defines subsubsections and paragraphs which are
    handled as @heading (unnumbered).
    """

    def __init__(self, document, builder):
        nodes.NodeVisitor.__init__(self, document)
        # toctree uses some nodes for different purposes (namely:
        # compact_paragraph, bullet_list) that needs to know when they are
        # proessing a toctree. The following attributes take care of the needs.
        self.in_toctree = False
        # sections can be embedded and produce different directives depending
        # on the depth.
        self.section_level = -1
        # By default paragraghs are separated by newlines, but there are some
        # exceptions that set it to '' for some subtrees instead
        self.paragraph_sep = '\n'

    # The whole document

    def visit_document(self, node):
        if DEBUG:
            import sys
            sys.stdout.write(node.pformat().encode('utf8'))
        set_item_list_collector(node, 'text')

    def depart_document(self, node):
        self.body = ''.join(node['text'])

    # Layout

    def visit_section(self, node):
        self.section_level += 1
        set_item_list_collector(node, 'text')

    def depart_section(self, node):
        try:
            section_name = self.section_names[self.section_level]
        except IndexError:
            # Just use @heading, it's not numbered anyway
            section_name = 'heading'
        section_cmd = '@%s %s\n' % (section_name, node['title'])
        text = ''.join(node['text'])
        node.parent.collect_text(section_cmd + text)
        self.section_level -= 1

    def visit_topic(self, node):
        pass

    def depart_topic(self, node):
        pass

    def visit_paragraph(self, node):
        set_item_list_collector(node, 'text')

    def depart_paragraph(self, node):
        # End the paragraph with a new line (or '' depending on the parent) and
        # leave a blank line after it.
        text = ''.join(node['text']) + self.paragraph_sep * 2
        node.parent.collect_text(text)

    def visit_compact_paragraph(self, node):
        set_item_list_collector(node, 'text')
        if node.has_key('toctree'):
            self.in_toctree = True
        elif self.in_toctree:
            set_item_collector(node, 'reference')

    def depart_compact_paragraph(self, node):
        if node.has_key('toctree'):
            node.parent.collect_text('@menu\n')
            node.parent.collect_text(''.join(node['text']))
            node.parent.collect_text('@end menu\n')
            self.in_toctree = False
        elif self.in_toctree:
            # * FIRST-ENTRY-NAME:(FILENAME)NODENAME.     DESCRIPTION
            # XXX: the file name should probably be adjusted to the targeted
            # info file name
            node_name, file_name, entry_name = node['reference']
            if not node_name:
                node_name = entry_name
            description = '' # We can't specify a description in rest AFAICS
            # XXX: What if :maxdepth: is not 1 ?
            text = '* %s: (%s)%s. %s\n' % (entry_name, file_name,
                                           node_name, description)
            node.parent.collect_text(text)
        else:
            # End the paragraph with a new line (or '' depending on the parent)
            # and leave a blank line after it.
            text = ''.join(node['text']) + self.paragraph_sep * 2
            node.parent.collect_text(text)

    def visit_literal_block(self, node):
        set_item_collector(node, 'text')

    def depart_literal_block(self, node):
        text = '@samp{%s}' % ''.join(node['text']) + self.paragraph_sep * 2
        node.parent.collect_text(text)

    def visit_block_quote(self, node):
        set_item_list_collector(node, 'text')

    def depart_block_quote(self, node):
        node.parent.collect_text('@example\n')
        node.parent.collect_text(''.join(node['text']))
        node.parent.collect_text('@end example\n\n')

    def visit_note(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_warning(self, node):
        pass

    def visit_warning(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_note(self, node):
        pass

    def visit_footnote(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_footnote(self, node):
        pass

    def visit_comment(self, node):
        raise nodes.SkipNode # Not implemented yet

    # Attributes

    def visit_title(self, node):
        set_item_collector(node, 'text')

    def depart_title(self, node):
        node.parent['title'] = node['text']

    def visit_label(self, node):
        raise nodes.SkipNode # Not implemented yet

    def visit_substitution_definition(self, node):
        raise nodes.SkipNode # Not implemented yet

    # Plain text

    def visit_Text(self, node):
        pass

    def depart_Text(self, node):
        text = node.astext()
        if '@' in text:
            text = text.replace('@', '@@')
        if '{' in text:
            text = text.replace('{', '@{')
        if '}' in text:
            text = text.replace('}', '@}')
        node.parent.collect_text(text)


    # Styled text

    def visit_emphasis(self, node):
        set_item_collector(node, 'text')

    def depart_emphasis(self, node):
        text = '@emph{%s}' % node['text']
        node.parent.collect_text(text)

    def visit_strong(self, node):
        set_item_collector(node, 'text')

    def depart_strong(self, node):
        text = '@strong{%s}' % node['text']
        node.parent.collect_text(text)

    def visit_literal(self, node):
        set_item_collector(node, 'text')

    def depart_literal(self, node):
        text = '@code{%s}' % node['text']
        node.parent.collect_text(text)

    # Lists

    def _decorate_list(self, item_list, collect, item_fmt='%s',
                       head=None, foot=None):
        if head is not None:
            collect(head)
        for item in item_list:
            collect(item_fmt % item)
        if foot is not None:
            collect(foot)

    def visit_bullet_list(self, node):
        set_item_list_collector(node, 'list_item')

    def depart_bullet_list(self, node):
        l = node['list_item']
        if self.in_toctree:
            self._decorate_list(node['list_item'], node.parent.collect_text)
        else:
            self._decorate_list(node['list_item'], node.parent.collect_text,
                                '@item\n%s',
                                # FIXME: Should respect the 'bullet' attribute
                                '@itemize @bullet\n', '@end itemize\n')

    def visit_enumerated_list(self, node):
        set_item_list_collector(node, 'list_item')

    def depart_enumerated_list(self, node):
        self._decorate_list(node['list_item'], node.parent.collect_text,
                            '@item\n%s',
                            '@enumerate\n', '@end enumerate\n')

    def visit_definition_list(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_definition_list(self, node):
        raise nodes.SkipNode # Not implemented yet

    def visit_definition_list_item(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_definition_list_item(self, node):
        pass

    def visit_term(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_term(self, node):
        pass

    def visit_definition(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_definition(self, node):
        pass

    def visit_field_list(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_field_list(self, node):
        pass

    def visit_field(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_field(self, node):
        pass

    def visit_field_name(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_field_name(self, node):
        pass

    def visit_field_body(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_field_body(self, node):
        pass

    def visit_list_item(self, node):
        set_item_list_collector(node, 'text')

    def depart_list_item(self, node):
        text = ''.join(node['text'])
        node.parent.collect_list_item(text)

    def visit_option_list(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_option_list(self, node):
        pass

    def visit_option_list_item(self, node):
        pass

    def depart_option_list_item(self, node):
        pass

    def visit_option_group(self, node):
        pass

    def depart_option_group(self, node):
        pass

    def visit_option(self, node):
        pass

    def depart_option(self, node):
        pass

    def visit_option_string(self, node):
        pass
    def depart_option_string(self, node):
        pass

    def visit_option_argument(self, node):
        pass

    def depart_option_argument(self, node):
        pass

    def visit_description(self, node):
        pass
    def depart_description(self, node):
        pass

    # Tables
    def visit_table(self, node):
        set_item_collector(node, 'table')

    def depart_table(self, node):
        node.parent.collect_text(node['table'])

    def visit_tgroup(self, node):
        set_item_list_collector(node, 'colspec')
        set_item_collector(node, 'head_entries')
        set_item_collector(node, 'body_rows')

    def depart_tgroup(self, node):
        header = []
        # The '@multitable {xxx}{xxx}' line
        self._decorate_list(node['colspec'], header.append,
                            '{%s}', '@multitable ', '\n')
        # The '@headitem xxx @tab yyy...' line
        head_entries = node['head_entries']
        if head_entries is not None:
            # Not all tables define titles for the columns... rest parser bug ?
            # FIXME: need a test
            self._decorate_list(head_entries[1:], header.append,
                                ' @tab %s',
                                '@headitem %s' % head_entries[0], '\n')
        header = ''.join(header)
        # The '@item xxx\n @tab yyy\n ...' lines
        body_rows = node['body_rows']
        rows = []
        for r in body_rows:
            self._decorate_list(r[1:], rows.append,
                                '@tab %s\n', '@item %s\n' % r[0])
        footer = '@end multitable\n'
        node.parent.collect_table(header + ''.join(rows) + footer)

    def visit_colspec(self, node):
        pass

    def depart_colspec(self, node):
        node.parent.collect_colspec('x' * node['colwidth'])

    def visit_thead(self, node):
        set_item_collector(node, 'row')

    def depart_thead(self, node):
        node.parent.collect_head_entries(node['row'])

    def visit_tbody(self, node):
        set_item_list_collector(node, 'row')

    def depart_tbody(self, node):
        node.parent.collect_body_rows(node['row'])

    def visit_row(self, node):
        set_item_list_collector(node, 'entry')

    def depart_row(self, node):
        node.parent.collect_row(node['entry'])

    def visit_entry(self, node):
        set_item_list_collector(node, 'text')
        node['par_sep_orig'] = self.paragraph_sep
        self.paragraph_sep = ''

    def depart_entry(self, node):
        node.parent.collect_entry(''.join(node['text']))
        self.paragraph_sep = node['par_sep_orig']

    # References

    def visit_reference(self, node):
        for c in node.children:
            if getattr(c, 'parent', None) is None:
                # Bug sphinx
                node.setup_child(c)
        set_item_collector(node, 'text')

    def depart_reference(self, node):
        collect = getattr(node.parent, 'collect_reference', None)
        if collect is not None:
            # FIXME: this handle only the toctree references so far.
            collect((node.get('anchorname', ''),
                     node.get('refuri', ''),
                     ''.join(node['text']),
                     ))

    def visit_footnote_reference(self, node):
        raise nodes.SkipNode # Not implemented yet

    def visit_citation_reference(self, node):
        raise nodes.SkipNode # Not implemented yet

    def visit_title_reference(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_title_reference(self, node):
        pass

    def visit_target(self, node):
        raise nodes.SkipNode # Not implemented yet

    def depart_target(self, node):
        pass

    def visit_image(self, node):
        raise nodes.SkipNode # Not implemented yet

# Helpers to collect data in parent node

def set_item_collector(node, name):
    node[name] = None
    def set_item(item):
        node[name] = item
    setattr(node, 'collect_' + name, set_item)


def set_item_list_collector(node, name, sep=''):
    node[name] = []
    node[name + '_sep'] = sep
    def append_item(item):
        node[name].append(item)
    setattr(node, 'collect_' + name, append_item)


