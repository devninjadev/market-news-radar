---
name: market-news-radar
description: Use when users ask about current financial news, trending market events, market breadth, ETF risk signals, volatility conditions, or why U.S. equities are moving now.
---

# Market News Radar

Answer in Korean. Lead with the verdict, distinguish evidence states, and limit causal language to the strength of the evidence.

## Workflow

1. Resolve the question and time window.
2. Collect direct feeds, Telegram, market clock/snapshots, and VIX data with partial-failure tolerance.
3. Normalize and cluster syndicated copies before ranking events.
4. Search primary or authoritative sources when context or factual verification changes the answer.
5. Keep influential observed statements even when their contents remain unverified.
6. Synthesize: verdict → event → importance → market confirmation/contradiction → watch conditions → material limits.

Read [source-contracts.md](references/source-contracts.md) before collection. Run `scripts/collect_sources.py --source all` for the three RSS.app feeds, Trump archive, and VIX observations. Open the three Telegram pages with agent web tools. Check the Alpaca market clock before requesting the seven ETF snapshots. Use web search only when additional context or verification could materially change the answer.

For a broad briefing, prioritize the latest six hours, retain material events from the latest 24 hours, and rank only important event clusters, normally capping the list at five to eight. Do not pad the list when fewer events are important or sources fail. For a targeted causal question, narrow collection to the relevant event and pre/post window, then compare timing, cross-sectional ETF moves, volatility observations, and independent confirmation.

Continue with successful sources when one source fails. State a missing source near any conclusion it materially weakens. If every core source fails, say that the current situation cannot be verified.

## Evidence contract

Label and keep these states separate:

- `발언 확인`: Record who said or reposted what, where, and when; link the observed statement.
- `내용 미검증`: Preserve a market-relevant statement while marking its factual or policy content unverified.
- `공식 확인`: Link the primary document or authoritative confirmation and state exactly what it confirms.
- `반박·충돌`: Show a denial, conflicting source, or market signal that does not support the narrative.
- `해석`: Mark the agent's inference and calibrate it to the evidence.

Do not delete an influential observed statement merely because its contents remain unverified. Separate the attributed statement, factual or policy status, official confirmation or conflict, observed price response, and causal confidence.

When a user asks whether to omit an influential or market-relevant observed statement because its contents are unverified, the opening verdict must explicitly contrast retaining the observed market event with not promoting the claim contents to verified fact.

Attach a direct original or official link and normalized UTC `published_at` to each central factual claim when available; use `published_at_raw` when the original wording or timezone matters. Attach observation time and feed scope to price and volatility claims. Put access failures, missing source timestamps, stale/future timestamps, and feed limits next to the affected claim rather than only in a closing disclaimer.

For Trump archive items, use `statement_kind`, `original_author`, `original_url`, and archive-preserved `truth_social_url` to distinguish a direct statement from a repost. Treat `truth_social_url` as an archive reference, not automatic evidence of original authorship. Attribute a repost's content only when an explicit `RT @author` signal exists or an allowed Truth Social `/@user/...` URL identifies a non-Trump author; otherwise say the original author is unavailable. Do not infer authorship from arbitrary URLs or text.

Treat copies of the same wire, Telegram reposts, and headlines pointing to one original as one event cluster. Preserve their links, but never count channel count as independent confirmation.

Use causal language only when temporal order, cross-asset or cross-sectional confirmation, and independent evidence support it. Otherwise say the evidence is `consistent with`, `may reflect`, or `does not establish` the proposed cause. Use untimestamped or otherwise unverified price observations only as supporting signals.

Interpret the VIX sheet only as the supplied ordered maturity observations. Do not describe it as a precise futures term structure. When source timestamps are absent, do not attribute intraday moves or claim changes from a prior period.

Use IEX ETF data for direction and relative moves when applicable, but never present IEX volume as consolidated U.S. market volume.

## Response shape

1. Give a one- or two-sentence verdict.
2. Explain each ranked event, its importance, and its evidence state with nearby links and times.
3. Show ETF breadth, credit, and volatility confirmation or contradiction.
4. State the conditions that would strengthen, weaken, or reverse the verdict.
5. End with only the material data, freshness, access, and verification limits not already stated nearby.
