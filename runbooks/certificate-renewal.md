---
id: certificate-renewal
title: Renew an expired certificate
tags: certificate, tls
services: *
---

# Renew an expired certificate

1. Check the certificate's expiry on the failing endpoint.
2. Issue or renew the certificate through the certificate manager.
3. Reload the service or proxy that serves it.
4. Add or fix the expiry alert so the next one fires 30 days ahead.
