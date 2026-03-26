# Dromedary

Dromedary is a transport layer abstraction for version control systems, extracted from the [Breezy](https://www.breezy-vcs.org/) version control system.

## Overview

Dromedary provides a uniform interface for accessing files and directories across different protocols and storage backends. It supports:

- Local filesystem access
- HTTP/HTTPS for web-based repositories
- SFTP for secure remote access
- Memory-based transport for testing
- Various transport decorators for additional functionality

## Features

- Protocol abstraction layer
- Support for multiple transport protocols (file, http, https, sftp, memory)
- Transport decorators for logging, readonly access, etc.
- Comprehensive test coverage
- Well-documented API

## Installation

```bash
pip install dromedary
```

## Usage

```python
from dromedary import get_transport

# Get a transport for a local directory
transport = get_transport('/path/to/directory')

# Get a transport for an HTTP URL
transport = get_transport('http://example.com/repo')

# Use the transport
files = transport.list_dir('.')
content = transport.get('filename').read()
```

## Requirements

- Python 3.8+
- breezy (core dependency)

Optional dependencies:
- paramiko (for SFTP support)
- pygobject (for GIO transport support)

## License

GNU General Public License v2 or later (GPLv2+)