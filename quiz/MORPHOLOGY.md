# Adding vocabulary and answer keys

Add new chapter vocabulary in the same Markdown format as before. The
morphology tester draws words only from the chapters you select. Dictionary
definitions supply answers; they do not add extra words to the draw.

Most regular first/second/fourth/fifth-declension nouns, first/second-declension
adjectives, and two/three-termination third-declension adjectives work directly
from their complete chapter listings. Regular verbs with `-āre`, `-ēre` or
`-īre` infinitives can be recognized directly for active quizzes. Ambiguous
classes, lexical restrictions, and exceptions go in **`morphology.json` in
the chapter folder**. With `--vault`, this means that vault's `morphology.json`.

The server reads this file for each new quiz and pool refresh. Save it and
click **reload files**; no restart or Python edit is needed. Existing quizzes
and retests keep the answers with which they were created.

## Minimal definitions

The chapter already supplies dictionary forms and gender, so you can add
only the extra information the generator needs:

```json
{
  "version": 1,
  "nouns": {
    "ignis": { "declension": 3, "i_stem": true }
  },
  "adjectives": {
    "felix": { "declension": 3, "i_stem": true },
    "unus": { "declension": 2, "pronominal": true }
  },
  "verbs": {
    "lego": { "conjugation": 3, "passive": true },
    "capio": { "conjugation": "3io", "passive": true }
  }
}
```

Use headwords as keys. Case and macrons do not affect lookup. Every
third-declension noun needs its subtype declared: `i_stem: true` uses
genitive plural `-ium`; the default `false` uses `-um`. For third-declension
adjectives with one termination, declare `i_stem` explicitly. The chapter's
second form is the genitive (`fēlīx, fēlīcis`); for two terminations it is the
neuter (`fortis, forte`); three terminations list all genders (`ācer, ācris,
ācre`). Adjective `declension: 2` denotes the first/second-declension pattern.

Supported verb classes are `1`, `2`, `3`, `"3io"`, `4`, and `"custom"`.
Set `passive: true` only when a complete personal passive is appropriate.
Otherwise the verb is offered only in the active voice. An unmarked `-ere`
infinitive needs a definition because it cannot reliably distinguish the
second and third conjugations.

## Canonical dictionary forms and quantities

Optionally supply canonical forms to fill in missing chapter information or
restore macrons in the answer key:

```json
{
  "version": 1,
  "nouns": {
    "manus": {
      "forms": ["manus", "manūs"],
      "gender": "f",
      "declension": 4
    }
  },
  "verbs": {
    "moneo": {
      "headword": "moneō",
      "infinitive": "monēre",
      "conjugation": 2,
      "passive": true
    }
  }
}
```

Noun `forms` contains nominative and genitive, including plural dictionary
forms when `number: "pl"`. Adjective `forms` contains its usual two or three
dictionary forms. Noun `gender` accepts `"m"`, `"f"`, `"n"`, and combinations
such as `"m/f"`. Use `number: "sg"` or `"pl"` for number restrictions; omit it
for both numbers. `stem` can override the stem derived from dictionary forms.

When canonical dictionary forms are supplied, quantities are considered
known by default. Set `quantities_known: false` if macrons are incomplete.
Definitions containing only classification metadata default to unknown
quantities; correct letters count as correct without misleading macron
corrections. `quantities_known: true` can explicitly trust fully macronized
chapter forms. A `source` string can record where a definition was checked.

Regular fifth-declension nouns other than `rēs` and `diēs` default to singular
only when inferred from chapter text. Add a definition and any needed
overrides for a noun whose plural is incomplete. Known fourth-declension
exceptions such as `domus`, `lacus` and `tribus` also need definitions.

## Exceptions and accepted variants

Overrides replace the generated answer for a particular cell. A string is
one answer; a list accepts any listed answer. Nominal cell keys combine a
case and number, such as `genitive_plural` or `ablative_singular`.

```json
{
  "version": 1,
  "nouns": {
    "lacus": {
      "declension": 4,
      "overrides": {
        "dative_plural": "lacubus",
        "ablative_plural": "lacubus"
      }
    },
    "filia": {
      "overrides": { "dative_plural": ["fīliābus", "fīliīs"] }
    }
  },
  "adjectives": {
    "meus": {
      "overrides": { "m": { "vocative_singular": "mī" } }
    }
  }
}
```

Definitions merge with the bundled vocabulary, including nested overrides.
Thus an existing word needs only the settings you want to change. Lists
replace existing lists. Adjective overrides are grouped by `m`, `f`, and `n`;
verb overrides are grouped by `active` and `passive`.

Use `null` for an unavailable nominal cell. It is disabled and not graded.
For entirely irregular nouns or adjectives, set `declension: "custom"` and
supply all six cases in both numbers through `overrides`. An adjective needs
one complete table per gender. A number-restricted noun needs only its
available number's six keys. Complete custom tables can include variants
and unavailable cells, without adding an inflection rule in Python.

## Entirely irregular verbs

Use `conjugation: "custom"` and complete `paradigms`. Each offered voice needs
six persons and the matching infinitive. For example:

```json
{
  "version": 1,
  "verbs": {
    "fero": {
      "headword": "ferō",
      "infinitive": "ferre",
      "conjugation": "custom",
      "passive": true,
      "paradigms": {
        "active": {
          "p1_singular": "ferō", "p2_singular": "fers", "p3_singular": "fert",
          "p1_plural": "ferimus", "p2_plural": "fertis", "p3_plural": "ferunt",
          "infinitive": "ferre"
        },
        "passive": {
          "p1_singular": "feror", "p2_singular": ["ferris", "ferre"], "p3_singular": "fertur",
          "p1_plural": "ferimur", "p2_plural": "feriminī", "p3_plural": "feruntur",
          "infinitive": "ferrī"
        }
      }
    }
  }
}
```

`aliases` can list earlier inflected chapter headwords which should resolve
to this verb. When using aliases, provide the canonical `headword` explicitly.
Ordinary verbs can use individual `overrides` without replacing the complete
paradigm. Infinitive overrides also accept lists of variants.

## Validation and sources

Invalid JSON, unsupported settings, misspelled form keys, incomplete custom
tables, and duplicate headwords produce errors identifying the file and
definition. Words needing more information appear under **unavailable chapter
entries**. No guessed answer is substituted for missing class information.

The bundled definitions are in `quiz/morphology_lexicon.json`. Keep personal
extensions in the root `morphology.json`, so they are independent of quiz code.
The generator uses standard paradigms from Allen & Greenough:

- [Fourth-declension paradigms and gender](https://dcc.dickinson.edu/grammar/latin/4th-declension-stem-paradigm-and-gender)
- [Fourth-declension exceptions](https://dcc.dickinson.edu/grammar/latin/4th-declension-case-forms)
- [Fifth-declension paradigms](https://dcc.dickinson.edu/grammar/latin/5th-declension-stem-paradigm-and-gender)
- [Fifth-declension restrictions](https://dcc.dickinson.edu/grammar/latin/5th-declension-case-forms)
- [Third-declension adjective paradigms](https://dcc.dickinson.edu/grammar/latin/3rd-declension-adjectives-classification-and-paradigms)

Run all regression and extension tests with:

```sh
python -B -m unittest discover -s quiz -p 'test_*.py'
```
