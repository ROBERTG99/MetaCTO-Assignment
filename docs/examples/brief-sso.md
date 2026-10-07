# Decision brief: IT director needs SAML SSO with Okta to enforce single sign-on across the organization and eliminate standalone passwords for Brightboard

Model: claude-sonnet-5-5 (prompt decision_brief_v1), confidence 0.80: Five independent accounts describe the same blocker and the facts agree, but effort is unknown, confirmed supporters are zero, and requests differ on provider and protocol.
Verification: All 28 claims checked against the data.

## Summary

Five accounts, four customers and one prospect, say they cannot standardize or roll out Brightboard without enterprise single sign-on. Okta is named by three of them and Azure AD / Entra ID by two. The decision is whether to build SAML SSO now and how far to extend it to other identity providers and enforcement.

## Problem

Organizations that centralize identity cannot let Brightboard keep separate passwords. They want users to sign in through the corporate identity provider, ideally with SSO enforced so there is no password fallback, and with MFA or conditional access applied at the IdP. Requests name different protocols and providers (SAML with Okta, OIDC or Entra ID with conditional access), but the underlying problem is the same: no supported SSO, so security teams block or limit rollout.

## Who is affected

IT and security roles (IT Director, Head of IT Infrastructure, Security & Compliance Lead, IT Administrator) at four enterprise accounts and one mid-market account. Northwind Logistics and Vantage Insurance use Okta, Helix Health Systems and Meridian Bank use Azure AD / Entra ID, and Bluepeak Software asks about Okta. Vantage is a prospect; the others are customers. End users are affected indirectly through blocked rollouts and manual password handling.

## Business impact

- Customer accounts asking carry significant recurring revenue, and several are enterprise accounts whose wider rollout is blocked until SSO exists. (ARR of the customer accounts asking: $1,314,000; Accounts asking: 5; Customer accounts: 4)
- A prospect has made SSO a hard condition of a deal with a stated signing target, so this affects new pipeline as well as the installed base. (Pipeline of the prospect accounts asking: $380,000; Prospect accounts: 1)
- Several asking customers renew soon, so unresolved SSO could become a retention risk. (Customer accounts renewing within 90 days: 3 (Northwind Logistics, Meridian Bank, Bluepeak Software))
- The need is rated high on priority, demand and urgency, with at least one request at blocker severity. It fits the enterprise readiness goal directly; strategic fit is not rated in the data. (Priority score (0-100): 89.9 / 100; Urgency (0-1): 1.00; Highest severity asked: blocker; Strategic fit (0-1): not rated)

## Evidence

> ideally with SSO enforced for our domain so nobody can fall back to a password
>
> Request #1

> no SSO, no deal
>
> Request #4

> our IT team won't approve rolling Brightboard out past the pilot group without SSO
>
> Request #5

> Until that's possible we can't onboard the wider finance org.
>
> Request #2

## Related needs

