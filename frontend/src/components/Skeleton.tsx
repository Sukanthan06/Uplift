interface SkeletonProps {
  className?: string
}

export default function Skeleton({ className = '' }: SkeletonProps) {
  return <div className={`animate-pulse rounded bg-gray-200 ${className}`} />
}

export function OverviewSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="rounded-lg border border-gray-200 bg-white px-4 py-3">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="mt-2 h-7 w-20" />
          </div>
        ))}
      </div>
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <Skeleton className="h-4 w-56" />
        <Skeleton className="mt-4 h-40 w-full" />
      </div>
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <Skeleton className="h-4 w-56" />
        <Skeleton className="mt-4 h-40 w-full" />
      </div>
    </div>
  )
}
