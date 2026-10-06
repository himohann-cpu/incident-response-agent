---
id: rate-limit
title: Handle a rate limit or quota
tags: rate-limit, quota
services: *
---

# Handle a rate limit or quota

1. Identify which caller is consuming the quota.
2. Reduce request volume: back off, batch, or shed low-priority traffic.
3. Request a temporary quota increase from the provider if needed.
