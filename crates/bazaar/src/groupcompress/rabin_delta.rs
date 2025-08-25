use crate::groupcompress::delta::{
    decode_instruction, read_base128_int, write_base128_int, write_instruction, Instruction,
    MAX_COPY_SIZE, MAX_INSERT_SIZE,
};
use std::collections::HashMap;
use std::convert::TryInto;
use std::io::Write;

/// diff-delta.rs: generate a delta between two buffers
///
/// This code was greatly inspired by parts of LibXDiff from Davide Libenzi
/// http://www.xmailserver.org/xdiff-lib.html
///
/// Rewritten for GIT by Nicolas Pitre <nico@fluxnic.net>, (C) 2005-2007
/// Adapted for Bazaar by John Arbash Meinel <john@arbash-meinel.com> (C) 2009
///
/// Ported to Rust by Jelmer Vernooĳ <jelmer@jelmer.uk> and significantly rewritten.
///
/// This program is free software; you can redistribute it and/or modify
/// it under the terms of the GNU General Public License as published by
/// the Free Software Foundation; either version 2 of the License, or
/// (at your option) any later version.
///
/// NB: The version in GIT is 'version 2 of the Licence only', however Nicolas
/// has granted permission for use under 'version 2 or later' in private email
/// to Robert Collins and Karl Fogel on the 6th April 2009.

// maximum hash entry list for the same hash bucket
const RABIN_SHIFT: usize = 23;
const RABIN_WINDOW: usize = 16;

