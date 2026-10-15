"""Weekly token activity and daily rolling-seven-day costs from Ramp's TSM sample."""
from ramp_data.schemas import TOKENOMICS_DATASETS
from ramp_data.sources.ai_index import RampAiIndexSource


class RampTokenomicsSource(RampAiIndexSource):
    # Reuse the existing transport and RSC decoder, with independent quality
    # gates so a change to monthly adoption cannot silently discard TSM data.
    name = "ramp_tokenomics"
    datasets = TOKENOMICS_DATASETS
