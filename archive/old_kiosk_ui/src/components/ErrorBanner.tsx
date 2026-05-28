import { useSession } from '../state/session'
import { kk } from '../strings/kk'
import { AlertCircle } from 'lucide-react'

export function ErrorBanner() {
  const status = useSession((s) => s.status)
  const error = useSession((s) => s.error)
  if (status !== 'error') return null
  return (
    <div className="absolute top-6 left-1/2 -translate-x-1/2 z-40">
      <div className="flex items-center gap-3 px-5 py-3 rounded-xl bg-red-50 border border-red-200 shadow-lg">
        <AlertCircle className="w-5 h-5 text-red-600" />
        <div className="text-red-800 text-sm font-medium">
          {error || kk.errGeneric}
        </div>
      </div>
    </div>
  )
}
