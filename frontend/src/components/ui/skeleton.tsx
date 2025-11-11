import * as React from "react"
import cn from "clsx"

/**
 * Skeleton component for loading states
 * Provides a shimmer effect while content is loading
 */
function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-gray-200", className)}
      {...props}
    />
  )
}

export { Skeleton }
