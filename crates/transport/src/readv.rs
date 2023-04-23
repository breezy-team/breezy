use std::io::{Read, Seek, SeekFrom};

pub struct OverlappingRange {
    last_end: usize,
    start: usize,
}

impl std::fmt::Display for OverlappingRange {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(
            f,
            "Overlapping range not allowed: last range ended at {}, new one starts at {}",
            self.last_end, self.start
        )
    }
}

/// Yield coalesced offsets.
///
/// With a long list of neighboring requests, combine them
/// into a single large request, while retaining the original
/// offsets.
/// Turns  [(15, 10), (25, 10)] => [(15, 20, [(0, 10), (10, 10)])]
/// Note that overlapping requests are not permitted. (So [(15, 10), (20,
/// 10)] will raise a ValueError.) This is because the data we access never
/// overlaps, and it allows callers to trust that we only need any byte of
/// data for 1 request (so nothing needs to be buffered to fulfill a second
/// request.)
///
/// :param offsets: A list of (start, length) pairs
/// :param limit: Only combine a maximum of this many pairs Some transports
///         penalize multiple reads more than others, and sometimes it is
///         better to return early.
///         0 means no limit
/// :param fudge_factor: All transports have some level of 'it is
///         better to read some more data and throw it away rather
///         than seek', so collapse if we are 'close enough'
/// :param max_size: Create coalesced offsets no bigger than this size.
///         When a single offset is bigger than 'max_size', it will keep
///         its size and be alone in the coalesced offset.
///         0 means no maximum size.
/// :return: return a list of _CoalescedOffset objects, which have members
///     for where to start, how much to read, and how to split those chunks
///     back up
pub fn coalesce_offsets(
    offsets: &[(usize, usize)],
    limit: Option<usize>,
    fudge_factor: Option<usize>,
    max_size: Option<usize>,
) -> std::result::Result<Vec<(usize, usize, Vec<(usize, usize)>)>, OverlappingRange> {
    struct CoalescedOffset {
        start: usize,
        length: usize,
        ranges: Vec<(usize, usize)>,
    }

    if offsets.is_empty() {
        return Ok(vec![]);
    }

    let mut cur = CoalescedOffset {
        start: offsets[0].0,
        length: offsets[0].1,
        ranges: vec![(0, offsets[0].1)],
    };
    let mut last_end = cur.start + cur.length;
    let mut coalesced_offsets = Vec::new();

    let fudge_factor = fudge_factor.unwrap_or(0);

    // unlimited, but we actually take this to mean 100MB buffer limit
    let max_size = max_size.unwrap_or(100 * 1024 * 1024);

    for (start, size) in &offsets[1..] {
        let end = start + size;
        if *start <= last_end + fudge_factor
            && *start >= cur.start
            && (limit.is_none() || cur.ranges.len() < limit.unwrap())
            && (end - cur.start <= max_size)
        {
            if *start < last_end {
                return Err(OverlappingRange {
                    last_end,
                    start: *start,
                });
            }
            cur.length = end - cur.start;
            cur.ranges.push((start - cur.start, *size));
        } else {
            coalesced_offsets.push((cur.start, cur.length, cur.ranges));
            cur = CoalescedOffset {
                start: *start,
                length: *size,
                ranges: vec![(0, *size)],
            };
        }
        last_end = end;
    }

    coalesced_offsets.push((cur.start, cur.length, cur.ranges));
    Ok(coalesced_offsets)
}

/// An implementation of readv that uses fp.seek and fp.read.
///
/// This uses _coalesce_offsets to issue larger reads and fewer seeks.
///
/// :param fp: A file-like object that supports seek() and read(size).
///    Note that implementations are allowed to call .close() on this file
///    handle, so don't trust that you can use it for other work.
/// :param offsets: A list of offsets to be read from the given file.
/// :return: yield (pos, data) tuples for each request
pub fn seek_and_read<T: Read + Seek>(
    mut fp: T,
    offsets: &[(usize, usize)],
    max_readv_combine: usize,
    bytes_to_read_before_seek: usize,
) -> std::io::Result<impl Iterator<Item = (usize, Vec<u8>)>> {
    let mut offsets = offsets.to_vec();
    offsets.sort();

    // Turn list of offsets into a stack
    let coalesced = coalesce_offsets(
        &offsets,
        Some(max_readv_combine),
        Some(bytes_to_read_before_seek),
        None,
    )
    .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))?;

    // Cache the results, but only until they have been fulfilled
    let mut data_map = std::collections::HashMap::new();
    for (start, length, ranges) in coalesced {
        fp.seek(SeekFrom::Start(start as u64))?;
        let mut data = vec![0; length];
        fp.read_exact(&mut data)?;
        for (suboffset, subsize) in ranges {
            let key = (start + suboffset, subsize);
            data_map.insert(key, data[suboffset..suboffset + subsize].to_vec());
        }
    }

    Ok(offsets.into_iter().map(move |(offset, size)| {
        let key = (offset, size);
        let data = data_map.remove(&key).unwrap();
        (offset, data)
    }))
}
