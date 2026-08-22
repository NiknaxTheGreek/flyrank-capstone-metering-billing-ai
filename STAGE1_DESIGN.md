# Stage 1 Design

## T1.1 Problem Statement

FlyRank's Usage Metering & Billing Engine is a small backend service that keeps a reliable tenant-level record of metered product use and makes that record usable for billing and plan-limit decisions. Its purpose is to give the product a single, understandable answer about each tenant's current usage position without expanding into a broad billing platform.

In this system, a **tenant** is the trusted boundary for one customer organization or workspace. Usage, cost information, and plan-limit decisions belong to that tenant and must remain separate from every other tenant.

The service answers three core questions for a tenant:

1. **How much has the tenant used?** It reports the tenant's recorded API-call and AI-token usage for the relevant billing period.
2. **What does that usage cost?** It determines the billable cost associated with the tenant's recorded usage under its plan.
3. **Has the tenant reached its limit?** It determines whether the tenant can continue using the metered capability within the limits of its current plan.

The capstone stays deliberately small: it focuses on Free and Pro tenants, the two metered usage dimensions of API calls and AI tokens, and the minimum billing information needed to answer these three questions.

## T1.2 Explicit Non-Goal

This project is not a full billing or invoicing platform. The core capstone scope explicitly excludes:

- Invoicing
- Overage charging
- Proration
- Complex dashboards
- Microservices
- Paid infrastructure