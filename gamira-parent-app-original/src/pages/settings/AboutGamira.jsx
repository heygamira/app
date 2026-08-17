import ReactMarkdown from 'react-markdown';
import SettingsHeader from '@/components/SettingsHeader';
import { useT } from '@/lib/i18n';

const content = `## About Gamira

Gamira is built to make everyday life easier for aging parents and their families.

### For Parents

Gamira is a simple companion that parents can use throughout their day. They can talk to Gamira, get reminders for medicines and important tasks, call their family, and quickly ask for help when they need it.

Everything is designed to be simple and easy to use, so parents can stay independent without feeling overwhelmed by technology.

### For Family & Admin

The family app helps children and caregivers stay connected with their parents. It brings important information, reminders, schedules, health updates, and alerts into one place.

Families can check in on their parents, manage their daily routines, receive important notifications, and stay informed without constantly having to call or ask whether everything is okay.

### Our Goal

Gamira is not here to replace family. It is here to help families stay closer, even when they cannot always be there.

**Gamira — The AI Companion for Independent Aging.**
`;

export default function AboutGamira() {
  const t = useT();
  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <SettingsHeader title={t('aboutGamira')} />
      <main className="flex-1 overflow-y-auto px-5 pb-12 pt-2">
        <ReactMarkdown
          components={{
            h2: ({ node, ...p }) => <h2 className="mb-2 text-xl font-bold text-foreground" {...p} />,
            h3: ({ node, ...p }) => <h3 className="mt-5 mb-1 text-lg font-semibold text-foreground" {...p} />,
            p: ({ node, ...p }) => <p className="mb-3 text-base leading-relaxed text-muted-foreground" {...p} />,
            strong: ({ node, ...p }) => <strong className="mt-4 block text-base font-semibold text-foreground" {...p} />,
          }}
        >
          {content}
        </ReactMarkdown>
      </main>
    </div>
  );
}
