import { useEffect } from 'react';
import {
  FileAudio2,
  FileCheck2,
  FileImage,
  FileVideo2,
  Laptop,
  X,
} from 'lucide-react';

import {
  fileArrivalKind,
  formatFileArrivalSize,
} from '../features/mesh/fileArrival';
import type { MeshFileReceived } from '../features/mesh/types';
import { useTranslation } from '../i18n/useTranslation';

const VISIBLE_MS = 6200;

export function FileArrivalNotice({
  eventId,
  receipt,
  onDismiss,
}: {
  eventId: string;
  receipt: MeshFileReceived;
  onDismiss: (eventId: string) => void;
}) {
  const { t } = useTranslation();
  const kind = fileArrivalKind(receipt);
  const Icon =
    kind === 'image'
      ? FileImage
      : kind === 'video'
        ? FileVideo2
        : kind === 'audio'
          ? FileAudio2
          : FileCheck2;

  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(eventId), VISIBLE_MS);
    return () => window.clearTimeout(timer);
  }, [eventId, onDismiss]);

  return (
    <article className="file-arrival-card pointer-events-auto relative w-[min(23rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border px-4 py-3.5">
      <div className="file-arrival-shine" aria-hidden />
      <div className="relative flex items-center gap-3.5">
        <div className="file-arrival-route shrink-0" aria-hidden>
          <span className="file-arrival-device">
            <Laptop size={14} strokeWidth={1.8} />
          </span>
          <span className="file-arrival-beam">
            <span />
          </span>
          <span className="file-arrival-file">
            <Icon size={17} strokeWidth={1.9} />
          </span>
        </div>

        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-[0.15em] text-emerald-600 dark:text-emerald-300">
            {t('mesh.fileArrival.title')}
          </p>
          <p
            className="mt-0.5 truncate text-sm font-semibold"
            style={{ color: 'var(--color-text)' }}
            title={receipt.fileName}
          >
            {receipt.fileName}
          </p>
          <p className="mt-0.5 truncate text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {t('mesh.fileArrival.from', { device: receipt.sourceDeviceName })}
            <span className="px-1.5 opacity-50">·</span>
            {formatFileArrivalSize(receipt.sizeBytes)}
          </p>
        </div>

        <button
          type="button"
          onClick={() => onDismiss(eventId)}
          className="rounded-full p-1.5 transition-colors hover:bg-black/5 dark:hover:bg-white/10"
          style={{ color: 'var(--color-text-secondary)' }}
          aria-label={t('mesh.fileArrival.dismiss')}
        >
          <X size={14} />
        </button>
      </div>
      <span className="file-arrival-lifetime" aria-hidden />
    </article>
  );
}
