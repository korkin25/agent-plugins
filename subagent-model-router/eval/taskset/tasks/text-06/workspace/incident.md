# Incident report: payment API outage

Status: resolved
Reported by: Helena Vasquez-Moore, support lead
Incident commander: Tomas Adeyemi, site reliability engineer (on call)
Internal ticket: OPS-4471

## What happened

On 2027-01-14 at 09:02 UTC the public payment API began rejecting new
connections. Merchants saw "connection reset" errors when they tried to create
charges. The monitoring system raised the first alert at 09:05 UTC, and Tomas
Adeyemi acknowledged it at 09:09 UTC.

The outage lasted 47 minutes: the service was fully restored at 09:49 UTC.
During that window 1,284 payment requests failed. No payment was charged twice
and no card data was exposed. Requests that failed can be retried safely.

## Root cause

The TLS certificate on the load balancer lb-east-2 expired at 09:00 UTC. The
automatic renewal job had been failing silently since 2026-12-02, because its
service account lost write access to the certificate store during a
permissions clean-up. New TLS handshakes with lb-east-2 failed. The second load
balancer, lb-east-1, carries only internal traffic and was not affected.

## Resolution

Tomas Adeyemi issued a new certificate manually, deployed it to lb-east-2 at
09:44 UTC and confirmed recovery at 09:49 UTC. Affected merchants included
Bramblewood Tea, Corvid Books and Lumen Pet Supplies; the support team
contacted each of them on the same day.

## Follow-up actions

1. Restore the renewal job's write access and alert when a renewal fails
   (owner: Platform team, due 2027-01-21).
2. Alert 14 days before any certificate expires (owner: Platform team,
   due 2027-01-28).
3. Add a certificate check to the weekly on-call handover (owner: SRE team,
   due 2027-02-04).
