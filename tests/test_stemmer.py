"""Unit tests for the PsyClaw stemmer (NLTK PorterStemmer + custom domain map).

`enhanced_porter_stem` is the public alias for `stem_token`. Expected values are
baselined against the stemmer's ACTUAL output (NLTK Porter + the `_CUSTOM_STEMS`
domain dictionary), not an idealized stemmer — e.g. Porter yields `polici`/`run`
for `policies`/`running`, and the domain map intentionally folds `kubernetes`→`k8s`.
"""

import pytest
from retrieval.stemmer import stem_token as enhanced_porter_stem, tokenize_and_stem


class TestPorterStem:
    def test_short_words_preserved(self):
        assert enhanced_porter_stem("api") == "api"
        assert enhanced_porter_stem("cpu") == "cpu"

    def test_plurals(self):
        assert enhanced_porter_stem("processes") == "process"
        assert enhanced_porter_stem("policies") == "polici"   # NLTK Porter: -ies → -i
        assert enhanced_porter_stem("addresses") == "address"

    def test_verb_forms(self):
        assert enhanced_porter_stem("running") == "run"       # NLTK Porter collapses -ing
        assert enhanced_porter_stem("configured") == "configur"

    def test_technical_terms_domain_mapped(self):
        # `kubernetes` is an intentional domain normalization (_CUSTOM_STEMS → k8s).
        assert enhanced_porter_stem("kubernetes") == "k8s"

    def test_ss_ending_preserved(self):
        assert enhanced_porter_stem("access") == "access"

    def test_ies_ending(self):
        assert enhanced_porter_stem("policies") == "polici"

    def test_suffix_reduction(self):
        assert enhanced_porter_stem("rationalization") == "ration"


class TestTokenizeAndStem:
    def test_basic_tokenization(self):
        tokens = tokenize_and_stem("Configure the backup repository")
        assert len(tokens) == 4
        assert all(isinstance(t, str) for t in tokens)

    def test_filters_short_words(self):
        tokens = tokenize_and_stem("I am a big fan of AI")
        # "big" and "fan" survive (3+ chars alpha)
        assert len(tokens) >= 1

    def test_empty_input(self):
        assert tokenize_and_stem("") == []

    def test_numeric_ignored(self):
        tokens = tokenize_and_stem("version 2.5.1 release")
        assert all(t.isalpha() for t in tokens)

    def test_consistency(self):
        t1 = tokenize_and_stem("backup configuration")
        t2 = tokenize_and_stem("backup configuration")
        assert t1 == t2
