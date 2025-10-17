/**
 * Formats a number as currency
 * @param amount - The amount to format (can be number, string, null, or undefined)
 * @param options - Optional formatting options
 * @returns Formatted currency string
 */
export function formatCurrency(
  amount: number | string | null | undefined,
  options?: { decimals?: number; symbol?: string },
): string {
  const num = typeof amount === 'string' ? parseFloat(amount) : typeof amount === 'number' ? amount : 0
  
  if (!isFinite(num)) {
    return `${options?.symbol ?? '$'}0`
  }
  
  const decimals = options?.decimals ?? 0
  const symbol = options?.symbol ?? '$'
  
  return `${symbol}${num.toFixed(decimals)}`
}
