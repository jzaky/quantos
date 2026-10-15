# Dependency, licence and supply-chain assessment

Date: 2026-10-14. Scope: the Quant OS safety and AEGIS work on branch `claude/quantos-safety-aegis`, and the approved evaluation of Syft and Trivy for CI.

## 1. Dependencies added by this work

**None.**
- `order_safety.py` and `aegis_client.py` use the Python standard library only.
- The tests use the standard library `unittest` plus `fastapi.testclient`, which needs `httpx`. Quant OS already relied on httpx for its tests, and it is not added to `requirements.txt`.
- The AEGIS-side setup script uses AEGIS's existing packages only.

## 2. Existing runtime dependencies (requirements.txt)

| Package | Pin | Licence | Notes |
|---|---|---|---|
| fastapi | ==0.141.1 | MIT | |
| uvicorn[standard] | >=0.35,<1.0 | BSD-3-Clause | range, not pinned |
| pydantic | >=2.11,<3.0 | MIT | range, not pinned |
| safety | **unpinned** | MIT (verify for the resolved version) | **Finding.** Not imported anywhere in Quant OS, yet installed in the production image by `Dockerfile.railway`. Recent Safety CLI versions call a remote service and require an account. Recommendation: remove it from runtime requirements, or pin it and move it to a dev-only file. Listed for approval; not changed here. |

Recommendation: pin every runtime dependency to an exact version and generate hashes (`pip-compile --generate-hashes`, then `pip install --require-hashes`) before any deployment that can reach a broker.

## 3. Syft (SBOM generation): evaluated, not installed

| Check | Finding |
|---|---|
| Official repository | `github.com/anchore/syft` (Anchore) |
| Licence | Apache-2.0: permissive, compatible with commercial use; keep the NOTICE when redistributing (we would not redistribute) |
| Current release | v1.54.1 (2026-10-06), from the official releases page |
| Provenance and integrity | Each release ships `checksums.txt` signed with cosign keyless signing (`checksums.txt.pem` and `checksums.txt.sig`), issued to Anchore's GitHub Actions workflow identity with OIDC issuer `https://token.actions.githubusercontent.com`. Verify the signature, then `sha256sum -c checksums.txt`. Use cosign >= 3.0.4 or >= 2.6.2 (CVE-2026-22703 let a crafted bundle pass verification in earlier versions). |
| Advisories | No Syft compromise comparable to the Trivy incident was found in this review. Re-check the GitHub advisory database at adoption time. |
| Telemetry and network | Syft checks for application updates unless `SYFT_CHECK_FOR_APP_UPDATE=false`. Scanning a local directory needs no network. |
| Execution | Runs as an unprivileged user on the checked-out source; needs no secrets. |

**Decision: recommended for CI, pending approval.** Proposed CI step:
- download the pinned release archive by URL and verify cosign and the checksum in the job (fail closed);
- run `SYFT_CHECK_FOR_APP_UPDATE=false syft dir:. -o spdx-json`;
- keep the SBOM as a build artifact;
- give the job no secrets and `permissions: contents: read`.

The binary's sha256 is recorded in the workflow when it is added. It was not downloaded during this evaluation.

## 4. Trivy (vulnerability scanning): evaluated, not installed; adoption deferred

| Check | Finding |
|---|---|
| Official repository | `github.com/aquasecurity/trivy` (Aqua Security) |
| Licence | Apache-2.0 |
| Advisory | **GHSA-69fq-xp46-6x23 / CVE-2026-33634, critical.** In March 2026, stolen credentials were used to publish malicious content. |
| Advisory: malicious binary | trivy v0.69.4: GitHub, deb, rpm, get.trivy.dev, and images on GHCR, ECR and Docker Hub. |
| Advisory: malicious images | v0.69.5 and v0.69.6, on Docker Hub only. |
| Advisory: trivy-action | 76 of 77 tags were force-pushed to credential-stealing code. |
| Advisory: setup-trivy | All tags were force-pushed. |
| Advisory: exposure windows | About 3 to 12 hours each, on 2026-03-19 to 20 and 2026-03-22 to 23. |
| Advisory: per-component safe versions | binary v0.69.2 or v0.69.3, trivy-action 0.35.0, setup-trivy v0.2.6. Releases have been made since (v0.70.0 in April 2026; later ones are reported). |
| Advisory: guidance | Pin GitHub Actions to full commit SHAs, use images by digest, and rotate any secrets exposed to affected pipelines. |
| Provenance | Release binaries carry cosign `.sigstore.json` bundles, verified against identity regexp `https://github\.com/aquasecurity/` and issuer `https://token.actions.githubusercontent.com`. The advisory recommends checking the signing timestamp as well. |
| Telemetry and network | The vulnerability database is downloaded from a registry, so a scan needs network unless the DB is fetched in a separate step and the scan uses `--skip-db-update --offline-scan`. Version checks and any usage reporting must be disabled with the flags documented for the pinned version (verify the exact flag names for that release before use). |
| Execution | A filesystem scan needs no privileges. An image scan must not mount the Docker socket in CI. |

**Decision: do not adopt yet.**
- Adoption is not ruled out, but it would need to meet all of the following:
  - the Trivy binary is installed by direct download of a pinned version, verified with cosign including the signing timestamp, and recorded by sha256;
  - `trivy-action` and `setup-trivy` are not used;
  - the vulnerability DB is pulled in a separate step with no secrets in the job;
  - the scan runs offline.
- Because Quant OS's Python dependency set is small, a lower-risk alternative for dependency vulnerabilities is OSV-Scanner (Apache-2.0, Google) or `pip-audit` (Apache-2.0, PyPA) against a hash-pinned lock file. Both are listed for approval; neither is installed.
- AEGIS already runs an OSV-based check in its own CI.

## 5. Provenance

All code in this work was written for Quant OS and AEGIS:
- No DNRS designs, formulas or workflows were used.
- No AGPL or GPL source was copied.
- The risk limits are Quant OS's existing `risk_engine.Limits` values.
- The new single-symbol exposure check uses the existing, previously unused `max_symbol_exposure_pct`.

## Sources

- [GHSA-69fq-xp46-6x23 (GitHub Advisory Database)](https://github.com/advisories/GHSA-69fq-xp46-6x23)
- [Trivy security advisory](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23)
- [GitLab advisory, CVE-2026-33634](https://advisories.gitlab.com/golang/github.com/aquasecurity/trivy/CVE-2026-33634/)
- [Trivy releases](https://github.com/aquasecurity/trivy/releases)
- [Syft releases](https://github.com/anchore/syft/releases)
- [Anchore: verifying downloads](https://oss.anchore.com/docs/installation/verification/)
