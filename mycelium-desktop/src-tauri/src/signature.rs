// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Checking an update's signature before it installs.
//!
//! The updater plugin checks the signature only inside its own `download()`,
//! and its `install()` takes the bytes as given. The app downloads the archive
//! itself so a dropped connection can resume (`download.rs`), so the check is
//! made here, the same way the plugin makes it: the minisign signature from
//! `latest.json` against the public key built into the app, then the version
//! the signature names (its trusted comment) against the version announced.

use base64::Engine;
use minisign_verify::{PublicKey, Signature};

fn decoded(base64_text: &str, what: &str) -> Result<String, String> {
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(base64_text.trim())
        .map_err(|_| format!("the update's {what} isn't readable"))?;
    String::from_utf8(bytes).map_err(|_| format!("the update's {what} isn't readable"))
}

/// The version a signature's trusted comment names, when it names one.
fn signed_version(trusted_comment: &str) -> Option<&str> {
    trusted_comment.split('\t').find_map(|field| field.strip_prefix("version:"))
}

fn same_version(a: &str, b: &str) -> bool {
    match (
        semver::Version::parse(a.trim_start_matches('v')),
        semver::Version::parse(b.trim_start_matches('v')),
    ) {
        (Ok(a), Ok(b)) => a == b,
        _ => a == b,
    }
}

/// Whether `data` is the archive the release signed for `version`. The error
/// says why not, in words for the update window.
pub fn verify(data: &[u8], signature: &str, pubkey: &str, version: &str) -> Result<(), String> {
    let key = PublicKey::decode(&decoded(pubkey, "public key")?)
        .map_err(|_| "the app's update key isn't readable".to_string())?;
    let signature = Signature::decode(&decoded(signature, "signature")?)
        .map_err(|_| "the update's signature isn't readable".to_string())?;
    key.verify(data, &signature, true)
        .map_err(|_| "the download doesn't match the release's signature".to_string())?;
    // Only trusted once the signature above has checked out, since it covers it.
    match signed_version(signature.trusted_comment()) {
        Some(signed) if !same_version(signed, version) => Err(format!(
            "the download is signed for version {signed}, not {version}"
        )),
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const PAYLOAD: &[u8] = b"mycelium update archive\n";

    /// A throwaway key pair, and `PAYLOAD` signed with it under `comment`,
    /// each base64-encoded the way `tauri signer` and `latest.json` carry them.
    fn signed(comment: &str) -> (String, String) {
        let b64 = |text: String| base64::engine::general_purpose::STANDARD.encode(text);
        let pair = minisign::KeyPair::generate_unencrypted_keypair().unwrap();
        let signature = minisign::sign(Some(&pair.pk), &pair.sk, PAYLOAD, Some(comment), None).unwrap();
        (b64(pair.pk.to_box().unwrap().to_string()), b64(signature.to_string()))
    }

    #[test]
    fn a_signed_archive_for_its_version_passes() {
        let (key, signature) = signed("timestamp:0\tversion:9.9.9");
        assert_eq!(verify(PAYLOAD, &signature, &key, "9.9.9"), Ok(()));
        assert_eq!(verify(PAYLOAD, &signature, &key, "v9.9.9"), Ok(()));
    }

    #[test]
    fn a_signature_naming_no_version_passes_as_the_plugin_allows() {
        let (key, signature) = signed("timestamp:0");
        assert_eq!(verify(PAYLOAD, &signature, &key, "9.9.9"), Ok(()));
    }

    #[test]
    fn a_changed_archive_is_refused() {
        let (key, signature) = signed("timestamp:0\tversion:9.9.9");
        let err = verify(b"mycelium update archive, tampered\n", &signature, &key, "9.9.9");
        assert_eq!(err, Err("the download doesn't match the release's signature".into()));
    }

    #[test]
    fn another_key_is_refused() {
        let (_, signature) = signed("timestamp:0\tversion:9.9.9");
        let (other_key, _) = signed("timestamp:0\tversion:9.9.9");
        assert!(verify(PAYLOAD, &signature, &other_key, "9.9.9").is_err());
    }

    #[test]
    fn an_archive_signed_for_another_version_is_refused() {
        let (key, signature) = signed("timestamp:0\tversion:9.9.9");
        let err = verify(PAYLOAD, &signature, &key, "9.9.10");
        assert_eq!(err, Err("the download is signed for version 9.9.9, not 9.9.10".into()));
    }

    #[test]
    fn an_unreadable_signature_is_refused() {
        let (key, _) = signed("timestamp:0");
        assert!(verify(PAYLOAD, "not base64!", &key, "9.9.9").is_err());
    }
}
