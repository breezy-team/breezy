use byteorder::{ReadBytesExt, WriteBytesExt};
use std::io::{Read, Write};

pub const MAX_INSERT_SIZE: usize = 0x7F;
pub const MAX_COPY_SIZE: usize = 0x10000;

#[deprecated]
pub fn encode_base128_int(val: u128) -> Vec<u8> {
    let mut data = Vec::new();
    write_base128_int(&mut data, val).unwrap();
    data
}

/// Encode an integer using base128 encoding.
pub fn write_base128_int<W: std::io::Write>(mut writer: W, val: u128) -> std::io::Result<usize> {
    let mut val = val;
    let mut length = 0;
    while val >= 0x80 {
        writer.write_all(&[((val | 0x80) & 0xFF) as u8])?;
        length += 1;
        val >>= 7;
    }
    writer.write_all(&[val as u8])?;
    Ok(length + 1)
}

/// Decode a base128 encoded integer.
pub fn read_base128_int<R: Read>(reader: &mut R) -> Result<u128, std::io::Error> {
    let mut val: u128 = 0;
    let mut shift = 0;
    let mut bval = [0];
    reader.read_exact(&mut bval)?;
    while bval[0] >= 0x80 {
        val |= ((bval[0] & 0x7F) as u128) << shift;
        reader.read_exact(&mut bval)?;
        shift += 7;
    }

    val |= (bval[0] as u128) << shift;
    Ok(val)
}

#[cfg(test)]
mod test_base128_int {
    #[test]
    fn test_decode_base128_int() {
        assert_eq!(super::decode_base128_int(&[0x00]), (0, 1));
        assert_eq!(super::decode_base128_int(&[0x01]), (1, 1));
        assert_eq!(super::decode_base128_int(&[0x7F]), (127, 1));
        assert_eq!(super::decode_base128_int(&[0x80, 0x01]), (128, 2));
        assert_eq!(super::decode_base128_int(&[0xFF, 0x01]), (255, 2));
        assert_eq!(super::decode_base128_int(&[0x80, 0x02]), (256, 2));
        assert_eq!(super::decode_base128_int(&[0x81, 0x02]), (257, 2));
        assert_eq!(super::decode_base128_int(&[0x82, 0x02]), (258, 2));
        assert_eq!(super::decode_base128_int(&[0xFF, 0x7F]), (16383, 2));
        assert_eq!(super::decode_base128_int(&[0x80, 0x80, 0x01]), (16384, 3));
        assert_eq!(super::decode_base128_int(&[0xFF, 0xFF, 0x7F]), (2097151, 3));
        assert_eq!(
            super::decode_base128_int(&[0x80, 0x80, 0x80, 0x01]),
            (2097152, 4)
        );
        assert_eq!(
            super::decode_base128_int(&[0xFF, 0xFF, 0xFF, 0x7F]),
            (268435455, 4)
        );
        assert_eq!(
            super::decode_base128_int(&[0x80, 0x80, 0x80, 0x80, 0x01]),
            (268435456, 5)
        );
        assert_eq!(
            super::decode_base128_int(&[0xFF, 0xFF, 0xFF, 0xFF, 0x7F]),
            (34359738367, 5)
        );
        assert_eq!(
            super::decode_base128_int(&[0x80, 0x80, 0x80, 0x80, 0x80, 0x01]),
            (34359738368, 6)
        );
    }

    #[test]
    fn test_encode_base128_int() {
        assert_eq!(super::encode_base128_int(0), [0x00]);
        assert_eq!(super::encode_base128_int(1), [0x01]);
        assert_eq!(super::encode_base128_int(127), [0x7F]);
        assert_eq!(super::encode_base128_int(128), [0x80, 0x01]);
        assert_eq!(super::encode_base128_int(255), [0xFF, 0x01]);
        assert_eq!(super::encode_base128_int(256), [0x80, 0x02]);
        assert_eq!(super::encode_base128_int(257), [0x81, 0x02]);
        assert_eq!(super::encode_base128_int(258), [0x82, 0x02]);
        assert_eq!(super::encode_base128_int(16383), [0xFF, 0x7F]);
        assert_eq!(super::encode_base128_int(16384), [0x80, 0x80, 0x01]);
        assert_eq!(super::encode_base128_int(2097151), [0xFF, 0xFF, 0x7F]);
        assert_eq!(super::encode_base128_int(2097152), [0x80, 0x80, 0x80, 0x01]);
        assert_eq!(
            super::encode_base128_int(268435455),
            [0xFF, 0xFF, 0xFF, 0x7F]
        );
        assert_eq!(
            super::encode_base128_int(268435456),
            [0x80, 0x80, 0x80, 0x80, 0x01]
        );
        assert_eq!(
            super::encode_base128_int(34359738367),
            [0xFF, 0xFF, 0xFF, 0xFF, 0x7F]
        );
        assert_eq!(
            super::encode_base128_int(34359738368),
            [0x80, 0x80, 0x80, 0x80, 0x80, 0x01]
        );
        assert_eq!(
            super::encode_base128_int(4398046511103),
            [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x7F]
        );
        assert_eq!(
            super::encode_base128_int(4398046511104),
            [0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x01]
        );
    }
}

