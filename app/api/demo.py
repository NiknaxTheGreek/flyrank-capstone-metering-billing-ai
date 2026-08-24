"""Human-friendly demo UI for the seeded tenant in explicit demo mode only."""

from __future__ import annotations

import csv
import io
import os
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.data.models import MonthlyUsageRollup, UsageEvent
from app.data.seed import DEMO_FREE_TENANT_ID
from app.data.session import get_session
from app.services.metering import (
    MeterUsageCommand,
    SubscriptionNotEligibleError,
    TenantNotFoundError,
    meter_usage,
)
from app.services.quota import QuotaExceededError
from app.services.usage_summary import UsageSummaryNotFoundError, get_usage_summary

router = APIRouter(prefix="/demo", include_in_schema=False)


def _require_demo_mode() -> None:
    if os.getenv("DEMO_MODE", "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


class DemoGenerateRequest(BaseModel):
    """A safe public-demo request bound to the deterministic demo tenant."""

    usage_type: Literal["api_call", "ai_token"]
    quantity: Annotated[int, Field(gt=0)]
    token_category: Literal["input", "cached_input", "output", "reasoning"] | None = None
    idempotency_key: Annotated[str | None, Field(max_length=255)] = None

    @model_validator(mode="after")
    def validate_usage_combination(self) -> "DemoGenerateRequest":
        if self.usage_type == "ai_token" and self.token_category is None:
            raise ValueError("AI-token usage requires a token category.")
        if self.usage_type == "api_call" and self.token_category is not None:
            raise ValueError("API-call usage cannot include a token category.")
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            self.idempotency_key = None
        return self


def _summary_payload(session: Session) -> dict[str, object]:
    summary = get_usage_summary(session, tenant_id=DEMO_FREE_TENANT_ID)
    return {
        "tenant_id": str(summary.tenant_id),
        "billing_period": {
            "start": summary.billing_period.start.isoformat(),
            "end": summary.billing_period.end.isoformat(),
        },
        "plan": {
            "code": summary.plan.code,
            "status": summary.subscription.status,
            "api_call_limit": summary.plan.included_api_calls,
            "ai_token_limit": summary.plan.included_ai_tokens,
        },
        "usage": {
            "api_calls": summary.usage.api_calls,
            "input_tokens": summary.usage.input_tokens,
            "cached_input_tokens": summary.usage.cached_input_tokens,
            "output_tokens": summary.usage.output_tokens,
            "reasoning_tokens": summary.usage.reasoning_tokens,
            "ai_tokens": summary.usage.ai_tokens,
        },
        "remaining_allowance": {
            "api_calls": summary.remaining_api_calls,
            "ai_tokens": summary.remaining_ai_tokens,
        },
        "estimated_ai_cost_cents": summary.estimated_ai_cost_cents,
    }


@router.get("", response_class=HTMLResponse)
def demo_page() -> HTMLResponse:
    _require_demo_mode()
    return HTMLResponse(DEMO_HTML)


@router.get("/api/usage")
def demo_usage(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    _require_demo_mode()
    try:
        return _summary_payload(session)
    except UsageSummaryNotFoundError as error:
        raise HTTPException(status_code=404, detail="Demo tenant is not seeded.") from error


@router.post("/api/generate")
def demo_generate(
    request: DemoGenerateRequest,
    session: Annotated[Session, Depends(get_session)],
) -> JSONResponse:
    _require_demo_mode()
    key = request.idempotency_key or f"demo-{uuid.uuid4()}"
    try:
        result = meter_usage(
            session,
            MeterUsageCommand(
                tenant_id=DEMO_FREE_TENANT_ID,
                usage_type=request.usage_type,
                quantity=request.quantity,
                idempotency_key=key,
                token_category=request.token_category,
            ),
        )
        payload = {
            "request": {
                "idempotency_key": key,
                "usage_type": result.usage_event.usage_type,
                "token_category": result.usage_event.token_category,
                "quantity": result.usage_event.quantity,
            },
            "result": {
                "generated_text": "simulated-generation",
                "usage_event_id": str(result.usage_event.id),
                "idempotent_replay": result.idempotent_replay,
            },
            "usage_summary": _summary_payload(session),
        }
    except TenantNotFoundError as error:
        session.rollback()
        raise HTTPException(status_code=404, detail="Demo tenant is not seeded.") from error
    except SubscriptionNotEligibleError as error:
        session.rollback()
        raise HTTPException(status_code=402, detail="Demo subscription is not eligible.") from error
    except QuotaExceededError as error:
        session.rollback()
        evaluation = error.evaluation
        raise HTTPException(
            status_code=429,
            detail={
                "code": "quota_exhausted",
                "usage_type": evaluation.usage_type,
                "limit": evaluation.limit,
                "current_usage": evaluation.current_usage,
                "attempted_quantity": evaluation.attempted_quantity,
            },
        ) from error

    return JSONResponse(
        status_code=200 if result.idempotent_replay else 201,
        content=payload,
    )


@router.post("/api/reset")
def reset_demo(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    _require_demo_mode()
    deleted_usage = session.execute(
        delete(UsageEvent).where(UsageEvent.tenant_id == DEMO_FREE_TENANT_ID)
    ).rowcount
    deleted_rollups = session.execute(
        delete(MonthlyUsageRollup).where(MonthlyUsageRollup.tenant_id == DEMO_FREE_TENANT_ID)
    ).rowcount
    session.commit()
    return {
        "reset": True,
        "deleted_usage_events": int(deleted_usage or 0),
        "deleted_rollups": int(deleted_rollups or 0),
        "usage_summary": _summary_payload(session),
    }


@router.get("/report.json")
def demo_report_json(
    session: Annotated[Session, Depends(get_session)],
) -> JSONResponse:
    _require_demo_mode()
    return JSONResponse(
        content=_summary_payload(session),
        headers={"Content-Disposition": 'attachment; filename="flyrank-usage-report.json"'},
    )


@router.get("/report.csv")
def demo_report_csv(
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    _require_demo_mode()
    summary = _summary_payload(session)
    plan = summary["plan"]
    usage = summary["usage"]
    remaining = summary["remaining_allowance"]
    period = summary["billing_period"]
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "tenant_id",
            "period_start",
            "period_end",
            "plan",
            "status",
            "api_calls",
            "api_call_limit",
            "api_calls_remaining",
            "ai_tokens",
            "ai_token_limit",
            "ai_tokens_remaining",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "estimated_ai_cost_cents",
        ],
    )
    writer.writeheader()
    writer.writerow(
        {
            "tenant_id": summary["tenant_id"],
            "period_start": period["start"],
            "period_end": period["end"],
            "plan": plan["code"],
            "status": plan["status"],
            "api_calls": usage["api_calls"],
            "api_call_limit": plan["api_call_limit"],
            "api_calls_remaining": remaining["api_calls"],
            "ai_tokens": usage["ai_tokens"],
            "ai_token_limit": plan["ai_token_limit"],
            "ai_tokens_remaining": remaining["ai_tokens"],
            "input_tokens": usage["input_tokens"],
            "cached_input_tokens": usage["cached_input_tokens"],
            "output_tokens": usage["output_tokens"],
            "reasoning_tokens": usage["reasoning_tokens"],
            "estimated_ai_cost_cents": summary["estimated_ai_cost_cents"],
        }
    )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="flyrank-usage-report.csv"'},
    )


DEMO_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FlyRank Metering & Billing Demo</title>
<style>
:root{font-family:Inter,system-ui,-apple-system,sans-serif;color:#182235;background:#f4f7fa}*{box-sizing:border-box}body{margin:0}.wrap{max-width:1100px;margin:auto;padding:28px 18px 60px}.hero{background:#0b1d32;color:white;padding:28px;border-radius:16px;margin-bottom:20px}.hero h1{margin:0 0 8px;font-size:clamp(25px,4vw,40px)}.hero p{margin:0;color:#d6e2ec;max-width:760px}.grid{display:grid;grid-template-columns:1.05fr .95fr;gap:18px}@media(max-width:820px){.grid{grid-template-columns:1fr}}.card{background:white;border:1px solid #dce5ec;border-radius:14px;padding:20px;box-shadow:0 8px 24px rgba(11,29,50,.06)}h2{font-size:18px;margin:0 0 16px}label{font-size:13px;font-weight:650;display:block;margin:12px 0 6px}input,select{width:100%;padding:11px 12px;border:1px solid #bdcbd6;border-radius:8px;background:white;font-size:15px}button,.btn{border:0;border-radius:8px;padding:11px 14px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}.primary{background:#0077a3;color:white}.secondary{background:#eaf1f7;color:#0b1d32}.danger{background:#fff0f0;color:#9c2f37}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.metric{background:#f7fafc;border:1px solid #e0e8ee;border-radius:10px;padding:13px}.metric small{display:block;color:#637383}.metric strong{font-size:22px}.bar{height:8px;background:#e2e8ee;border-radius:99px;overflow:hidden;margin-top:8px}.bar>span{display:block;height:100%;background:#0a8fc2;width:0}.log{margin-top:18px;background:#101923;color:#d7e4ec;border-radius:10px;padding:14px;min-height:120px;white-space:pre-wrap;overflow:auto;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}.note{font-size:12px;color:#637383;margin-top:10px}.status{display:inline-flex;align-items:center;gap:6px;font-size:13px}.dot{width:9px;height:9px;border-radius:50%;background:#2c9c69}.token-only{display:none}.footer{margin-top:18px;font-size:12px;color:#637383}
</style>
</head>
<body><div class="wrap">
<section class="hero"><div class="status"><span class="dot"></span>Live demo mode</div><h1>Usage Metering & Billing Engine</h1><p>Submit real metering requests against the seeded PostgreSQL demo tenant. The same service layer enforces idempotency, quotas and integer-safe billing estimates.</p></section>
<div class="grid">
<section class="card"><h2>Make a real metering request</h2>
<label for="usageType">Usage type</label><select id="usageType"><option value="api_call">API call</option><option value="ai_token">AI tokens</option></select>
<div id="tokenWrap" class="token-only"><label for="tokenCategory">Token category</label><select id="tokenCategory"><option value="input">Input</option><option value="cached_input">Cached input</option><option value="output">Output</option><option value="reasoning">Reasoning</option></select></div>
<label for="quantity">Quantity</label><input id="quantity" type="number" min="1" value="1">
<label for="idem">Idempotency key <span style="font-weight:400;color:#637383">(reuse it to prove retry safety)</span></label><input id="idem" maxlength="255" placeholder="Leave blank for an automatic unique key">
<div class="actions"><button class="primary" id="send">Send request</button><button class="secondary" id="refresh">Refresh usage</button><button class="danger" id="reset">Reset demo usage</button></div>
<p class="note">The core protected API remains unchanged. These demo endpoints are enabled only when the server starts with DEMO_MODE=true and are permanently bound to the seeded demo tenant.</p>
<div class="log" id="log">Ready. Submit a request to see the real HTTP result here.</div></section>
<section class="card"><h2>Current monthly usage</h2><div class="metrics">
<div class="metric"><small>Plan</small><strong id="plan">—</strong><small id="status">—</small></div>
<div class="metric"><small>Estimated AI cost</small><strong id="cost">—</strong><small>integer cents</small></div>
<div class="metric"><small>API calls</small><strong id="apiUsage">—</strong><small id="apiLimit">—</small><div class="bar"><span id="apiBar"></span></div></div>
<div class="metric"><small>AI tokens</small><strong id="tokenUsage">—</strong><small id="tokenLimit">—</small><div class="bar"><span id="tokenBar"></span></div></div>
</div><div style="margin-top:16px" class="metric"><small>Token breakdown</small><div id="breakdown" style="margin-top:5px">—</div></div>
<div class="actions"><a class="btn secondary" href="/demo/report.json">Download JSON</a><a class="btn secondary" href="/demo/report.csv">Download CSV</a><a class="btn secondary" href="/docs" target="_blank">Advanced API docs</a></div><p class="footer" id="period"></p></section>
</div></div>
<script>
const $=id=>document.getElementById(id); const log=$('log');
function pct(n,d){return d?Math.min(100,Math.round(n/d*100)):0}
async function parse(r){let body;try{body=await r.json()}catch{body=await r.text()}return {status:r.status,body}}
function showResult(label,res){log.textContent=`${label}\nHTTP ${res.status}\n\n${typeof res.body==='string'?res.body:JSON.stringify(res.body,null,2)}`}
function render(s){$('plan').textContent=s.plan.code.toUpperCase();$('status').textContent=s.plan.status;$('cost').textContent=s.estimated_ai_cost_cents+'¢';$('apiUsage').textContent=s.usage.api_calls.toLocaleString();$('apiLimit').textContent=`of ${s.plan.api_call_limit.toLocaleString()} · ${s.remaining_allowance.api_calls.toLocaleString()} remaining`;$('tokenUsage').textContent=s.usage.ai_tokens.toLocaleString();$('tokenLimit').textContent=`of ${s.plan.ai_token_limit.toLocaleString()} · ${s.remaining_allowance.ai_tokens.toLocaleString()} remaining`;$('apiBar').style.width=pct(s.usage.api_calls,s.plan.api_call_limit)+'%';$('tokenBar').style.width=pct(s.usage.ai_tokens,s.plan.ai_token_limit)+'%';$('breakdown').textContent=`Input ${s.usage.input_tokens.toLocaleString()} · Cached ${s.usage.cached_input_tokens.toLocaleString()} · Output ${s.usage.output_tokens.toLocaleString()} · Reasoning ${s.usage.reasoning_tokens.toLocaleString()}`;$('period').textContent=`Billing period: ${s.billing_period.start} → ${s.billing_period.end}`}
async function refresh(show=false){const r=await fetch('/demo/api/usage');const res=await parse(r);if(r.ok)render(res.body);if(show)showResult('GET /demo/api/usage',res)}
$('usageType').onchange=()=>{$('tokenWrap').style.display=$('usageType').value==='ai_token'?'block':'none'};
$('send').onclick=async()=>{const body={usage_type:$('usageType').value,quantity:Number($('quantity').value)};if(body.usage_type==='ai_token')body.token_category=$('tokenCategory').value;if($('idem').value.trim())body.idempotency_key=$('idem').value.trim();const r=await fetch('/demo/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const res=await parse(r);showResult('POST /demo/api/generate',res);if(r.ok)render(res.body.usage_summary)};
$('refresh').onclick=()=>refresh(true);
$('reset').onclick=async()=>{if(!confirm('Reset all metered usage for the public demo tenant?'))return;const r=await fetch('/demo/api/reset',{method:'POST'});const res=await parse(r);showResult('POST /demo/api/reset',res);if(r.ok)render(res.body.usage_summary)};
refresh();
</script></body></html>'''
