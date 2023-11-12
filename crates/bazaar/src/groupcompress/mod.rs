pub mod delta;
pub mod line_delta;
use sha1::{Digest as _, Sha1};

lazy_static::lazy_static! {
    pub static ref NULL_SHA1: Vec<u8> = format!("{:x}", Sha1::new().finalize()).as_bytes().to_vec();
}

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

pub type CopyInstruction = (usize, usize, usize);

pub fn decode_copy_instruction(
    data: &[u8],
    cmd: u8,
    pos: usize,
) -> Result<CopyInstruction, String> {
    if cmd & 0x80 != 0x80 {
        return Err("copy instructions must have bit 0x80 set".to_string());
    }
    let mut offset = 0;
    let mut length = 0;
    let mut new_pos = pos;

    if cmd & 0x01 != 0 {
        offset = data[new_pos] as usize;
        new_pos += 1;
    }
    if cmd & 0x02 != 0 {
        offset |= (data[new_pos] as usize) << 8;
        new_pos += 1;
    }
    if cmd & 0x04 != 0 {
        offset |= (data[new_pos] as usize) << 16;
        new_pos += 1;
    }
    if cmd & 0x08 != 0 {
        offset |= (data[new_pos] as usize) << 24;
        new_pos += 1;
    }
    if cmd & 0x10 != 0 {
        length = data[new_pos] as usize;
        new_pos += 1;
    }
    if cmd & 0x20 != 0 {
        length |= (data[new_pos] as usize) << 8;
        new_pos += 1;
    }
    if cmd & 0x40 != 0 {
        length |= (data[new_pos] as usize) << 16;
        new_pos += 1;
    }
    if length == 0 {
        length = 65536;
    }

    Ok((offset, length, new_pos))
}

pub fn apply_delta(basis: &[u8], delta: &[u8]) -> Result<Vec<u8>, String> {
    let (target_length, mut pos) = decode_base128_int(delta);
    let mut lines = Vec::new();
    let len_delta = delta.len();

    while pos < len_delta {
        let cmd = delta[pos];
        pos += 1;

        if cmd & 0x80 != 0 {
            let (offset, length, new_pos) = decode_copy_instruction(delta, cmd, pos)?;
            pos = new_pos;
            let last = offset + length;
            if last > basis.len() {
                return Err("data would copy bytes past the end of source".to_string());
            }
            lines.extend_from_slice(&basis[offset..last]);
        } else {
            if cmd == 0 {
                return Err("Command == 0 not supported yet".to_string());
            }
            lines.extend_from_slice(&delta[pos..pos + cmd as usize]);
            pos += cmd as usize;
        }
    }

    if lines.len() != target_length as usize {
        return Err(format!(
            "Delta claimed to be {} long, but ended up {} long",
            target_length,
            lines.len()
        ));
    }

    Ok(lines)
}

pub fn apply_delta_to_source(
    source: &[u8],
    delta_start: usize,
    delta_end: usize,
) -> Result<Vec<u8>, String> {
    let source_size = source.len();
    if delta_start >= source_size {
        return Err("delta starts after source".to_string());
    }
    if delta_end > source_size {
        return Err("delta ends after source".to_string());
    }
    if delta_start >= delta_end {
        return Err("delta starts after it ends".to_string());
    }
    let delta_bytes = &source[delta_start..delta_end];
    apply_delta(source, delta_bytes)
}

pub fn encode_copy_instruction(mut offset: usize, mut length: usize) -> Vec<u8> {
    // Convert this offset into a control code and bytes.
    let mut copy_command: u8 = 0x80;
    let mut copy_bytes: Vec<u8> = vec![];

    for copy_bit in [0x01, 0x02, 0x04, 0x08].iter() {
        let base_byte = (offset & 0xff) as u8;
        if base_byte != 0 {
            copy_command |= *copy_bit;
            copy_bytes.push(base_byte);
        }
        offset >>= 8;
    }
    if length > 0x10000 {
        panic!("we don't emit copy records for lengths > 64KiB");
    }
    if length == 0 {
        panic!("We cannot emit a copy of length 0");
    }
    if length != 0x10000 {
        // A copy of length exactly 64*1024 == 0x10000 is sent as a length of 0,
        // since that saves bytes for large chained copies
        for copy_bit in [0x10, 0x20].iter() {
            let base_byte = (length & 0xff) as u8;
            if base_byte != 0 {
                copy_command |= *copy_bit;
                copy_bytes.push(base_byte);
            }
            length >>= 8;
        }
    }
    copy_bytes.insert(0, copy_command);
    copy_bytes
}

#[cfg(test)]
mod test_copy_instruction {
    fn assert_encode(expected: &[u8], offset: usize, length: usize) {
        let data = super::encode_copy_instruction(offset, length);
        assert_eq!(expected, data);
    }

    fn assert_decode(
        exp_offset: usize,
        exp_length: usize,
        exp_newpos: usize,
        data: &[u8],
        mut pos: usize,
    ) {
        let cmd = data[pos];
        pos += 1;
        let out = super::decode_copy_instruction(data, cmd, pos).unwrap();
        assert_eq!((exp_offset, exp_length, exp_newpos), out);
    }

