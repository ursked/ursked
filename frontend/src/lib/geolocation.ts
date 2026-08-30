/**
 * Browser geolocation capture for the time clock.
 *
 * Two rules drive the shape of this:
 *
 * 1. Browsers only expose `navigator.geolocation` in a SECURE CONTEXT — https,
 *    or http on localhost. On a plain-http LAN address there is no prompt and no
 *    coordinates, and nothing in application code can change that. So the check
 *    happens up front and returns a distinct reason, which the UI can explain
 *    before the user presses anything and which the backend stores as
 *    `location_status='insecure_context'` rather than a vague failure.
 *
 * 2. A punch must never wait on a sensor. The capture is raced against a timer
 *    and the punch proceeds regardless of the outcome — a clock-in button that
 *    hangs on a permission dialog is worse than one that records without a
 *    location, which the grace window exists to repair.
 */

export type GeoFailure = 'insecure_context' | 'unavailable' | 'denied' | 'timeout';

export type GeoResult =
  | { ok: true; latitude: number; longitude: number; accuracy_m: number }
  | { ok: false; reason: GeoFailure };

/** Whether the browser will even offer location here. */
export function canCaptureLocation(): boolean {
  if (typeof window === 'undefined') return false;
  return window.isSecureContext === true && 'geolocation' in navigator;
}

export function geoFailureMessage(reason: GeoFailure): string {
  switch (reason) {
    case 'insecure_context':
      return 'This site is not served over HTTPS, so your browser will not share your location. Your time will still be recorded.';
    case 'denied':
      return 'Location permission was declined. Your time is recorded; you can add a location shortly.';
    case 'timeout':
      return 'Your device did not return a location in time. Your time is recorded.';
    default:
      return 'Your device could not determine a location. Your time is recorded.';
  }
}

export async function captureLocation(timeoutMs = 10_000): Promise<GeoResult> {
  if (typeof window === 'undefined') return { ok: false, reason: 'unavailable' };
  // Checked first so the reason is precise. Calling getCurrentPosition on an
  // insecure origin can otherwise fail in browser-specific and confusing ways.
  if (!window.isSecureContext) return { ok: false, reason: 'insecure_context' };
  if (!('geolocation' in navigator)) return { ok: false, reason: 'unavailable' };

  return new Promise<GeoResult>((resolve) => {
    let settled = false;
    const finish = (r: GeoResult) => {
      if (!settled) {
        settled = true;
        resolve(r);
      }
    };
    // Our own timer as well as the API's: some browsers never invoke either
    // callback while a permission prompt sits unanswered.
    const timer = setTimeout(() => finish({ ok: false, reason: 'timeout' }), timeoutMs);

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        clearTimeout(timer);
        finish({
          ok: true,
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy,
        });
      },
      (err) => {
        clearTimeout(timer);
        const reason: GeoFailure =
          err.code === 1 ? 'denied' : err.code === 3 ? 'timeout' : 'unavailable';
        finish({ ok: false, reason });
      },
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 0 },
    );
  });
}
