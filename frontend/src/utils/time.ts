/**
 * Utility functions for handling timestamps from the backend.
 *
 * The backend stores all timestamps as UTC in the database (TIMESTAMP WITHOUT TIME ZONE)
 * and serializes them as ISO strings without timezone info (e.g., "2025-10-17T04:30:00").
 *
 * These utilities ensure all timestamps are correctly interpreted as UTC and converted
 * to the user's local timezone when displayed.
 */

/**
 * Parse a timestamp string from the backend as UTC and return a Date object.
 * Appends 'Z' to the timestamp if not present to explicitly mark it as UTC.
 *
 * @param timestamp - ISO timestamp string from backend (e.g., "2025-10-17T04:30:00")
 * @returns Date object or null if invalid
 */
export function parseUTCTimestamp(timestamp: string | undefined | null): Date | null {
  if (!timestamp) return null

  try {
    // Append 'Z' if not present to explicitly mark as UTC
    const utcTimestamp = timestamp.endsWith('Z') ? timestamp : timestamp + 'Z'
    const date = new Date(utcTimestamp)

    // Check if date is valid
    if (isNaN(date.getTime())) {
      return null
    }

    return date
  } catch {
    return null
  }
}

/**
 * Parse a timestamp string from the backend and return milliseconds since epoch.
 * Useful for time calculations and comparisons.
 *
 * @param timestamp - ISO timestamp string from backend
 * @returns Milliseconds since epoch or null if invalid
 */
export function parseUTCTimestampToMs(timestamp: string | undefined | null): number | null {
  const date = parseUTCTimestamp(timestamp)
  return date ? date.getTime() : null
}

/**
 * Format a timestamp from the backend as a localized time string.
 *
 * @param timestamp - ISO timestamp string from backend
 * @param options - Intl.DateTimeFormatOptions for formatting
 * @returns Formatted time string in user's local timezone
 */
export function formatUTCTime(
  timestamp: string | undefined | null,
  options: Intl.DateTimeFormatOptions = {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  },
): string {
  const date = parseUTCTimestamp(timestamp)
  if (!date) return ''

  return date.toLocaleTimeString([], options)
}

/**
 * Format a timestamp from the backend as a localized date string.
 *
 * @param timestamp - ISO timestamp string from backend
 * @param options - Intl.DateTimeFormatOptions for formatting
 * @returns Formatted date string in user's local timezone
 */
export function formatUTCDate(
  timestamp: string | undefined | null,
  options: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  },
): string {
  const date = parseUTCTimestamp(timestamp)
  if (!date) return ''

  return date.toLocaleDateString([], options)
}

/**
 * Format a Date as a human-readable relative time string (e.g., "5 seconds ago").
 *
 * @param date - The date to compare against now
 * @param now - The current time (defaults to new Date())
 * @returns Human-readable string like "just now", "5 seconds ago", "2 hours ago"
 */
export function timeAgo(date: Date, now: Date = new Date()): string {
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000)
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds} seconds ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.floor(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

export function timeAgoShort(date: Date, now: Date = new Date()): string {
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000)
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

/**
 * Format a timestamp from the backend as a localized date and time string.
 *
 * @param timestamp - ISO timestamp string from backend
 * @param options - Intl.DateTimeFormatOptions for formatting
 * @returns Formatted date and time string in user's local timezone
 */
export function formatUTCDateTime(
  timestamp: string | undefined | null,
  options: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  },
): string {
  const date = parseUTCTimestamp(timestamp)
  if (!date) return ''

  return date.toLocaleString([], options)
}
