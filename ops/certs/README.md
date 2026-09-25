# ops/certs — intermediate certificates a publisher forgets to send

`globalsign-gcc-r46-dv-tls-ca-2025.pem` — for www.pcbs.gov.ps (ops/fetch_pcbs.py).

PCBS serves its leaf (`CN=*.pcbs.gov.ps`, issued by *GlobalSign GCC R46 DV TLS CA 2025*) together with the WRONG
intermediate (*GlobalSign GCC R3 DV TLS CA 2020*). Browsers repair that from the certificate's AIA URL; Python and
curl fail with "unable to get local issuer certificate". The right intermediate, taken from that AIA URL
(http://secure.globalsign.com/cacert/gsgccr46dvtlsca2025.crt) on 2026-09-25, is ADDED to the system trust store for
PCBS requests only — verification stays on, and the chain still has to end at *GlobalSign Root R46*, which the
system store carries.

- subject: `C=BE, O=GlobalSign nv-sa, CN=GlobalSign GCC R46 DV TLS CA 2025`
- issuer: `C=BE, O=GlobalSign nv-sa, CN=GlobalSign Root R46`
- valid: 2025-09-17 → 2029-06-23
- sha256: `B5:94:10:F3:67:B9:86:E9:8E:53:A9:78:9A:65:80:55:3A:74:BE:51:52:11:D9:F6:EC:B6:E8:A1:1E:83:AE:AA`

If PCBS fixes its chain, nothing breaks; if it rotates to another CA, `ops/fetch_pcbs.py` fails with a TLS error in
the fetch ledger and the gap radar calls the line dead after three nights — replace this file from the new
certificate's AIA URL.
