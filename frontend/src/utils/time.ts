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
  }
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
  }
): string {
  const date = parseUTCTimestamp(timestamp)
  if (!date) return ''
  
  return date.toLocaleDateString([], options)
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
  }
): string {
  const date = parseUTCTimestamp(timestamp)
  if (!date) return ''
  
  return date.toLocaleString([], options)
}
