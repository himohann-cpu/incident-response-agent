---
id: dependency-outage
title: Handle an upstream dependency outage
tags: dependency, upstream
services: *
---

# Handle an upstream dependency outage

1. Confirm the dependency is failing for other callers too, using its status page or dashboard.
2. Page the owning team or open a ticket with the provider.
3. Enable degraded mode or the circuit breaker for the affected feature, if one exists.
4. Do not roll back your own service unless there is separate evidence against it.
5. Post a status update that names the dependency.
