"""PCM playback / audio streaming helpers for streaming voice.

The synthesis methods (_synthesize_to_pcm, _synthesize_via_worker,
_synthesize_subprocess_to_pcm) are kept on StreamingVoicePipeline in
pipeline.py because they are tightly coupled to the pipeline's worker state
and configuration.
"""
