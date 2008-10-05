from bzrlib import pack
from bzrlib.util import bencode


def serialize(tt):
    new_name = dict((k, v.encode('utf-8')) for k, v in tt._new_name.items())
    new_executability = dict((k, int(v)) for k, v in
                             tt._new_executability.items())
    attribs = {
        '_id_number': tt._id_number,
        '_new_name': new_name,
        '_new_parent': tt._new_parent,
        '_new_executability': new_executability,
        '_new_id': tt._new_id,
        }
    serializer = pack.ContainerSerialiser()
    yield serializer.begin()
    yield serializer.bytes_record(bencode.bencode(attribs), (('attribs',),))
    for trans_id, kind in tt._new_contents.items():
        if kind == 'file':
            cur_file = open(tt._limbo_name(trans_id), 'rb')
            try:
                content = cur_file.read()
            finally:
                cur_file.close()
        if kind == 'directory':
            content = ''
        yield serializer.bytes_record(content, ((trans_id, kind),))
    yield serializer.end()


def deserialize(tt, input):
    parser = pack.ContainerPushParser()
    for bytes in input:
        parser.accept_bytes(bytes)
    iterator = iter(parser.read_pending_records())
    names, content = iterator.next()
    attribs = bencode.bdecode(content)
    tt._id_number = attribs['_id_number']
    tt._new_name = dict((k, v.decode('utf-8'))
                        for k, v in attribs['_new_name'].items())
    tt._new_parent = attribs['_new_parent']
    tt._new_executability = dict((k, bool(v)) for k, v in
        attribs['_new_executability'].items())
    tt._new_id = attribs['_new_id']
    tt._r_new_id = dict((v, k) for k, v in tt._new_id.items())
    for ((trans_id, kind),), content in iterator:
        if kind == 'file':
            tt.create_file(content, trans_id)
        if kind == 'directory':
            tt.create_directory(trans_id)
