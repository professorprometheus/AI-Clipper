# ALPHA — Product Bible
Version: 0.2
Status: Build-ready V0

## 1. Product definition

Alpha is a quantitative social-media intelligence and clipping system. It accepts a Content Rewards campaign brief, researches what is currently working on social media, studies successful supplied clips and successful clipping channels, searches all approved source material for promising moments, creates campaign-compliant clips, asks a human to approve or modify them, publishes only after approval, and learns from both human feedback and actual market performance.

Alpha is not primarily an AI video editor. Its differentiator is the research, decision, experimentation and feedback system that sits before and after editing.

## 2. North-star question

Given:
- the campaign rules,
- all approved source material,
- the campaign's successful example clips,
- what is working across social media now,
- Alpha's historical experiments,
- and the performance of the user's own accounts,

what should Alpha publish next to maximise expected return?

## 3. Primary user workflow

1. User creates a campaign.
2. User enters/pastes Content Rewards information.
3. User supplies:
   - campaign name and economics;
   - content requirements;
   - multiple approved source URLs, commonly YouTube videos/playlists;
   - successful example clip URLs supplied by Content Rewards;
   - required branding/watermarks;
   - restrictions;
   - target social accounts/platforms.
4. User submits.
5. User may close the browser and switch off their laptop.
6. Alpha performs asynchronous server-side work:
   - source ingestion/transcription;
   - successful-example analysis;
   - wider social research;
   - successful clipper/channel analysis;
   - trend/outlier detection;
   - style-profile inference;
   - candidate moment discovery across all approved sources;
   - candidate ranking;
   - clip rendering;
   - campaign-rule enforcement;
   - automated QA.
7. Alpha emails the user when review-ready.
8. User reviews each clip and can:
   - approve;
   - request natural-language changes;
   - reject and select/give a reason.
9. Approved clips may be posted to connected accounts only after explicit human approval in V0.
10. Alpha later collects available performance data and asks the user how well it did.
11. Human feedback + observed performance are stored as research/evaluation data.
12. The system refines future ranking, style and experimentation policies.

## 4. Non-negotiable product requirements

- Multiple approved sources per campaign are first-class.
- YouTube URLs and playlists are common source types.
- Successful example clips are first-class campaign inputs.
- Research is required, not optional.
- Long-running campaign jobs must be asynchronous and server-side.
- Jobs must survive browser closure, logout, client disconnect and user-device shutdown.
- Work must be resumable after worker/process failure.
- V0 must target approximately £0 cash infrastructure cost where practical.
- Paid dependencies must not be required for a functional local/development path.
- V0 posting always requires human approval.
- The system must ask for feedback.
- The system must record why clips were selected and why they were rejected.
- Deterministic campaign rules must be enforced by code rather than entrusted to an LLM.
- AI-evaluated requirements must be stored separately from deterministic requirements.
- No campaign source outside the approved-source set may be used for the published clip unless the campaign explicitly permits external material.
- Platform terms, access rights and source-authorisation restrictions must be respected.

## 5. Research doctrine

Alpha begins by learning from successful humans.

It should analyse:
- campaign-provided successful examples;
- successful clipping accounts/channels;
- current viral/outlier posts;
- emerging topics;
- repeated hooks;
- clip durations;
- pacing;
- captions;
- framing/cropping;
- structure;
- humour;
- controversy;
- emotional pattern;
- payoff timing;
- cross-platform patterns;
- creator-relative outperformance.

The objective is to infer reusable style/strategy patterns, not to duplicate another creator's exact expressive work frame-for-frame.

Alpha should distinguish:
- viral post;
- viral angle;
- viral topic;
- emerging trend;
- format/meme trend;
- macro attention shift.

## 6. Quantitative principles

Prefer:
- relative performance over raw views;
- view/engagement velocity over stale totals;
- creator-normalised outlier scores;
- cross-creator confirmation;
- cross-platform confirmation;
- novelty;
- saturation;
- source-match strength;
- expected £ return;
- revenue per clip;
- revenue per human hour.

Views are an intermediate measure, not the final objective.

## 7. Style learning

Alpha may infer style profiles from sets of successful clips, for example:
- opening type;
- headline presence;
- caption density;
- words per caption chunk;
- cut frequency;
- crop style;
- speaker tracking;
- average clip length;
- ending style;
- context amount;
- emotion/angle.

Style profiles are reusable strategies, not copies of a single video's unique expression.

## 8. Experimentation and self-improvement

Alpha must not literally rewrite its own source code autonomously in V0.

Instead, it improves through a controlled experimentation system:
- record prediction before outcome;
- run explicit hypotheses;
- compare variants where platform/campaign rules allow;
- store control/treatment outcomes;
- update configurable strategy weights/policies;
- retain a Research Ledger;
- preserve an exploration budget so it does not get trapped exploiting one historical pattern.

Initial policy target:
- 80–90% exploitation of currently strong strategies;
- 10–20% exploration of promising alternatives.

## 9. Feedback loops

### Human feedback
Capture:
- approve/reject;
- bad moment;
- weak hook;
- bad editing;
- wrong topic;
- too much context;
- captions;
- crop;
- missed campaign requirement;
- overdone/saturated;
- free-text feedback.

### Market feedback
Capture where available:
- post URL;
- publication time;
- views over time;
- likes;
- comments;
- shares;
- qualified views;
- Content Rewards acceptance;
- revenue;
- payout;
- creator/account baseline.

Alpha should compare user preference against market results and surface meaningful disagreements.

## 10. Campaign-aware creative enrichment

Enrichment is an optional, evidence-driven strategy rather than decoration. The raw campaign brief remains the source record, while structured controls fail closed for music, memes/reactions, B-roll, sound effects and external image/video. A renderer may use external media only when the asset has recorded rights, licence, commercial-use and campaign provenance.

Each selected moment receives a versioned Enrichment Plan containing exact timing, duration, purpose, reason and asset lineage. Candidate suitability, successful-example feature evidence and campaign permissions inform that decision. Features that cannot be measured from public evidence must be labelled unavailable rather than invented. Native edits such as punch-ins, crops, freeze frames and emphasis graphics remain available without external copyright dependencies.

Enrichment choices are stored as measurable strategy features with the immutable clip version. Human edits create child plans, and performance experiments compare strategies such as music/silence, meme/no-meme, B-roll density and zoom timing without assuming that enrichment helps.

## 11. V0 success criteria

The V0 thesis to test:

Systematic social research + source matching can select better clips than uninformed/manual selection while reducing human research time.

Milestones:
1. A campaign can be entered and processed asynchronously.
2. Multiple approved sources can be indexed.
3. Research evidence is attached to recommendations.
4. Clips are rendered and campaign rules are verified.
5. Email review notification works.
6. Human modification/rejection feedback is stored.
7. Explicit approval gates publishing.
8. Performance records can be attached.
9. First £1 of attributable revenue.
10. Compare Alpha-selected clips against a human/control baseline.

## 12. Cost doctrine

At £0 revenue, prefer free/open-source/local/free-tier components.

Do not optimise for permanently spending £0. Optimise for return on cost.

A paid service becomes rational when expected incremental value comfortably exceeds incremental cost and the evidence is recorded.

## 13. Long-term moat hypothesis

The moat is not FFmpeg, Whisper or a foundation model.

The potential moat is:
- proprietary campaign/source/performance data;
- research history;
- labelled human feedback;
- experiment outcomes;
- learned strategy policies;
- longitudinal knowledge of what works, where, when and under what conditions.
