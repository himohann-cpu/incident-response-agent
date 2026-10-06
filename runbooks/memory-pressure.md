---
id: memory-pressure
title: Respond to out-of-memory restarts
tags: memory, oom
services: *
---

# Respond to out-of-memory restarts

1. Check whether memory climbs steadily (a leak) or jumps with traffic (load).
2. Restart the affected instances to restore service.
3. If a recent change added caching or buffering, roll it back.
4. Capture a heap profile before the next restart if the cause is still unknown.
