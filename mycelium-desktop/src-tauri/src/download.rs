// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Downloading an update into a file that a dropped connection can resume.
//!
//! The archive is a few hundred megabytes. It is written to a partial file as
//! it arrives, and each attempt asks only for the bytes after what's already
//! there (an HTTP `Range` request; GitHub's release downloads honour it). A
//! server that answers with the whole file instead starts the file over. Each
//! attempt ends in one of three ways: the file is complete, the connection
//! went and it's worth trying again ([`Failed::Retry`]), or something no retry
//! fixes, such as a missing file or a full disk ([`Failed::Stop`]).

use std::io::{ErrorKind, Write};
use std::path::Path;
use std::time::Duration;

use futures_util::StreamExt;
use reqwest::header::{HeaderMap, HeaderValue, ACCEPT, CONTENT_RANGE, RANGE};
use reqwest::StatusCode;

/// Why an attempt ended before the file was complete, in words for the window.
#[derive(Debug, PartialEq, Eq)]
pub enum Failed {
    /// The connection dropped or the server stumbled: try again shortly.
    Retry(String),
    /// Trying again won't help.
    Stop(String),
}

fn retry(why: impl ToString) -> Failed {
    Failed::Retry(why.to_string())
}

/// The HTTP client a download uses. A read that stalls this long counts as a
/// dropped connection, since a network that goes away often says nothing.
pub fn client(proxy: Option<&str>, no_proxy: bool) -> Result<reqwest::Client, String> {
    // The TLS setup the updater plugin makes for itself; a second install is a no-op.
    let _ = rustls::crypto::ring::default_provider().install_default();
    let mut builder = reqwest::Client::builder()
        .user_agent(concat!("mycelium-desktop/", env!("CARGO_PKG_VERSION")))
        .connect_timeout(Duration::from_secs(15))
        .read_timeout(Duration::from_secs(30));
    if no_proxy {
        builder = builder.no_proxy();
    } else if let Some(proxy) = proxy {
        builder = builder.proxy(reqwest::Proxy::all(proxy).map_err(|e| e.to_string())?);
    }
    builder.build().map_err(|e| e.to_string())
}

/// How many bytes the partial file at `path` already holds.
pub fn held(path: &Path) -> u64 {
    std::fs::metadata(path).map(|m| m.len()).unwrap_or(0)
}

/// The total size in a `Content-Range` header (`bytes 100-199/1000`, or
/// `bytes */1000` on a 416), when it gives one.
fn range_total(headers: &HeaderMap) -> Option<u64> {
    let value = headers.get(CONTENT_RANGE)?.to_str().ok()?;
    value.rsplit('/').next()?.parse().ok()
}

/// The first byte a `206 Partial Content` answer starts at.
fn range_start(headers: &HeaderMap) -> Option<u64> {
    let value = headers.get(CONTENT_RANGE)?.to_str().ok()?;
    let range = value.strip_prefix("bytes ")?.split('/').next()?;
    range.split('-').next()?.parse().ok()
}

fn content_length(headers: &HeaderMap) -> Option<u64> {
    headers.get(reqwest::header::CONTENT_LENGTH)?.to_str().ok()?.parse().ok()
}

fn disk_error(e: &std::io::Error) -> Failed {
    if e.kind() == ErrorKind::StorageFull {
        Failed::Stop("the disk is full".into())
    } else {
        Failed::Stop(format!("couldn't save the download: {e}"))
    }
}

