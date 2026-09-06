# Syndicate NAV analysis loading experience

The Cherry CFO workbench must keep the waiting experience engaging **without fabricating finance progress**.

The current Syndicate UI has two kinds of progress and treats them differently.

## 1. Browser-side evidence preparation

For the public Vercel demo, large Excel files may need transport optimisation before upload.

These are real client-side stages and can be shown explicitly:

```text
Preparing evidence
Optimising workbook
Summarising oversized investor GL when required
Uploading evidence
Evidence classified
Assessing NAV readiness
NAV analysis ready
```

The progress bar represents real preparation/upload milestones initiated by the browser. It must not claim that a NAV control passed before the backend returns the corresponding state.

## 2. Backend finance workflow

The finance stages are represented as case state, not simulated percentages:

```text
Evidence readiness
        ↓
Deterministic controls
        ↓
Agentic review
        ↓
Human decision
```

A stage is shown as completed only after the backend has returned it in the case payload.

## Initial hero

Before any evidence exists, the canvas should prioritise one action:

> **Upload NAV documents**

The chat composer and asset dock are hidden in the initial empty state so they cannot cover the upload CTA on common laptop viewports.

The hero is positioned relative to the visible scroll viewport rather than the centre of the larger virtual canvas.

## Upload experience

The upload dialog supports:

- multiple files in one picker selection;
- additional picker batches without replacing earlier files;
- folder selection where the browser supports it;
- removal of individual staged files;
- evidence from different sources in one NAV review; and
- later evidence additions to an existing case.

The dialog should remain scrollable on short screens and use high-contrast secondary text.

## Large-file behaviour

A hosted request-size failure should never look like a finance-analysis failure.

For oversized Excel evidence the browser can create a smaller transport representation. Recognised investor-GL transport compaction preserves the structured dimensions needed by the NAV controller and can aggregate rows when necessary.

If the file still cannot fit safely, the UI should explain the hosting limitation and ask for a smaller extract rather than silently dropping rows or pretending the upload succeeded.

## Cancellation

Cancel closes the upload flow and aborts any in-flight request owned by the transport-safe uploader. A cancelled request must not later surface a stale 413/error toast as though the user had continued the analysis.

## Truthful empty / partial states

The canvas should visually distinguish:

- no evidence uploaded;
- evidence uploaded but readiness not yet assessed;
- partial review supported;
- full NAV review supported;
- deterministic findings available;
- agent review available; and
- human decision recorded.

The most important UX rule is:

> **Never turn “waiting”, “missing evidence” or “not run” into a cosmetic success state.**

That is both an interface requirement and part of Cherry CFO's financial-control philosophy.
