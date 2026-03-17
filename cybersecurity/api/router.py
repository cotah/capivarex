"""CyberSecurity API — main router that mounts all sub-routers."""

from __future__ import annotations

from fastapi import APIRouter

from cybersecurity.api.dashboard import router as dashboard_router
from cybersecurity.api.findings import router as findings_router
from cybersecurity.api.scans import router as scans_router
from cybersecurity.api.reports import router as reports_router
from cybersecurity.api.settings import router as settings_router

router = APIRouter(prefix="/api/admin/cybersecurity", tags=["cybersecurity"])

router.include_router(dashboard_router)
router.include_router(findings_router)
router.include_router(scans_router)
router.include_router(reports_router)
router.include_router(settings_router)
