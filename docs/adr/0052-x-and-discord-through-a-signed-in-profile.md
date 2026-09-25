# ADR-0052 — X and Discord through a signed-in profile

Status: accepted · 2026-09-25

## Context

ADR-0051 recorded the operator's decision: the agents read social media
through this machine, and the operator accepts the risk to their accounts.
M50 shipped the readers that need no account, Reddit and public Telegram
channels. X and Discord cannot be read without one: X answers a logged-out
visitor with an error, and a Discord channel is visible only to a member.

## Decision

- **A dedicated Edge profile**, `<workspace>/browser`, used only by Aurelis.
  It runs through Playwright on the Microsoft Edge already installed, so no
  browser is downloaded. The everyday browser, with its passwords, email and
  bank sessions, is never opened.
- **One sign-in, by the person.** `aurelis social login` opens a visible
  window of that profile on the X and Discord sign-in pages. The person
  signs in there. Nothing is typed for them, and Aurelis keeps no password
  or token. It sees X signed in by the session cookie, and Discord by the app
  loading. It then writes `signed-in.json`, which holds only the platforms
  and the time. Until that file names a platform, the wake does not open a
  page for it, and it says `not read, needs a person to sign into x once`.
- **Read-only by construction**, as in ADR-0051:
  - a reader opens one URL it built from a validated handle: an account's
    page, a live cashtag search, or a Discord channel;
  - it keeps the JSON the site's own page fetched (X's `UserTweets` and
    `SearchTimeline`, and Discord's channel messages), and only GET responses;
  - it never clicks, types or opens a link found in a post.
  The parsers walk that JSON for posts, so a change in the shape around a
  post does not lose it.
- **A budget per wake.** Twelve X accounts (the followed memecoins' own, then
  the chosen) and eight live cashtag searches, followed memecoins first. The
  searches rotate hour by hour, so every instrument comes up in turn without a
  burst in any one hour. Discord reads every followed channel.
- **Signed out means stop.** A page that sends the profile to a sign-in page
  ends that platform's reading for the wake, with the failure named. The wake
  does not retry against a signed-out session.
- **Targets.** X accounts come from the followed memecoins' own links and
  `aurelis social follow x`. Discord channels come from
  `aurelis social follow discord <channel link>`, in servers the signed-in
  profile has joined; the person joins them.

## Consequences

- The memecoin desk now hears a token's own X account and its cashtag
  chatter, which is where the operator expects hype to form first.
- X and Discord can detect the automation and restrict the account, which
  the operator accepted. The small per-wake budget and headless reading keep
  the pace near a person's. If X refuses the headless profile, setting
  `AURELIS_BROWSER_HEADED=1` shows the window instead.
- The browser holds each site's session cookie in the git-ignored workspace
  folder, as any browser profile does. Deleting `<workspace>/browser` signs
  Aurelis out of both.
- **Not done.** Agents do not yet add or drop targets themselves by each
  target's measured lead over price. The table accepts their decisions, and
  the curation seat is next.
