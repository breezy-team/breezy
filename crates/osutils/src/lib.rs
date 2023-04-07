use memchr::memchr;

pub fn chunks_to_lines<'a, I>(mut chunks: I) -> impl Iterator<Item = Vec<u8>>
where
    I: Iterator<Item = &'a [u8]> + 'a,
{
    let mut tail: Option<Vec<u8>> = None;

    std::iter::from_fn(move || -> Option<Vec<u8>> {
        loop {
            // See if we can find a line in tail
            if let Some(mut chunk) = tail.take() {
                if let Some(newline) = memchr(b'\n', &chunk) {
                    if newline == chunk.len() - 1 {
                        // The chunk ends with a newline, so it contains a single line
                        return Some(chunk);
                    } else {
                        // The chunk contains multiple lines, so split it into lines
                        let line = chunk[..=newline].to_vec();
                        tail = Some(chunk[newline + 1..].to_vec());
                        return Some(line);
                    }
                } else {
                    let next_chunk = chunks.next();
                    if next_chunk.is_none() {
                        // We've reached the end of the chunks, so return the last chunk
                        return Some(chunk);
                    }
                    chunk.extend_from_slice(next_chunk.unwrap());
                    tail = Some(chunk);
                }
            } else {
                let next_chunk = chunks.next()?;
                tail = Some(next_chunk.to_vec());
            }
        }
    })
}
