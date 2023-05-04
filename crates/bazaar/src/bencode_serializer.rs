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

    fn write_revision_to_string(&self, rev: &Revision) -> std::result::Result<Vec<u8>, Error> {
        let mut e = Encoder::new();
        e.emit_dict(|mut e| {
            e.emit_pair(b"format", 10)?;
            if let Some(committer) = rev.committer.as_ref() {
                e.emit_pair(b"committer", committer)?;
            }
            if let Some(timezone) = rev.timezone {
                e.emit_pair(b"timezone", timezone)?;
            }
            e.emit_pair(b"properties", &rev.properties)?;
            e.emit_pair(b"timestamp", format!("{:.3}", rev.timestamp))?;
            e.emit_pair(b"revision-id", &rev.revision_id.0)?;
            e.emit_pair(
                b"parent-ids",
                rev.parent_ids
                    .iter()
                    .map(|p| p.0.as_slice())
                    .collect::<Vec<&[u8]>>(),
            )?;
            if let Some(inventory_sha1) = rev.inventory_sha1.as_ref() {
                e.emit_pair(b"inventory-sha1", inventory_sha1)?;
            }
            e.emit_pair(b"message", &rev.message)?;
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

        let lines: Vec<Vec<u8>> = buf
            .split(|&c| c == b'\n')
            .map(|l| l.to_vec())
            .collect::<Vec<Vec<u8>>>();

        Box::new(lines.into_iter().map(Ok))
    }

    fn read_revision_from_string(&self, text: &[u8]) -> std::result::Result<Revision, Error> {
        let mut decoder = bendy::decoding::Decoder::new(text);
        let mut d = if let Some(Object::Dict(d)) = decoder
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
        while let Some((key, value)) = d
            .next_pair()
            .map_err(|e| Error::DecodeError(format!("failed to decode bencode: {}", e)))?
        {
            match key {
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
                b"parent_ids" => {
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
                b"revision_id" => {
                    revision_id = Some(RevisionId::from(
                        value
                            .bytes_or(Err(Error::DecodeError("invalid revision_id".to_string())))?,
                    ));
                }
                b"inventory_sha1" => {
                    inventory_sha1 = Some(
                        value
                            .bytes_or(Err(Error::DecodeError(
                                "invalid inventory_sha1".to_string(),
                            )))?
                            .to_vec(),
                    );
                }
                b"properties" => {
                    properties = Some(
                        value
                            .dictionary_or_else(|_| {
                                Err(Error::DecodeError("invalid properties".to_string()))
                            })
                            .map(|mut d| {
                                let mut ps = std::collections::HashMap::new();
                                while let Some((k, v)) = d.next_pair().map_err(|e| {
                                    Error::DecodeError(format!("failed to decode bencode: {}", e))
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
                                Ok(ps)
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
                    return Err(Error::DecodeError("unknown key".to_string()));
                }
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
