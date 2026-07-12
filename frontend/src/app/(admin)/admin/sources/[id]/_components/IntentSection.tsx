'use client'

/**
 * IntentSection — the source-intent review surface on the Settings tab.
 *
 * Domain (004-agentic-pipeline, US1 / FR-001, FR-002):
 *   A source's *intent* is a small bundle the admin authors + reviews:
 *     - purpose            (admin-authored prose, ≤ 500 chars)
 *     - example_questions  (≤ 5 items; AI-proposable)
 *     - out_of_scope       (≤ 10 items; AI-proposable; gains hard-decline
 *                           authority once reviewed → user_set)
 *
 *   The capability ramp lives on `intent_status`:
 *     - pending_ai — admin opted into AI authoring; the draft hasn't landed.
 *     - ai_set     — the assistant wrote a draft. Reviewing (Save) activates
 *                    out-of-scope decline authority — hence the explicit
 *                    "AI-proposed — review to activate declines" badge copy.
 *     - user_set   — an admin reviewed/edited; authoritative, and the propose
 *                    pass will no longer overwrite it.
 *
 * Flow (mirrors AINamingCard's settings UX, but this card owns its own
 * persistence — there is no shared form here):
 *   1. `useSourceIntent` loads the current bundle into a react-hook-form.
 *   2. Save → PUT (`useUpdateIntent`). The server flips status → user_set and
 *      returns the persisted bundle, which we seed back into the form so the
 *      badge updates to "Reviewed" and the form re-baselines clean.
 *   3. "Regenerate draft" → POST propose (`useProposeIntent`). A 409 (study /
 *      proposal already in flight) surfaces as a Sonner toast.
 *
 * Validation: a Zod schema mirrors the server caps (≤500 / ≤5 / ≤10) so the
 * common cases are blocked client-side before the request leaves. The server
 * remains the source of truth — a 422 (sanitisation / cap) is surfaced inline.
 *
 * Immutability: list editors never mutate field-array entries in place — every
 * add / remove / edit goes through react-hook-form's field-array API, which
 * returns new arrays.
 */

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  useProposeIntent,
  useSourceIntent,
  useUpdateIntent,
} from '@/features/sources/hooks/useSources'
import { extractApiErrorMessage } from '@/lib/api-error'
import { IntentProposalConflictError } from '@/lib/api/sources'
import type { IntentStatus, SourceIntent, SourceIntentUpdate } from '@/lib/api/sources'
import { zodResolver } from '@hookform/resolvers/zod'
import { PlusIcon, SparklesIcon, Trash2Icon } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { FieldErrors } from 'react-hook-form'
import { useFieldArray, useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

// ---------------------------------------------------------------------------
// Caps — mirror the server (contracts/intent-api.yaml). Server is the source
// of truth; these constants keep the Zod schema and the UI copy in sync.
// ---------------------------------------------------------------------------

const PURPOSE_MAX = 500
const EXAMPLE_QUESTIONS_MAX = 5
const OUT_OF_SCOPE_MAX = 10

const CONFLICT_TOAST = 'A study or proposal is already running.'

// ---------------------------------------------------------------------------
// Zod schema (client mirror). The field arrays are modelled as `{ value }`
// objects so react-hook-form's `useFieldArray` can give each row a stable key
// (a bare `string[]` has no per-item identity). We flatten back to `string[]`
// at submit time.
// ---------------------------------------------------------------------------

// FIX 3 — a list item must be non-blank after trimming. Without this the
// form-array cap counts blank rows while `compactList` drops them at submit,
// so the in-form count diverges from the wire payload (you could "fill" the
// cap with empties and never hit it). Trimming inside the validator makes a
// whitespace-only row fail inline on the row that owns it.
const listItemSchema = z.object({
  value: z.string().trim().min(1, 'Enter a value or remove this row.'),
})

const intentFormSchema = z.object({
  purpose: z.string().max(PURPOSE_MAX, `Purpose must be ${PURPOSE_MAX} characters or fewer.`),
  example_questions: z
    .array(listItemSchema)
    .max(EXAMPLE_QUESTIONS_MAX, `Add at most ${EXAMPLE_QUESTIONS_MAX} example questions.`),
  out_of_scope: z
    .array(listItemSchema)
    .max(OUT_OF_SCOPE_MAX, `Add at most ${OUT_OF_SCOPE_MAX} out-of-scope topics.`),
})

type IntentFormValues = z.infer<typeof intentFormSchema>

// ---------------------------------------------------------------------------
// Mapping helpers (immutable). Wire shape ⇄ form shape.
// ---------------------------------------------------------------------------

function toFormValues(intent: SourceIntent | undefined): IntentFormValues {
  return {
    purpose: intent?.purpose ?? '',
    example_questions: (intent?.example_questions ?? []).map((value) => ({ value })),
    out_of_scope: (intent?.out_of_scope ?? []).map((value) => ({ value })),
  }
}

/** Drop blank rows and trim — the server sanitises, but we keep the wire clean. */
function compactList(items: { value: string }[]): string[] {
  return items.map((item) => item.value.trim()).filter((value) => value.length > 0)
}

function toUpdatePayload(values: IntentFormValues): SourceIntentUpdate {
  const purpose = values.purpose.trim()
  return {
    purpose: purpose.length > 0 ? purpose : null,
    example_questions: compactList(values.example_questions),
    out_of_scope: compactList(values.out_of_scope),
  }
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

interface StatusBadge {
  label: string
  variant: 'default' | 'secondary' | 'outline'
}

function statusBadge(status: IntentStatus): StatusBadge {
  switch (status) {
    case 'user_set':
      return { label: 'Reviewed', variant: 'default' }
    case 'ai_set':
      // FR-002: the review surface must make clear that reviewing activates
      // out-of-scope decline authority. Copy is asserted verbatim by the test.
      return { label: 'AI-proposed — review to activate declines', variant: 'secondary' }
    default:
      return { label: 'Draft pending', variant: 'outline' }
  }
}

// ---------------------------------------------------------------------------
// List editor — keyboard-operable, labelled, immutable add/remove
// ---------------------------------------------------------------------------

interface ListEditorProps {
  legend: string
  description: string
  name: 'example_questions' | 'out_of_scope'
  max: number
  addLabel: string
  placeholder: string
  control: ReturnType<typeof useForm<IntentFormValues>>['control']
  register: ReturnType<typeof useForm<IntentFormValues>>['register']
  error?: string
  /** Per-row validation errors (FIX 3 — blank rows fail inline on their row). */
  itemErrors?: FieldErrors<IntentFormValues>[ListEditorProps['name']]
}

function ListEditor({
  legend,
  description,
  name,
  max,
  addLabel,
  placeholder,
  control,
  register,
  error,
  itemErrors,
}: ListEditorProps) {
  const { fields, append, remove } = useFieldArray({ control, name })
  const atCap = fields.length >= max

  return (
    <fieldset className="space-y-2" data-testid={`intent-${name}`}>
      <legend className="text-xs font-medium text-foreground/80">{legend}</legend>
      <p className="text-xs text-muted-foreground">{description}</p>
      <ul className="space-y-2">
        {fields.map((field, index) => {
          const inputId = `intent-${name}-${field.id}`
          const itemError = itemErrors?.[index]?.value?.message
          return (
            <li key={field.id} className="space-y-1">
              <div className="flex items-center gap-2">
                <Label htmlFor={inputId} className="sr-only">
                  {`${legend} item ${index + 1}`}
                </Label>
                <Input
                  id={inputId}
                  placeholder={placeholder}
                  {...register(`${name}.${index}.value` as const)}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => remove(index)}
                  aria-label={`Remove ${legend.toLowerCase()} item ${index + 1}`}
                  data-testid={`intent-${name}-remove-${index}`}
                >
                  <Trash2Icon className="h-4 w-4" aria-hidden />
                </Button>
              </div>
              {itemError ? (
                <p
                  className="text-xs text-destructive"
                  role="alert"
                  data-testid={`intent-${name}-error-${index}`}
                >
                  {itemError}
                </p>
              ) : null}
            </li>
          )
        })}
      </ul>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => append({ value: '' })}
        disabled={atCap}
        data-testid={`intent-${name}-add`}
      >
        <PlusIcon className="mr-1.5 h-4 w-4" aria-hidden />
        {addLabel}
      </Button>
      {atCap ? (
        <p className="text-xs text-muted-foreground">{`Maximum of ${max} reached.`}</p>
      ) : null}
      {error ? (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </fieldset>
  )
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

export interface IntentSectionProps {
  sourceId: string
}

export function IntentSection({ sourceId }: IntentSectionProps) {
  // FIX 2 — propose→GET staleness. The propose endpoint returns 202 and the
  // worker writes the draft asynchronously; a single refetch races the worker.
  // We flip `isRegenerating` on a successful propose so the intent query polls
  // (every 3s, bounded) until the status leaves `pending_ai`, then clear it.
  const [isRegenerating, setIsRegenerating] = useState(false)
  const {
    data: intent,
    isLoading,
    isError,
  } = useSourceIntent(sourceId, { pollWhileRegenerating: isRegenerating })
  const updateIntent = useUpdateIntent(sourceId)
  const proposeIntent = useProposeIntent(sourceId)

  // Surfaces a server-side 422 (sanitisation / cap) inline — the interceptor
  // flattens problem+json to an Error, so we show its message rather than a
  // structured field map. Cleared on every new submit/successful save.
  const [serverError, setServerError] = useState<string | null>(null)

  const form = useForm<IntentFormValues>({
    resolver: zodResolver(intentFormSchema),
    defaultValues: toFormValues(intent),
  })

  const {
    control,
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty },
  } = form

  // Re-baseline whenever the loaded/persisted intent changes (initial load,
  // and after a successful Save where the hook seeds the cache). The reset
  // makes the saved bundle the new pristine baseline.
  useEffect(() => {
    reset(toFormValues(intent))
  }, [intent, reset])

  // FIX 2 — once the polled draft lands (status off pending_ai), stop polling.
  useEffect(() => {
    if (isRegenerating && intent && intent.intent_status !== 'pending_ai') {
      setIsRegenerating(false)
    }
  }, [isRegenerating, intent])

  const status: IntentStatus = intent?.intent_status ?? 'pending_ai'
  const badge = statusBadge(status)
  const purposeValue = form.watch('purpose') ?? ''

  const onSubmit = handleSubmit((values) => {
    setServerError(null)
    updateIntent.mutate(toUpdatePayload(values), {
      onSuccess: (updated) => {
        toast.success('Intent reviewed and saved.')
        reset(toFormValues(updated))
      },
      onError: (err) => {
        // 422 (cap / sanitisation) → inline; everything else → toast.
        setServerError(extractApiErrorMessage(err))
      },
    })
  })

  function handleRegenerate() {
    setServerError(null)
    proposeIntent.mutate(undefined, {
      onSuccess: () => {
        toast.success('Regenerating the AI draft…')
        // Begin polling the intent slice — the worker writes the draft later.
        setIsRegenerating(true)
      },
      onError: (err) => {
        if (err instanceof IntentProposalConflictError) {
          toast.error(CONFLICT_TOAST)
          return
        }
        toast.error(extractApiErrorMessage(err))
      },
    })
  }

  return (
    <Card data-testid="intent-section">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <SparklesIcon className="h-4 w-4 text-primary" aria-hidden />
            Source intent
          </CardTitle>
          <Badge variant={badge.variant} data-testid="intent-status-badge" data-status={status}>
            {badge.label}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          Describe what this source is for. Reviewing an AI-proposed draft activates its
          out-of-scope topics as hard declines.
        </p>
      </CardHeader>

      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground" data-testid="intent-loading">
            Loading intent…
          </p>
        ) : isError ? (
          <p className="text-sm text-destructive" role="alert" data-testid="intent-error">
            Could not load source intent.
          </p>
        ) : (
          <form onSubmit={onSubmit} className="space-y-5" aria-label="Source intent" noValidate>
            {/* Purpose ------------------------------------------------------ */}
            <div className="space-y-2">
              <Label htmlFor="intent-purpose" className="text-xs font-medium text-foreground/80">
                Purpose
              </Label>
              <Textarea
                id="intent-purpose"
                rows={3}
                maxLength={PURPOSE_MAX}
                placeholder="What questions should this source answer?"
                {...register('purpose')}
              />
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  Admin-authored. Not overwritten by the AI draft.
                </p>
                <span
                  className="text-xs tabular-nums text-muted-foreground"
                  data-testid="intent-purpose-count"
                >
                  {purposeValue.length}/{PURPOSE_MAX}
                </span>
              </div>
              {errors.purpose ? (
                <p className="text-xs text-destructive" role="alert">
                  {errors.purpose.message}
                </p>
              ) : null}
            </div>

            {/* Example questions ------------------------------------------- */}
            <ListEditor
              legend="Example questions"
              description="Representative questions this source should answer well."
              name="example_questions"
              max={EXAMPLE_QUESTIONS_MAX}
              addLabel="Add question"
              placeholder="e.g. How do I reset my password?"
              control={control}
              register={register}
              error={errors.example_questions?.message}
              itemErrors={errors.example_questions}
            />

            {/* Out of scope ------------------------------------------------ */}
            <ListEditor
              legend="Out of scope"
              description="Topics this source must NOT answer. Once reviewed, these become hard declines."
              name="out_of_scope"
              max={OUT_OF_SCOPE_MAX}
              addLabel="Add topic"
              placeholder="e.g. Payroll and salary data"
              control={control}
              register={register}
              error={errors.out_of_scope?.message}
              itemErrors={errors.out_of_scope}
            />

            {serverError ? (
              <p
                className="text-sm text-destructive"
                role="alert"
                data-testid="intent-server-error"
              >
                {serverError}
              </p>
            ) : null}

            {/* Actions ----------------------------------------------------- */}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="submit"
                size="sm"
                disabled={updateIntent.isPending || !isDirty}
                data-testid="intent-save"
              >
                {updateIntent.isPending ? 'Saving…' : 'Save'}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleRegenerate}
                disabled={proposeIntent.isPending || status === 'user_set'}
                data-testid="intent-regenerate"
              >
                {proposeIntent.isPending ? 'Regenerating…' : 'Regenerate draft'}
              </Button>
            </div>
            {status === 'user_set' ? (
              <p className="text-xs text-muted-foreground">
                This intent has been reviewed; the AI draft pass no longer overwrites it.
              </p>
            ) : null}
          </form>
        )}
      </CardContent>
    </Card>
  )
}
