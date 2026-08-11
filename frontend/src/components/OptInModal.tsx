import { useState } from 'react';
import { Lock, Zap, DollarSign, Cpu, Trophy, X } from 'lucide-react';
import { useAppStore } from '../lib/store';
import { isProfane } from '../lib/profanity';
import { useTranslation } from '../i18n/useTranslation';

interface OptInModalProps {
  onClose: () => void;
}

export function OptInModal({ onClose }: OptInModalProps) {
  const { t } = useTranslation();
  const setOptIn = useAppStore((s) => s.setOptIn);
  const optInDisplayName = useAppStore((s) => s.optInDisplayName);
  const optInEnabled = useAppStore((s) => s.optInEnabled);

  const optInEmail = useAppStore((s) => s.optInEmail);

  const [name, setName] = useState(optInDisplayName);
  const [email, setEmail] = useState(optInEmail);
  const [error, setError] = useState('');
  const [joined, setJoined] = useState(optInEnabled);

  const handleJoin = () => {
    const trimmed = name.trim();
    const trimmedEmail = email.trim();
    if (!trimmed) {
      setError(t('leaderboard.error.nameRequired'));
      return;
    }
    if (trimmed.length < 2 || trimmed.length > 30) {
      setError(t('leaderboard.error.nameLength'));
      return;
    }
    if (isProfane(trimmed)) {
      setError(t('leaderboard.error.nameNotAllowed'));
      return;
    }
    if (!trimmedEmail || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setError(t('leaderboard.error.emailInvalid'));
      return;
    }
    setError('');
    setOptIn(true, trimmed, trimmedEmail);
    setJoined(true);
  };

  const handleOptOut = () => {
    setOptIn(false, '', '');
    setJoined(false);
    onClose();
  };

  const features = [
    { icon: Lock, label: t('leaderboard.feature.private') },
    { icon: Zap, label: t('leaderboard.feature.energy') },
    { icon: DollarSign, label: t('leaderboard.feature.cost') },
    { icon: Cpu, label: t('leaderboard.feature.efficiency') },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backdropFilter: 'blur(8px)', background: 'rgba(0,0,0,0.4)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="relative w-full max-w-md mx-4 overflow-hidden"
        style={{
          background: 'var(--color-bg)',
          borderRadius: 16,
          boxShadow: '0 24px 80px rgba(0,0,0,0.25)',
          border: '1px solid var(--color-border)',
        }}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 p-1.5 rounded-lg transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          aria-label={t('common.close')}
        >
          <X size={16} />
        </button>

        <div className="px-8 pt-8 pb-6">
          {/* Trophy icon */}
          <div
            className="flex items-center justify-center w-14 h-14 rounded-2xl mb-5 mx-auto"
            style={{
              background: 'linear-gradient(135deg, var(--color-accent), var(--color-accent-purple))',
            }}
          >
            <Trophy size={28} color="white" />
          </div>

          {/* Heading */}
          <h2
            className="text-xl font-semibold text-center mb-2"
            style={{ color: 'var(--color-text)' }}
          >
            {t('leaderboard.shareSavings')}
          </h2>
          <p
            className="text-sm text-center mb-6 leading-relaxed"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {t('leaderboard.optInBody')}
          </p>

          {/* Feature list */}
          <div className="flex flex-col gap-3 mb-6">
            {features.map(({ icon: Icon, label }) => (
              <div key={label} className="flex items-center gap-3">
                <div
                  className="flex items-center justify-center w-8 h-8 rounded-full shrink-0"
                  style={{ background: 'var(--color-bg-secondary)' }}
                >
                  <Icon size={14} style={{ color: 'var(--color-accent)' }} />
                </div>
                <span
                  className="text-sm"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  {label}
                </span>
              </div>
            ))}
          </div>

          {/* Success state */}
          {joined ? (
            <div className="text-center">
              <div
                className="inline-flex items-center gap-2 px-4 py-2 rounded-full mb-4"
                style={{
                  background: 'var(--color-accent-subtle)',
                  color: 'var(--color-accent)',
                }}
              >
                <Trophy size={14} />
                <span className="text-sm font-medium">
                  {t('leaderboard.joined')}
                </span>
              </div>
              <div className="flex gap-2 justify-center">
                <button
                  onClick={onClose}
                  className="px-5 py-2.5 rounded-xl text-sm font-medium transition-colors cursor-pointer"
                  style={{
                    background: 'var(--color-accent)',
                    color: 'var(--color-on-accent)',
                  }}
                >
                  {t('common.done')}
                </button>
                <button
                  onClick={handleOptOut}
                  className="px-5 py-2.5 rounded-xl text-sm transition-colors cursor-pointer"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  {t('leaderboard.optOut')}
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* Name input */}
              <div className="mb-3">
                <label
                  className="block text-xs font-medium mb-1.5"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  {t('leaderboard.displayName')}
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value);
                    if (error) setError('');
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleJoin();
                  }}
                  placeholder={t('leaderboard.namePlaceholder')}
                  maxLength={30}
                  className="w-full px-3 py-2.5 rounded-xl text-sm outline-none transition-colors"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    border: '1.5px solid var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                  autoFocus
                />
              </div>

              {/* Email input */}
              <div className="mb-4">
                <label
                  className="block text-xs font-medium mb-1.5"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  {t('leaderboard.email')} <span style={{ color: 'var(--color-error)' }}>*</span>
                  <span className="font-normal ml-1" style={{ color: 'var(--color-text-tertiary)' }}>{t('leaderboard.emailNote')}</span>
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    if (error) setError('');
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleJoin();
                  }}
                  placeholder={t('leaderboard.emailPlaceholder')}
                  className="w-full px-3 py-2.5 rounded-xl text-sm outline-none transition-colors"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    border: '1.5px solid var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                />
                {error && (
                  <p
                    className="text-xs mt-1"
                    style={{ color: 'var(--color-error)' }}
                  >
                    {error}
                  </p>
                )}
              </div>

              {/* Buttons */}
              <button
                onClick={handleJoin}
                className="w-full py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer"
                style={{
                  background: 'var(--color-accent)',
                  color: 'var(--color-on-accent)',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.9')}
                onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
              >
                {t('leaderboard.join')}
              </button>
              <button
                onClick={onClose}
                className="w-full py-2 text-sm transition-colors cursor-pointer mt-2"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                {t('leaderboard.noThanks')}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
