/**
 * Tenant master currency helpers.
 *
 * All monetary values in the app (salary grades, payroll, compensation,
 * payslips, exports) are denominated in the tenant's single master currency,
 * stored as an ISO 4217 code on AppSettings.currency_code (default "PHP").
 *
 * `formatMoney` is a pure formatter; `useCurrency` reads the tenant setting and
 * returns a bound formatter so components never hardcode a currency again.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

/** Curated shortlist shown in the settings picker. The admin can also enter any
 *  custom ISO 4217 code, so this list is for convenience, not a hard limit. */
export const CURATED_CURRENCIES: { code: string; label: string }[] = [
  { code: 'PHP', label: 'Philippine Peso' },
  { code: 'USD', label: 'US Dollar' },
  { code: 'EUR', label: 'Euro' },
  { code: 'GBP', label: 'British Pound' },
  { code: 'JPY', label: 'Japanese Yen' },
  { code: 'AUD', label: 'Australian Dollar' },
  { code: 'CAD', label: 'Canadian Dollar' },
  { code: 'SGD', label: 'Singapore Dollar' },
  { code: 'HKD', label: 'Hong Kong Dollar' },
  { code: 'AED', label: 'UAE Dirham' },
  { code: 'INR', label: 'Indian Rupee' },
  { code: 'CNY', label: 'Chinese Yuan' },
  { code: 'MYR', label: 'Malaysian Ringgit' },
  { code: 'THB', label: 'Thai Baht' },
  { code: 'IDR', label: 'Indonesian Rupiah' },
  { code: 'VND', label: 'Vietnamese Dong' },
]

const DEFAULT_CURRENCY = 'PHP'

/** Normalise a possibly-empty/invalid code to a usable ISO 4217 code. */
export function normalizeCurrency(code?: string | null): string {
  const c = (code || '').trim().toUpperCase()
  return /^[A-Z]{3}$/.test(c) ? c : DEFAULT_CURRENCY
}

/**
 * Format a numeric amount in the given currency. Falls back gracefully if the
 * code is one the runtime's Intl doesn't recognise (renders "CODE 1,234.00").
 */
export function formatMoney(amount: number | null | undefined, code?: string | null): string {
  const value = typeof amount === 'number' && isFinite(amount) ? amount : 0
  const currency = normalizeCurrency(code)
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(value)
  } catch {
    // Unknown ISO code for this runtime — show code + grouped number.
    return `${currency} ${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  }
}

/**
 * Hook returning the tenant currency code and a bound `format` function.
 * Backed by the shared app-settings query (any authenticated user may read it),
 * so Finances tabs and employee payslips all resolve the same currency.
 */
export function useCurrency(): { code: string; format: (amount: number | null | undefined) => string } {
  const { data } = useQuery({
    queryKey: ['app-settings'],
    queryFn: () => api.getAppSettings(),
    staleTime: 5 * 60 * 1000,
  })
  const code = normalizeCurrency(data?.currency_code)
  return { code, format: (amount) => formatMoney(amount, code) }
}
