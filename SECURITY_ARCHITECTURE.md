# NHRA Tech Data — Security & Access Architecture (v0.33)

## Objective

The distributed desktop application must use the **same NHRA Tech Services identity** as the website rather than creating a second username/password database. The desktop must not embed or persist the user's Tech Services password and must not scrape/reuse browser session cookies.

A read-only audit of `csnead290c/nhratechservices` at commit `77eb280fe94825f93f2cdfdd3ab2568851aa6a19` confirmed the current API model: the website login endpoint accepts email/password and returns a signed Bearer token with a seven-day expiration; protected API routes read `Authorization: Bearer ...` and enforce server-side capabilities. The audited source does **not** provide an authorization-code/PKCE flow, refresh-token endpoint, desktop callback, or signed offline entitlement.

## Native desktop sign-in status

The preferred production native-app design remains a browser/device handoff that lets Tech Services authenticate the user without the desktop collecting the website password. PKCE is still a strong fit if Tech Services adds an authorization-code bridge, but v0.33 does not pretend that bridge exists today.

Until that server-side handoff exists, a protected/frozen desktop remains fail-closed. Development and integration tooling can use an explicitly supplied Bearer token for source-verified GET requests, but that is a testing seam rather than the final end-user sign-in UX.

A future PKCE/browser handoff would work as follows:

1. Desktop creates a high-entropy `state` and PKCE verifier/challenge (`S256`).
2. Desktop opens the system browser at a Tech Services authorization page.
3. Tech Services handles the normal account login/policy flow.
4. Tech Services returns a one-time authorization code to a desktop loopback/app redirect.
5. Desktop exchanges that code plus the verifier for a short-lived access token and, if supported, a rotating refresh token.
6. Refresh/offline secrets are stored only in the OS credential vault.

This is a **server addition still required**, not a description of the current website API.

## Current implementation

`runlab.auth` now provides:

- PKCE verifier/challenge/state generation;
- stable user identity plus roles/scopes;
- short-lived access-token session state;
- explicit offline-entitlement window support;
- refresh/revoke provider boundary;
- `KeyringCredentialStore`, which uses the platform credential vault and has **no plaintext-file fallback**;
- fail-closed `UnboundTechServicesAuthProvider` until the website exposes a safe native-desktop handoff.
- source-verified Bearer HTTP mechanics in `runlab.tech_services_http` for read-only integration/probing.

`runlab.transport.AuthorizedTechServicesTransport` enforces independent scopes before a network operation is attempted:

- `desktop.access` — application entitlement;
- `runs.read` — catalog/run metadata;
- `assets.read` — source-file download;
- `analysis.write` — approved derived-analysis write-back;
- `simulation.use` — RSA/vehicle simulation tools (desktop feature entitlement).

The workstation scope names remain a client-side product boundary; the audited website already performs its own server-side role/capability checks on protected routes. Final mapping should happen when the telemetry catalog endpoints are added.

## Protected-build behavior

`runlab.security.desktop_auth_required()` applies the release policy:

- source/development execution: authentication is not forced while the live adapter is still unbound;
- frozen/distributed executable: authentication is required by default;
- a protected build with no validated online session or signed unexpired offline entitlement **fails closed**;
- CI/development packaging can explicitly set `NHRA_TECH_DEV_UNAUTHENTICATED=1`; that override must not be used in production distribution.

This prevents a future release from accidentally becoming a permanent guest-capable engineering application.

## Offline track use

Track-side operation cannot depend on continuous Internet access. The proposed server contract therefore includes a **signed, bounded offline entitlement**. The desktop treats the grant as opaque and only a bound provider/public-key verifier can validate it. It must contain or bind at least:

- user identity;
- desktop entitlement/scopes;
- issued/expiry times;
- intended application/audience;
- optional organization/team restrictions.

The offline grant should be measured in hours/days, not months. Cached Runs remain subject to the user's authorization and the local machine's disk security.

## Local data at rest

Application login does not magically encrypt files already downloaded to disk. v0.25 still uses the SHA-256 content-addressed cache for integrity, not confidentiality.

Production deployment should therefore require normal endpoint controls (Windows account security plus BitLocker, or FileVault on macOS). If NHRA requires application-level encryption independent of OS disk encryption, add an encrypted object-cache layer whose key is sealed in the OS credential vault. Do not implement ad-hoc crypto.

## Executable integrity and distribution

The Windows build script now optionally Authenticode-signs the produced executable when `NHRA_CODESIGN_CERT_SHA1` and `NHRA_CODESIGN_TIMESTAMP_URL` are configured. It uses SHA-256 and an RFC 3161 timestamp and verifies the result with SignTool.

Microsoft guidance:

- SignTool: https://learn.microsoft.com/windows/win32/seccrypto/signtool
- Current Windows code-signing options: https://learn.microsoft.com/windows/apps/package-and-deploy/code-signing-options

A consistent trusted publisher signature provides tamper/authorship verification and builds Windows publisher reputation. It is not DRM.

## Protecting the application/RSA intellectual property

Authentication and code signing control **who may use the product** and whether a binary is genuine. They do not make Python bytecode impossible to inspect.

Long-term defense in depth:

1. keep source repositories private;
2. distribute signed binaries rather than source;
3. enforce server-issued feature entitlements;
4. compile the highest-value simulation/inverse modules to native code (Cython/Nuitka/Rust/C++) if IP resistance warrants it;
5. optionally execute selected proprietary fitting/model services server-side when network availability is acceptable;
6. retain a controlled local/offline solver for event use;
7. never rely on obfuscation as the only access control.

## Tech Services backend items still to implement/verify

The v0.32 source audit resolves the basic auth mechanism and current-user/run-history behavior. Remaining production items are:

- add a safe native-desktop browser/device authorization handoff; PKCE authorization code is the preferred design;
- define refresh/revocation semantics and refresh-token rotation if long-lived desktop sessions are required;
- define access-token audience/desktop claims or map server roles/capabilities into workstation entitlements;
- add bounded signed offline entitlement issuance/verification for track use;
- expose the existing Entry→Run bridge through the Run read API and add authoritative permanent Run→Asset catalog/download endpoints;
- enforce server-side authorization on Run/Asset/case/model endpoints;
- add audit logging for protected downloads and approved derived-analysis writes;
- expose public verification metadata if offline token/JWS verification is required.

The current direct login endpoint can remain for the website. The desktop does **not** need another password database, and v0.33 intentionally does not call that password endpoint from the end-user desktop.
