---
title: Track Your Savings
description: A local dashboard that tells you exactly how much you saved by running on-device
---

# 💸 Track Your Savings — the local dashboard that makes local-first feel real

<figure markdown>
  ![Diapason savings dashboard](../assets/showcase/cost-savings.png){ .showcase-screenshot loading=lazy }
  <figcaption>The on-device savings dashboard. The comparison is what a month of Diapason usage would have cost on the cloud — measured per-query, not estimated. Nothing is uploaded.</figcaption>
</figure>

Diapason tracks every inference call you make — the tokens, the latency, the GPU energy — and computes what that same call *would have cost* on OpenAI, Anthropic, Google, and Bedrock. Those numbers stay on your machine.

My current month is roughly:

| | |
|---|---|
| Local inference cost | **`$0.00`** |
| Cloud-equivalent cost | **`$342.18`** (Claude Sonnet 4.6 baseline) |
| Energy used | **`1.4 kWh`** (~12¢ of grid power) |
| Prompts sent to a third party | **`0`** |

The dollar number is the hook. The bottom row is the actual reason I run Diapason.

## Why it's nice

- **You can see what each query costs you.** Not estimated, not "roughly" — measured. Watt-hours per token, FLOPs per token, latency. Every primitive in Diapason treats compute cost as a first-class quantity alongside accuracy.
- **It makes "local-first" stop being abstract.** Watching a bar chart accumulate `$X` a week that *didn't* leave your hands is a different kind of motivating than "your data is private" claims that you can't verify.
- **Privacy stops being an act of faith.** Every prompt I send to Diapason can be traced through the codebase to local-only paths. No "cloud failover" hiding behind a switch.

## How I set this up

You don't, really — metering is on by default and stays local. Every `diapason ask`, `diapason serve` request, and channel-routed message is recorded by the [telemetry system](../telemetry.md).

→ **[Telemetry overview](../telemetry.md)** — what's measured, where it's stored, and how to inspect it yourself with `diapason telemetry`.
