# Syndicate by Maximor readiness — Track 2

## Submission identity

- **Hackathon:** Syndicate by Maximor
- **Track:** 2 — Autonomous Office of the CFO
- **Project:** Cherry CFO — Autonomous Finance Agent
- **Judge-facing workflow:** NAV Quality Controller
- **Live demo:** https://cherry-cfo-canvas.vercel.app
- **Feature branch:** `ui/syndicate-cfo-canvas`
- **Hackathon base branch:** `hackathon/syndicate-cfo-2026`

## Official build boundary

The recorded official build start is:

```text
2026-09-05 17:00 Europe/London
```

The pre-kickoff baseline is:

```text
811420327923a8c20795fd72bf221aab0a534bad
```

Everything reachable from that baseline is treated as pre-existing and must not be described as built during Syndicate.

See:

- `../SYNDICATE_BUILD_LOG.md`
- `../PREEXISTING_CODE.md`

No Syndicate documentation should imply that the whole repository was created during the event.

## AO requirement

AO is mandatory for Syndicate and is part of the submission evidence.

The canonical AO session record lives in `../SYNDICATE_BUILD_LOG.md`. At the time this readiness document was written, sessions 1–7 are recorded as completed and session 8 remains planned. Do not mark a session completed unless a genuine AO session and its result exist.

Useful evidence to retain for the demo/submission:

- AO session list / board;
- meaningful session names;
- screenshots or session identifiers;
- resulting commit SHA(s);
- short explanation of what changed because of the session.

## Final problem statement

A fund controller receives a fragmented NAV close pack and must determine whether there is enough reliable evidence to sign off.

The workflow needs to answer:

1. What evidence was supplied?
2. What type of evidence is each file?
3. Which financial controls can run from that evidence?
4. What reconciles?
5. Which findings are genuine breaks versus evidence gaps?
6. What should be investigated or returned to the administrator?
7. What final decision requires human judgement?

Cherry CFO addresses this as one evidence-led NAV review rather than as a generic finance chatbot.

## Final product flow

```text
Upload close-pack evidence
        ↓
Classify + validate
        ↓
Evidence readiness
        ↓
Deterministic NAV / GL controls
        ↓
Structured exceptions
        ↓
Agentic investigation + remediation
        ↓
Human NAV decision
        ↓
Canvas + controller document / audit trail
```

## Judging alignment

### Is this a real Office of the CFO pain point?

Yes. The solution focuses on controller review of a NAV close pack: evidence completeness, reconciliation, exception handling, administrator remediation and sign-off.

The product is intentionally narrower than a general “AI CFO.”

### Is the human judgement intuitive?

Human judgement is an explicit workflow state. A reviewer can choose:

- Approve NAV
- Approve with exception
- Request evidence
- Return to administrator
- Escalate

The user sees the evidence and deterministic control state before deciding.

### Is the automation deep enough?

The architecture separates:

- evidence classification;
- readiness;
- deterministic controls;
- exception investigation;
- remediation;
- human decision; and
- evidence lineage.

The model cannot override the deterministic finance result.

### Could an accountant use it?

The workflow is evidence-led and fail-closed:

- unknown evidence remains unknown;
- missing evidence remains missing;
- supported partial controls can still run;
- financial arithmetic is deterministic;
- findings retain source lineage; and
- final sign-off remains human.

## Evidence intake checklist

The workbench can accept mixed sources including:

- administrator NAV evidence;
- investor-level GL workbooks;
- structured side-letter rules;
- statements / supporting PDFs;
- Excel / CSV / JSON data;
- bank/custodian evidence; and
- ZIP / text supporting packs where supported.

The public Vercel demo includes browser-side transport optimisation for large Excel files. This is a hosting workaround, not a control shortcut.

## Demo checklist

Before recording/submitting:

- [ ] Hard-refresh the live app and confirm the upload CTA is visible.
- [ ] Confirm multi-file / multi-batch selection works.
- [ ] Confirm a case is created after upload.
- [ ] Confirm evidence appears as canvas nodes.
- [ ] Confirm readiness runs and shows supported controls/gaps.
- [ ] Confirm deterministic NAV controls run for supported evidence.
- [ ] Confirm an exception / evidence gap is visible.
- [ ] Confirm agent review can run when model access is available.
- [ ] Confirm agent output is advisory and cannot change deterministic state.
- [ ] Confirm the human-decision dialog shows all supported decision routes.
- [ ] Confirm Document view renders the same case state.
- [ ] Confirm no production write/payment action exists in the demo.
- [ ] Capture AO sessions for the final video.
- [ ] Show only genuine AO sessions, not artificial session-count padding.

## Preferred 2-minute story

1. **Problem:** fragmented NAV evidence creates repetitive controller investigation.
2. **Upload:** bring multiple source files into one review.
3. **Readiness:** Cherry shows what can actually be checked.
4. **Controls:** deterministic finance checks produce the authoritative result.
5. **Agent:** exceptions are consolidated and explained.
6. **Human:** controller records sign-off / evidence / escalation decision.
7. **Close:** “Cherry does the finance work required to reach a decision; humans remain responsible for the decisions that matter.”

See `DEMO_SCRIPT.md` for timings.

## Safety / authority checklist

- [x] AI does not manufacture authoritative NAV figures.
- [x] Missing evidence is not filled by inference.
- [x] Deterministic controls own financial calculations.
- [x] Agent review cannot overwrite deterministic state.
- [x] Human decision is explicit.
- [x] No payment initiation is part of the NAV workbench.
- [x] No silent official-NAV or production-ledger write is part of the NAV workbench.
- [x] Evidence identity / lineage is preserved in the case model.

## Observability

The branch contains Neatlogs instrumentation that can be enabled with `NEATLOGS_API_KEY` for agent tracing. Observability is optional to finance correctness: if tracing is unavailable, the control outcome must remain unchanged.

## Current limits to disclose rather than hide

- Full NAV controls require the evidence each check needs.
- A raw NAV workbook may be recognised without having a complete normalisation adapter into the administrator-summary contract.
- The hosted Vercel demo has request-size limits and therefore uses browser transport optimisation for large Excel inputs.
- In-memory case state is demo/session state unless durable persistence is configured.
- Model-backed review depends on an available provider; deterministic controls should fail closed / remain usable when the provider is unavailable.

## Legacy repository naming

Some pre-existing source/test modules retain `ylookup_*` names because they originated in earlier private-markets work and are still useful for parsing/regression compatibility.

For this branch's README, docs, demo and submission use **Syndicate / Cherry CFO NAV Quality Controller** terminology.

Do not delete working legacy code solely to remove a historical name; keep the provenance boundary explicit instead.

## Final submission links

- **Live:** https://cherry-cfo-canvas.vercel.app
- **Source:** https://github.com/sohamtech-uk/cherry-agentic-finops/tree/ui/syndicate-cfo-canvas
- **Build evidence:** `../SYNDICATE_BUILD_LOG.md`

Add the final Devpost, YouTube and public X/LinkedIn demo-post URLs once they are published.
