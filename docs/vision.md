# Kairos — Product Vision

> **Κairós** (*καιρός*) — ancient Greek for "the opportune moment". In trading, timing is everything. The name fits.
>
> **Status**: vision document, not an implementation spec. All OpenSpec change proposals should align to this document.

## Manifesto

**Kairos is not another trading framework.**

Kairos is an **adaptive trading engine** that stands on the shoulders of the open-source trading ecosystem — we openly use the best primitives available — and **layers on top something nobody else offers**: continuous, multi-source learning that makes the engine smarter every week.

Three principles:

1. **Curate the best, don't reinvent.** We build on `ccxt` for exchange connectivity, proven indicator libraries for math, battle-tested WebSocket reconnect patterns from `hummingbot`, clean strategy structure from `Jesse`. We're not here to reimplement what the community has already solved.
2. **Add our grain of sand.** The *value* we add is a single coherent layer on top: **adaptivity**. Adaptive execution, adaptive risk, adaptive tuning, adaptive regime awareness — powered by a self-improving meta-layer that ingests the ecosystem's evolution automatically.
3. **Kairos learns from three sources at once**: live performance (feedback per fill), user behavior (federated learning, privacy-preserving), and the entire public ecosystem (monitors competitors and research automatically, evaluates improvements, incorporates what works).

This is the moat. It cannot be replicated by forking — a fork starts at zero accumulated adaptation while Kairos keeps widening the gap every week.

## What Kairos is

- A **live Python trading runtime** built on the best community primitives + our adaptivity layer
- A **learning system** that treats every trade as a training signal
- A **research agent** that crawls GitHub, arxiv, and strategy marketplaces weekly, evaluates improvements on our data, merges what wins
- A **commercial product** — packaged, documented, versioned, monetizable, proprietary

## What Kairos is not

- Not a from-scratch rewrite of everything in trading
- Not a thin wrapper on ccxt with a new logo
- Not static — it ships behavior changes every week without manual releases
- Not a NautilusTrader clone

## The curation-plus-differentiation architecture

```
┌────────────────────────────────────────────────────────┐
│  KAIROS — OUR LAYER (proprietary IP)                   │
│  - Continual learning + Bayesian parameter posteriors  │
│  - Adaptive execution engine (regime × pair policies)  │
│  - Behavioral risk model (personalized per user)       │
│  - Why-card explanations                               │
│  - Counterfactual shadow simulation                    │
│  - Federated cross-user learning                       │
│  - IngestionActor (the meta-improvement engine)        │
│  - Cryptographically-signed track records              │
└────────────────────────────────────────────────────────┘
       ↑ our code, our IP, competitive moat
       │
┌────────────────────────────────────────────────────────┐
│  CURATED FOUNDATION (open source, embraced publicly)   │
│  - ccxt: exchange connectivity (200+ exchanges)        │
│  - pandas-ta / ta-lib: indicator math                  │
│  - WebSocket patterns adapted from hummingbot          │
│  - Strategy structure inspired by Jesse, Freqtrade     │
│  - Backtest mechanics inspired by vectorbt             │
│  - Order/actor patterns inspired by NautilusTrader     │
│  - asyncio event loop (stdlib)                         │
└────────────────────────────────────────────────────────┘
       ↑ we cite, attribute, and stay current
```

We don't hide the foundation. We celebrate it. Our pitch is honest: *"Best of the ecosystem, curated and made coherent, with an adaptive layer on top."* That honesty is a competitive asset — users trust what they understand.

## Core differentiators (our grain of sand)

### 1. Adaptive execution

The OrderManager learns, per (instrument × regime × spread), the best order type + timing for realized slippage. Over weeks, it converges to per-pair execution policies that outperform any static rule.

Example: on BTCUSDC during low-liquidity hours (02-06 UTC), Kairos learns to prefer limit at mid+1 with a 30s fallback to market. On ETHUSDC during high vol, it learns the opposite.

**This is proprietary. This is Kairos.**

### 2. Risk that learns from your behavior

No fixed 3% daily stop. Kairos observes revealed preferences — when the user manually halts, when they let it ride through DD, when they add capital post-losses — and builds a **personal risk tolerance model**. ProtectionActor uses that model. Conservative user's bot halts at 7% DD automatically; aggressive user's at 20%. Personalized without asking.

### 3. Continual parameter tuning

Today's ParameterTuner does iterative 4h tuning. Kairos generalizes: **every trade updates a Bayesian posterior over strategy parameters**. Continuous, not cyclic. Each strategy converges to its optimal parameter set for *this* user's market, not a static backtest winner. Model persists across restarts.

### 4. Cross-asset signal fusion

Strategies don't operate in isolation. IntelligenceActor publishes regime signals and cross-asset facts (BTC dominance, ETH/BTC ratio inflection, altcoin rotation) as first-class events. Strategies subscribe. A DCA pauses during rotation; a grid widens when dominance rises. Unlocks strategies impossible on single-pair frameworks.

