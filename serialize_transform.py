from bzrlib.util import bencode


def serialize(tt):
    new_name = dict((k, v.encode('utf-8')) for k, v in tt._new_name.items())
    attribs = {
        '_id_number': tt._id_number,
        '_new_name': new_name,
        '_new_id': tt._new_id,
        }
    return bencode.bencode(attribs)

def deserialize(tt, input):
    attribs = bencode.bdecode(input)
    tt._id_number = attribs['_id_number']
    tt._new_name = dict((k, v.decode('utf-8'))
                        for k, v in attribs['_new_name'].items())
    tt._new_id = attribs['_new_id']
    tt._r_new_id = dict((v, k) for k, v in tt._new_id.items())
