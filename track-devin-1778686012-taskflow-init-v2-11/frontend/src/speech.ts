/**
 * Minimal wrapper around the browser Web Speech API.
 * Returns null if speech recognition is not available in this browser.
 */

import type { AssistantLanguage } from './types'

interface SpeechRecognitionAlternativeLike {
  transcript: string
}
interface SpeechRecognitionResultLike {
  readonly isFinal: boolean
  readonly length: number
  item(index: number): SpeechRecognitionAlternativeLike
  [index: number]: SpeechRecognitionAlternativeLike
}
interface SpeechRecognitionResultListLike {
  readonly length: number
  item(index: number): SpeechRecognitionResultLike
  [index: number]: SpeechRecognitionResultLike
}
interface SpeechRecognitionEventLike extends Event {
  readonly resultIndex: number
  readonly results: SpeechRecognitionResultListLike
}
interface SpeechRecognitionErrorEventLike extends Event {
  readonly error: string
  readonly message?: string
}

export interface BrowserSpeechRecognition {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
  onstart: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}

type SpeechRecognitionConstructor = new () => BrowserSpeechRecognition

interface SpeechWindow {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
}

function getConstructor(): SpeechRecognitionConstructor | null {
  const w = window as unknown as SpeechWindow
  return w.SpeechRecognition || w.webkitSpeechRecognition || null
}

export function isSpeechRecognitionSupported(): boolean {
  return getConstructor() !== null
}

export function createRecognition(language: AssistantLanguage): BrowserSpeechRecognition | null {
  const Ctor = getConstructor()
  if (!Ctor) return null
  const rec = new Ctor()
  rec.lang = language
  // continuous=true keeps the recognizer running through natural pauses, so
  // mid-sentence silence doesn't end the session. The user explicitly clicks
  // "Stop" (or closes the modal) to end the recording.
  rec.continuous = true
  rec.interimResults = true
  return rec
}

export function extractTranscript(event: SpeechRecognitionEventLike): {
  finalText: string
  interimText: string
} {
  let finalText = ''
  let interimText = ''
  for (let i = event.resultIndex; i < event.results.length; i += 1) {
    const result = event.results[i]
    const alt = result[0]
    if (result.isFinal) {
      finalText += alt.transcript
    } else {
      interimText += alt.transcript
    }
  }
  return { finalText, interimText }
}
