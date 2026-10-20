// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Signing a person in, in the app: OIDC Authorization Code with PKCE, in the
//! system browser, redirected back to a listener on this machine's loopback.
//!
//! The same flow as the CLI's (`mycelium.oidc.authorization_code_login`), run
//! here so the refresh token it brings back is only ever in the app. The CLI
//! asks for it (`mycelium login`, a `login` request through the supervisor)
//! and gets an access token alone.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use base64::Engine;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use url::Url;

/// How long the browser has to come back.
pub const WAIT: Duration = Duration::from_secs(300);
/// Where the provider sends the browser back to.
const CALLBACK_PATH: &str = "/callback";

/// What the CLI asked the app to sign in with: its issuer and client, the
/// scopes and audience to ask for, and the loopback port the provider
/// expects (0 for any).
#[derive(Debug, Clone, PartialEq)]
pub struct Request {
    pub issuer: String,
    pub client_id: String,
    pub scope: String,
    pub audience: Option<String>,
    pub redirect_port: u16,
}

impl Request {
    pub fn of(login: &Value) -> Result<Self, String> {
        let text = |k: &str| login.get(k).and_then(Value::as_str).map(str::trim).filter(|s| !s.is_empty());
        let issuer = text("issuer").ok_or("no issuer to sign in with")?;
        let issuer = Url::parse(issuer).map_err(|_| "the issuer isn't a URL".to_string())?;
        if !matches!(issuer.scheme(), "https" | "http") {
            return Err("the issuer isn't a web address".into());
        }
        Ok(Self {
            issuer: issuer.as_str().trim_end_matches('/').to_string(),
            client_id: text("client_id").ok_or("no client id to sign in as")?.to_string(),
            scope: text("scope").unwrap_or("openid").to_string(),
            audience: text("audience").map(String::from),
            redirect_port: login
                .get("redirect_port")
                .and_then(Value::as_u64)
                .and_then(|p| u16::try_from(p).ok())
                .unwrap_or(0),
        })
    }
}

fn now() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

fn random_b64(bytes: usize) -> String {
    let mut buf = vec![0u8; bytes];
    getrandom::fill(&mut buf).expect("the system's random source");
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(buf)
}

/// A PKCE verifier and its S256 challenge.
fn pkce() -> (String, String) {
    let verifier = random_b64(48);
    let challenge = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()));
    (verifier, challenge)
}

fn get_json(url: &str) -> Result<Value, String> {
    let url = url.to_string();
    tauri::async_runtime::block_on(async move {
        let resp = crate::download::client(None, false)?.get(&url).send().await.map_err(|e| e.to_string())?;
        let status = resp.status();
        let bytes = resp.bytes().await.map_err(|e| e.to_string())?;
        if !status.is_success() {
            return Err(format!("{url} answered {status}"));
        }
        serde_json::from_slice(&bytes).map_err(|e| e.to_string())
    })
}

fn post_form(url: &str, form: &[(&str, &str)]) -> Result<Value, String> {
    let body = url::form_urlencoded::Serializer::new(String::new()).extend_pairs(form).finish();
    let url = url.to_string();
    tauri::async_runtime::block_on(async move {
        let resp = crate::download::client(None, false)?
            .post(&url)
            .header(reqwest::header::CONTENT_TYPE, "application/x-www-form-urlencoded")
            .body(body)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        let status = resp.status();
        let bytes = resp.bytes().await.map_err(|e| e.to_string())?;
        let answer: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
        if !status.is_success() {
            let error = answer.get("error").and_then(Value::as_str).unwrap_or("refused");
            let detail = answer.get("error_description").and_then(Value::as_str);
            return Err(detail.map_or(error.to_string(), |d| format!("{error}: {d}")));
        }
        Ok(answer)
    })
}

