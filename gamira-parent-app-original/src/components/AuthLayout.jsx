import ThemeToggle from '@/components/ThemeToggle';

export default function AuthLayout({ icon: Icon, title, subtitle, footer = null, children }) {
  return (
    <div className="min-h-[100dvh] w-full bg-background">
      <div className="mx-auto flex min-h-[100dvh] w-full max-w-md flex-col px-5 py-6">
        <div className="flex justify-end">
          <ThemeToggle />
        </div>

        <div className="flex flex-1 flex-col justify-center">
          <div className="mb-8 flex flex-col items-center text-center">
            {Icon && (
              <div
                className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl text-white"
                style={{
                  background: 'linear-gradient(135deg, #2563EB 0%, #7C5CFC 100%)',
                  boxShadow: '0 12px 32px rgba(124,92,252,0.35)',
                }}
              >
                <Icon className="h-8 w-8" strokeWidth={2} aria-hidden="true" />
              </div>
            )}
            <h1 className="text-2xl font-bold tracking-tight text-foreground">{title}</h1>
            {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
          </div>

          <div className="rounded-3xl border border-border bg-card p-6 shadow-sm">{children}</div>

          {footer && (
            <p className="mt-6 text-center text-sm text-muted-foreground">{footer}</p>
          )}
        </div>
      </div>
    </div>
  );
}
