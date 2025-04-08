use crate::groupcompress::delta::{encode_base128_int, encode_copy_instruction};
use std::borrow::Cow;
pub struct OutputHandler<'a> {
    out_lines: Vec<Cow<'a, [u8]>>,
    index_lines: Vec<bool>,
    min_len_to_index: usize,
    cur_insert_lines: Vec<Cow<'a, [u8]>>,
    cur_insert_len: usize,
}

impl<'a> OutputHandler<'a> {
    pub fn new(
        out_lines: Vec<Cow<'a, [u8]>>,
        index_lines: Vec<bool>,
        min_len_to_index: usize,
    ) -> Self {
        OutputHandler {
            out_lines,
            index_lines,
            min_len_to_index,
            cur_insert_lines: Vec::new(),
            cur_insert_len: 0,
        }
    }

    pub fn add_copy(&mut self, start_byte: usize, end_byte: usize) {
        // The data stream allows >64kB in a copy, but to match the compiled
        // code, we will also limit it to a 64kB copy
        for start in (start_byte..end_byte).step_by(64 * 1024) {
            let num_bytes = (end_byte - start).min(64 * 1024);
            let copy_bytes = encode_copy_instruction(start, num_bytes);
            self.out_lines.push(Cow::Owned(copy_bytes));
            self.index_lines.push(false);
        }
    }

    fn flush_insert(&mut self) {
        if self.cur_insert_lines.is_empty() {
            return;
        }
        if self.cur_insert_len > 0x7f {
            panic!("We cannot insert more than 127 bytes at a time.");
        }
        self.out_lines
            .push(Cow::Owned(vec![self.cur_insert_len as u8]));
        self.index_lines.push(false);
        self.out_lines
            .extend_from_slice(self.cur_insert_lines.as_slice());
        self.index_lines.extend(vec![
            self.cur_insert_len >= self.min_len_to_index;
            self.cur_insert_lines.len()
        ]);
        self.cur_insert_lines.clear();
        self.cur_insert_len = 0;
    }

    fn insert_long_line(&mut self, line: Cow<'a, [u8]>) {
        // Flush out anything pending
        self.flush_insert();
        let line_len = line.len();
        for start_index in (0..line_len).step_by(0x7f) {
            let next_len = (line_len - start_index).min(0x7f);
            self.out_lines.push(Cow::Owned(vec![next_len as u8]));
            self.index_lines.push(false);
            // TODO(mem): This should ideally be Cow::Borrowed:
            self.out_lines.push(Cow::Owned(
                line.as_ref()[start_index..start_index + next_len].to_vec(),
            ));
            // We don't index long lines, because we won't be able to match
            // a line split across multiple inserts anway
            self.index_lines.push(false);
        }
    }

    pub fn add_insert(&mut self, lines: impl Iterator<Item = Cow<'a, [u8]>>) {
        if !self.cur_insert_lines.is_empty() {
            panic!("self.cur_insert_lines must be empty when adding a new insert");
        }

        for line in lines {
            if line.len() > 0x7f {
                self.insert_long_line(line);
            } else {
                let next_len = line.len() + self.cur_insert_len;
                if next_len > 0x7f {
                    // Adding this line would overflow, so flush, and start over
                    self.flush_insert();
                    self.cur_insert_len = line.len();
                    self.cur_insert_lines = vec![line];
                } else {
                    self.cur_insert_lines.push(line);
                    self.cur_insert_len = next_len;
                }
            }
        }
        self.flush_insert();
    }
}

/// This class indexes matches between strings.
///
/// # Attributes
/// * `lines`: The 'static' lines that will be preserved between runs.
/// * `matching_lines`: A dict of {line:[matching offsets]}
/// * `line_offsets`: The byte offset for the end of each line, used to quickly map between a
/// matching line number and the byte location
/// * `endpoint: The total number of bytes in self.line_offsets
use std::collections::{HashMap, HashSet};

pub struct LinesDeltaIndex {
    lines: Vec<Vec<u8>>,
    line_offsets: Vec<usize>,
    endpoint: usize,
    matching_lines: HashMap<Vec<u8>, HashSet<usize>>,
}

impl LinesDeltaIndex {
    const MIN_MATCH_BYTES: usize = 10;
    const SOFT_MIN_MATCH_BYTES: usize = 200;

