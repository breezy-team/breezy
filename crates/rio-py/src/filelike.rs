use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::io::{self, Write, Read};

pub struct PyFileLikeObject {
    file_like: PyObject,
}

impl PyFileLikeObject {
    pub fn new(file_like: PyObject) -> Self {
        PyFileLikeObject { file_like }
    }
}

impl Write for PyFileLikeObject {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let gil = Python::acquire_gil();
        let py = gil.python();
        let py_buffer = PyBytes::new(py, buf);

        match self.file_like.call_method(py, "write", (py_buffer,), None) {
            Ok(py_result) => {
                let written_size = py_result
                    .extract::<usize>(py)
                    .map_err(|_| io::Error::new(io::ErrorKind::Other, "Failed to extract write size"))?;
                Ok(written_size)
            }
            Err(e) => {
                e.print(py);
                Err(io::Error::new(io::ErrorKind::Other, "Failed to call write method"))
            }
        }
    }

    fn flush(&mut self) -> io::Result<()> {
        let gil = Python::acquire_gil();
        let py = gil.python();

        match self.file_like.call_method(py, "flush", (), None) {
            Ok(_) => Ok(()),
            Err(e) => {
                e.print(py);
                Err(io::Error::new(io::ErrorKind::Other, "Failed to call flush method"))
            }
        }
    }
}

impl Read for PyFileLikeObject {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        let gil = Python::acquire_gil();
        let py = gil.python();

        match self.file_like.call_method(py, "read", (buf.len(),), None) {
            Ok(py_result) => {
                let py_buffer = py_result.downcast::<PyBytes>(py).map_err(|_| {
                    io::Error::new(io::ErrorKind::Other, "Failed to downcast read result")
                })?;
                let read_size = py_buffer.len()?;
                buf[..read_size].copy_from_slice(py_buffer.as_bytes());
                Ok(read_size)
            }
            Err(e) => {
                e.print(py);
                Err(io::Error::new(io::ErrorKind::Other, "Failed to call read method"))
            }
        }
    }
}

