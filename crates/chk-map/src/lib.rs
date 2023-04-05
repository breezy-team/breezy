use crc32fast::Hasher;
use std::fmt::Write;

fn _crc32(bit: &[u8]) -> u32 {
    let mut hasher = Hasher::new();
    hasher.update(bit);
    hasher.finalize()
}

pub fn _search_key_16(key: &[&[u8]]) -> Vec<u8> {
    let mut result = String::new();
    for bit in key {
        write!(&mut result, "{:08X}\x00", _crc32(bit)).unwrap();
    }
    result.as_bytes().to_vec()
}

pub fn _search_key_255(key: &[&[u8]]) -> Vec<u8> {
    let mut result = vec![];
    for bit in key {
        let crc = _crc32(bit);
        let crc_bytes = crc.to_be_bytes();
        result.extend(&crc_bytes);
        result.push(0x00);
    }
    result.iter().map(|b| if *b == 0x0A { b'_'} else { *b }).collect()
}
