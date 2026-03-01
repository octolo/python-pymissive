"""Provider monitoring mixin without Django dependencies."""

from __future__ import annotations

from typing import Any, Dict


class BaseMonitoringMixin:
    """Provider monitoring functionality mixin."""

    def get_service_status(self) -> Dict[str, Any]:
        """Return provider service status. Override in subclasses."""
        clock_fn = getattr(self, "_clock", None)
        last_check = clock_fn() if callable(clock_fn) else None

        services_getter = getattr(self, "_get_services", None)
        if callable(services_getter):
            services = services_getter()
        else:
            services = list(getattr(self, "services", []))

        return {
            "status": "unknown",
            "is_available": None,
            "services": services,
            "credits": {
                "type": "unknown",
                "remaining": None,
                "currency": "",
                "limit": None,
                "percentage": None,
            },
            "rate_limits": {
                "per_second": None,
                "per_minute": None,
                "per_hour": None,
                "per_day": None,
            },
            "sla": {
                "uptime_percentage": None,
                "response_time_ms": None,
                "success_rate": None,
            },
            "last_check": last_check,
            "warnings": ["Monitoring not implemented for this provider"],
            "details": {},
        }

    def check_credits(self) -> Dict[str, Any]:
        """Check available provider credits."""
        status = self.get_service_status()
        credits = status.get("credits", {})

        threshold = 10
        percentage = credits.get("percentage")
        needs_refill = percentage is not None and percentage < threshold

        return {
            "type": credits.get("type", "unknown"),
            "remaining": credits.get("remaining"),
            "currency": credits.get("currency", ""),
            "limit": credits.get("limit"),
            "percentage": percentage,
            "threshold_warning": threshold,
            "needs_refill": needs_refill,
            "refill_url": "",
        }

    def check_rate_limits(self) -> Dict[str, Any]:
        """Return current rate-limit information."""
        status = self.get_service_status()
        rate_limits = status.get("rate_limits", {})

        return {
            "limits": rate_limits,
            "current_usage": {},
            "remaining": {},
            "reset_at": None,
            "is_throttled": False,
        }

    def get_sla_metrics(self) -> Dict[str, Any]:
        """Return SLA metrics for the provider."""
        status = self.get_service_status()
        sla = status.get("sla", {})

        uptime = sla.get("uptime_percentage")
        target = 99.9
        meets_sla = uptime is not None and uptime >= target

        return {
            "uptime_percentage": uptime,
            "uptime_target": target,
            "meets_sla": meets_sla,
            "incidents_30d": None,
            "mttr_minutes": None,
            "response_time_avg_ms": sla.get("response_time_ms"),
            "response_time_p95_ms": None,
            "success_rate": sla.get("success_rate"),
            "last_incident": None,
            "status_page_url": "",
        }

    def health_check(self) -> Dict[str, Any]:
        """Perform a holistic provider health check."""
        issues = []
        recommendations = []

        status = self.get_service_status()
        if status["status"] == "down":
            issues.append("Service unavailable")
        elif status["status"] == "degraded":
            issues.append("Service degraded")

        credits = self.check_credits()
        if credits.get("needs_refill"):
            issues.append(f"Low credits: {credits['remaining']} {credits['currency']}")
            recommendations.append("Refill provider account")

        rate_limits = self.check_rate_limits()
        if rate_limits.get("is_throttled"):
            issues.append("Rate limit reached")
            recommendations.append("Reduce sending cadence")

        if not issues:
            health_status = "healthy"
            is_healthy = True
            summary = f"{getattr(self, 'name', 'Provider')} : All systems nominal ✅"
        elif len(issues) == 1 and "Low credits" in issues[0]:
            health_status = "warning"
            is_healthy = True
            summary = f"{getattr(self, 'name', 'Provider')} : Warning - {issues[0]} ⚠️"
        elif status["status"] == "down":
            health_status = "down"
            is_healthy = False
            summary = f"{getattr(self, 'name', 'Provider')} : Service unavailable ❌"
        else:
            health_status = "critical"
            is_healthy = False
            summary = (
                f"{getattr(self, 'name', 'Provider')} : Critical issues detected ⚠️"
            )

        return {
            "is_healthy": is_healthy,
            "status": health_status,
            "issues": issues,
            "recommendations": recommendations,
            "summary": summary,
        }
