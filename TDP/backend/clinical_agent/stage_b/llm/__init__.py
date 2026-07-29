"""Stage B LLM review exports."""

from stage_b.llm.ambiguity_resolver import StageBAmbiguityResolver, build_default_stage_b_resolver

__all__ = ["StageBAmbiguityResolver", "build_default_stage_b_resolver"]