- depends on: IT Director needs automatic user provisioning from Okta to avoid manual seat management and address annual audit findings about offboarding (need #10). SCIM provisioning from Okta requires SSO first, so this need sets the order. Shipping SSO unlocks the provisioning and offboarding work and its audit benefits.
- overlaps: End users need to authenticate via Google login to access Brightboard without managing separate credentials (need #27). Google sign-in also removes separate credentials through an external identity provider. Shared authentication groundwork may be reusable, but it serves a different audience (end users, not IT admins).
- overlaps: End users need to authenticate with their Google Workspace account to avoid password management friction (need #12). Google Workspace login addresses the same password friction. Consider scoping it together with SSO so identity-provider work is sequenced once.

## Options

- **Build SAML 2.0 SSO now with enforcement.** Ship SAML SSO that works with Okta and Azure AD / Entra ID, with a domain-level option to enforce SSO and disable password login. Tradeoffs: Covers all five accounts' core need and the Vantage deal condition. Highest effort and security-sensitive. Conditional access and MFA depend on the IdP, so Meridian's OIDC request may need follow-up.
- **Smaller first step: SAML for Okta only, enforcement later.** Deliver SAML with Okta first, then add other providers and enforcement. Tradeoffs: Lower effort and serves Northwind, Vantage and Bluepeak. Leaves out Helix and Meridian (Azure AD / Entra ID), and without enforcement Northwind's no-fallback requirement is not met.
- **Workaround and validate while waiting.** Hold the build, give accounts a clear answer on status, and gather more detail on required protocols and timelines. Tradeoffs: No engineering cost now, but risks the Vantage deal and the soon-renewing accounts, and leaves rollouts blocked.

## Recommendation

Build SAML SSO now, designed to work with both Okta and Entra ID and to support enforcement, because demand is independent across five accounts, several are blocked, and it ties to enterprise readiness. If effort forces a phase, include enforcement and Entra ID early, since they appear in customer requests. Sequence SCIM after it.

## Risks

- Entra ID/OIDC and conditional access needs may require more than SAML, expanding scope.
- The Vantage deadline may not be achievable, so the deal could be lost regardless.
- Supporter confirmation is zero, so stated demand has not been validated beyond these requests.
- Okta-only phasing could leave Azure AD accounts blocked.

## Open questions

- What is the engineering effort for SAML, and for adding OIDC / Entra ID support?
- Do Meridian and Helix need conditional access features beyond standard SAML?
- What are the renewal dates and risk levels for the three accounts renewing within 90 days?
- Is the Vantage signing date negotiable, and would a roadmap commitment suffice?
- Should Google sign-in be scoped together with SSO?

## How this brief was built

1. **Related-needs agent** (claude-haiku-4-5, prompt related_needs_v1): 5 of 8 tool calls, read-only tools only; complete.

| # | Tool | Arguments | Result | Size | Latency |
|---|---|---|---|---|---|
| 1 | search_needs | `{"query": "single sign-on SSO identity provider authentication"}` | ok | 1319 chars | 8 ms |
| 2 | search_needs | `{"query": "Azure AD Entra ID OIDC conditional access"}` | ok | 1352 chars | 5 ms |
| 3 | get_need | `{"need_id": 10}` | ok | 1285 chars | 0 ms |
| 4 | get_need | `{"need_id": 27}` | ok | 664 chars | 0 ms |
| 5 | get_need | `{"need_id": 12}` | ok | 704 chars | 0 ms |

2. **Findings, checked in code** (a failing finding never reaches the brief):

- depends_on need #10 (IT Director needs automatic user provisioning from Okta to avoid manual seat management and address annual audit findings about offboarding), request #8: "Following up on SSO: once that's in, we also need SCIM so that when someone joins or leaves in Okta their Brightboard seat is created or removed automatically." (verified)
- overlaps need #27 (End users need to authenticate via Google login to access Brightboard without managing separate credentials), request #7: "Please add Sign in with Google." (verified)
- overlaps need #12 (End users need to authenticate with their Google Workspace account to avoid password management friction), request #3: "Kai from Pixelforge says his team keeps forgetting their Brightboard passwords and asks if they can just log in with their Google Workspace accounts like every other tool they use." (verified)

3. **Brief** (claude-sonnet-5-5, prompt decision_brief_v1), then 28 checks in code. Model calls (from ai_runs):

| Run | Step | Model | Input | Cache write | Cache read | Output | Cost | Latency | Outcome |
|---|---|---|---|---|---|---|---|---|---|
| 124 | related_needs | claude-haiku-4-5-20251001 | 2228 | 0 | 0 | 109 | $0.0028 | 8146 ms | ok |
| 125 | related_needs | claude-haiku-4-5-20251001 | 3120 | 0 | 0 | 131 | $0.0038 | 3111 ms | ok |
| 126 | related_needs | claude-haiku-4-5-20251001 | 4020 | 0 | 0 | 291 | $0.0055 | 4623 ms | ok |
| 127 | decision_brief | claude-sonnet-5-5 | 2169 | 2621 | 0 | 1978 | $0.0307 | 21302 ms | ok |

Total: 4 calls, $0.0427.
