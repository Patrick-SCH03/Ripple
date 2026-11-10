// 밝기 메뉴(자동 · 밝게 · 어둡게)와 버전 정보. 버전은 결정에 필요하지 않아 메뉴 안에만 두고, 지도 ID는 개발 모드에서만.
import { Monitor, Moon, Sun } from 'lucide-react'
import type { Health } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { THEME_CHOICES, THEME_NAMES, type ThemeChoice, type ThemeState } from '@/lib/theme'

const ICONS = { auto: Monitor, light: Sun, dark: Moon } as const

export function ThemeMenu({ theme, health }: { theme: ThemeState; health: Health | null }) {
  const Icon = ICONS[theme.choice]
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`밝기: ${THEME_NAMES[theme.choice]}`}>
          <Icon aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel>밝기</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme.choice} onValueChange={(value) => theme.choose(value as ThemeChoice)}>
          {THEME_CHOICES.map((choice) => (
            <DropdownMenuRadioItem key={choice} value={choice}>
              {THEME_NAMES[choice]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {health && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs font-normal text-foreground-secondary">
              엔진 {health.engine_version} · 규칙표 {health.rules_version}
              {health.build && (
                <>
                  <br />
                  빌드 <span className="font-mono">{health.build.slice(0, 7)}</span>
                </>
              )}
              {/* 지도 ID는 개발 모드에서만(DESIGN 6절: 지도 ID는 보이지 않는다) */}
              {health.auth?.required === false && (
                <>
                  <br />
                  지도 <span className="font-mono">{health.snapshot_id ?? '—'}</span>
                </>
              )}
            </DropdownMenuLabel>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
