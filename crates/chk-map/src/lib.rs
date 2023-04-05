use crc32fast::Hasher;
use std::fmt::Write;

fn _crc32(bit: &[u8]) -> u32 {
    let mut hasher = Hasher::new();
    hasher.update(bit);
    hasher.finalize()
}

pub fn search_key_16(key: &[&[u8]]) -> Vec<u8> {
    let mut result = String::new();
    for bit in key {
        write!(&mut result, "{:08X}\x00", _crc32(bit)).unwrap();
    }
    result.as_bytes().to_vec()
}

pub fn search_key_255(key: &[&[u8]]) -> Vec<u8> {
    let mut result = vec![];
    for bit in key {
        let crc = _crc32(bit);
        let crc_bytes = crc.to_be_bytes();
        result.extend(&crc_bytes);
        result.push(0x00);
    }
    result.iter().map(|b| if *b == 0x0A { b'_'} else { *b }).collect()
}

pub fn bytes_to_text_key(data: &[u8]) -> (&[u8], &[u8]) {
    let sections: Vec<&[u8]> = data.split(|&byte| byte == b'\n').collect();

    let first_section: Vec<&[u8]> = sections[0].split(|&byte| byte == b':').collect();
    let file_id = first_section[1].split(|&byte| !byte.is_ascii_whitespace()).collect::<Vec<&[u8]>>()[0];

    let rev_id = sections[3];

    (file_id, rev_id)
}
