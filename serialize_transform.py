import os

from bzrlib import multiparent
from bzrlib.util import bencode


def get_parents_texts(tt, trans_id):
    return tuple(''.join(p) for p in get_parents_lines(tt, trans_id))


def get_parents_lines(tt, trans_id):
    file_id = tt.tree_file_id(trans_id)
    if file_id is None:
        return ()
    else:
        return (tt._tree.get_file(file_id).readlines(),)


def serialize(tt, serializer):
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
    yield serializer.bytes_record(bencode.bencode(attribs), (('attribs',),))
    for trans_id, kind in tt._new_contents.items():
        if kind == 'file':
            cur_file = open(tt._limbo_name(trans_id), 'rb')
            try:
                lines = cur_file.readlines()
            finally:
                cur_file.close()
            parents = get_parents_lines(tt, trans_id)
            mpdiff = multiparent.MultiParent.from_lines(lines, parents)
            content = ''.join(mpdiff.to_patch())
        if kind == 'directory':
            content = ''
        if kind == 'symlink':
            content = os.readlink(tt._limbo_name(trans_id))
        yield serializer.bytes_record(content, ((trans_id, kind),))


def deserialize(tt, records):
    names, content = records.next()
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
    for ((trans_id, kind),), content in records:
        if kind == 'file':
            mpdiff = multiparent.MultiParent.from_patch(content)
            lines = mpdiff.to_lines(get_parents_texts(tt, trans_id))
            tt.create_file(lines, trans_id)
        if kind == 'directory':
            tt.create_directory(trans_id)
        if kind == 'symlink':
            tt.create_symlink(content, trans_id)
