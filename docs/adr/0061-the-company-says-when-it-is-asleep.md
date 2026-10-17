# ADR-0061 — The company says when it is asleep

Status: accepted · 2026-10-18

## Context

The company has stopped thinking twice without anyone being told.

- **15–24 September.** A failed wake killed the service (ADR-0046). For nine
  days nothing ran.
- **7–18 October.** The Claude subscription login the `agent_sdk` seats use
  expired. The service kept waking every hour: it fetched bars, books,
  funding, news and social posts, settled views and wrote its rows. But every
  `judge`, `discover` and curation action failed with *"Failed to
  authenticate: OAuth session expired"*. The autonomy loop records a failed
  action and moves on, by design. So each wake ended normally with zero model
  calls.

The facility showed "0 model call(s)" in small print. `service status`
listed a curation warning among a dozen vendor warnings. In eleven days no
agent sealed a view, wrote a note or stated a mechanism, and nothing told the
operator. A fact you have to go looking for is not an alarm.

## Decision

1. **A provider failure is marked on the cycle.** `CycleRecord.provider_down`
   is set when an action fails with `ProviderUnavailable`. A refused or
   unusable answer is the agent's own failure and is not marked.
   `AutonomyRun.provider_failures` collects what the provider said.
2. **A wake that tried to think and could not raises one critical alert.**
   It fires when the wake made no model call and at least one action failed
   on the provider (or the loop itself raised `ProviderUnavailable`). Its
   source is fixed (`service.asleep`) and so is its subject (`the company`),
   so the existing de-duplication keeps a week of failed wakes as one open
   alert. `wake_up_instruction` turns the provider's message into words a
   person can act on:
   - an expired login: run `claude`, then `/login`;
   - a spent allowance: wait for the reset;
   - anything else: check the connection and that `claude -p hi` answers.
3. **The first wake that makes a call closes it**, with the call count as
   the resolution.
4. **The person is told on the desktop**, once when it opens and once when it
   closes. Nothing is sent on the wakes in between. `service/notify.py`
   raises a Windows toast through PowerShell with no extra module, and the
   text travels in environment variables, never in the script. On other
   platforms, or when the toast fails, the message is printed to the service
   window. The notifier is injected, so tests collect messages instead of
   showing them.
5. **The facility answers "is it thinking?" before anything else.**
   `station/health.py` reduces the record to four states, worst first:
   - *asleep*: the open alert, in its own words;
   - *stopped*: no wake has started for 2½ hours, covering a dead or stuck
     service, which the alert cannot report because nothing is running to
     raise it;
   - *thinking*: a model answered in the last two hours;
   - *quiet*: none of the above.

   The two alarming states are drawn large and red at the top of `/` and
   `/now`.

## Consequences

- An expired login now costs at most one wake before the operator is told,
  instead of eleven days.
- *Stopped* is read by the station, which runs as a separate process, so a
  dead service is visible as long as the station runs. If the station is
  also dead, nothing tells the operator.
- **Not done.** No message reaches a phone. The toast needs the PC on and
  someone at it.
- **Not done.** Being asleep is not yet a condition on the mandate. A company
  that could not think for a week should arguably not count that week
  towards anything.