const T: &[u32; 256] = &[
    0x00000000, 0xab59b4d1, 0x56b369a2, 0xfdeadd73, 0x063f6795, 0xad66d344, 0x508c0e37, 0xfbd5bae6,
    0x0c7ecf2a, 0xa7277bfb, 0x5acda688, 0xf1941259, 0x0a41a8bf, 0xa1181c6e, 0x5cf2c11d, 0xf7ab75cc,
    0x18fd9e54, 0xb3a42a85, 0x4e4ef7f6, 0xe5174327, 0x1ec2f9c1, 0xb59b4d10, 0x48719063, 0xe32824b2,
    0x1483517e, 0xbfdae5af, 0x423038dc, 0xe9698c0d, 0x12bc36eb, 0xb9e5823a, 0x440f5f49, 0xef56eb98,
    0x31fb3ca8, 0x9aa28879, 0x6748550a, 0xcc11e1db, 0x37c45b3d, 0x9c9defec, 0x6177329f, 0xca2e864e,
    0x3d85f382, 0x96dc4753, 0x6b369a20, 0xc06f2ef1, 0x3bba9417, 0x90e320c6, 0x6d09fdb5, 0xc6504964,
    0x2906a2fc, 0x825f162d, 0x7fb5cb5e, 0xd4ec7f8f, 0x2f39c569, 0x846071b8, 0x798aaccb, 0xd2d3181a,
    0x25786dd6, 0x8e21d907, 0x73cb0474, 0xd892b0a5, 0x23470a43, 0x881ebe92, 0x75f463e1, 0xdeadd730,
    0x63f67950, 0xc8afcd81, 0x354510f2, 0x9e1ca423, 0x65c91ec5, 0xce90aa14, 0x337a7767, 0x9823c3b6,
    0x6f88b67a, 0xc4d102ab, 0x393bdfd8, 0x92626b09, 0x69b7d1ef, 0xc2ee653e, 0x3f04b84d, 0x945d0c9c,
    0x7b0be704, 0xd05253d5, 0x2db88ea6, 0x86e13a77, 0x7d348091, 0xd66d3440, 0x2b87e933, 0x80de5de2,
    0x7775282e, 0xdc2c9cff, 0x21c6418c, 0x8a9ff55d, 0x714a4fbb, 0xda13fb6a, 0x27f92619, 0x8ca092c8,
    0x520d45f8, 0xf954f129, 0x04be2c5a, 0xafe7988b, 0x5432226d, 0xff6b96bc, 0x02814bcf, 0xa9d8ff1e,
    0x5e738ad2, 0xf52a3e03, 0x08c0e370, 0xa39957a1, 0x584ced47, 0xf3155996, 0x0eff84e5, 0xa5a63034,
    0x4af0dbac, 0xe1a96f7d, 0x1c43b20e, 0xb71a06df, 0x4ccfbc39, 0xe79608e8, 0x1a7cd59b, 0xb125614a,
    0x468e1486, 0xedd7a057, 0x103d7d24, 0xbb64c9f5, 0x40b17313, 0xebe8c7c2, 0x16021ab1, 0xbd5bae60,
    0x6cb54671, 0xc7ecf2a0, 0x3a062fd3, 0x915f9b02, 0x6a8a21e4, 0xc1d39535, 0x3c394846, 0x9760fc97,
    0x60cb895b, 0xcb923d8a, 0x3678e0f9, 0x9d215428, 0x66f4eece, 0xcdad5a1f, 0x3047876c, 0x9b1e33bd,
    0x7448d825, 0xdf116cf4, 0x22fbb187, 0x89a20556, 0x7277bfb0, 0xd92e0b61, 0x24c4d612, 0x8f9d62c3,
    0x7836170f, 0xd36fa3de, 0x2e857ead, 0x85dcca7c, 0x7e09709a, 0xd550c44b, 0x28ba1938, 0x83e3ade9,
    0x5d4e7ad9, 0xf617ce08, 0x0bfd137b, 0xa0a4a7aa, 0x5b711d4c, 0xf028a99d, 0x0dc274ee, 0xa69bc03f,
    0x5130b5f3, 0xfa690122, 0x0783dc51, 0xacda6880, 0x570fd266, 0xfc5666b7, 0x01bcbbc4, 0xaae50f15,
    0x45b3e48d, 0xeeea505c, 0x13008d2f, 0xb85939fe, 0x438c8318, 0xe8d537c9, 0x153feaba, 0xbe665e6b,
    0x49cd2ba7, 0xe2949f76, 0x1f7e4205, 0xb427f6d4, 0x4ff24c32, 0xe4abf8e3, 0x19412590, 0xb2189141,
    0x0f433f21, 0xa41a8bf0, 0x59f05683, 0xf2a9e252, 0x097c58b4, 0xa225ec65, 0x5fcf3116, 0xf49685c7,
    0x033df00b, 0xa86444da, 0x558e99a9, 0xfed72d78, 0x0502979e, 0xae5b234f, 0x53b1fe3c, 0xf8e84aed,
    0x17bea175, 0xbce715a4, 0x410dc8d7, 0xea547c06, 0x1181c6e0, 0xbad87231, 0x4732af42, 0xec6b1b93,
    0x1bc06e5f, 0xb099da8e, 0x4d7307fd, 0xe62ab32c, 0x1dff09ca, 0xb6a6bd1b, 0x4b4c6068, 0xe015d4b9,
    0x3eb80389, 0x95e1b758, 0x680b6a2b, 0xc352defa, 0x3887641c, 0x93ded0cd, 0x6e340dbe, 0xc56db96f,
    0x32c6cca3, 0x999f7872, 0x6475a501, 0xcf2c11d0, 0x34f9ab36, 0x9fa01fe7, 0x624ac294, 0xc9137645,
    0x26459ddd, 0x8d1c290c, 0x70f6f47f, 0xdbaf40ae, 0x207afa48, 0x8b234e99, 0x76c993ea, 0xdd90273b,
    0x2a3b52f7, 0x8162e626, 0x7c883b55, 0xd7d18f84, 0x2c043562, 0x875d81b3, 0x7ab75cc0, 0xd1eee811,
];

