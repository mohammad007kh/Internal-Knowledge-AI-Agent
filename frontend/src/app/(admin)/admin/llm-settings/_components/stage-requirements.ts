import type { StageRequirement } from '@/components/admin/AiModelPicker'
import type { LlmStage } from '@/lib/api/llm-settings'

/**
 * Capability requirements for each pipeline stage.
 *
 * Source of truth for the stage-name keys: backend
 * `src/api/v1/admin/llm_settings.py` `STAGES` list. The 10 keys below map
 * 1:1 onto the runtime LangGraph stages — the design doc §11 used
 * aspirational names (`query_rewriter`, `answer_generator`, …) that don't
 * exist in code; this file mirrors what the backend actually serves.
 *
 * Stages not listed here have no hard requirement and accept any model.
 */
export const STAGE_REQUIREMENTS: Partial<Record<LlmStage, StageRequirement>> = {
  // Inspects source schemas — needs tool/function calling to walk the graph
  // and a generous context for table-rich payloads.
  schema_inspector: { capabilities: ['function_calling'], min_context_tokens: 8000 },
  // Lightweight classifier; no special capability required, modest context.
  clarification_detector: { min_context_tokens: 4000 },
  // Rewrites the query — modest context is enough.
  query_analyzer: { min_context_tokens: 4000 },
  // Picks which source(s) to call → needs function_calling.
  source_router: { capabilities: ['function_calling'] },
  // Retrieval is mostly vector ops; no LLM-side capability required, but
  // surfaces the prompt for re-ranking so we keep a context floor.
  retrieval: { min_context_tokens: 8000 },
  // SQL/Cypher generation benefits from JSON-mode for tool calls.
  text_to_query: { capabilities: ['json_mode'], min_context_tokens: 4000 },
  // Final answer generator — must stream and hold a large context window.
  synthesizer: { capabilities: ['streaming'], min_context_tokens: 16000 },
  // Reflector critiques drafts; structured output simplifies parsing.
  reflector: { capabilities: ['json_mode'], min_context_tokens: 8000 },
  // Guardrails decide policy verdicts — JSON mode keeps the schema strict.
  input_guard: { capabilities: ['json_mode'] },
  output_guard: { capabilities: ['json_mode'] },
}

export function requirementsFor(stage: LlmStage): StageRequirement | undefined {
  return STAGE_REQUIREMENTS[stage]
}