### 5. Regime-aware everything

Regime modulates execution (§1), risk thresholds (vol-scaled), position sizing (Kelly-fraction per regime), actor behavior, even UI (dashboard highlights different metrics). The regime detector itself is adaptive — it learns transition probabilities per-market.

### 6. Every trade has a "why" card

Every fill carries an **explanation record**:
- Indicator values at entry
- Regime detected
- Which filter triggered
- Estimated win probability (from the continual-learning model)
- Counterfactual: "if I hadn't traded, probability of missing X% move"

Surfaced on the dashboard as a tap-to-expand card. **No other retail framework offers this.**

### 7. Counterfactual shadow strategies

Kairos internally runs shadow instances of every other strategy on the user's live market. Measures counterfactual PnL. Surfaces recommendations: *"if you'd used Range Master last 7 days, +4.2% vs your current. Try it?"*

This is how Kairos **sells upgrades without nagging** — data-driven, user-opted.

### 8. Cryptographically-signed track records

Every marketplace strategy has an Ed25519-signed performance history. Not falsifiable. Publishable. Auditable. A marketing weapon in an industry full of cherry-picked screenshots.

### 9. Federated cross-user learning

SaaS advantage: as we grow, aggregate patterns emerge. *"Users with risk profile Q in regime R found strategy S performed best"* → defaults improve for new users. Privacy preserved (differential privacy + anonymized features). **Compounds with user count**: a competitor with 10 users learns 100x slower than Kairos with 1000.

### 10. IngestionActor — the meta-improvement engine (THE moat)

**Kairos continuously surveys the open-source trading ecosystem and incorporates improvements automatically.**

Every week, a background service (`IngestionActor`) does:

1. **Crawl target repos**: NautilusTrader, ccxt, Freqtrade, Jesse, Hummingbot, VNPY, qlib, stumpy, ta-lib, pandas-ta. Monitors their releases, commits, issues.
2. **Sample research**: arxiv q-fin.TR, q-fin.ST. Strategy marketplaces (Tradingview Pine public, OKX mass strategies).
3. **Diff against our state**: what's new since last scan?
4. **LLM-powered classification** (Anthropic API): bug fix? new indicator? new strategy concept? performance optimization? irrelevant?
5. **Evaluate**: port the candidate minimally, run through unit tests, backtest on 90 days of our production data, stability tests, edge cases.
6. **Decide**:
   - **Auto-merge** if: clean fix + all gates pass + metrics improve/match
   - **Propose PR** if: new feature, or significant improvement (>5%) in any regime
   - **Archive** if: metrics worse, too complex, inapplicable
7. **Accumulate a knowledge base**: every evaluation, including rejections, logged permanently. Over months, we build *"what works, what doesn't, in which conditions"* — a dataset nobody else has.

Dashboard surfaces a public **"Kairos Research"** page: *"This week we evaluated 47 proposals — 3 merged, 12 reviewing, 32 rejected. Here's what's new in your strategies."* Public, transparent, trust-building.

**Commercial story:**
> *"Your trading framework ships improvements annually when the maintainers feel like it. Kairos ships what the entire trading open-source community learned this week, tested against your real data, automatically."*

**Unfakeable.** Requires years of accumulated knowledge to replicate. Self-improving — the evaluator itself learns. Costs pennies per week (API calls + compute).

## User journeys

### The curious user

Lands on `trading-autopilot.dev`. Sees *"Powered by Kairos"* footer with a link. Clicks. Reads the Kairos vision. Sees signed track records. Sees per-trade explanations. Trusts. Signs up.

### The analytical user

After 2 weeks, dashboard shows: *"Kairos has adapted your bot. Your risk threshold moved from 3% DD to 4.2% because you never halted during 3-4% drawdowns. You can override this."* The adaptation is explained. Autonomy preserved.

### The sophisticated user

Opens the **Kairos Research** tab. Sees the weekly evaluation log. Reads auto-generated summaries of merged improvements. Feels the platform is alive and evolving *for them*.

### The strategy creator

Publishes a strategy to the marketplace. 3 months later: *"Your strategy has been adopted by 47 users. Kairos found 2 candidate improvements from the community — want to apply them?"*

### The skeptical user

Reads the risk adaptation. Can disable it. Fixes thresholds manually. Freedom preserved — adaptation is default, never forced.

## Glossary (Kairos vocabulary)

Terms we coin and own:

- **Adaptive execution** — OrderManager self-tuning per regime
- **Behavioral risk model** — personalized ProtectionActor
- **Continual tuning** — Bayesian posterior over parameters, per-trade updates
- **Cross-asset signal fusion** — multi-market regime + factor events
- **Why card** — per-trade explanation record
- **Counterfactual shadow** — always-on parallel sim of alternative strategies
- **Signed track record** — Ed25519-signed performance history
- **Federated intelligence** — privacy-preserving cross-user learning
- **IngestionActor** — background agent that crawls the ecosystem
- **Kairos Research** — the public weekly evaluation dashboard
- **Curated foundation** — the open-source primitives we embrace

