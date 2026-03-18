"""Threat Intelligence — polls CVE databases and security advisories.

Enriches dependency scanner findings with CVSS scores, exploit availability,
and remediation guidance from NVD (National Vulnerability Database) and
GitHub Security Advisories.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("cybersecurity.threat_intel")


async def enrich_cve(cve_id: str) -> dict | None:
    """Fetch CVE details from NVD API.

    Returns dict with: id, description, cvss_score, severity, references, published
    """
    if not cve_id or not cve_id.startswith("CVE-"):
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://services.nvd.nist.gov/rest/json/cves/2.0",
                params={"cveId": cve_id},
            )
            if resp.status_code != 200:
                logger.debug("NVD API returned %d for %s", resp.status_code, cve_id)
                return None

            data = resp.json()
            vulnerabilities = data.get("vulnerabilities", [])
            if not vulnerabilities:
                return None

            cve_data = vulnerabilities[0].get("cve", {})

            # Extract CVSS score
            cvss_score = None
            severity = None
            metrics = cve_data.get("metrics", {})

            # Try CVSS v3.1 first, then v3.0, then v2.0
            for version in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                metric_list = metrics.get(version, [])
                if metric_list:
                    cvss_data = metric_list[0].get("cvssData", {})
                    cvss_score = cvss_data.get("baseScore")
                    severity = cvss_data.get("baseSeverity", "").lower()
                    break

            # Extract description (English)
            descriptions = cve_data.get("descriptions", [])
            description = ""
            for desc in descriptions:
                if desc.get("lang") == "en":
                    description = desc.get("value", "")
                    break

            # Extract references
            references = [
                ref.get("url")
                for ref in cve_data.get("references", [])
                if ref.get("url")
            ][:5]

            return {
                "id": cve_id,
                "description": description[:1000],
                "cvss_score": cvss_score,
                "severity": severity or _cvss_to_severity(cvss_score),
                "references": references,
                "published": cve_data.get("published"),
                "last_modified": cve_data.get("lastModified"),
            }
    except ImportError:
        logger.debug("httpx not available — cannot query NVD")
    except Exception:
        logger.debug("Failed to fetch CVE details for %s", cve_id)

    return None


async def get_advisories_for_package(
    package_name: str,
    ecosystem: str = "pip",
) -> list[dict]:
    """Fetch security advisories for a package from GitHub Security Advisories.

    Returns list of dicts with: ghsa_id, cve_id, summary, severity, published
    """
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        return []

    # Map ecosystem names to GitHub GraphQL values
    ecosystem_map = {
        "pip": "PIP",
        "npm": "NPM",
        "pypi": "PIP",
    }
    gh_ecosystem = ecosystem_map.get(ecosystem.lower(), "PIP")

    try:
        import httpx

        query = """
        query($package: String!, $ecosystem: SecurityAdvisoryEcosystem!) {
            securityVulnerabilities(
                first: 10,
                ecosystem: $ecosystem,
                package: $package,
                orderBy: {field: UPDATED_AT, direction: DESC}
            ) {
                nodes {
                    advisory {
                        ghsaId
                        summary
                        severity
                        publishedAt
                        identifiers {
                            type
                            value
                        }
                    }
                    vulnerableVersionRange
                    firstPatchedVersion {
                        identifier
                    }
                }
            }
        }
        """

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.github.com/graphql",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "variables": {"package": package_name, "ecosystem": gh_ecosystem},
                },
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            nodes = (
                data.get("data", {}).get("securityVulnerabilities", {}).get("nodes", [])
            )

            advisories = []
            for node in nodes:
                advisory = node.get("advisory", {})
                identifiers = advisory.get("identifiers", [])
                cve_id = None
                for ident in identifiers:
                    if ident.get("type") == "CVE":
                        cve_id = ident.get("value")
                        break

                advisories.append(
                    {
                        "ghsa_id": advisory.get("ghsaId"),
                        "cve_id": cve_id,
                        "summary": advisory.get("summary", ""),
                        "severity": (advisory.get("severity") or "moderate").lower(),
                        "published": advisory.get("publishedAt"),
                        "vulnerable_range": node.get("vulnerableVersionRange"),
                        "first_patched": (
                            node.get("firstPatchedVersion", {}) or {}
                        ).get("identifier"),
                    }
                )

            return advisories
    except ImportError:
        logger.debug("httpx not available — cannot query GitHub Advisories")
    except Exception:
        logger.debug("Failed to fetch advisories for %s", package_name)

    return []


def _cvss_to_severity(score: float | None) -> str:
    if score is None:
        return "medium"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"
