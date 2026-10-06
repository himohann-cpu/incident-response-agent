---
id: database-locks
title: Clear blocking database locks
tags: database, locks, migration
services: *
---

# Clear blocking database locks

1. List long-running statements and the locks they hold.
2. If a migration is holding the lock, stop it; get the database owner's approval first.
3. Confirm blocked queries drain and latency recovers.
4. Re-plan the migration to run without a blocking lock.
