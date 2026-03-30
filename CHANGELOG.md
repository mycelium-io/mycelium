# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.9] - 2026-03-23

### Added
- Centralized backend support — local file writes, git sync, volume mount

### Fixed
- Pin litellm to 1.82.3 (1.82.7 and 1.82.8 are compromised)
- Migration 0009 drops and recreates embedding column

### Changed
- Reverted pluggable embedding providers in favor of sentence-transformers (all-MiniLM-L6-v2, local)
