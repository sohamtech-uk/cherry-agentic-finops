# Agents for Humans: Building Cherry Agent — Human-Governed Finance Ops with Strands Agents and Amazon Bedrock

Small-business owners rarely start a company because they enjoy reconciling bank transactions, chasing receipts, checking invoices, or reviewing bookkeeping exceptions.

Yet these small administrative tasks accumulate quickly.

We built **Cherry Agent** around a simple question:

> What if an AI agent could quietly handle routine finance operations, while involving a human only when judgment or approval is genuinely required?

Cherry Agent is our submission for the **Agents for Humans** hackathon in the **Professional Agents** track.

## The problem

A typical SME finance workflow can involve:

- receiving an invoice or receipt;
- extracting supplier and payment information;
- categorising the expense;
- finding the corresponding bank transaction;
- reconciling the records;
- checking company policy;
- requesting approval where needed;
- and preserving evidence for bookkeeping and audit.

Most accounting software provides tools for these steps, but the human still orchestrates the process.

Cherry Agent changes that relationship.

Instead of asking the user to move through every screen, the agent coordinates the workflow and surfaces only the cases that genuinely need attention.

## The architecture

For this hackathon we built a new orchestration layer using the **Strands Agents SDK**.

The architecture is deliberately divided into two layers:

```text
SME user
   |
   v
Cherry Agent
Strands Agents SDK
   |
   v
Amazon Bedrock
Claude
   |
   +----------------------+
   |          |           |
   v          v           v
Workflow   Control     Evidence
Agent      Agent       Agent
   |          |           |
   +----------+-----------+
              |
              v
     Deterministic Cherry
       finance controls
              |
       +------+------+
       |             |
       v             v
Automatic       Human review
completion        required
       |             |
       +------+------+
              |
              v
          Audit trail
```

The distinction is important.

**Strands handles reasoning, orchestration and tool selection.**

Our deterministic finance engine remains responsible for calculations, reconciliation decisions, thresholds and financial-control outcomes.

We intentionally do not allow the language model to become the source of truth for financial arithmetic.

## Specialist agents

Cherry Agent uses several specialised Strands agents.

### Workflow Specialist

The Workflow Specialist handles routine finance operations and calls bounded tools for tasks such as reconciliation.

It can answer questions such as:

> “Process this routine finance workflow and tell me whether it can be reconciled automatically.”

### Control Specialist

The Control Specialist explains why a deterministic financial control allowed or stopped a workflow.

For example:

> “This invoice cannot continue automatically because the supplier bank details have changed.”

The agent explains the issue, but **it cannot override the control**.

### Evidence Specialist

The Evidence Specialist turns the workflow history into something useful for the human reviewer.

It can explain:

- what evidence was used;
- which controls ran;
- what failed;
- who needs to act;
- and what remains unresolved.

That makes the system more understandable and auditable than a black-box AI decision.

## Human approval is an action, not a failure

One design decision became particularly important while building Cherry Agent.

Agents are often judged by how much work they can perform autonomously.

In finance, however, **knowing when not to act is equally important**.

Consider an invoice where the supplier's bank details have changed.

A fully autonomous system might try to continue.

Cherry Agent instead stops:

```text
Changed bank details detected
        |
        v
Deterministic control fails
        |
        v
Human verification required
        |
        v
Agent explains the reason
        |
        v
Human decides
```

The agent is deliberately unable to manufacture that approval.

Human approval remains outside the agent's unrestricted tool surface.

This is central to our interpretation of **Agents for Humans**: AI should remove repetitive work without removing human authority from consequential decisions.

## Why Strands Agents

Strands was a natural fit because Cherry Agent is not simply a chatbot.

It needs to:

1. understand the user's objective;
2. determine which specialist should handle it;
3. select bounded tools;
4. inspect their results;
5. decide whether further work is necessary;
6. and explain the outcome.

The agent is therefore an orchestrator around real software capabilities.

Rather than giving one giant model access to everything, we expose a limited tool surface to specialised agents.

That separation also makes the system easier to reason about and safer to extend.

## Amazon Bedrock

Our Strands implementation uses **Amazon Bedrock** as the model provider.

For the hackathon AWS implementation, the flow is:

```text
Strands Agent
      |
      v
Amazon Bedrock
      |
      v
Claude Sonnet
      |
      v
Finance tools
```

This means normal AWS IAM controls can govern model access rather than embedding external API credentials inside the application.

## Amazon Bedrock AgentCore

We also designed Cherry Agent to run on **Amazon Bedrock AgentCore Runtime**.

The AgentCore entry point receives a request such as:

```json
{
  "prompt": "Run an approval scenario and explain why a human is required."
}
```

and invokes a fresh Cherry Agent hierarchy for that request.

Our target deployment is in AWS `eu-west-2`.

The production architecture therefore becomes:

```text
User
  |
  v
Application
  |
  v
Amazon Bedrock AgentCore
  |
  v
Cherry Agent / Strands
  |
  v
Amazon Bedrock
  |
  v
Deterministic finance controls
```

## Three scenarios demonstrate the model

Our hackathon demonstration focuses on three cases.

### 1. Routine automation

The evidence is complete and the financial controls pass.

Cherry Agent completes the reconciliation workflow without asking the user to inspect routine work.

### 2. Human approval

A deterministic policy identifies something requiring human judgment.

The agent explains:

- what happened;
- which control stopped the workflow;
- and what the human needs to review.

It does not approve the transaction itself.

### 3. Evidence exception

Information is incomplete or conflicting.

Instead of guessing, Cherry Agent surfaces the missing evidence.

This behaviour is particularly important in professional agent systems: **uncertainty should become visible work rather than an invisible hallucination.**

## What was reused and what we built for the hackathon

Transparency about this boundary is important.

Cherry Money and parts of our deterministic finance engine existed before this hackathon.

For **Agents for Humans**, we built the new AWS-focused agent layer around that foundation, including:

- Strands Agents SDK orchestration;
- Strands specialist agents;
- Amazon Bedrock integration;
- AgentCore-compatible runtime;
- AWS deployment architecture;
- and the new hackathon-specific human-governed agent workflow.

The existing finance engine is treated as a tool and control layer rather than being represented as newly created hackathon work.

## What we learned

Our biggest lesson was that useful professional agents should not simply maximise autonomy.

They should maximise **appropriate autonomy**.

For finance, that means combining:

$$
\text{Agent reasoning}
+
\text{Deterministic controls}
+
\text{Human authority}
$$

The agent is excellent at understanding context, deciding what to investigate and coordinating tools.

Traditional software is excellent at exact arithmetic, rules and invariant enforcement.

Humans remain best placed to make consequential decisions when evidence is incomplete or risk is elevated.

Cherry Agent combines all three.

## What's next

Next we want Cherry Agent to handle a broader set of small-business finance operations:

- receipt processing;
- accounts payable;
- transaction categorisation;
- bank reconciliation;
- approval routing;
- duplicate and anomaly detection;
- cash-flow monitoring;
- bookkeeping preparation;
- and month-end evidence collection.

Our longer-term goal is not to replace accountants or business owners.

It is to remove the repetitive administrative work around them.

**The best finance agent should be almost invisible when everything is normal — and extremely clear when a human is needed.**

---

**Built with:** Strands Agents SDK · Amazon Bedrock · Amazon Bedrock AgentCore · Python · FastAPI · Pydantic · Docker

**GitHub:** https://github.com/sohamtech-uk/cherry-agentic-finops

> Publishing note: the final bonus post must be published on builder.aws and should keep “Agents for Humans” in the title.