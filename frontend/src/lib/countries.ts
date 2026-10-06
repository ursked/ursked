/**
 * Countries the organisation can say it is in, with each one's usual currency.
 *
 * ursked has no home country. Nothing is assumed until the admin picks one in
 * Settings -> General; the pick only *suggests* the currency (the admin
 * confirms it) and preselects the public-holiday calendar.
 *
 * Names come from the browser (Intl.DisplayNames), so they read in English
 * without a hand-kept name table that drifts.
 */

/** ISO 3166-1 alpha-2 -> ISO 4217. */
const CURRENCY_BY_COUNTRY: Record<string, string> = {
  AE: 'AED', AR: 'ARS', AT: 'EUR', AU: 'AUD', BD: 'BDT', BE: 'EUR', BG: 'BGN', BH: 'BHD',
  BR: 'BRL', CA: 'CAD', CH: 'CHF', CL: 'CLP', CN: 'CNY', CO: 'COP', CR: 'CRC', CY: 'EUR',
  CZ: 'CZK', DE: 'EUR', DK: 'DKK', DO: 'DOP', EC: 'USD', EE: 'EUR', EG: 'EGP', ES: 'EUR',
  ET: 'ETB', FI: 'EUR', FJ: 'FJD', FR: 'EUR', GB: 'GBP', GH: 'GHS', GR: 'EUR', GT: 'GTQ',
  HK: 'HKD', HR: 'EUR', HU: 'HUF', ID: 'IDR', IE: 'EUR', IL: 'ILS', IN: 'INR', IS: 'ISK',
  IT: 'EUR', JM: 'JMD', JO: 'JOD', JP: 'JPY', KE: 'KES', KH: 'KHR', KR: 'KRW', KW: 'KWD',
  KZ: 'KZT', LB: 'LBP', LK: 'LKR', LT: 'EUR', LU: 'EUR', LV: 'EUR', MA: 'MAD', MT: 'EUR',
  MU: 'MUR', MX: 'MXN', MY: 'MYR', NG: 'NGN', NL: 'EUR', NO: 'NOK', NP: 'NPR', NZ: 'NZD',
  OM: 'OMR', PA: 'PAB', PE: 'PEN', PH: 'PHP', PK: 'PKR', PL: 'PLN', PR: 'USD', PT: 'EUR',
  QA: 'QAR', RO: 'RON', RS: 'RSD', SA: 'SAR', SE: 'SEK', SG: 'SGD', SI: 'EUR', SK: 'EUR',
  TH: 'THB', TN: 'TND', TR: 'TRY', TW: 'TWD', TZ: 'TZS', UA: 'UAH', UG: 'UGX', US: 'USD',
  UY: 'UYU', VN: 'VND', ZA: 'ZAR', ZM: 'ZMW',
}

const regionNames =
  typeof Intl !== 'undefined' && 'DisplayNames' in Intl
    ? new Intl.DisplayNames(['en'], { type: 'region' })
    : null

export function countryName(code?: string | null): string {
  if (!code) return ''
  try {
    return regionNames?.of(code) ?? code
  } catch {
    return code
  }
}

export function currencyForCountry(code?: string | null): string | null {
  return (code && CURRENCY_BY_COUNTRY[code]) || null
}

/** Every country in the list, alphabetical by English name. */
export const COUNTRIES: { code: string; name: string }[] = Object.keys(CURRENCY_BY_COUNTRY)
  .map((code) => ({ code, name: countryName(code) }))
  .sort((a, b) => a.name.localeCompare(b.name))