/// One attempt to bring the file at `path` up to the whole of `url`.
///
/// `on_progress` hears the bytes on disk and the total, when known, as they
/// arrive. Returns once the file holds the whole download.
pub async fn attempt(
    client: &reqwest::Client,
    url: &str,
    headers: &HeaderMap,
    path: &Path,
    on_progress: &mut (dyn FnMut(u64, Option<u64>) + Send),
) -> Result<(), Failed> {
    let have = held(path);
    let mut request = client.get(url).headers(headers.clone());
    if !headers.contains_key(ACCEPT) {
        request = request.header(ACCEPT, HeaderValue::from_static("application/octet-stream"));
    }
    if have > 0 {
        request = request.header(RANGE, format!("bytes={have}-"));
    }
    let response = request.send().await.map_err(|e| retry(format!("the connection failed: {e}")))?;
    let status = response.status();

    // Where this answer's bytes go in the file, and how big the whole is.
    let (start, total) = match status {
        StatusCode::PARTIAL_CONTENT => {
            let total = range_total(response.headers());
            match range_start(response.headers()) {
                Some(start) if start == have => (have, total),
                // Not the range asked for: start the file over.
                _ => {
                    let _ = std::fs::remove_file(path);
                    return Err(retry("the server sent a different part of the file"));
                }
            }
        }
        // The whole file, whether or not a range was asked for.
        s if s.is_success() => (0, content_length(response.headers())),
        StatusCode::RANGE_NOT_SATISFIABLE => {
            // Nothing after what's held: either it's all here, or the file is
            // not the one the server has, and it starts over.
            if range_total(response.headers()) == Some(have) {
                on_progress(have, Some(have));
                return Ok(());
            }
            let _ = std::fs::remove_file(path);
            return Err(retry("the saved part didn't match the download"));
        }
        s if s.is_server_error() || s == StatusCode::TOO_MANY_REQUESTS => {
            return Err(retry(format!("the server answered {s}")));
        }
        s => return Err(Failed::Stop(format!("the download isn't available (the server answered {s})"))),
    };

    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .append(start > 0)
        .truncate(start == 0)
        .open(path)
        .map_err(|e| disk_error(&e))?;
    let mut on_disk = start;
    on_progress(on_disk, total);
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = match chunk {
            Ok(chunk) => chunk,
            Err(e) => {
                let _ = file.flush();
                return Err(retry(format!("the connection dropped: {e}")));
            }
        };
        file.write_all(&chunk).map_err(|e| disk_error(&e))?;
        on_disk += chunk.len() as u64;
        on_progress(on_disk, total);
    }
    file.flush().map_err(|e| disk_error(&e))?;
    match total {
        Some(total) if on_disk < total => Err(retry("the connection closed early")),
        Some(total) if on_disk > total => {
            let _ = std::fs::remove_file(path);
            Err(retry("the download came out longer than expected"))
        }
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader};
    use std::net::TcpListener;
    use std::sync::{Arc, Mutex};

    const BODY: &[u8] = b"0123456789abcdefghijklmnopqrstuvwxyz";

    /// How the test server answers.
    #[derive(Clone, Copy, Default)]
    struct Serve {
        /// Drop the connection after this many bytes of body.
        cut_after: Option<usize>,
        /// Answer this status with no body.
        status: Option<u16>,
        /// Send the whole file even when a range was asked for.
        ignore_range: bool,
    }

    /// A one-file HTTP server on localhost that honours `Range` unless told
    /// not to. Returns its URL and the `Range` of every request it got.
    fn serve(how: Serve) -> (String, Arc<Mutex<Vec<String>>>) {
        let Serve { cut_after, status, ignore_range } = how;
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}/update.tar.gz", listener.local_addr().unwrap());
        let ranges = Arc::new(Mutex::new(Vec::new()));
        let seen = ranges.clone();
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let mut stream = stream.unwrap();
                let mut reader = BufReader::new(stream.try_clone().unwrap());
                let mut range = String::new();
                loop {
                    let mut line = String::new();
                    if reader.read_line(&mut line).unwrap_or(0) == 0 || line == "\r\n" {
                        break;
                    }
                    if let Some(value) = line.to_ascii_lowercase().strip_prefix("range: bytes=") {
                        range = value.trim().trim_end_matches('-').to_string();
                    }
                }
                seen.lock().unwrap().push(range.clone());
                if let Some(status) = status {
                    let _ = write!(stream, "HTTP/1.1 {status} Nope\r\nContent-Length: 0\r\n\r\n");
                    continue;
                }
                let from: usize = if ignore_range { 0 } else { range.parse().unwrap_or(0) };
                let part = &BODY[from..];
                let head = if from > 0 {
                    format!(
                        "HTTP/1.1 206 Partial Content\r\nContent-Length: {}\r\nContent-Range: bytes {from}-{}/{}\r\n\r\n",
                        part.len(),
                        BODY.len() - 1,
                        BODY.len()
                    )
                } else {
                    format!("HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n", part.len())
                };
                let _ = stream.write_all(head.as_bytes());
                let send = cut_after.map_or(part.len(), |n| n.min(part.len()));
                let _ = stream.write_all(&part[..send]);
                // Close the connection, early or not, as a dropped network would.
                let _ = stream.flush();
                let _ = stream.shutdown(std::net::Shutdown::Both);
            }
        });
        (url, ranges)
    }

    fn client() -> reqwest::Client {
        super::client(None, true).unwrap()
    }

    #[tokio::test]
    async fn a_dropped_connection_resumes_from_what_is_on_disk() {
        let dir = tempdir();
        let path = dir.join("update.part");
        let (cut_url, _) = serve(Serve { cut_after: Some(10), ..Serve::default() });
        let mut seen = Vec::new();
        let first = attempt(&client(), &cut_url, &HeaderMap::new(), &path, &mut |n, t| seen.push((n, t))).await;
        assert!(matches!(first, Err(Failed::Retry(_))), "{first:?}");
        assert_eq!(held(&path), 10);
        assert_eq!(seen.last(), Some(&(10, Some(BODY.len() as u64))));

        let (url, ranges) = serve(Serve::default());
        let second = attempt(&client(), &url, &HeaderMap::new(), &path, &mut |_, _| {}).await;
        assert_eq!(second, Ok(()));
        assert_eq!(std::fs::read(&path).unwrap(), BODY);
        // It asked only for the bytes it didn't have.
        assert_eq!(ranges.lock().unwrap().as_slice(), ["10"]);
    }

    #[tokio::test]
    async fn a_whole_file_answer_starts_the_file_over() {
        let dir = tempdir();
        let path = dir.join("update.part");
        // Bytes on disk, and a server that ignores the range and sends it all.
        std::fs::write(&path, b"0123456789").unwrap();
        let (url, ranges) = serve(Serve { ignore_range: true, ..Serve::default() });
        let done = attempt(&client(), &url, &HeaderMap::new(), &path, &mut |_, _| {}).await;
        assert_eq!(done, Ok(()));
        // Written once, from the start, rather than appended after what was held.
        assert_eq!(std::fs::read(&path).unwrap(), BODY);
        assert_eq!(ranges.lock().unwrap().as_slice(), ["10"]);
    }

    #[tokio::test]
    async fn a_missing_file_stops_and_a_server_error_retries() {
        let dir = tempdir();
        let path = dir.join("update.part");
        let (gone, _) = serve(Serve { status: Some(404), ..Serve::default() });
        let stop = attempt(&client(), &gone, &HeaderMap::new(), &path, &mut |_, _| {}).await;
        assert!(matches!(stop, Err(Failed::Stop(ref why)) if why.contains("404")), "{stop:?}");
        let (busy, _) = serve(Serve { status: Some(503), ..Serve::default() });
        let again = attempt(&client(), &busy, &HeaderMap::new(), &path, &mut |_, _| {}).await;
        assert!(matches!(again, Err(Failed::Retry(_))), "{again:?}");
    }

    #[tokio::test]
    async fn no_server_at_all_is_worth_retrying() {
        let dir = tempdir();
        let path = dir.join("update.part");
        let closed = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}/x", closed.local_addr().unwrap());
        drop(closed);
        let result = attempt(&client(), &url, &HeaderMap::new(), &path, &mut |_, _| {}).await;
        assert!(matches!(result, Err(Failed::Retry(_))), "{result:?}");
    }

    fn tempdir() -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "mycelium-download-{}-{}",
            std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }
}
