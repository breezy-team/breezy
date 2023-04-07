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
    result.pop();
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
    result.pop();
    result.iter().map(|b| if *b == 0x0A { b'_'} else { *b }).collect()
}

pub fn bytes_to_text_key(data: &[u8]) -> Result<(&[u8], &[u8]), String> {
    let sections: Vec<&[u8]> = data.split(|&byte| byte == b'\n').collect();

    let delimiter_position = sections[0]
        .windows(2)
        .position(|window| window == b": ");

    if delimiter_position.is_none() {
        return Err("Invalid key file".to_string());
    }

    let (_kind, file_id) = sections[0].split_at(delimiter_position.unwrap() + 2);

    Ok((file_id, sections[3]))
}