const U: &[u32; 256] = &[
    0x00000000, 0x7eb5200d, 0x5633f4cb, 0x2886d4c6, 0x073e5d47, 0x798b7d4a, 0x510da98c, 0x2fb88981,
    0x0e7cba8e, 0x70c99a83, 0x584f4e45, 0x26fa6e48, 0x0942e7c9, 0x77f7c7c4, 0x5f711302, 0x21c4330f,
    0x1cf9751c, 0x624c5511, 0x4aca81d7, 0x347fa1da, 0x1bc7285b, 0x65720856, 0x4df4dc90, 0x3341fc9d,
    0x1285cf92, 0x6c30ef9f, 0x44b63b59, 0x3a031b54, 0x15bb92d5, 0x6b0eb2d8, 0x4388661e, 0x3d3d4613,
    0x39f2ea38, 0x4747ca35, 0x6fc11ef3, 0x11743efe, 0x3eccb77f, 0x40799772, 0x68ff43b4, 0x164a63b9,
    0x378e50b6, 0x493b70bb, 0x61bda47d, 0x1f088470, 0x30b00df1, 0x4e052dfc, 0x6683f93a, 0x1836d937,
    0x250b9f24, 0x5bbebf29, 0x73386bef, 0x0d8d4be2, 0x2235c263, 0x5c80e26e, 0x740636a8, 0x0ab316a5,
    0x2b7725aa, 0x55c205a7, 0x7d44d161, 0x03f1f16c, 0x2c4978ed, 0x52fc58e0, 0x7a7a8c26, 0x04cfac2b,
    0x73e5d470, 0x0d50f47d, 0x25d620bb, 0x5b6300b6, 0x74db8937, 0x0a6ea93a, 0x22e87dfc, 0x5c5d5df1,
    0x7d996efe, 0x032c4ef3, 0x2baa9a35, 0x551fba38, 0x7aa733b9, 0x041213b4, 0x2c94c772, 0x5221e77f,
    0x6f1ca16c, 0x11a98161, 0x392f55a7, 0x479a75aa, 0x6822fc2b, 0x1697dc26, 0x3e1108e0, 0x40a428ed,
    0x61601be2, 0x1fd53bef, 0x3753ef29, 0x49e6cf24, 0x665e46a5, 0x18eb66a8, 0x306db26e, 0x4ed89263,
    0x4a173e48, 0x34a21e45, 0x1c24ca83, 0x6291ea8e, 0x4d29630f, 0x339c4302, 0x1b1a97c4, 0x65afb7c9,
    0x446b84c6, 0x3adea4cb, 0x1258700d, 0x6ced5000, 0x4355d981, 0x3de0f98c, 0x15662d4a, 0x6bd30d47,
    0x56ee4b54, 0x285b6b59, 0x00ddbf9f, 0x7e689f92, 0x51d01613, 0x2f65361e, 0x07e3e2d8, 0x7956c2d5,
    0x5892f1da, 0x2627d1d7, 0x0ea10511, 0x7014251c, 0x5facac9d, 0x21198c90, 0x099f5856, 0x772a785b,
    0x4c921c31, 0x32273c3c, 0x1aa1e8fa, 0x6414c8f7, 0x4bac4176, 0x3519617b, 0x1d9fb5bd, 0x632a95b0,
    0x42eea6bf, 0x3c5b86b2, 0x14dd5274, 0x6a687279, 0x45d0fbf8, 0x3b65dbf5, 0x13e30f33, 0x6d562f3e,
    0x506b692d, 0x2ede4920, 0x06589de6, 0x78edbdeb, 0x5755346a, 0x29e01467, 0x0166c0a1, 0x7fd3e0ac,
    0x5e17d3a3, 0x20a2f3ae, 0x08242768, 0x76910765, 0x59298ee4, 0x279caee9, 0x0f1a7a2f, 0x71af5a22,
    0x7560f609, 0x0bd5d604, 0x235302c2, 0x5de622cf, 0x725eab4e, 0x0ceb8b43, 0x246d5f85, 0x5ad87f88,
    0x7b1c4c87, 0x05a96c8a, 0x2d2fb84c, 0x539a9841, 0x7c2211c0, 0x029731cd, 0x2a11e50b, 0x54a4c506,
    0x69998315, 0x172ca318, 0x3faa77de, 0x411f57d3, 0x6ea7de52, 0x1012fe5f, 0x38942a99, 0x46210a94,
    0x67e5399b, 0x19501996, 0x31d6cd50, 0x4f63ed5d, 0x60db64dc, 0x1e6e44d1, 0x36e89017, 0x485db01a,
    0x3f77c841, 0x41c2e84c, 0x69443c8a, 0x17f11c87, 0x38499506, 0x46fcb50b, 0x6e7a61cd, 0x10cf41c0,
    0x310b72cf, 0x4fbe52c2, 0x67388604, 0x198da609, 0x36352f88, 0x48800f85, 0x6006db43, 0x1eb3fb4e,
    0x238ebd5d, 0x5d3b9d50, 0x75bd4996, 0x0b08699b, 0x24b0e01a, 0x5a05c017, 0x728314d1, 0x0c3634dc,
    0x2df207d3, 0x534727de, 0x7bc1f318, 0x0574d315, 0x2acc5a94, 0x54797a99, 0x7cffae5f, 0x024a8e52,
    0x06852279, 0x78300274, 0x50b6d6b2, 0x2e03f6bf, 0x01bb7f3e, 0x7f0e5f33, 0x57888bf5, 0x293dabf8,
    0x08f998f7, 0x764cb8fa, 0x5eca6c3c, 0x207f4c31, 0x0fc7c5b0, 0x7172e5bd, 0x59f4317b, 0x27411176,
    0x1a7c5765, 0x64c97768, 0x4c4fa3ae, 0x32fa83a3, 0x1d420a22, 0x63f72a2f, 0x4b71fee9, 0x35c4dee4,
    0x1400edeb, 0x6ab5cde6, 0x42331920, 0x3c86392d, 0x133eb0ac, 0x6d8b90a1, 0x450d4467, 0x3bb8646a,
];

