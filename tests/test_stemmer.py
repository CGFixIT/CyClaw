# ============================================================================
# BUILD-ALIGNMENT NOTE (2026-06-13): Targets a FUTURE build (pending Dropbox
# sync). Imports retrieval.stemmer.enhanced_porter_stem, which does not exist
# at HEAD (current build exposes stem_token / tokenize_and_stem). Expected to
# fail until the future build is pushed. Do not 'fix' to match the pushed API.
# ============================================================================
"""Unit tests for Porter stemmer."""

import pytest
from retrieval.stemmer import enhanced_porter_stem, tokenize_and_stem


class TestPorterStem:
    def test_short_words_preserved(self):
        assert enhanced_porter_stem("api") == "api"
        assert enhanced_porter_stem("cpu") == "cpu"

    def test_plurals(self):
        assert enhanced_porter_stem("processes") == "process"
        assert enhanced_porter_stem("policies") == "policy"
        assert enhanced_porter_stem("addresses") == "address"

    def test_verb_forms(self):
        assert enhanced_porter_stem("running") == "runn"
        assert enhanced_porter_stem("configured") == "configur"

    def test_technical_terms_not_overstemmed(self):
        stem = enhanced_porter_stem("kubernetes")
        assert len(stem) >= 6

    def test_ss_ending_preserved(self):
        assert enhanced_porter_stem("access") == "access"

    def test_ies_to_y(self):
        assert enhanced_porter_stem("policies") == "policy"

    def test_suffix_reduction(self):
        assert enhanced_porter_stem("rationalization") == "rationalize"


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
