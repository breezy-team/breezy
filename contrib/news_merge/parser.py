

def simple_parse(content):
    """Returns blocks, where each block is a 2-tuple (kind, text)."""
    blocks = content.split('\n\n')
    for block in blocks:
        if block.startswith('###'):
            # First line is ###...: Top heading
            yield 'heading', block
            continue
        last_line = block.rsplit('\n', 1)[-1]
        if last_line.startswith('###'):
            # last line is ###...: 2nd-level heading
            yield 'release', block
        elif last_line.startswith('***'):
            # last line is ***...: 3rd-level heading
            yield 'section', block
        elif block.startswith('* '):
            # bullet
            yield 'bullet', block
        elif block.strip() == '':
            # empty
            yield 'empty', block
        else:
            # plain text
            yield 'text', block


if __name__ == '__main__':
    import sys
    content = open(sys.argv[1], 'rb').read()
    for result in simple_parse(content):
        print result
