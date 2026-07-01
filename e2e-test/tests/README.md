# Unit Tests

Offline unit tests for pyATS harness libraries (`libs/`, provisioners, scenario factory).

## Running

```bash
cd /home/ubuntu/mycelium-e2e-test
uv run pytest tests/unit -q
```

## E2E runs

End-to-end tests are pyATS jobs under `jobs/` and `suites/`. See the repo [README](../README.md) for lab and CI usage.
