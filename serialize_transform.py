import os

from bzrlib import pack
from bzrlib.util import bencode


def serialize(tt):
    new_name = dict((k, v.encode('utf-8')) for k, v in tt._new_name.items())
    new_executability = dict((k, int(v)) for k, v in
                             tt._new_executability.items())
    tree_path_ids = dict((k.encode('utf-8'), v)
                         for k, v in tt._tree_path_ids.items())
    attribs = {
        '_id_number': tt._id_number,
        '_new_name': new_name,
        '_new_parent': tt._new_parent,
        '_new_executability': new_executability,
        '_new_id': tt._new_id,
        '_tree_path_ids': tree_path_ids,
        '_removed_id': list(tt._removed_id),
        '_removed_contents': list(tt._removed_contents),
        '_non_present_ids': tt._non_present_ids,
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
        if kind == 'symlink':
            content = os.readlink(tt._limbo_name(trans_id))
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
    tt._tree_path_ids = {}
    tt._tree_id_paths = {}
    for bytepath, trans_id in attribs['_tree_path_ids'].items():
        path = bytepath.decode('utf-8')
        tt._tree_path_ids[path] = trans_id
        tt._tree_id_paths[trans_id] = path
    tt._removed_id = set(attribs['_removed_id'])
    tt._removed_contents = set(attribs['_removed_contents'])
    tt._non_present_ids = attribs['_non_present_ids']
    for ((trans_id, kind),), content in iterator:
        if kind == 'file':
            tt.create_file(content, trans_id)
        if kind == 'directory':
            tt.create_directory(trans_id)
        if kind == 'symlink':
            tt.create_symlink(content, trans_id)
