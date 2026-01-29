import type { Actor } from '@/types'

const STORAGE_KEY = 'petmovie-actors'

export function getActors(): Actor[] {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (!stored) return []
  try {
    return JSON.parse(stored)
  } catch {
    return []
  }
}

export function saveActor(actor: Actor): void {
  const actors = getActors()
  actors.push(actor)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(actors))
}

export function deleteActor(id: string): void {
  const actors = getActors().filter(a => a.id !== id)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(actors))
}

export function generateId(): string {
  return Math.random().toString(36).substr(2, 9)
}
