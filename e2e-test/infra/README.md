# Mycelium E2E Test Infrastructure

Ephemeral EC2 infrastructure for running the distributed E2E test suite.
Spins up 3 spot instances in a VPC, runs tests, tears everything down.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  VPC 10.100.0.0/24                                      │
│                                                         │
│  ┌─────────────────┐  ┌──────────┐  ┌──────────┐      │
│  │  Orchestrator   │  │  Node 2  │  │  Node 3  │      │
│  │                 │  │          │  │          │      │
│  │  - Matrix       │  │  - OC GW │  │  - OC GW │      │
│  │  - Mycelium BE  │  │  - Agent │  │  - Agent │      │
│  │  - CFN stack    │  │          │  │          │      │
│  │  - OC Gateway   │  │          │  │          │      │
│  │  - Test runner  │  │          │  │          │      │
│  └─────────────────┘  └──────────┘  └──────────┘      │
│         .10                .11           .12            │
└─────────────────────────────────────────────────────────┘
```

## Running

### Automated (GitHub Actions)

The workflow runs weekly on Monday 06:00 UTC or on-demand via `workflow_dispatch`.

### Manual

```bash
cd infra/terraform

# Generate SSH key
ssh-keygen -t ed25519 -f /tmp/e2e-key -N ""

# Apply
terraform init
terraform apply \
  -var="ssh_public_key=$(cat /tmp/e2e-key.pub)" \
  -var="matrix_shared_secret=YOUR_SECRET" \
  -var="bedrock_access_key_id=AKIA..." \
  -var="bedrock_secret_access_key=..."

# SSH in
ssh -i /tmp/e2e-key ubuntu@$(terraform output -raw orchestrator_ip)

# Tear down
terraform destroy
```

## Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `AWS_ROLE_ARN` | IAM role ARN for OIDC auth (needs EC2, VPC permissions) |
| `MATRIX_SHARED_SECRET` | Synapse registration shared secret |
| `MYCELIUM_DB_PASSWORD` | PostgreSQL password for mycelium-db |
| `BEDROCK_ACCESS_KEY_ID` | AWS key for LLM (Bedrock) API calls |
| `BEDROCK_SECRET_ACCESS_KEY` | AWS secret for LLM API calls |

## Cost Estimate

- 3x `t3.medium` spot instances (~$0.013/hr each) x ~45 min = **~$0.03/run**
- EBS: 3x 30GB gp3 = negligible (deleted on teardown)
- Data transfer: minimal (internal VPC traffic)

**Weekly cost: < $0.15/month**

## Debugging

Use `workflow_dispatch` with `skip_teardown: true` to keep instances alive after
a failed run. SSH in using the key from the `ssh-key` artifact.

## What Gets Tested

1. **Sections 1-10**: Backend health, room CRUD, CFN connectivity
2. **Sections 11-15**: CLI memory operations, sync negotiation
3. **Sections 16-22**: Multi-agent convergence scenarios
4. **Section 23**: Reindex verification
5. **Section 30**: Matrix E2E (single-node agents via OpenClaw)
6. **Sections 40-49**: Distributed multi-device negotiation + cross-channel return-trip
