"""Directly runnable, idempotent monthly usage reconciliation job."""

import argparse
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.data.database import create_database_engine
from app.data.models import MonthlyUsageRollup, Subscription
from app.services.usage_summary import get_usage_summary

logger = logging.getLogger(__name__)


class MonthlyRollupJobError(RuntimeError):
    """Raised after the job exhausts its bounded transient retry budget."""


@dataclass(frozen=True)
class MonthlyRollupJobResult:
    reconciled_tenants: int
    attempts: int


def reconcile_monthly_usage_rollups(
    session: Session,
    *,
    as_of: datetime | None = None,
) -> int:
    """Upsert one source-of-truth reconciliation row per tenant and UTC month."""
    tenant_ids = session.scalars(select(Subscription.tenant_id).distinct()).all()
    reconciled = 0
    for tenant_id in tenant_ids:
        summary = get_usage_summary(session, tenant_id=tenant_id, as_of=as_of)
        rollup = session.scalar(
            select(MonthlyUsageRollup).where(
                MonthlyUsageRollup.tenant_id == tenant_id,
                MonthlyUsageRollup.billing_period_start
                == summary.billing_period.start,
            )
        )
        if rollup is None:
            rollup = MonthlyUsageRollup(
                tenant_id=tenant_id,
                billing_period_start=summary.billing_period.start,
                billing_period_end=summary.billing_period.end,
                api_calls=0,
                input_tokens=0,
                cached_input_tokens=0,
                output_tokens=0,
                reasoning_tokens=0,
                estimated_ai_cost_cents=0,
            )
            session.add(rollup)
        rollup.billing_period_end = summary.billing_period.end
        rollup.api_calls = summary.usage.api_calls
        rollup.input_tokens = summary.usage.input_tokens
        rollup.cached_input_tokens = summary.usage.cached_input_tokens
        rollup.output_tokens = summary.usage.output_tokens
        rollup.reasoning_tokens = summary.usage.reasoning_tokens
        rollup.estimated_ai_cost_cents = summary.estimated_ai_cost_cents
        reconciled += 1
    session.commit()
    return reconciled


def run_monthly_usage_rollup_job(
    session_factory: Callable[[], Session],
    *,
    as_of: datetime | None = None,
    max_attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    reconcile: Callable[[Session], int] | None = None,
) -> MonthlyRollupJobResult:
    """Run reconciliation outside HTTP with bounded, observable retries."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one.")
    operation = reconcile or (lambda session: reconcile_monthly_usage_rollups(session, as_of=as_of))
    for attempt in range(1, max_attempts + 1):
        try:
            with session_factory() as session:
                reconciled = operation(session)
            return MonthlyRollupJobResult(
                reconciled_tenants=reconciled,
                attempts=attempt,
            )
        except SQLAlchemyError as error:
            # Do not log error text: database exceptions can include connection details.
            logger.warning("monthly_usage_rollup transient_failure attempt=%s", attempt)
            if attempt == max_attempts:
                logger.error("monthly_usage_rollup exhausted_retries attempts=%s", attempt)
                raise MonthlyRollupJobError(
                    "Monthly usage rollup exhausted its retry budget."
                ) from error
            sleep(0)
    raise AssertionError("unreachable")


def _parse_as_of(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--as-of must include a timezone.")
    return parsed.astimezone(UTC)


def main() -> None:
    """Run as ``python -m app.jobs.monthly_usage_rollup``."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=_parse_as_of)
    arguments = parser.parse_args()
    engine = create_database_engine()
    try:
        result = run_monthly_usage_rollup_job(
            lambda: Session(engine),
            as_of=arguments.as_of,
        )
    except MonthlyRollupJobError:
        logger.error("monthly_usage_rollup failed")
        raise SystemExit(1) from None
    finally:
        engine.dispose()
    print(
        "monthly_usage_rollup completed "
        f"reconciled_tenants={result.reconciled_tenants} attempts={result.attempts}"
    )


if __name__ == "__main__":
    main()