/// Sign in, in the browser, and return the session to keep (refresh token
/// included), in the CLI's `StoredToken` shape.
pub fn sign_in(req: &Request) -> Result<Value, String> {
    let meta = get_json(&format!("{}/.well-known/openid-configuration", req.issuer))?;
    let advertised = meta.get("issuer").and_then(Value::as_str).unwrap_or_default();
    if advertised.trim_end_matches('/') != req.issuer {
        return Err(format!("{} says its issuer is {advertised}", req.issuer));
    }
    let endpoint = |k: &str| meta.get(k).and_then(Value::as_str).map(String::from).ok_or(format!("the provider names no {k}"));
    let authorize = endpoint("authorization_endpoint")?;
    let token_endpoint = endpoint("token_endpoint")?;

    let listener = TcpListener::bind(("127.0.0.1", req.redirect_port))
        .map_err(|e| format!("can't listen on port {} for the browser: {e}", req.redirect_port))?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    let redirect_uri = format!("http://127.0.0.1:{port}{CALLBACK_PATH}");
    let (verifier, challenge) = pkce();
    let state = random_b64(24);
    let mut query = vec![
        ("response_type", "code"),
        ("client_id", req.client_id.as_str()),
        ("redirect_uri", redirect_uri.as_str()),
        ("scope", req.scope.as_str()),
        ("state", state.as_str()),
        ("code_challenge", challenge.as_str()),
        ("code_challenge_method", "S256"),
    ];
    if let Some(audience) = &req.audience {
        query.push(("audience", audience));
    }
    let url = Url::parse_with_params(&authorize, &query).map_err(|e| e.to_string())?;
    crate::paths::open(std::ffi::OsStr::new(url.as_str())).map_err(|e| format!("can't open the browser: {e}"))?;

    let params = wait_for_redirect(&listener, WAIT)?;
    if let Some(error) = params.iter().find(|(k, _)| k == "error").map(|(_, v)| v.clone()) {
        let detail = params.iter().find(|(k, _)| k == "error_description").map(|(_, v)| v.as_str());
        return Err(detail.map_or(error.clone(), |d| format!("{error}: {d}")));
    }
    let given = params.iter().find(|(k, _)| k == "state").map(|(_, v)| v.as_str()).unwrap_or_default();
    if !same(given, &state) {
        return Err("the browser came back from a sign-in this app didn't start".into());
    }
    let code = params.iter().find(|(k, _)| k == "code").map(|(_, v)| v.clone()).ok_or("no code came back")?;
    let grant = post_form(
        &token_endpoint,
        &[
            ("grant_type", "authorization_code"),
            ("code", &code),
            ("redirect_uri", &redirect_uri),
            ("client_id", &req.client_id),
            ("code_verifier", &verifier),
        ],
    )?;
    session_of(&grant, req, &token_endpoint, now())
}

/// The session to keep from a token response.
fn session_of(grant: &Value, req: &Request, token_endpoint: &str, at: f64) -> Result<Value, String> {
    let access = grant.get("access_token").and_then(Value::as_str).filter(|s| !s.is_empty());
    let access = access.ok_or("the provider sent no access token")?;
    let expires_at = grant.get("expires_in").and_then(Value::as_f64).map(|s| at + s);
    // An offline token says refresh_expires_in: 0, meaning it doesn't expire.
    let refresh_expires_at = grant.get("refresh_expires_in").and_then(Value::as_f64).filter(|s| *s > 0.0).map(|s| at + s);
    Ok(json!({
        "access_token": access,
        "refresh_token": grant.get("refresh_token").and_then(Value::as_str),
        "expires_at": expires_at,
        "refresh_expires_at": refresh_expires_at,
        "issuer": req.issuer,
        "client_id": req.client_id,
        "token_endpoint": token_endpoint,
        "scope": grant.get("scope").and_then(Value::as_str).unwrap_or(&req.scope),
    }))
}