#[deprecated]
pub fn decode_base128_int(data: &[u8]) -> (u128, usize) {
    let mut cursor = std::io::Cursor::new(data);
    let val = read_base128_int(&mut cursor).unwrap();
    (val, cursor.position() as usize)
}

#[deprecated]
pub fn decode_copy_instruction(
    data: &[u8],
    cmd: u8,
    pos: usize,
) -> Result<(usize, usize, usize), String> {
    let mut c = std::io::Cursor::new(&data[pos..]);

    let (offset, length) = read_copy_instruction(&mut c, cmd).unwrap();

    Ok((offset, length, pos + c.position() as usize))
}

pub type CopyInstruction = (usize, usize);

pub fn read_copy_instruction<R: Read>(
    reader: &mut R,
    cmd: u8,
) -> Result<CopyInstruction, std::io::Error> {
    if cmd & 0x80 != 0x80 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::Other,
            "copy instructions must have bit 0x80 set".to_string(),
        ));
    }
    let mut offset = 0;
    let mut length = 0;

    if cmd & 0x01 != 0 {
        offset = reader.read_u8()? as usize;
    }
    if cmd & 0x02 != 0 {
        offset |= (reader.read_u8()? as usize) << 8;
    }
    if cmd & 0x04 != 0 {
        offset |= (reader.read_u8()? as usize) << 16;
    }
    if cmd & 0x08 != 0 {
        offset |= (reader.read_u8()? as usize) << 24;
    }
    if cmd & 0x10 != 0 {
        length = reader.read_u8()? as usize;
    }
    if cmd & 0x20 != 0 {
        length |= (reader.read_u8()? as usize) << 8;
    }
    if cmd & 0x40 != 0 {
        length |= (reader.read_u8()? as usize) << 16;
    }
    if length == 0 {
        length = 65536;
    }

    Ok((offset, length))
}

