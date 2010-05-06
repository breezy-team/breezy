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

    # Sphinx and texinfo doesn't use the same names for the section levels,
    # since this can be confusing, here are the correspondances (sphinx ->
    # texinfo).
    # part -> chapter
    # chapter -> section
    # section -> subsection
    # subsection -> subsubsection
    # Additionally, sphinx defines subsubsections and paragraphs
    section_names = ['chapter', 'section', 'subsection', 'subsubsection']
    """texinfo section names differ from the sphinx ones.

    Since this can be confusing, the correspondences are shown below
    (shpinx -> texinfo):
    part       -> chapter
    chapter    -> section
    section    -> subsection
    subsection -> subsubsection

    Additionally, sphinx defines subsubsections and paragraphs.
    """

    def __init__(self, document, builder):
        nodes.NodeVisitor.__init__(self, document)
        self.chunks = []
        # toctree uses some nodes for different purposes (namely:
        # caompact_paragraph, bullet_list, reference, list_item) that needs to
        # know when they are proessing a toctree. The following attributes take
        # care of the needs.
        self.in_toctree = False
        self.toctree_current_ref = None
        # sections can be embedded and produce different directives depending
        # on the depth.
        self.section_level = -1
        # The title text is in a Text node that shouldn't be output literally
        self.in_title = False
        # Tables has some specific nodes but need more help
        self.in_table = False
        self.tab_nb_cols = None
        self.tab_item_cmd = None
        self.tab_tab_cmd = None
        self.tab_entry_num = None

    def add_text(self, text):
        self.chunks.append(text)

    # The whole document

    def visit_document(self, node):
        # The debug killer trick
        # print node.pformat()
        pass

    def depart_document(self, node):
        self.body = ''.join(chunk for chunk in self.chunks)

    # Layout

    def visit_section(self, node):
        self.section_level += 1

    def depart_section(self, node):
        self.section_level -= 1

    def visit_topic(self, node):
        pass

    def depart_topic(self, node):
        pass

    def visit_paragraph(self, node):
        pass

    def depart_paragraph(self, node):
        if not self.in_table:
            # End the paragraph with a new line and leave a blank line after
            # it.
            self.add_text('\n\n')

    def visit_compact_paragraph(self, node):
        if node.has_key('toctree'):
            self.in_toctree = True
            self.add_text('@menu\n')
        elif self.in_toctree:
            self.toctree_current_ref = None

    def depart_compact_paragraph(self, node):
        if node.has_key('toctree'):
            self.add_text('@end menu\n')
            self.in_toctree = False
        elif self.in_toctree:
            # * FIRST-ENTRY-NAME:(FILENAME)NODENAME.     DESCRIPTION
            entry_name = node.astext()
            # XXX: the file name should probably be adjusted to the targeted
            # info file name
            file_name = self.toctree_current_ref
            node_name = entry_name
            description = ''
            # XXX: What if :maxdepth: is not 1 ?
            self.add_text('* %s:(%s)%s. %s\n' % (entry_name, file_name,
                                                 node_name, description))
            self.toctree_current_ref = None
        else:
            # End the paragraph with a new line and leave a blank line after it.
            self.add_text('\n\n')

    def visit_literal_block(self, node):
        self.add_text('@samp{')

    def depart_literal_block(self, node):
        self.add_text('}\n')

    def visit_block_quote(self, node):
        pass

    def depart_block_quote(self, node):
        pass

    def visit_note(self, node):
        pass

    def depart_warning(self, node):
        pass

    def visit_warning(self, node):
        pass

    def depart_note(self, node):
        pass

    def visit_footnote(self, node):
        pass

    def depart_footnote(self, node):
        pass

    def visit_comment(self, node):
        raise nodes.SkipNode

    # Document attributes

    def visit_title(self, node):
        self.in_title = True
        try:
            section_name = self.section_names[self.section_level]
        except IndexError:
            # Just use @heading, it's not numbered anyway
            section_name = 'heading'
        self.add_text('@%s %s\n' % (section_name, node.astext()))

    def depart_title(self, node):
        self.in_title = False

    def visit_label(self, node):
        raise nodes.SkipNode

    def visit_substitution_definition(self, node):
        raise nodes.SkipNode

    # Plain text

    def visit_Text(self, node):
        pass

    def depart_Text(self, node):
        if not self.in_toctree and not self.in_title and not self.in_table:
            text = node.astext()
            if '@' in text:
                text = text.replace('@', '@@')
            if '{' in text:
                text = text.replace('{', '@{')
            if '}' in text:
                text = text.replace('}', '@}')
            self.add_text(text)

    # Styled text

    def visit_emphasis(self, node):
        self.add_text('@emph{')

    def depart_emphasis(self, node):
        self.add_text('}')

    def visit_strong(self, node):
        self.add_text('@strong{')

    def depart_strong(self, node):
        self.add_text('}')

    def visit_literal(self, node):
        self.add_text('@code{')

    def depart_literal(self, node):
        self.add_text('}')

    # Lists

    def visit_bullet_list(self, node):
        if self.in_toctree:
            pass
        else:
            self.add_text('@itemize @bullet\n')

    def depart_bullet_list(self, node):
        if self.in_toctree:
            pass
        else:
            self.add_text('@end itemize\n')

    def visit_enumerated_list(self, node):
        self.add_text('@enumerate\n')

    def depart_enumerated_list(self, node):
        self.add_text('@end enumerate\n')

    def visit_definition_list(self, node):
        pass

    def depart_definition_list(self, node):
        pass

    def visit_definition_list_item(self, node):
        pass

    def depart_definition_list_item(self, node):
        pass

    def visit_term(self, node):
        pass

    def depart_term(self, node):
        pass

    def visit_definition(self, node):
        pass

    def depart_definition(self, node):
        pass

    def visit_field_list(self, node):
        pass
    def depart_field_list(self, node):
        pass

    def visit_field(self, node):
        pass
    def depart_field(self, node):
        pass

    def visit_field_name(self, node):
        pass

    def depart_field_name(self, node):
        pass

    def visit_field_body(self, node):
        pass

    def depart_field_body(self, node):
        pass

    def visit_list_item(self, node):
        if not self.in_toctree:
            self.add_text('@item\n')

    def depart_list_item(self, node):
        # The item contains a paragraph which already ends with a blank line.
        pass

    def visit_option_list(self, node):
        pass

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
        self.in_table = True
        self.add_text('@multitable ')

    def depart_table(self, node):
        self.add_text('@end multitable\n')
        # Leave a blank line after a table
        self.add_text('\n')
        self.in_table = False

    def visit_tgroup(self, node):
        self.tab_nb_cols = node['cols']

    def depart_tgroup(self, node):
        self.tab_nb_cols = None

    def visit_colspec(self, node):
        self.add_text('{%s}' % ('x' * node['colwidth']))

    def depart_colspec(self, node):
        self.tab_nb_cols -= 1
        if self.tab_nb_cols == 0:
            self.add_text('\n') # end the @multitable line

    def visit_thead(self, node):
        self.tab_item_cmd = '@headitem %s '
        self.tab_tab_cmd = '@tab %s'

    def depart_thead(self, node):
        self.add_text('\n')
        self.tab_item_cmd = None
        self.tab_tab_cmd = None

    def visit_tbody(self, node):
        self.tab_item_cmd = '@item %s\n'
        self.tab_tab_cmd = '@tab %s\n'

    def depart_tbody(self, node):
        self.tab_item_cmd = None
        self.tab_tab_cmd = None

    def visit_row(self, node):
        self.tab_entry_num = 0

    def depart_row(self, node):
        self.tab_entry_num = None

    def visit_entry(self, node):
        if self.tab_entry_num == 0:
            cmd = self.tab_item_cmd
        else:
            cmd = self.tab_tab_cmd
        self.add_text(cmd % node.astext())
        self.tab_entry_num += 1

    def depart_entry(self, node):
        pass

    # References

    def visit_reference(self, node):
        uri = node.get('refuri', '')
        if self.in_toctree:
            self.toctree_current_ref = uri

    def depart_reference(self, node):
        pass

    def visit_footnote_reference(self, node):
        raise nodes.SkipNode

    def visit_citation_reference(self, node):
        raise nodes.SkipNode

    def visit_title_reference(self, node):
        pass

    def depart_title_reference(self, node):
        pass

    def visit_target(self, node):
        pass

    def depart_target(self, node):
        pass

    def visit_image(self, node):
        self.add_text(_('[image]'))
        raise nodes.SkipNode