fn same(a: &str, b: &str) -> bool {
    a.len() == b.len() && a.bytes().zip(b.bytes()).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

/// Answer requests on `listener` until the provider's redirect arrives (its
/// query, as pairs), or `wait` runs out. Anything else (a favicon) gets a 404.
fn wait_for_redirect(listener: &TcpListener, wait: Duration) -> Result<Vec<(String, String)>, String> {
    listener.set_nonblocking(true).map_err(|e| e.to_string())?;
    let deadline = Instant::now() + wait;
    while Instant::now() < deadline {
        match listener.accept() {
            Ok((stream, _)) => {
                if let Some(params) = serve(stream) {
                    return Ok(params);
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => std::thread::sleep(Duration::from_millis(100)),
            Err(e) => return Err(e.to_string()),
        }
    }
    Err(format!("the browser didn't come back within {} minutes", wait.as_secs() / 60))
}

fn serve(mut stream: TcpStream) -> Option<Vec<(String, String)>> {
    let _ = stream.set_nonblocking(false);
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let mut buf = Vec::new();
    let mut chunk = [0u8; 2048];
    while !buf.windows(4).any(|w| w == b"\r\n\r\n") && buf.len() < 16 * 1024 {
        match stream.read(&mut chunk) {
            Ok(0) | Err(_) => break,
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
        }
    }
    let params = redirect_params(&String::from_utf8_lossy(&buf));
    let (status, body) = match &params {
        Some(p) if p.iter().any(|(k, _)| k == "code") => ("200 OK", page("You're signed in to Mycelium.", "You can close this tab.")),
        Some(_) => ("200 OK", page("Sign-in didn't finish.", "Go back to Mycelium and try again.")),
        None => ("404 Not Found", String::new()),
    };
    let _ = write!(
        stream,
        "HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    params
}

/// The query of a `GET /callback?…` request carrying a code or an error.
fn redirect_params(request: &str) -> Option<Vec<(String, String)>> {
    let target = request.lines().next()?.strip_prefix("GET ")?.split(' ').next()?;
    let url = Url::parse(&format!("http://127.0.0.1{target}")).ok()?;
    if url.path() != CALLBACK_PATH {
        return None;
    }
    let pairs: Vec<(String, String)> = url.query_pairs().map(|(k, v)| (k.into_owned(), v.into_owned())).collect();
    pairs.iter().any(|(k, _)| k == "code" || k == "error").then_some(pairs)
}

fn page(heading: &str, detail: &str) -> String {
    format!(
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Mycelium</title></head>\
         <body style=\"font-family: system-ui, sans-serif; padding: 3rem; text-align: center\">\
         <h2>{heading}</h2><p style=\"color:#666\">{detail}</p></body></html>"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request() -> Request {
        Request::of(&json!({ "issuer": "https://idp.test/realms/m/", "client_id": "cli", "scope": "openid offline_access" })).unwrap()
    }

    #[test]
    fn a_request_says_what_to_sign_in_with() {
        let req = request();
        assert_eq!(req.issuer, "https://idp.test/realms/m");
        assert_eq!(req.redirect_port, 0);
        assert!(Request::of(&json!({ "client_id": "cli" })).is_err());
        assert!(Request::of(&json!({ "issuer": "file:///etc", "client_id": "cli" })).is_err());
    }

    #[test]
    fn pkce_is_s256_of_its_verifier() {
        let (verifier, challenge) = pkce();
        let want = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()));
        assert_eq!(challenge, want);
        assert!(verifier.len() >= 43);
    }

    #[test]
    fn only_the_callback_with_a_code_or_error_finishes() {
        let got = redirect_params("GET /callback?code=c1&state=s HTTP/1.1\r\nHost: x\r\n\r\n").unwrap();
        assert!(got.contains(&("code".into(), "c1".into())));
        assert!(redirect_params("GET /favicon.ico HTTP/1.1\r\n\r\n").is_none());
        assert!(redirect_params("GET /callback?x=1 HTTP/1.1\r\n\r\n").is_none());
        assert!(redirect_params("POST /callback?code=c HTTP/1.1\r\n\r\n").is_none());
    }

    #[test]
    fn a_grant_becomes_the_clis_session_shape() {
        let grant = json!({ "access_token": "at", "refresh_token": "rt", "expires_in": 300, "refresh_expires_in": 0 });
        let s = session_of(&grant, &request(), "https://idp.test/token", 1000.0).unwrap();
        assert_eq!(s["expires_at"], 1300.0);
        assert!(s["refresh_expires_at"].is_null());
        assert_eq!(s["refresh_token"], "rt");
        assert_eq!(s["scope"], "openid offline_access");
        assert!(session_of(&json!({}), &request(), "t", 0.0).is_err());
    }
}
