import * as React from "react"
import { cn } from "cn"

/** 브라우저 기본 고르기 상자(키보드·화면 읽기·터치가 기본으로 됨). 모양은 Input과 같다. */
function NativeSelect({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      data-slot="native-select"
      className={cn(
        "h-9 w-full min-w-0 rounded-lg border border-input bg-transparent px-2 py-1 text-sm transition-colors outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:bg-input/30 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 [&>option]:bg-surface [&>optgroup]:bg-surface",
        className
      )}
      {...props}
    />
  )
}

export { NativeSelect }
