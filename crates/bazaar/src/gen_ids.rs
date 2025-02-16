use breezy_osutils::rand_chars;
use lazy_regex::regex;
use lazy_static::lazy_static;
use regex::bytes::Regex;
use std::time::{SystemTime, UNIX_EPOCH};

lazy_static! {
    // the regex removes any weird characters; we don't escape them
    // but rather just pull them out

    static ref FILE_ID_CHARS_RE: Regex = Regex::new(r#"[^\w.]"#).unwrap();
    static ref REV_ID_CHARS_RE: Regex = Regex::new(r#"[^-\w.+@]"#).unwrap();
    static ref GEN_FILE_ID_SUFFIX: String = gen_file_id_suffix();
}

fn gen_file_id_suffix() -> String {
    let current_time = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let random_chars = rand_chars(16);
    format!(
        "-{}-{}-",
        breezy_osutils::time::compact_date(current_time),
        random_chars
    )
}

pub fn next_id_suffix(suffix: Option<&str>) -> Vec<u8> {
    static GEN_FILE_ID_SERIAL: std::sync::atomic::AtomicUsize =
        std::sync::atomic::AtomicUsize::new(0);

    // XXX TODO: change breezy.add.smart_add_tree to call workingtree.add() rather
    // than having to move the id randomness out of the inner loop like this.
    // XXX TODO: for the global randomness this uses we should add the thread-id
    // before the serial #.
    // XXX TODO: jam 20061102 I think it would be good to reset every 100 or
    //           1000 calls, or perhaps if time.time() increases by a certain
    //           amount. time.time() shouldn't be terribly expensive to call,
    //           and it means that long-lived processes wouldn't use the same
    //           suffix forever.
    let serial = GEN_FILE_ID_SERIAL.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    format!(
        "{}{}",
        suffix.unwrap_or(GEN_FILE_ID_SUFFIX.as_str()),
        serial
    )
    .into_bytes()
}

pub fn gen_file_id(name: &str) -> Vec<u8> {
    // The real randomness is in the _next_id_suffix, the
    // rest of the identifier is just to be nice.
    // So we:
    // 1) Remove non-ascii word characters to keep the ids portable
    // 2) squash to lowercase, so the file id doesn't have to
    //    be escaped (case insensitive filesystems would bork for ids
    //    that only differ in case without escaping).
    // 3) truncate the filename to 20 chars. Long filenames also bork on some
    // filesystems
    // 4) Removing starting '.' characters to prevent the file ids from
    //    being considered hidden.

    let name_bytes = name
        .chars()
        .filter(|c| c.is_ascii())
        .collect::<String>()
        .to_ascii_lowercase()
        .as_bytes()
        .to_vec();
    let ascii_word_only = FILE_ID_CHARS_RE
        .replace_all(&name_bytes, |_: &regex::bytes::Captures| b"")
        .to_vec();
    let without_dots = ascii_word_only
        .into_iter()
        .skip_while(|c| *c == b'.')
        .collect::<Vec<u8>>();
    let short = without_dots.iter().take(20).cloned().collect::<Vec<u8>>();
    let suffix = next_id_suffix(None);
    [short, suffix].concat()
}

pub fn gen_root_id() -> Vec<u8> {
    gen_file_id("tree_root")
}

fn get_identifier(s: &str) -> Vec<u8> {
    let mut identifier = s.to_string();
    if let Some(start) = s.find('<') {
        let end = s.rfind('>');
        if end.is_some()
            && start < end.unwrap()
            && end.unwrap() == s.len() - 1
            && s[start..].find('@').is_some()
        {
            identifier = s[start + 1..end.unwrap()].to_string();
        }
    }
    let identifier: String = identifier
        .to_ascii_lowercase()
        .replace(' ', "_")
        .chars()
        .filter(|c| c.is_ascii())
        .collect();
    REV_ID_CHARS_RE
        .replace_all(identifier.as_bytes(), |_: &regex::bytes::Captures| b"")
        .to_vec()
}

pub fn gen_revision_id(username: &str, timestamp: Option<u64>) -> Vec<u8> {
    let user_or_email = get_identifier(username);
    // This gives 36^16 ~= 2^82.7 ~= 83 bits of entropy
    let unique_chunk = breezy_osutils::rand_chars(16).as_bytes().to_vec();
    let timestamp = timestamp.unwrap_or_else(|| {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
    });
    vec![
        user_or_email,
        breezy_osutils::time::compact_date(timestamp)
            .as_bytes()
            .to_vec(),
        unique_chunk,
    ]
    .join(&b'-')
}
