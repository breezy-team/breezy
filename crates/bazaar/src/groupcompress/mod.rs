pub mod delta;

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

pub fn encode_copy_instruction(mut offset: usize, mut length: usize) -> Result<Vec<u8>, String> {
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
        return Err("we don't emit copy records for lengths > 64KiB".to_string());
    }
    if length == 0 {
        return Err("We cannot emit a copy of length 0".to_string());
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
    Ok(copy_bytes)
}
