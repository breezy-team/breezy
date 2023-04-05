pub fn encode_base128_int(mut val: u128) -> Vec<u8> {
    let mut data = Vec::new();
    while val >= 0x80 {
        data.push(((val | 0x80) & 0xFF) as u8);
        val >>= 7;
    }
    data.push(val as u8);
    data
}

pub fn decode_base128_int(data: &[u8]) -> (u128, usize) {
    let mut offset = 0;
    let mut val: u128 = 0;
    let mut shift = 0;
    let mut bval = data[offset];
    while bval >= 0x80 {
        val |= ((bval & 0x7F) as u128) << shift;
        shift += 7;
        offset += 1;
        bval = data[offset];
    }
    val |= (bval as u128) << shift;
    offset += 1;
    (val, offset)
}
