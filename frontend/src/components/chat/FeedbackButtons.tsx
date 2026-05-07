'use client'

import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Textarea } from '@/components/ui/textarea'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useMutation } from '@tanstack/react-query'
import { ThumbsDownIcon, ThumbsUpIcon } from 'lucide-react'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'

type Rating = 1 | -1 | null

interface FeedbackPayload {
  rating: 1 | -1
  comment: string | null
}

interface FeedbackResponse {
  id: string
  rating: 1 | -1
  comment: string | null
}

const MAX_COMMENT = 500

interface FeedbackButtonsProps {
  sessionId: string
  messageId: string
  initialRating?: Rating
}

async function submitFeedback(
  sessionId: string,
  messageId: string,
  payload: FeedbackPayload
): Promise<FeedbackResponse> {
  const res = await apiClient.post<FeedbackResponse>(
    `/api/v1/chat/sessions/${sessionId}/messages/${messageId}/feedback`,
    payload
  )
  return res.data
}

export function FeedbackButtons({ sessionId, messageId, initialRating }: FeedbackButtonsProps) {
  const [rating, setRating] = useState<Rating>(initialRating ?? null)
  const [comment, setComment] = useState('')
  const [thumbsDownOpen, setThumbsDownOpen] = useState(false)

  const mutation = useMutation({
    mutationFn: (payload: FeedbackPayload) => submitFeedback(sessionId, messageId, payload),
    onSuccess: (data) => {
      setRating(data.rating)
      setThumbsDownOpen(false)
      setComment('')
    },
    onError: () => toast.error('Failed to save feedback.'),
  })

  const handleThumbsUp = useCallback(() => {
    if (mutation.isPending) return
    if (rating === 1) {
      return
    }
    setRating(1)
    mutation.mutate({ rating: 1, comment: null })
  }, [rating, mutation])

  const handleThumbsDownSubmit = useCallback(() => {
    if (mutation.isPending) return
    mutation.mutate({ rating: -1, comment: comment.trim() || null })
  }, [comment, mutation])

  return (
    <div className="flex items-center gap-0.5" aria-label="Message feedback">
      <Button
        size="icon"
        variant="ghost"
        className={cn('h-6 w-6', rating === 1 && 'text-green-600 dark:text-green-400')}
        onClick={handleThumbsUp}
        disabled={mutation.isPending || rating !== null}
        aria-label="Mark as helpful"
        aria-pressed={rating === 1}
      >
        <ThumbsUpIcon className="h-3.5 w-3.5" />
      </Button>

      <Popover
        open={thumbsDownOpen}
        onOpenChange={(o) => {
          if (rating !== null) return
          setThumbsDownOpen(o)
        }}
      >
        <PopoverTrigger asChild>
          <Button
            size="icon"
            variant="ghost"
            className={cn('h-6 w-6', rating === -1 && 'text-red-600 dark:text-red-400')}
            disabled={mutation.isPending || rating !== null}
            aria-label="Mark as unhelpful"
            aria-pressed={rating === -1}
          >
            <ThumbsDownIcon className="h-3.5 w-3.5" />
          </Button>
        </PopoverTrigger>

        <PopoverContent
          className="w-72 p-3"
          side="top"
          align="start"
          role="dialog"
          aria-label="Provide feedback details"
        >
          <p className="mb-2 text-xs font-medium text-foreground">
            What went wrong? <span className="font-normal text-muted-foreground">(optional)</span>
          </p>
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="e.g. Missing information, incorrect answer…"
            className="mb-2 h-20 resize-none text-xs"
            maxLength={MAX_COMMENT}
            aria-label="Feedback comment"
          />
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">
              {comment.length}/{MAX_COMMENT}
            </span>
            <div className="flex gap-1.5">
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs"
                onClick={() => setThumbsDownOpen(false)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                className="h-7 text-xs"
                onClick={handleThumbsDownSubmit}
                disabled={mutation.isPending}
              >
                Submit
              </Button>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  )
}
