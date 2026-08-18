import { useNavigate } from 'react-router-dom';
import { User, Globe, Volume2, ShieldAlert, Accessibility, Headphones, Info, Contrast, ArrowLeft, Brain, Users } from 'lucide-react';
import SettingRow from '@/components/SettingRow';
import { getSettings } from '@/lib/userSettings';
import { getStoredTheme } from '@/lib/theme';
import { useT, nativeName } from '@/lib/i18n';

const voiceKey = {
  'Warm Female': 'warmFemale',
  'Calm Female': 'calmFemale',
  'Warm Male': 'warmMale',
  'Calm Male': 'calmMale',
};

export default function Settings() {
  const navigate = useNavigate();
  const t = useT();
  const s = getSettings();
  const theme = getStoredTheme();
  const themeLabel = t(theme === 'system' ? 'system' : theme === 'dark' ? 'dark' : 'light');

  return (
    <>
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-border bg-background/90 px-5 pt-5 pb-3 backdrop-blur">
        <div className="flex items-center gap-1">
          <button
            onClick={() => navigate('/')}
            aria-label={t('back')}
            className="flex h-11 w-11 items-center justify-center rounded-full text-foreground active:bg-muted"
          >
            <ArrowLeft className="h-6 w-6" strokeWidth={2} />
          </button>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">{t('settings')}</h1>
        </div>
      </header>

      <div className="flex flex-col gap-3 px-5 py-5">
        <p className="mb-3 text-base text-muted-foreground">{t('settingsSubtitle')}</p>

        <SettingRow
          icon={User}
          iconBg="bg-primary/10"
          iconColor="text-primary"
          title={t('myProfile')}
          description={t('profileDesc')}
          onClick={() => navigate('/settings/profile')}
        />
        <SettingRow
          icon={Globe}
          iconBg="bg-primary/10"
          iconColor="text-primary"
          title={t('language')}
          description={t('languageDesc')}
          value={nativeName(s.language || 'English')}
          onClick={() => navigate('/settings/language')}
        />
        <SettingRow
          icon={Volume2}
          iconBg="bg-primary/10"
          iconColor="text-primary"
          title={t('voice')}
          description={t('voiceDesc')}
          value={t(voiceKey[s.voice] || 'warmFemale')}
          onClick={() => navigate('/settings/voice')}
        />
        {/*
          Directly under Voice, because it is about the same thing: what
          happens when they talk to Gamira. Somebody who is uneasy about being
          remembered should not have to hunt for the list.
        */}
        <SettingRow
          icon={Brain}
          iconBg="bg-primary/10"
          iconColor="text-primary"
          title="What Gamira remembers"
          description="The few things she keeps about you — remove any of them"
          onClick={() => navigate('/settings/memory')}
        />
        <SettingRow
          icon={Users}
          iconBg="bg-primary/10"
          iconColor="text-primary"
          title="What your family was told"
          description="Everything Gamira has passed on about you"
          onClick={() => navigate('/settings/family-notices')}
        />
        <SettingRow
          icon={ShieldAlert}
          iconBg="bg-destructive/15"
          iconColor="text-destructive"
          title={t('emergency')}
          description={t('emergencyDesc')}
          onClick={() => navigate('/settings/emergency')}
        />
        <SettingRow
          icon={Accessibility}
          iconBg="bg-primary/10"
          iconColor="text-primary"
          title={t('accessibility')}
          description={t('accessibilityDesc')}
          onClick={() => navigate('/settings/accessibility')}
        />
        <SettingRow
          icon={Contrast}
          iconBg="bg-primary/10"
          iconColor="text-primary"
          title={t('theme')}
          description={t('themeDesc')}
          value={themeLabel}
          onClick={() => navigate('/settings/theme')}
        />
        <SettingRow
          icon={Headphones}
          iconBg="bg-primary/10"
          iconColor="text-primary"
          title={t('contactSupport')}
          description={t('contactSupportDesc')}
          onClick={() => navigate('/settings/contact-support')}
        />
        <SettingRow
          icon={Info}
          iconBg="bg-primary/10"
          iconColor="text-primary"
          title={t('aboutGamira')}
          description={t('aboutGamiraDesc')}
          onClick={() => navigate('/settings/about')}
        />
      </div>
    </>
  );
}
