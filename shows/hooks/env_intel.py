"""Environmental Intelligence pronunciation overrides.

EI's audience is Canadian environmental professionals who know acronyms
like CCME, CEPA, EPA, ESA as spoken letter sequences or words.  The
default pronunciation module in ``assets/pronunciation.py`` expands these
to spaced single letters ("C C M E") which causes ElevenLabs TTS to
insert unnatural pauses between each letter.  This hook tells the
pronunciation module to skip those expansions and let ElevenLabs handle
the uppercase acronyms natively — it does a much better job reading them
as smooth letter sequences without explicit spelling.
"""

from __future__ import annotations


def pronunciation_overrides() -> dict:
    """Return EI-specific pronunciation overrides."""
    return {
        "skip_acronyms": {
            "CCME",
            "CEPA",
            "CSR",
            "EMA",
            "ESA",
            "EPA",
            "SVE",
            "PFAS",
            "EPEA",
            "AER",
            "IAA",
            "GHG",
            "SARA",
            "CER",
            "NEB",
        },
    }