    #[test]
    fn test_encode_no_length() {
        assert_encode(b"\x80", 0, 64 * 1024);
        assert_encode(b"\x81\x01", 1, 64 * 1024);
        assert_encode(b"\x81\x0a", 10, 64 * 1024);
        assert_encode(b"\x81\xff", 255, 64 * 1024);
        assert_encode(b"\x82\x01", 256, 64 * 1024);
        assert_encode(b"\x83\x01\x01", 257, 64 * 1024);
        assert_encode(b"\x8F\xff\xff\xff\xff", 0xFFFFFFFF, 64 * 1024);
        assert_encode(b"\x8E\xff\xff\xff", 0xFFFFFF00, 64 * 1024);
        assert_encode(b"\x8D\xff\xff\xff", 0xFFFF00FF, 64 * 1024);
        assert_encode(b"\x8B\xff\xff\xff", 0xFF00FFFF, 64 * 1024);
        assert_encode(b"\x87\xff\xff\xff", 0x00FFFFFF, 64 * 1024);
        assert_encode(b"\x8F\x04\x03\x02\x01", 0x01020304, 64 * 1024);
    }

    #[test]
    fn test_encode_no_offset() {
        assert_encode(b"\x90\x01", 0, 1);
        assert_encode(b"\x90\x0a", 0, 10);
        assert_encode(b"\x90\xff", 0, 255);
        assert_encode(b"\xA0\x01", 0, 256);
        assert_encode(b"\xB0\x01\x01", 0, 257);
        assert_encode(b"\xB0\xff\xff", 0, 0xFFFF);
        // Special case, if copy == 64KiB, then we store exactly 0
        // Note that this puns with a copy of exactly 0 bytes, but we don't care
        // about that, as we would never actually copy 0 bytes
        assert_encode(b"\x80", 0, 64 * 1024)
    }

    #[test]
    fn test_encode() {
        assert_encode(b"\x91\x01\x01", 1, 1);
        assert_encode(b"\x91\x09\x0a", 9, 10);
        assert_encode(b"\x91\xfe\xff", 254, 255);
        assert_encode(b"\xA2\x02\x01", 512, 256);
        assert_encode(b"\xB3\x02\x01\x01\x01", 258, 257);
        assert_encode(b"\xB0\x01\x01", 0, 257);
        // Special case, if copy == 64KiB, then we store exactly 0
        // Note that this puns with a copy of exactly 0 bytes, but we don't care
        // about that, as we would never actually copy 0 bytes
        assert_encode(b"\x81\x0a", 10, 64 * 1024);
    }

    #[test]
    fn test_decode_no_length() {
        // If length is 0, it is interpreted as 64KiB
        // The shortest possible instruction is a copy of 64KiB from offset 0
        assert_decode(0, 65536, 1, b"\x80", 0);
        assert_decode(1, 65536, 2, b"\x81\x01", 0);
        assert_decode(10, 65536, 2, b"\x81\x0a", 0);
        assert_decode(255, 65536, 2, b"\x81\xff", 0);
        assert_decode(256, 65536, 2, b"\x82\x01", 0);
        assert_decode(257, 65536, 3, b"\x83\x01\x01", 0);
        assert_decode(0xFFFFFFFF, 65536, 5, b"\x8F\xff\xff\xff\xff", 0);
        assert_decode(0xFFFFFF00, 65536, 4, b"\x8E\xff\xff\xff", 0);
        assert_decode(0xFFFF00FF, 65536, 4, b"\x8D\xff\xff\xff", 0);
        assert_decode(0xFF00FFFF, 65536, 4, b"\x8B\xff\xff\xff", 0);
        assert_decode(0x00FFFFFF, 65536, 4, b"\x87\xff\xff\xff", 0);
        assert_decode(0x01020304, 65536, 5, b"\x8F\x04\x03\x02\x01", 0);
    }

    #[test]
    fn test_decode_no_offset() {
        assert_decode(0, 1, 2, b"\x90\x01", 0);
        assert_decode(0, 10, 2, b"\x90\x0a", 0);
        assert_decode(0, 255, 2, b"\x90\xff", 0);
        assert_decode(0, 256, 2, b"\xA0\x01", 0);
        assert_decode(0, 257, 3, b"\xB0\x01\x01", 0);
        assert_decode(0, 65535, 3, b"\xB0\xff\xff", 0);
        // Special case, if copy == 64KiB, then we store exactly 0
        // Note that this puns with a copy of exactly 0 bytes, but we don't care
        // about that, as we would never actually copy 0 bytes
        assert_decode(0, 65536, 1, b"\x80", 0);
    }

    #[test]
    fn test_decode() {
        assert_decode(1, 1, 3, b"\x91\x01\x01", 0);
        assert_decode(9, 10, 3, b"\x91\x09\x0a", 0);
        assert_decode(254, 255, 3, b"\x91\xfe\xff", 0);
        assert_decode(512, 256, 3, b"\xA2\x02\x01", 0);
        assert_decode(258, 257, 5, b"\xB3\x02\x01\x01\x01", 0);
        assert_decode(0, 257, 3, b"\xB0\x01\x01", 0);
    }

    #[test]
    fn test_decode_not_start() {
        assert_decode(1, 1, 6, b"abc\x91\x01\x01def", 3);
        assert_decode(9, 10, 5, b"ab\x91\x09\x0ade", 2);
        assert_decode(254, 255, 6, b"not\x91\xfe\xffcopy", 3);
    }
}