// Result type for functions that have multiple failure modes
#[derive(Debug)]
pub enum DeltaError {
    Io(std::io::Error), // An IO error occurred
    DeltaTooLarge,      // The delta is too large to be encoded
}

impl std::fmt::Display for DeltaError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            DeltaError::Io(err) => write!(f, "IO error: {}", err),
            DeltaError::DeltaTooLarge => write!(f, "Delta too large"),
        }
    }
}

impl From<std::io::Error> for DeltaError {
    fn from(err: std::io::Error) -> DeltaError {
        DeltaError::Io(err)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RabinHash(u32);

impl RabinHash {
    pub fn pushright(&mut self, c: u8) {
        self.0 = ((self.0 << 8) | c as u32) ^ T[(self.0 >> RABIN_SHIFT) as usize];
    }

    pub fn popleft(&mut self, c: u8) {
        self.0 ^= U[c as usize];
    }

    pub fn finish(&self) -> u32 {
        self.0
    }
}

impl From<RabinHash> for u32 {
    fn from(val: RabinHash) -> u32 {
        val.0
    }
}

pub fn rabin_hash(data: [u8; RABIN_WINDOW]) -> RabinHash {
    assert_eq!(data.len(), RABIN_WINDOW);
    let mut val = RabinHash(0);
    for c in data.iter().take(RABIN_WINDOW) {
        val.pushright(*c);
    }
    val
}

pub struct RabinWindow {
    data: [u8; RABIN_WINDOW],
    pos: usize,
    hash: RabinHash,
}

impl RabinWindow {
    pub fn new(data: [u8; RABIN_WINDOW]) -> Self {
        let hash = rabin_hash(data);
        RabinWindow { data, hash, pos: 0 }
    }

    pub fn push(&mut self, c: u8) {
        self.hash.pushright(c);
        self.hash.popleft(self.data[self.pos]);
        self.data[self.pos] = c;
        self.pos = (self.pos + 1) % RABIN_WINDOW;
    }

    pub fn hash(&self) -> RabinHash {
        self.hash
    }
}

#[derive(Debug, Clone)]
pub struct DeltaIndex<'a> {
    entries: HashMap<u32, Vec<IndexEntry<'a>>>,
    last_offset: usize,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct IndexEntry<'a> {
    /// Absolute offset
    pub offset: usize,

    pub data: &'a [u8],
}

impl IndexEntry<'_> {
    pub fn add(&self, offset: usize) -> Self {
        Self {
            offset: self.offset + offset,
            data: &self.data[offset..],
        }
    }
}

impl Default for DeltaIndex<'_> {
    fn default() -> Self {
        Self::new()
    }
}

impl<'a> DeltaIndex<'a> {
    pub fn iter_matches(&self, val: &RabinHash) -> impl Iterator<Item = &IndexEntry<'a>> + '_ {
        self.entries
            .get(&val.finish())
            .into_iter()
            .flat_map(|v| v.iter())
    }

    fn find_match(
        &self,
        hash: RabinHash,
        data: &[u8],
        mut min_size: usize,
        good_enough_size: Option<usize>,
    ) -> Option<(IndexEntry<'a>, usize)> {
        let mut msource = None;

        for entry in self.iter_matches(&hash) {
            if entry.data.len() <= min_size {
                // no point in checking this one
                continue;
            }
            let overlap = entry
                .data
                .iter()
                .zip(data.iter())
                .take_while(|(x, y)| x == y)
                .count();
            if overlap > min_size {
                /* this is our best match so far */
                min_size = overlap;
                msource = Some(*entry);
                if let Some(good_enough_size) = good_enough_size {
                    if min_size >= good_enough_size {
                        /* good enough */
                        return Some((msource.unwrap(), min_size));
                    }
                }
            }
        }

        msource.map(|s| (s, min_size))
    }

    pub fn new() -> Self {
        Self {
            entries: HashMap::new(),
            last_offset: 0,
        }
    }