pub fn apply_delta(basis: &[u8], mut delta: &[u8]) -> Result<Vec<u8>, String> {
    let target_length = read_base128_int(&mut delta).map_err(|e| e.to_string())?;
    let mut lines = Vec::new();

    while !delta.is_empty() {
        let cmd = delta.read_u8().map_err(|e| e.to_string())?;

        if cmd & 0x80 != 0 {
            let (offset, length) =
                read_copy_instruction(&mut delta, cmd).map_err(|e| e.to_string())?;
            let last = offset + length;
            if last > basis.len() {
                return Err("data would copy bytes past the end of source".to_string());
            }
            lines.extend_from_slice(&basis[offset..last]);
        } else {
            if cmd == 0 {
                return Err("Command == 0 not supported yet".to_string());
            }
            lines.extend_from_slice(&delta[..cmd as usize]);
            delta = &delta[cmd as usize..];
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

#[cfg(test)]
mod test_apply_delta {
    const TEXT1: &[u8] = b"This is a bit
of source text
which is meant to be matched
against other text
";

    const TEXT2: &[u8] = b"This is a bit
of source text
which is meant to differ from
against other text
";

    #[test]
    fn test_apply_delta() {
        let target =
            super::apply_delta(TEXT1, b"N\x90/\x1fdiffer from\nagainst other text\n").unwrap();
        assert_eq!(target, TEXT2);
        let target =
            super::apply_delta(TEXT2, b"M\x90/\x1ebe matched\nagainst other text\n").unwrap();
        assert_eq!(target, TEXT1);
    }
}

#[deprecated]
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
    let mut copy_bytes = vec![];
    // Convert this offset into a control code and bytes.
    let mut copy_command: u8 = 0x80;

    for copy_bit in [0x01, 0x02, 0x04, 0x08].iter() {
        let base_byte = (offset & 0xff) as u8;
        if base_byte != 0 {
            copy_command |= *copy_bit;
            copy_bytes.push(base_byte);
        }
        offset >>= 8;
    }
    assert!(
        length <= MAX_COPY_SIZE,
        "we don't emit copy records for lengths > 64KiB"
    );
    assert_ne!(length, 0, "we don't emit copy records for lengths == 0");
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

pub fn write_copy_instruction<W: Write>(
    mut writer: W,
    offset: usize,
    length: usize,
) -> Result<usize, std::io::Error> {
    let data = encode_copy_instruction(offset, length);
    writer.write_all(data.as_slice())?;
    Ok(data.len())
}

pub fn write_insert_instruction<W: Write>(
    mut writer: W,
    data: &[u8],
) -> Result<usize, std::io::Error> {
    assert!(data.len() <= 0x7F);
    writer.write_u8(data.len() as u8)?;
    writer.write_all(data)?;
    Ok(data.len() + 1)
}

#[derive(Debug, PartialEq, Eq)]
pub enum Instruction<T: std::borrow::Borrow<[u8]>> {
    r#Copy { offset: usize, length: usize },
    Insert(T),
}

pub fn write_instruction<W: Write, T: std::borrow::Borrow<[u8]>>(
    writer: W,
    instruction: &Instruction<T>,
) -> std::io::Result<usize> {
    match instruction {
        Instruction::Copy { offset, length } => write_copy_instruction(writer, *offset, *length),
        Instruction::Insert(data) => write_insert_instruction(writer, data.borrow()),
    }
}

pub fn read_instruction<R: Read>(mut reader: R) -> Result<Instruction<Vec<u8>>, std::io::Error> {
    let cmd = reader.read_u8()?;
    if cmd & 0x80 != 0 {
        let (offset, length) = read_copy_instruction(&mut reader, cmd)?;
        Ok(Instruction::Copy { offset, length })
    } else if cmd == 0 {
        Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "Command == 0 not supported yet",
        ))
    } else {
        let length = cmd as usize;
        let mut data = vec![0; length];
        reader.read_exact(&mut data)?;
        Ok(Instruction::Insert(data))
    }
}

/// Decode a copy instruction from the given data, starting at the given position.
pub fn decode_instruction(data: &[u8], pos: usize) -> Result<(Instruction<&[u8]>, usize), String> {
    let cmd = data[pos];
    if cmd & 0x80 != 0 {
        let mut c = std::io::Cursor::new(&data[pos + 1..]);
        let (offset, length) = read_copy_instruction(&mut c, cmd).map_err(|e| e.to_string())?;
        let newpos = pos + 1 + c.position() as usize;
        Ok((Instruction::Copy { offset, length }, newpos))
    } else {
        let length = cmd as usize;
        let newpos = pos + 1 + length;
        if newpos > data.len() {
            return Err(format!(
                "Instruction length {} at position {} extends past end of data",
                length, pos
            ));
        }
        Ok((Instruction::Insert(&data[pos + 1..newpos]), newpos))
    }
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

#[cfg(test)]
mod test_instruction {
    use super::{decode_instruction, Instruction};

    #[test]
    fn test_decode_copy_instruction() {
        assert_eq!(
            Ok((
                Instruction::Copy {
                    offset: 0,
                    length: 65536
                },
                1
            )),
            decode_instruction(&b"\x80"[..], 0)
        );
        assert_eq!(
            Ok((
                Instruction::Copy {
                    offset: 10,
                    length: 65536
                },
                2
            )),
            decode_instruction(&b"\x81\x0a"[..], 0)
        );
    }

    #[test]
    fn test_decode_insert_instruction() {
        assert_eq!(
            Ok((Instruction::Insert(&b"\x00"[..]), 2)),
            decode_instruction(&b"\x01\x00"[..], 0)
        );
        assert_eq!(
            Ok((Instruction::Insert(&b"\x01"[..]), 2)),
            decode_instruction(&b"\x01\x01"[..], 0)
        );
        assert_eq!(
            Ok((Instruction::Insert(&b"\xff\x05"[..]), 3)),
            decode_instruction(&b"\x02\xff\x05"[..], 0)
        );
    }
}
