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
- Real AI calls; token counts may be simulated for this capstone

## T1.3 Domain Model

The core domain is intentionally small and uses four related concepts:

- **Tenant** — the trusted customer organization or workspace boundary. A tenant owns its usage records and keeps one customer's billing context isolated from every other customer.
- **Plan** — the conceptual definition of a service offering. A plan describes the entitlement, limits, and pricing policy that apply to tenants using that offering.
- **Subscription** — the current link between a tenant and a plan, together with the tenant's payment-related state. It represents which plan currently governs the tenant's entitlement.
- **Usage event** — an immutable record of billable activity. Every usage event belongs to exactly one tenant and contributes to the tenant's view of usage, cost, and limits.

At a high level, a tenant has a current subscription, and that subscription selects the plan that governs the tenant's entitlement and pricing policy. The tenant's usage events are recorded independently as activity occurs. Those events are interpreted through the tenant's current plan context to answer the service's three core questions about usage, cost, and limits.

## T1.4 Architecture

The capstone uses the simplest layered architecture that clearly separates HTTP concerns, business rules, persistence, and Stripe-specific work:

- **API layer** — owns HTTP handling, request validation, headers, status codes, and dependency wiring. Route handlers should stay thin: they translate between HTTP and the service layer rather than carrying business logic where practical.
- **Service layer** — owns metering, quotas, pricing, subscription rules, idempotency, and the business logic that coordinates the domain.
- **Data layer** — owns PostgreSQL persistence, queries, transactions, and database constraints. It provides reliable data access without deciding product or billing rules.
- **Stripe integration layer** — owns Stripe Checkout, webhook signature verification, and Stripe-specific object and event handling. It isolates Stripe concerns from the rest of the service.

The API layer calls the service layer to perform product decisions. The service layer uses the data layer for durable records and uses the Stripe integration layer when Stripe-specific behavior is needed. This keeps transport, business, persistence, and third-party integration concerns distinct without introducing unnecessary services or infrastructure.