    pub fn add_delta(&mut self, mut delta: &'a [u8], unused_bytes: usize) -> std::io::Result<()> {
        read_base128_int(&mut delta)?;
        let mut pos = 0;
        while !delta.is_empty() {
            pos = match decode_instruction(&delta[pos..], 0)
                .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?
            {
                (Instruction::Copy { .. }, pos) => pos,
                (Instruction::Insert(data), pos) => {
                    // The create_delta code requires a match at least 4 characters
                    // (including only the last char of the RABIN_WINDOW) before it
                    // will consider it something worth copying rather than inserting.
                    // So we don't want to index anything that we know won't ever be a
                    // match.
                    for i in 0..data.len() - 4 {
                        let val = rabin_hash(data[i..i + RABIN_WINDOW].try_into().unwrap());
                        self.entries
                            .entry(val.into())
                            .or_default()
                            .push(IndexEntry::<'a> {
                                offset: self.last_offset + pos,
                                data: &data[i..],
                            })
                    }
                    pos
                }
            }
        }
        self.last_offset += pos + unused_bytes;
        Ok(())
    }

    // Compute index data from given buffer
    //
    // # Arguments
    //
    // * `max_bytes_to_index`: Limit the number of regions to sample to this
    //      amount of text. We will store at most max_bytes_to_index / RABIN_WINDOW
    //      pointers into the source text.  Useful if src can be unbounded in size,
    //      and you are willing to trade match accuracy for peak memory.
    pub fn add_fulltext(
        &mut self,
        src: &'a [u8],
        unused_bytes: usize,
        max_bytes_to_index: Option<usize>,
    ) {
        let stride = if let Some(max_bytes_to_index) = max_bytes_to_index {
            std::cmp::min(max_bytes_to_index, src.len()) / RABIN_WINDOW
        } else {
            RABIN_WINDOW
        };

        let mut prev_val = None;
        for i in (0..(src.len().max(RABIN_WINDOW) - RABIN_WINDOW)).step_by(stride) {
            let val = rabin_hash(src[i..i + RABIN_WINDOW].try_into().unwrap());
            if Some(val) == prev_val {
                // keep the lowest of consecutive identical hashes
            } else {
                prev_val = Some(val);
                self.entries
                    .entry(val.into())
                    .or_default()
                    .push(IndexEntry::<'a> {
                        offset: self.last_offset + i,
                        data: &src[i..],
                    })
            }
        }

        self.last_offset += src.len() + unused_bytes;
    }
}

pub fn iter_delta_instructions<'a>(
    index: &'a DeltaIndex<'a>,
    mut target: &'a [u8],
) -> impl Iterator<Item = Instruction<&'a [u8]>> + 'a {
    assert!(target.len() >= RABIN_WINDOW);
    // Start the matching by filling out with a simple 'insert' instruction, of
    // the first RABIN_WINDOW bytes of the input.
    let mut block = &target[..RABIN_WINDOW];
    let mut window = RabinWindow::new(block.try_into().unwrap());

    let mut msize = 0;
    let mut msource: Option<IndexEntry<'a>> = None;

    std::iter::from_fn(move || -> Option<Instruction<&'a [u8]>> {
        while target.len() > block.len() {
            if msize < 4096 {
                // we don't have a 'worthy enough' match yet, so let's look for
                // one.
                // Shift the window by one byte.
                (msource, msize) = index
                    .find_match(window.hash(), target, msize, Some(4096))
                    .map_or((msource, msize), |(source, msize)| (Some(source), msize));
            }

            if msize < 4 {
                // The best match right now is less than 4 bytes long. So just add
                // the current byte to the insert instruction. Increment the insert
                // counter, and copy the byte of data into the output buffer.
                block = &target[..block.len() + 1];
                window.push(block[block.len() - 1]);
                msize = 0;
                if block.len() == MAX_INSERT_SIZE {
                    // We have a max length insert instruction, finalize it in the
                    // output.
                    target = &target[block.len()..];
                    let old_block = block;
                    block = &[];
                    return Some(Instruction::Insert(old_block));
                }
            } else {
                let region = msource.unwrap();
                assert!(msize <= region.data.len());
                let copy_len = msize.min(MAX_COPY_SIZE);

                msize -= copy_len;
                msource = Some(region.add(copy_len));
                target = &target[copy_len..];
                block = &[];

                if msize < 4096 {
                    // Keep the window in sync with the target buffer.
                    for c in &region.data[(copy_len - RABIN_WINDOW).min(0)..] {
                        window.push(*c);
                    }
                }
                return Some(Instruction::Copy {
                    offset: region.offset,
                    length: copy_len,
                });
            }
        }
        if !block.is_empty() {
            let old_block = block;
            block = &[];
            target = &[];
            return Some(Instruction::Insert(old_block));
        }

        None
    })
}

