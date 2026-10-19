# Morphology import accuracy audit

Generated offline from the saved Collatinus responses. Imported answers were not filled or corrected using the old schema.

- Cached lookup identities: 182 (including two pronouns and the locative lookup domī).
- Legacy-reference lemmas compared: 159 / 159.
- Existing drill cells compared: 2466.

| Result | Cells |
| --- | ---: |
| Same accepted forms, disregarding quantity marks | 2274 |
| Overlapping accepted forms with variant differences | 187 |
| Disjoint answers | 5 |
| Missing answers | 0 |

At least one old accepted spelling occurs in 99.80% of compared cells. This is agreement with the reference, not independent proof that every imported variant is correct.

Quantity annotations differ in 1002 cells that otherwise overlap. The cache retains the raw annotations, but imported grading forms omit quantity marks and have quantities_known=false. The old schema remains authoritative for reviewed quantities.

## Substantive differences

| Word | Features | Old accepted answers | Imported answers |
| --- | --- | --- | --- |
| fēlīx | case=nominative, number=singular, gender=n, degree=positive | fēlīx | felice |
| fēlīx | case=accusative, number=singular, gender=n, degree=positive | fēlīx | felice |
| fēlīx | case=vocative, number=singular, gender=n, degree=positive | fēlīx | felice |
| meus | case=vocative, number=singular, gender=m, degree=positive | mī | mee |
| tuus | case=vocative, number=singular, gender=m, degree=positive | tue | tuus |

The fēlīx neuter singular and the meus masculine vocative require correction/review before provider tables can replace the current keys. Allen & Greenough describes one-termination third-declension adjectives as sharing a nominative across genders, and gives mī for the vocative of meus:

- [Third-declension adjective classification](https://dcc.dickinson.edu/grammar/latin/3rd-declension-adjectives-classification-and-paradigms)
- [Possessive pronouns, §145](https://dcc.dickinson.edu/grammar/latin/possessive-pronouns-paradigm)

## Coverage and use

The parser retained 19161 feature-keyed cells. It also recorded 118 abbreviated finite tables as unparsed, preserving their raw responses. In particular, abbreviated compound perfect-passive paradigms are not complete six-person answer tables and have not been fabricated.

Broader tense/mood/degree/participle data is acquired, but this audit validates only overlap with the existing drills. Other cached variants and future topics need their own reference checks.

All imported records start unreviewed. Only explicit approval can enable a complete current-drill fallback. Bundled and user-supplied v1 definitions retain precedence. No imported answer silently replaces a reviewed current answer.

## Reproduce

```powershell
python quiz/import_morphology.py --offline --compare --check
```

See morphology_comparison.json for every variant/quantity difference and cache key. Unchanged runs reuse stored responses; --offline makes network access impossible.

Source: [Collatinus-web, Biblissima](https://outils.biblissima.fr/en/collatinus-web/index.php), Yves Ouvrard and Philippe Verkerk. Endpoint: the site's public inflection form handler. Each cache record includes source attribution, fetch time, response checksum and parser version.
