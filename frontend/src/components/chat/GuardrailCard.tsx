'use client'

import { ShieldAlertIcon, XIcon } from 'lucide-react'

interface GuardrailCardProps {
  message: string
  onDismiss: () => void
}

export function GuardrailCard({ message, onDismiss }: GuardrailCardProps) {
  return (
    <div
      role="region"
      aria-label="Request blocked"
      className="mx-4 mb-2 rounded-xl border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-950"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <ShieldAlertIcon
            className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400"
            aria-hidden="true"
          />
          <div className="flex flex-col gap-0.5">
            <p className="text-sm font-medium text-red-900 dark:text-red-100">
              Request blocked by policy
            </p>
            <p className="text-sm text-red-800 dark:text-red-200">{message}</p>
          </div>
        </div>
        <button
          type="button"
          aria-label="Dismiss guardrail notice"
          onClick={onDismiss}
          className="shrink-0 rounded p-0.5 text-red-600 hover:bg-red-100 dark:text-red-400 dark:hover:bg-red-900"
        >
          <XIcon className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}
