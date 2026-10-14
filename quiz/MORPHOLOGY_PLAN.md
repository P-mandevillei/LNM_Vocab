# Morphology tester: executive plan

Audit date: 13 October 2026. Status: chapter 10 work (step 1) is implemented;
provider evaluation and the remaining expansion are proposed.

Chapter 10 now covers all 19 individual inflectable words, with 26 exhaustive
entries when all four types are selected. All 40 tests pass, including complete
chapter 10 tables, agreement, infinitives and HTTP grading/retest checks. The
audit findings below describe the implementation before this update.

## Recommendation

Keep the existing quiz interface, chapter selection, random/exhaustive sampling,
grading and missed-entry retesting. Keep the local generator for the paradigms
it already handles. Add a provider/import boundary so a broader Latin morphology
source can supply reviewed, locally cached answer tables.

Chapter 10 alone needs a small lexical-data update, not a replacement engine.
However, the current implementation cannot cover the full range of later
introductory morphology through vocabulary additions alone. Its verb schema and
question construction are restricted to the present indicative and present
infinitive. A source integration is worth evaluating before expanding those
rules by hand. An API does not itself supply new exercise interfaces or support
syntax and translation topics; those remain separate curriculum features.

## Findings from the actual chapter 10 file

The audit used the current `ch10.md`, the default lexicon and an exhaustive draw.
There are 19 individual inflectable words, plus a verb phrase and a conjunction.

| Category | Available now | Missing definitions |
| --- | --- | --- |
| Nouns | 4 of 7 | `deus`, `hostis`, `nox` |
| Adjectives | 3 of 5 | `felix`, `pauci` |
| Individual verbs | 0 of 7 | All seven |

Thus seven distinct words are currently eligible. The additional four
noun/adjective pair entries reuse those words and do not increase coverage.

The engine already implements third-declension adjective patterns with one,
two and three terminations, and the mixed third conjugation (`3io`). `acer`,
`celeber` and `fortis` are recognized from their chapter listings. `felix` needs
its subtype declared. `pauci` needs a plural-only definition and an explicit
stem. `hostis` and `nox` need third-declension/i-stem metadata; `deus` needs
exceptional forms. The chapter's unmacronized verbs do not trigger the existing
inference and are absent from the lexicon. `capio`, `cupio` and `fugio` need
`3io` definitions; the others need their ordinary conjugation declared.

`consilia capere` is a phrase, so it cannot directly receive a single-word
conjugation table. `nec` has no inflection table. Both remain vocabulary items.
Passive availability must reflect the chapter sense; an intransitive verb
should not receive a fabricated six-person personal passive.

All 32 existing tests pass, including selected third-declension adjective and
mixed-conjugation fixtures. Their passing does not establish complete coverage
of the newly added chapter.

## Source assessment

[Collatinus at Biblissima](https://outils.biblissima.fr/en/collatinus-web/index.php)
is the first candidate: it offers full-table lookup and describes a lexical
database drawing on Gaffiot, Jeanneau, Lewis & Short and Georges. Its
[published web handler](https://github.com/biblissima/outils.biblissima.fr/blob/master/collatinus-web/collatinus-web.php)
dispatches inflection requests to Collatinus using `-F`; the
[browser client](https://github.com/biblissima/outils.biblissima.fr/blob/master/collatinus-web/collatinus-web.js)
receives HTML. This establishes a programmatic table-generation path, but does
not establish a supported, stable public JSON API or permission for automated
bulk requests. Hosted access, output completeness, reuse conditions and
deployment cost need a short proof before committing to this dependency.

Use Dickinson College's Allen & Greenough material as an independent reference
for fixtures, including its
[third-declension adjective paradigms](https://dcc.dickinson.edu/grammar/latin/3rd-declension-adjectives-classification-and-paradigms)
and [third-conjugation -io chart](https://dcc.dickinson.edu/sites/default/files/3rd_conj_io_verbs_pres.pdf).
These are reference documents rather than a verified table API.

## Proposed execution

1. **Complete chapter 10 with the current generator.** Add reviewed definitions
   for the twelve missing individual words, canonical quantities where known,
   accepted variants and restrictions. Exercise all four entry types, including
   plural-only agreement and the active/passive infinitives appropriate to each
   verb. This provides an immediately useful release independently of the
   provider evaluation.

2. **Prove the provider before adopting it.** Obtain and normalize representative
   tables for `deus`, `felix`, `pauci`, `capio` and later irregular/deponent
   examples. Check ambiguous lemmas, variants, unavailable forms, quantities,
   labels and source attribution against independent references. Determine
   whether supported hosted access is suitable. If it is not, assess a local
   Collatinus service behind our adapter. Report the dependency and maintenance
   tradeoffs before choosing that deployment. Do not build production grading
   around an unverified web endpoint.

3. **Generalize the answer data while preserving current contracts.** Introduce
   versioned lemma records with full dictionary/principal parts and cells
   identified by grammatical features: case, number, gender, degree, person,
   tense, mood, voice and nonfinite form as applicable. Record multiple accepted
   answers, absent forms, quantity confidence, grammatical restrictions, source
   and provider version. Distinguish grammatical voice from a deponent verb's
   meaning. Adapt these records to today's table format; retain compatibility
   with existing `morphology.json` overrides.

4. **Import and validate before quizzes start.** Resolve chapter listings to
   lemmas using dictionary forms and part of speech, not headword spelling
   alone. Fetch missing tables in a separate import/refresh operation, validate
   them and store them locally. Prefer explicit reviewed overrides, then
   validated cached tables, then applicable local rules. Display unresolved
   entries and reasons. Network failure must not change a quiz's answers or
   retest: both use the exact answer snapshot captured when the quiz was made.

5. **Expand by curriculum milestone.** First retain the present drills exactly
   as requested. Then add selections and views in the morphology tab for other
   indicative tenses, subjunctives/imperatives, deponents and irregular verbs,
   pronouns/numerals, comparative/superlative adjectives, and nonfinite forms
   such as participles, gerunds, gerundives and supines. Add locative and
   periphrastic forms where the curriculum calls for them. Each milestone needs
   independently checked examples; provider availability alone is insufficient
   evidence of correctness. The original vocabulary testing interface stays
   intact throughout.

## Acceptance and decision gates

- Chapter 10: all 19 individual inflectable words are eligible in appropriate
  modes; all four third-declension adjectives work in every gender; all three
  mixed-conjugation verbs have correct present active tables and infinitives,
  plus personal passive tables and infinitives where appropriate. Check every
  cell, not only nominatives or first-person forms.
- Check `deus` variants, `hostis`/`nox` genitive plurals, plural-only `pauci`, and
  noun/adjective agreement. Disabled singular cells must remain ungraded.
- Verify chapter selection, exhaustive coverage, random draws, per-cell grading
  and exact missed-entry retesting, as well as the original vocabulary workflow.
- Provider tests must cover offline use, timeouts, malformed/changed output,
  ambiguity, unavailable forms and changed cached versions. A source failure
  must never silently produce a guessed answer key.
- Continue with the provider only after its correctness, supported access/reuse
  and operating cost pass evaluation. Otherwise keep the local chapter 10 update
  and make a separate, explicit decision about the broader morphology backend.

This plan does not promise universal textbook coverage. It establishes an
extensible representation and a verification process for adding later topics
without rebuilding the quiz workflow or requiring live network access to grade.