Use these consistently in docs, UI, marketing. They become the language of the category we create.

## Moat

### Technical (compound over time)

- **IngestionActor's knowledge base** — accumulates weekly, never resets
- **Federated learning** — user-count dependent, compounds per user-month
- **Continual tuning** — per-user training data, compounds per trade

A day-one competitor is behind on engineering *and* on accumulated data. Catching up requires years of operation with users.

### Brand

- **Why cards** — UX felt immediately by users; competitor matches the feature, not the trust
- **Signed track records** — citeable by journalism, audits, regulators; first-mover gets cited
- **Kairos vocabulary** — we own the category lexicon

### Regulatory

- Signed history + why-cards = compliance narrative. MiCA, SEC, any KYC partner finds Kairos distinctively defensible

### Network

- SaaS users → federated learning → better defaults → more users. Two-sided data network effect

## Non-goals

- **Not** open-source (source-available for audits possibly; licensed for commercial use)
- **Not** the fastest engine (we sacrifice throughput for explainability and adaptability; our users are retail to mid-market, not HFT)
- **Not** replacing human strategy authors (marketplace values creativity; Kairos amplifies it)
- **Not** a no-code DSL at v1 (deferred)
- **Not** promising AI-generated strategies are safe (all AI suggestions go through our evaluation harness + human review)

## Relationship to Trading Autopilot (the SaaS)

- **Kairos** = the framework. Python library. Proprietary IP. Monetizable independently.
- **Trading Autopilot** = the SaaS. FastAPI + React + Stripe. Runs on Kairos. The **flagship reference customer**.

Kairos is designed to be **licensable**. Future partners can run their own SaaS on Kairos. Trading Autopilot proves it works at scale.

### Naming boundaries

| Surface | Name |
|---------|------|
| Python package on PyPI | `kairos-engine` (renames from `autopilot-engine`) |
| GitHub repo | `github.com/Vekkris76/kairos` (rename from `autopilot-engine`) |
| Domain | `kairos.dev` (or `kairostrading.dev` if .dev is taken) |
| Documentation site | `docs.kairos.dev` |
| The SaaS | stays `trading-autopilot.dev`, "powered by Kairos" footer |
| Internal dev dir | stays `nautilus/` briefly, renamed to `engine/` or `kairos/` during v3 migration |

We ship Kairos v1.0 with the new name. Existing `autopilot-engine` on PyPI is kept as a deprecated redirect for ~6 months.

## Versioning

- **autopilot-engine v0.1** (shipped, today's PyPI): indicators, paper exchange, Binance, order manager, risk, backtest, marketplace, analytics, `parity` module
- **Kairos v0.2** (3-4 wk): live runtime + actors + cache + execution + Binance WS upgrade → production-ready. **First release under the Kairos name.**
- **Kairos v0.3** (3-4 wk): adaptive execution (§1) + continual tuning (§3) + why card (§6) — the **learning milestone**
- **Kairos v0.4** (4-6 wk): IngestionActor v1 (§10) + counterfactual shadow (§7) — the **meta-improvement milestone**
- **Kairos v0.5** (4-6 wk): behavioral risk (§2) + cross-asset fusion (§4) + federated v1 (§9)
- **Kairos v0.6** (4-6 wk): signed track records (§8) + marketplace integration
- **Kairos v1.0** (GA, commercial launch): all 10 differentiators in production, licensing model, marketing push

Roughly 6-9 months to v1.0 at a steady pace. Quality over speed.

## The curation principle in action

A concrete example of *"curate + differentiate"*:

**Scenario**: adding WebSocket reconnect logic.

- **What we do not do**: write reconnect-with-backoff from scratch.
- **What we do**: study hummingbot's reconnect (solid), NT's reconciler (elegant), ccxt's transport layer (portable). Pick the best patterns. Integrate. Test on Binance testnet. Attribute in code comments (`# Pattern adapted from hummingbot v1.25 — MIT licensed`). Move on.
- **Where our grain goes**: above that reconnect layer, Kairos's IngestionActor notices that a new improvement landed in hummingbot's next release, auto-proposes the upgrade, evaluates it, merges if it wins. Our value is the *meta layer*, not the reconnect itself.

Apply this to every feature decision. Ask: *"who has already solved this? which primitive do we adopt? what do we add on top?"*

The answer is almost never "start from scratch".

## Execution principle

**Every feature must reinforce the "Kairos learns" narrative.**

If a feature doesn't get smarter over time or leverage adaptivity, we ship it but do not market it as a differentiator. Kairos's identity is continuous adaptation powered by ecosystem curation. Everything downstream follows that north star.
