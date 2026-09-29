'use client'

import { Suspense, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

/** The old address of the salary-access review page, still in emails already
 *  sent. Salary access is no longer part of Finances (an administrator who
 *  approves requests never opens Finances), so this only passes the token on
 *  to /salary-access/review. */
function Forward() {
  const router = useRouter()
  const params = useSearchParams()
  useEffect(() => {
    const token = params.get('token')
    router.replace(token ? `/salary-access/review?token=${encodeURIComponent(token)}` : '/salary-access')
  }, [params, router])
  return null
}

export default function OldReviewPage() {
  return (
    <Suspense fallback={null}>
      <Forward />
    </Suspense>
  )
}