    pub fn new(lines: Vec<Vec<u8>>) -> Self {
        let mut delta_index = LinesDeltaIndex {
            lines: vec![],
            line_offsets: vec![],
            endpoint: 0,
            matching_lines: HashMap::new(),
        };
        let index = vec![true; lines.len()];
        delta_index.extend_lines(lines.as_slice(), index.as_slice());
        delta_index
    }

    pub fn lines(&self) -> &[Vec<u8>] {
        self.lines.as_slice()
    }

    fn update_matching_lines(&mut self, new_lines: &[Vec<u8>], index: &[bool]) {
        let matches = &mut self.matching_lines;
        let start_idx = self.lines.len();
        if new_lines.len() != index.len() {
            panic!(
                "The number of lines to be indexed does not match the index/don't index flags: {} != {}",
                new_lines.len(),
                index.len()
            );
        }
        for (idx, (line, &do_index)) in std::iter::zip(new_lines, index).enumerate() {
            if !do_index {
                continue;
            }
            matches
                .entry(line.clone())
                .or_default()
                .insert(start_idx + idx);
        }
    }

    /// Return the lines which match the line in right
    pub fn get_matches(&self, line: &[u8]) -> Option<&HashSet<usize>> {
        self.matching_lines.get(line)
    }

    /// Look at all matches for the current line, return the longest.
    ///
    /// # Arguments
    ///
    /// * `lines`: The lines we are matching against
    /// * `pos`: The current location we care about
    /// * `locations`: A list of lines that matched the current location.
    ///    This may be None, but often we'll have already found matches for
    ///    this line.
    ///
    /// # Returns
    /// (start_in_self, start_in_lines, num_lines)
    /// All values are the offset in the list (aka the line number)
    /// If start_in_self is None, then we have no matches, and this line
    /// should be inserted in the target.
    fn get_longest_match(
        &self,
        lines: &[Cow<'_, [u8]>],
        mut pos: usize,
    ) -> (Option<(usize, usize, usize)>, usize) {
        let range_start = pos;
        let mut range_len = 0;
        let mut prev_locations: Option<HashSet<usize>> = None;
        let max_pos = lines.len();

        while pos < max_pos {
            match self.matching_lines.get(lines[pos].as_ref()) {
                Some(locations) => {
                    // We have a match
                    if let Some(prev) = prev_locations.as_ref() {
                        // We have a match started, compare to see if any of the curent matches can
                        // be continued.
                        let next_locations: HashSet<usize> = locations
                            .intersection(
                                &prev.iter().map(|&loc| loc + 1).collect::<HashSet<usize>>(),
                            )
                            .cloned()
                            .collect();

                        if !next_locations.is_empty() {
                            // At least one of the regions continues to match
                            prev_locations = Some(next_locations);
                            range_len += 1;
                        } else {
                            // All the current regions no longer match.
                            // This line does still match something, just not at the end of the
                            // previous matches. WE will return location so sthat we can avoid
                            // another _matching_lines lookup.
                            break;
                        }
                    } else {
                        // This is the first match in a range
                        prev_locations = Some(locations.clone());
                        range_len = 1;
                    }
                    pos += 1;
                }
                None => {
                    // No more matches, just return wahtever we have, but we know that this last
                    // position is not going to match anything.
                    pos += 1;
                    break;
                }
            }
        }

        if let Some(prev) = prev_locations {
            let smallest = *prev.iter().min().unwrap();
            (
                Some((smallest + 1 - range_len, range_start, range_len)),
                pos,
            )
        } else {
            (None, pos)
        }
    }

    /// Return the ranges in lines which match self.lines.
    ///
    /// # Arguments
    /// * `lines`: :param lines: lines to compress
    ///
    /// # Returns
    /// A list of (old_start, new_start, length) tuples which reflect
    /// a region in self.lines that is present in lines.  The last element
    /// of the list is always (old_len, new_len, 0) to provide a end point
    /// for generating instructions from the matching blocks list.
    fn get_matching_blocks(
        &self,
        lines: &[Cow<'_, [u8]>],
        soft: bool,
    ) -> Vec<(usize, usize, usize)> {
        // In this code, we iterate over multiple _get_longest_match calls, to
        // find the next longest copy, and possible insert regions. We then
        // convert that to the simple matching_blocks representation, since
        // otherwise inserting 10 lines in a row would show up as 10
        // instructions.

        let mut result = Vec::new();
        let mut pos = 0;
        let max_pos = lines.len();
        let min_match_bytes = if soft {
            Self::SOFT_MIN_MATCH_BYTES
        } else {
            Self::MIN_MATCH_BYTES
        };

        while pos < max_pos {
            let (block, new_pos) = self.get_longest_match(lines, pos);

            if let Some(block) = block {
                // Check to see if we match fewer than min_match_bytes. As we
                // will turn this into a pure 'insert', rather than a copy.
                // block[-1] is the number of lines. A quick check says if we
                // have more lines than min_match_bytes, then we know we have
                // enough bytes.
                if block.2 < min_match_bytes {
                    // This block may be a 'short' block, check
                    let (_old_start, new_start, range_len) = block;
                    let matched_bytes: usize = lines[new_start..new_start + range_len]
                        .iter()
                        .map(|line| line.len())
                        .sum();

                    if matched_bytes >= min_match_bytes {
                        result.push(block);
                    }
                } else {
                    result.push(block);
                }
            }

            pos = new_pos;
        }

        result.push((self.lines.len(), lines.len(), 0));
        result
    }

    /// Add more lines to the left-lines list.
    ///
    /// # Arguments
    /// * `lines`: The lines to add.
    /// * `index`: A list of booleans indicating whether each line should be indexed.
    pub fn extend_lines(&mut self, lines: &[Vec<u8>], index: &[bool]) {
        self.update_matching_lines(lines, index);
        self.lines.extend_from_slice(lines);
        let mut endpoint = self.endpoint;
        for line in lines {
            endpoint += std::convert::Into::<Cow<[u8]>>::into(line).len();
            self.line_offsets.push(endpoint);
        }
        assert_eq!(
            self.line_offsets.len(),
            self.lines.len(),
            "Somehow the line offset indicator got out of sync with the line counter"
        );
        self.endpoint = endpoint;
    }

    pub fn endpoint(&self) -> usize {
        self.endpoint
    }

    /// Compute the delta for this content versus the original content.
    pub fn make_delta<'a>(
        &self,
        new_lines: &'_ [Cow<'a, [u8]>],
        bytes_length: usize,
        soft: Option<bool>,
    ) -> (Vec<Cow<'a, [u8]>>, Vec<bool>) {
        let soft = soft.unwrap_or(false);
        let out_lines = vec![
            // reserved for content type, content length
            Cow::Owned(vec![]),
            Cow::Owned(vec![]),
            Cow::Owned(encode_base128_int(bytes_length as u128)),
        ];
        let index_lines = vec![false, false, false];

        let mut output_handler = OutputHandler::new(out_lines, index_lines, Self::MIN_MATCH_BYTES);
        let blocks = self.get_matching_blocks(new_lines, soft);

        let mut current_line_num = 0;

        // We either copy a range (while there are reusable lines) or we
        // insert new lines. To find reusable lines we traverse

        for (old_start, new_start, range_len) in blocks {
            if new_start != current_line_num {
                // non-matching region, insert the content
                output_handler.add_insert(new_lines[current_line_num..new_start].iter().cloned());
            }
            current_line_num = new_start + range_len;

            if range_len > 0 {
                // Convert the line based offsets into byte based offsets
                let first_byte = if old_start == 0 {
                    0
                } else {
                    self.line_offsets[old_start - 1]
                };

                let last_byte = self.line_offsets[old_start + range_len - 1];

                output_handler.add_copy(first_byte, last_byte);
            }
        }

        (output_handler.out_lines, output_handler.index_lines)
    }
}

/// Create a delta from source to target.
pub fn make_delta<'a>(
    source_bytes: &[u8],
    target_bytes: &'a [u8],
) -> impl Iterator<Item = Cow<'a, [u8]>> {
    // TODO(perf): Use Cow<[u8]> for the source lines
    let line_locations = LinesDeltaIndex::new(
        breezy_osutils::split_lines(source_bytes)
            .map(|x| x.into_owned())
            .collect::<Vec<_>>(),
    );
    let lines = breezy_osutils::split_lines(target_bytes).collect::<Vec<_>>();
    line_locations
        .make_delta(lines.as_slice(), target_bytes.len(), None)
        .0
        .into_iter()
}