pub fn create_delta<'a, W: Write>(
    mut writer: W,
    index: &DeltaIndex<'a>,
    target: &'a [u8],
    max_delta_size: Option<usize>,
) -> Result<(), DeltaError> {
    let mut size = 0;
    // store target buffer size
    size += write_base128_int(&mut writer, target.len() as u128)?;

    if target.len() < RABIN_WINDOW {
        // If the target is smaller than the Rabin window, we can't do any
        // matching, so just write out the whole target as an insert instruction.
        size += write_instruction(&mut writer, &Instruction::Insert(target))?;
        if let Some(max_delta_size) = max_delta_size {
            if size > max_delta_size {
                return Err(DeltaError::DeltaTooLarge);
            }
        }
    } else {
        for instruction in iter_delta_instructions(index, target) {
            size += write_instruction(&mut writer, &instruction)?;
            if let Some(max_delta_size) = max_delta_size {
                if size > max_delta_size {
                    return Err(DeltaError::DeltaTooLarge);
                }
            }
        }
    }

    Ok(())
}

/// Create a delta, this is a wrapper around DeltaIndex.make_delta.
pub fn make_delta(source_bytes: &[u8], target_bytes: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut di = DeltaIndex::new();
    di.add_fulltext(source_bytes, 0, None);
    create_delta(&mut out, &di, target_bytes, None).unwrap();
    out
}

#[cfg(test)]
mod tests {
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

    const TEXT3: &[u8] = b"This is a bit
of source text
which is meant to be matched
against other text
except it also
has a lot more data
at the end of the file
";

    const FIRST_TEXT: &[u8] = b"a bit of text, that
does not have much in
common with the next text
";

    const SECOND_TEXT: &[u8] = b"some more bit of text, that
does not have much in
common with the previous text
and has some extra text
";

    const THIRD_TEXT: &[u8] = b"a bit of text, that
has some in common with the previous text
and has some extra text
and not have much in
common with the next text
";

    const FOURTH_TEXT: &[u8] = b"123456789012345
same rabin hash
123456789012345
same rabin hash
123456789012345
same rabin hash
123456789012345
same rabin hash
";

    fn assert_delta(source: &[u8], target: &[u8], delta: &[u8]) {
        let mut di = super::DeltaIndex::new();
        di.add_fulltext(source, 0, None);
        let mut out = Vec::new();
        super::create_delta(&mut out, &di, target, None).unwrap();
        assert_eq!(
            delta,
            &out[..],
            "delta: {:?}",
            super::iter_delta_instructions(&di, target).collect::<Vec<_>>()
        );
    }

    #[test]
    fn test_make_noop_delta() {
        assert_delta(TEXT1, TEXT1, b"M\x90M");
        assert_delta(TEXT2, TEXT2, b"N\x90N");
        assert_delta(TEXT3, TEXT3, b"\x87\x01\x90\x87");
    }

    #[test]
    fn test_make_delta() {
        assert_delta(TEXT1, TEXT2, b"N\x90/\x1fdiffer from\nagainst other text\n");
        assert_delta(TEXT2, TEXT1, b"M\x90/\x1ebe matched\nagainst other text\n");
        assert_delta(TEXT3, TEXT1, b"M\x90M");
        assert_delta(TEXT3, TEXT2, b"N\x90/\x1fdiffer from\nagainst other text\n");
    }

    #[test]
    fn test_make_delta_with_large_copies() {
        // We want to have a copy that is larger than 64kB, which forces us to
        // issue multiple copy instructions.
        let big_text = TEXT3.repeat(1220);
        assert_delta(
            big_text.as_slice(),
            big_text.as_slice(),
            vec![
                &b"\xdc\x86\x0a"[..],     // Encoding the length of the uncompressed text
                &b"\x80"[..],             // Copy 64kB, starting at byte 0
                &b"\x84\x01"[..],         // and another 64kB starting at 64kB
                &b"\xb4\x02\x5c\x83"[..], // And the bit of tail.
            ]
            .concat()
            .as_slice(),
        )
    }
}
