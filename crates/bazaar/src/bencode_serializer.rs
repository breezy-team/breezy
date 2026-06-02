use crate::revision::Revision;
use crate::serializer::{Error, RevisionSerializer};
use crate::RevisionId;
use bendy::decoding::Object;
use bendy::encoding::Encoder;
use std::io::BufRead;
use std::io::Read;

pub struct BEncodeRevisionSerializer1;

impl RevisionSerializer for BEncodeRevisionSerializer1 {
    fn format_name(&self) -> &'static str {
        "10"
    }

    fn squashes_xml_invalid_characters(&self) -> bool {
        false
    }

    fn write_revision_to_string(&self, rev: &Revision) -> std::result::Result<Vec<u8>, Error> {
        let mut e = Encoder::new();
        e.emit_list(|e| {
            e.emit_list(|e| {
                e.emit_bytes(b"format")?;
                e.emit_int(10)?;
                Ok(())
            })?;
            if let Some(committer) = rev.committer.as_ref() {
                e.emit_list(|e| {
                    e.emit_bytes(b"committer")?;
                    e.emit_bytes(committer.as_bytes())?;
                    Ok(())
                })?;
            }
            if let Some(timezone) = rev.timezone {
                e.emit_list(|e| {
                    e.emit_bytes(b"timezone")?;
                    e.emit_int(timezone)?;
                    Ok(())
                })?;
            }
            e.emit_list(|e| {
                e.emit_bytes(b"properties")?;
                e.emit_dict(|mut e| {
                    let mut keys = rev.properties.keys().collect::<Vec<&String>>();
                    keys.sort_by_key(|k| k.as_bytes());
                    for k in keys {
                        let v = rev.properties.get(k).unwrap();
                        e.emit_pair_with(k.as_bytes(), |e| {
                            e.emit_bytes(v)?;
                            Ok(())
                        })?;
                    }
                    Ok(())
                })?;
                Ok(())
            })?;
            e.emit_list(|e| {
                e.emit_bytes(b"timestamp")?;
                e.emit_bytes(format!("{:.3}", rev.timestamp).as_bytes())?;
                Ok(())
            })?;
            e.emit_list(|e| {
                e.emit_bytes(b"revision-id")?;
                e.emit_bytes(rev.revision_id.0.as_slice())?;
                Ok(())
            })?;
            e.emit_list(|e| {
                e.emit_bytes(b"parent-ids")?;
                e.emit_list(|e| {
                    for p in rev.parent_ids.iter() {
                        e.emit_bytes(p.0.as_slice())?;
                    }
                    Ok(())
                })?;
                Ok(())
            })?;
            if let Some(inventory_sha1) = rev.inventory_sha1.as_ref() {
                e.emit_list(|e| {
                    e.emit_bytes(b"inventory-sha1")?;
                    e.emit_bytes(inventory_sha1.as_slice())?;
                    Ok(())
                })?;
            }
            e.emit_list(|e| {
                e.emit_bytes(b"message")?;
                e.emit_bytes(rev.message.as_bytes())?;
                Ok(())
            })?;
            Ok(())
        })
        .map_err(|e| Error::EncodeError(format!("failed to encode revision: {}", e)))?;
        e.get_output()
            .map_err(|e| Error::EncodeError(format!("failed to encode revision: {}", e)))
    }

    fn write_revision_to_lines(
        &self,
        rev: &Revision,
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>>> {
        let buf = self.write_revision_to_string(rev);

        if let Err(e) = buf {
            return Box::new(std::iter::once(Err(e)));
        }

        let buf = buf.unwrap();

        let mut cursor = std::io::Cursor::new(buf);

        Box::new(std::iter::from_fn(move || {
            let mut buf = Vec::new();
            if let Err(e) = cursor.read_until(b'\n', &mut buf) {
                return Some(Err(Error::EncodeError(format!(
                    "failed to encode revision: {}",
                    e
                ))));
            }
            if buf.is_empty() {
                None
            } else {
                Some(Ok(buf))
            }
        }))
    }

    fn read_revision_from_string(&self, text: &[u8]) -> std::result::Result<Revision, Error> {
        let mut decoder = bendy::decoding::Decoder::new(text);
        let mut d = if let Some(Object::List(d)) = decoder
            .next_object()
            .map_err(|e| Error::DecodeError(format!("failed to decode bencode: {}", e)))?
        {
            d
        } else {
            return Err(Error::DecodeError("expected dict".to_string()));
        };
        let mut timestamp = None;
        let mut timezone = None;
        let mut committer = None;
        let mut properties = None;
        let mut message = None;
        let mut parent_ids = None;
        let mut revision_id = None;
        let mut inventory_sha1 = None;
        while let Some(entry) = d
            .next_object()
            .map_err(|e| Error::DecodeError(format!("failed to decode bencode: {}", e)))?
        {
            let mut tuple =
                entry.list_or_else(|_| Err(Error::DecodeError("expected tuple".to_string())))?;
            let key = tuple
                .next_object()
                .map_err(|e| Error::DecodeError(format!("expected tuple with key: {}", e)))?
                .ok_or_else(|| Error::DecodeError("expected tuple with key".to_string()))?
                .bytes_or_else(|_| {
                    Err(Error::DecodeError("expected tuple with key".to_string()))
                })?;
            let value = tuple
                .next_object()
                .map_err(|e| Error::DecodeError(format!("expected tuple with value: {}", e)))?
                .ok_or_else(|| Error::DecodeError("expected tuple with value".to_string()))?;
            match key {
                b"format" => {
                    if value
                        .integer_or(Err(Error::DecodeError("invalid format".to_string())))?
                        .parse::<u64>()
                        .map_err(|e| Error::DecodeError(format!("invalid format: {}", e)))?
                        != 10
                    {
                        return Err(Error::DecodeError("invalid format".to_string()));
                    }
                }
                b"timezone" => {
                    timezone = Some(
                        value
                            .integer_or(Err(Error::DecodeError("invalid timezone".to_string())))?
                            .parse()
                            .map_err(|e| Error::DecodeError(format!("invalid timezone: {}", e)))?,
                    );
                }
                b"timestamp" => {
                    timestamp = Some(
                        String::from_utf8(
                            value
                                .bytes_or(Err(Error::DecodeError("invalid timestamp".to_string())))?
                                .to_vec(),
                        )
                        .map_err(|e| Error::DecodeError(format!("invalid timestamp: {}", e)))?
                        .parse::<f64>()
                        .map_err(|e| Error::DecodeError(format!("invalid timestamp: {}", e)))?,
                    );
                }
                b"committer" => {
                    committer = Some(
                        String::from_utf8(
                            value
                                .bytes_or(Err(Error::DecodeError("invalid committer".to_string())))?
                                .to_vec(),
                        )
                        .map_err(|e| Error::DecodeError(format!("invalid committer: {}", e)))?,
                    );
                }
                b"parent-ids" => {
                    let mut ps =
                        value.list_or(Err(Error::DecodeError("invalid parent_ids".to_string())))?;
                    let mut gs = Vec::new();
                    while let Some(o) = ps.next_object().map_err(|e| {
                        Error::DecodeError(format!("failed to decode bencode: {}", e))
                    })? {
                        let p = RevisionId::from(
                            o.bytes_or(Err(Error::DecodeError("invalid parent_id".to_string())))?,
                        );
                        gs.push(p);
                    }
                    parent_ids = Some(gs);
                }
                b"revision-id" => {
                    revision_id = Some(RevisionId::from(
                        value
                            .bytes_or(Err(Error::DecodeError("invalid revision_id".to_string())))?,
                    ));
                }
                b"inventory-sha1" => {
                    inventory_sha1 = Some(
                        value
                            .bytes_or(Err(Error::DecodeError(
                                "invalid inventory_sha1".to_string(),
                            )))?
                            .to_vec(),
                    );
                }
                b"properties" => {
                    properties =
                        Some(
                            value
                                .dictionary_or_else(|_| {
                                    Err(Error::DecodeError("invalid properties".to_string()))
                                })
                                .map(|mut d| {
                                    let mut ps = std::collections::HashMap::new();
                                    while let Some((k, v)) = d.next_pair().map_err(|e| {
                                        Error::DecodeError(format!(
                                            "failed to decode bencode: {}",
                                            e
                                        ))
                                    })? {
                                        let v = v
                                            .bytes_or(Err(Error::DecodeError(format!(
                                                "invalid property {}",
                                                String::from_utf8_lossy(k)
                                            ))))?
                                            .to_vec();
                                        let k = String::from_utf8(k.to_vec()).map_err(|e| {
                                            Error::DecodeError(format!(
                                                "invalid property {}: {}",
                                                String::from_utf8_lossy(k),
                                                e
                                            ))
                                        })?;
                                        ps.insert(k, v);
                                    }
                                    Ok::<
                                        std::collections::HashMap<std::string::String, Vec<u8>>,
                                        Error,
                                    >(ps)
                                })??,
                        );
                }
                b"message" => {
                    message = Some(
                        String::from_utf8(
                            value
                                .bytes_or(Err(Error::DecodeError("invalid message".to_string())))?
                                .to_vec(),
                        )
                        .map_err(|e| Error::DecodeError(format!("invalid message: {}", e)))?,
                    );
                }
                _ => {
                    return Err(Error::DecodeError(format!(
                        "unknown key {}",
                        String::from_utf8_lossy(key)
                    )));
                }
            }
            if tuple
                .next_object()
                .map_err(|e| Error::DecodeError(format!("expected tuple: {}", e)))?
                .is_some()
            {
                return Err(Error::DecodeError("extra item in tuple".to_string()));
            }
        }

        Ok(Revision::new(
            revision_id.ok_or(Error::DecodeError("missing revision_id".to_string()))?,
            parent_ids.ok_or(Error::DecodeError("missing parent_ids".to_string()))?,
            committer,
            message.ok_or(Error::DecodeError("missing message".to_string()))?,
            properties.ok_or(Error::DecodeError("missing properties".to_string()))?,
            inventory_sha1,
            timestamp.ok_or(Error::DecodeError("missing timestamp".to_string()))?,
            timezone,
        ))
    }

    fn read_revision(&self, f: &mut dyn Read) -> std::result::Result<Revision, Error> {
        let mut buf = Vec::new();
        f.read_to_end(&mut buf).map_err(Error::IOError)?;
        self.read_revision_from_string(&buf)
    }
}

#[allow(dead_code)]
const BENCODE_REVISION_SERIALIZER_V1: BEncodeRevisionSerializer1 = BEncodeRevisionSerializer1 {};
