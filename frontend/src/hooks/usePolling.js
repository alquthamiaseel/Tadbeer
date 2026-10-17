import { useEffect, useRef, useState } from 'react'

export function usePolling(fetcher, intervalMs, shouldContinue = () => true) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const fetcherRef = useRef(fetcher)
  const continueRef = useRef(shouldContinue)
  fetcherRef.current = fetcher
  continueRef.current = shouldContinue

  useEffect(() => {
    let cancelled = false
    let timer

    async function tick() {
      let keepGoing = true
      try {
        const result = await fetcherRef.current()
        if (cancelled) return
        setData(result)
        setError(null)
        keepGoing = continueRef.current(result)
      } catch (err) {
        if (cancelled) return
        setError(err)
      }
      if (!cancelled) setLoading(false)
      if (!cancelled && keepGoing) timer = setTimeout(tick, intervalMs)
    }

    tick()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [intervalMs])

  return { data, error, loading }
}
