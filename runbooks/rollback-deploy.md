---
id: rollback-deploy
title: Roll back a deploy
tags: rollback, deploy
services: *
---

# Roll back a deploy

1. Confirm the error rate rose after the suspect deploy and not before it.
2. Announce the rollback in the incident channel and get the on-call engineer's approval.
3. Roll the service back to the previous release.
4. Watch the error rate for 10 minutes; if it does not recover, the deploy was not the cause.
5. Open a ticket to fix forward, and link this incident.
