use crate::inventory::Entry;

/// Serialise entry as a single bytestring.
///
/// :param Entry: An inventory entry.
/// :return: A bytestring for the entry.
///
/// The BNF:
/// ENTRY ::= FILE | DIR | SYMLINK | TREE
/// FILE ::= "file: " COMMON SEP SHA SEP SIZE SEP EXECUTABLE
/// DIR ::= "dir: " COMMON
/// SYMLINK ::= "symlink: " COMMON SEP TARGET_UTF8
/// TREE ::= "tree: " COMMON REFERENCE_REVISION
/// COMMON ::= FILE_ID SEP PARENT_ID SEP NAME_UTF8 SEP REVISION
/// SEP ::= "\n"
pub fn chk_inventory_entry_to_bytes(entry: &Entry) -> Vec<u8> {
    let ts;

    let (header, mut lines) = match entry {
        Entry::File {
            name,
            executable,
            revision,
            text_sha1,
            text_size,
            parent_id,
            ..
        } => {
            ts = format!("{}", text_size.expect("no text size set"));

            (
                &b"file"[..],
                vec![
                    parent_id.as_bytes(),
                    name.as_bytes(),
                    revision.as_ref().expect("no revision set").as_bytes(),
                    text_sha1.as_ref().expect("no text sha1 set").as_slice(),
                    ts.as_bytes(),
                    if *executable { b"Y" } else { b"N" },
                ],
            )
        }
        Entry::Directory {
            revision,
            name,
            parent_id,
            ..
        } => (
            &b"dir"[..],
            vec![
                parent_id.as_bytes(),
                name.as_bytes(),
                revision.as_ref().expect("no revision set").as_bytes(),
            ],
        ),
        Entry::Root { revision, .. } => (
            &b"dir"[..],
            vec![
                &b""[..],
                &b""[..],
                revision.as_ref().expect("no revision set").as_bytes(),
            ],
        ),
        Entry::Link {
            name,
            revision,
            symlink_target,
            parent_id,
            ..
        } => (
            &b"symlink"[..],
            vec![
                parent_id.as_bytes(),
                name.as_bytes(),
                revision.as_ref().expect("no revision set").as_bytes(),
                symlink_target
                    .as_ref()
                    .expect("no symlink target set")
                    .as_bytes(),
            ],
        ),
        Entry::TreeReference {
            revision,
            name,
            reference_revision,
            parent_id,
            ..
        } => (
            &b"tree"[..],
            vec![
                parent_id.as_bytes(),
                name.as_bytes(),
                revision.as_ref().expect("no revision set").as_bytes(),
                reference_revision
                    .as_ref()
                    .expect("no reference revision set")
                    .as_bytes(),
            ],
        ),
    };

    let header = [header, b": ", entry.file_id().as_bytes()].concat();

    lines.insert(0, header.as_slice());

    lines.join(&b"\n"[..])
}

pub fn chk_inventory_bytes_to_entry(data: &[u8]) -> Entry {
    let sections = data.split(|&c| c == b'\n').collect::<Vec<_>>();

    let sp: Vec<&[u8]> = sections[0].splitn(2, |&c| c == b':').collect();
    assert!(&sp[1][..1] == b" ");

    let kind = sp[0];
    let file_id = crate::FileId::from(&sp[1][1..]);

    let name = String::from_utf8(sections[2].to_vec()).unwrap();
    let parent_id = if sections[1].is_empty() {
        None
    } else {
        Some(crate::FileId::from(sections[1]))
    };
    let revision = Some(crate::RevisionId::from(sections[3]));

    match String::from_utf8(kind.to_vec()).unwrap().as_str() {
        "file" => Entry::File {
            name,
            file_id,
            parent_id: parent_id.unwrap(),
            text_sha1: Some(sections[4].to_vec()),
            text_size: Some(
                String::from_utf8(sections[5].to_vec())
                    .unwrap()
                    .parse()
                    .unwrap(),
            ),
            executable: sections[6] == b"Y",
            revision,
            text_id: None,
        },
        "dir" => {
            if let Some(parent_id) = parent_id {
                Entry::Directory {
                    name,
                    file_id,
                    parent_id,
                    revision,
                }
            } else {
                Entry::Root { file_id, revision }
            }
        }
        "symlink" => Entry::Link {
            name,
            file_id,
            parent_id: parent_id.unwrap(),
            symlink_target: Some(String::from_utf8(sections[4].to_vec()).unwrap()),
            revision,
        },
        "tree" => Entry::TreeReference {
            name,
            file_id,
            parent_id: parent_id.unwrap(),
            reference_revision: Some(crate::RevisionId::from(sections[4])),
            revision,
        },
        _ => {
            panic!("Invalid inventory entry");
        }
    }
}

pub fn chk_inventory_bytes_to_utf8_name_key(
    data: &[u8],
) -> (&[u8], crate::FileId, crate::RevisionId) {
    let sections = data.split(|&c| c == b'\n').collect::<Vec<_>>();
    let sp: Vec<&[u8]> = sections[0].splitn(2, |&c| c == b':').collect();
    assert!(&sp[1][..1] == b" ");

    let file_id = crate::FileId::from(&sp[1][1..]);
    let revision = crate::RevisionId::from(sections[3]);
    (sections[2], file_id, revision)
}
