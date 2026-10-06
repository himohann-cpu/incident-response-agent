---
id: revert-config
title: Revert a configuration or flag change
tags: config, flag
services: *
---

# Revert a configuration or flag change

1. Identify the exact key that changed and its previous value.
2. Revert the change through the normal config pipeline, not by hand on a host.
3. Confirm the running instances have picked up the reverted value.
4. Watch the alerting signal for 10 minutes.
