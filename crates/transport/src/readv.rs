use std::collections::HashMap;
use std::collections::VecDeque;
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
    let mut offsets = offsets.to_vec();
    offsets.sort();

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

struct ReadvIter<T> {
    fp: T,
    offsets: VecDeque<(usize, usize)>,
    coalesced: VecDeque<(usize, usize, Vec<(usize, usize)>)>,
    data_map: HashMap<(usize, usize), Vec<u8>>,
}

impl<T: Read + Seek> ReadvIter<T> {
    fn new(
        fp: T,
        offsets: Vec<(usize, usize)>,
        max_readv_combine: usize,
        bytes_to_read_before_seek: usize,
    ) -> std::io::Result<Self> {
        // Turn list of offsets into a stack
        let coalesced = coalesce_offsets(
            &offsets,
            Some(max_readv_combine),
            Some(bytes_to_read_before_seek),
            None,
        )
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))?;

        Ok(Self {
            fp,
            offsets: VecDeque::from(offsets),
            coalesced: coalesced.into_iter().collect(),
            data_map: std::collections::HashMap::new(),
        })
    }

    fn read_more(&mut self) -> Result<bool, (std::io::Error, usize, usize, usize)> {
        // Cache the results, but only until they have been fulfilled
        if let Some((start, length, ranges)) = self.coalesced.pop_front() {
            self.fp
                .seek(SeekFrom::Start(start as u64))
                .map_err(|e| (e, start, length, 0))?;
            let mut data = vec![0; length];
            self.fp
                .read_exact(&mut data)
                .map_err(|e| (e, start, length, 0))?;
            for (suboffset, subsize) in ranges {
                self.data_map.insert(
                    (start + suboffset, subsize),
                    data[suboffset..suboffset + subsize].to_vec(),
                );
            }
            Ok(true)
        } else {
            Ok(false)
        }
    }
}

impl<T: Read + Seek> Iterator for ReadvIter<T> {
    type Item = Result<(usize, Vec<u8>), (std::io::Error, usize, usize, usize)>;

    fn next(&mut self) -> Option<Self::Item> {
        if let Some(key) = self.offsets.pop_front() {
            loop {
                if let Some(data) = self.data_map.remove(&key) {
                    break Some(Ok((key.0, data)));
                } else {
                    match self.read_more() {
                        Ok(true) => continue,
                        Ok(false) => break None,
                        Err(e) => break Some(Err(e)),
                    }
                }
            }
        } else {
            None
        }
    }
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
    fp: T,
    offsets: Vec<(usize, usize)>,
    max_readv_combine: usize,
    bytes_to_read_before_seek: usize,
) -> std::io::Result<
    impl Iterator<Item = Result<(usize, Vec<u8>), (std::io::Error, usize, usize, usize)>>,
> {
    ReadvIter::new(fp, offsets, max_readv_combine, bytes_to_read_before_seek)
}

pub fn sort_expand_and_combine(
    offsets: Vec<(u64, usize)>,
    upper_limit: Option<u64>,
    recommended_page_size: usize,
) -> Vec<(u64, usize)> {
    // Sort the offsets by start address.
    let mut sorted_offsets = offsets.to_vec();
    sorted_offsets.sort_unstable_by_key(|&(offset, _)| offset);

    // Short circuit empty requests.
    if sorted_offsets.is_empty() {
        return Vec::new();
    }

    // Expand the offsets by page size at either end.
    let maximum_expansion = recommended_page_size;
    let mut new_offsets = Vec::with_capacity(sorted_offsets.len());
    for (offset, length) in sorted_offsets {
        let expansion = maximum_expansion.saturating_sub(length);
        let reduction = expansion / 2;
        let new_offset = offset.saturating_sub(reduction as u64);
        let new_length = length + expansion;
        let new_length = if let Some(upper_limit) = upper_limit {
            let new_end = new_offset.saturating_add(new_length as u64);
            let new_length = std::cmp::min(upper_limit, new_end) - new_offset;
            std::cmp::max(0, new_length as isize) as usize
        } else {
            new_length
        };
        if new_length > 0 {
            new_offsets.push((new_offset, new_length));
        }
    }

    // Combine the expanded offsets.
    let mut result = Vec::with_capacity(new_offsets.len());
    if let Some((mut current_offset, mut current_length)) = new_offsets.first().copied() {
        let mut current_finish = current_offset + current_length as u64;
        for (offset, length) in new_offsets.iter().skip(1) {
            let finish = offset + *length as u64;
            if *offset > current_finish {
                result.push((current_offset, current_length));
                current_offset = *offset;
                current_length = *length;
                current_finish = finish;
            } else if finish > current_finish {
                current_finish = finish;
                current_length = (current_finish - current_offset) as usize;
            }
        }
        result.push((current_offset, current_length));
    }
    result
}
