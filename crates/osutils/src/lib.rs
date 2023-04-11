use memchr::memchr;

pub fn chunks_to_lines<'a, I, E>(mut chunks: I) -> impl Iterator<Item = Result<Vec<u8>, E>>
where
    I: Iterator<Item = Result<&'a [u8], E>> + 'a, E: std::fmt::Debug
{
    let mut tail: Option<Vec<u8>> = None;

    std::iter::from_fn(move || -> Option<Result<Vec<u8>, E>> {
        loop {
            // See if we can find a line in tail
            if let Some(mut chunk) = tail.take() {
                if let Some(newline) = memchr(b'\n', &chunk) {
                    if newline == chunk.len() - 1 {
                        assert!(!chunk.is_empty());
                        // The chunk ends with a newline, so it contains a single line
                        return Some(Ok(chunk));
                    } else {
                        // The chunk contains multiple lines, so split it into lines
                        let line = chunk[..=newline].to_vec();
                        assert!(!chunk.is_empty());
                        tail = Some(chunk[newline + 1..].to_vec());
                        return Some(Ok(line));
                    }
                } else {
                    if let Some(next_chunk) = chunks.next() {
                        if next_chunk.is_err() {
                            return Some(Err(next_chunk.unwrap_err()));
                        }
                        chunk.extend_from_slice(next_chunk.unwrap());
                    } else {
                        assert!(!chunk.is_empty());
                        // We've reached the end of the chunks, so return the last chunk
                        return Some(Ok(chunk));
                    }
                    if !chunk.is_empty() {
                        tail = Some(chunk);
                    }
                }
            } else {
                if let Some(next_chunk) = chunks.next() {
                    if next_chunk.is_err() {
                        return Some(Err(next_chunk.unwrap_err()));
                    }
                    let next_chunk = next_chunk.unwrap();
                    if !next_chunk.is_empty() {
                        tail = Some(next_chunk.to_vec());
                    }
                } else {
                    // We've reached the end of the chunks, so return None
                    return None;
                }
            }
        }
    })
}

pub fn set_or_unset_env(env_variable: &str, value: Option<&str>) -> Result<Option<String>, std::env::VarError> {
    let orig_val = std::env::var(env_variable);
    let ret: Option<String>;
    if let Err(std::env::VarError::NotPresent) = orig_val {
        ret = None;
        if value.is_some() {
            std::env::set_var(env_variable, value.unwrap());
        }
    } else if let Err(e) = orig_val {
        return Err(e);
    } else {
        assert!(orig_val.is_ok());
        ret = Some(orig_val.unwrap());
        match value {
            None => std::env::remove_var(env_variable),
            Some(val) => std::env::set_var(env_variable, val)
        }
    }
    Ok(ret)
}

pub mod sha;
pub mod path;

pub mod path;

#[cfg(test)]
mod tests;
