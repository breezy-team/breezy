// Protocol version strings.  These are sent as prefixes of bzr requests and
// responses to identify the protocol version being used. (There are no version
// one strings because that version doesn't send any).
pub const REQUEST_VERSION_TWO: &[u8] = b"bzr request 2\n";
pub const RESPONSE_VERSION_TWO: &[u8] = b"bzr response 2\n";

pub const MESSAGE_VERSION_THREE: &[u8] = b"bzr message 3 (bzr 1.6)\n";
pub const REQUEST_VERSION_THREE: &[u8] = MESSAGE_VERSION_THREE;
pub const RESPONSE_VERSION_THREE: &[u8] = MESSAGE_VERSION_THREE;
