import { useEffect, useRef } from 'react';
import { Keyboard, Loader2, Mic, MicOff, Square, X } from 'lucide-react';
import type { useConversationVocale } from '../../hooks/useConversationVocale';
import { useVoixPartagee } from '../../hooks/contexteVoix';
import { useTranslation } from '../../i18n/useTranslation';
import { cleEtatVocal } from '../../lib/etatVocal';
import { cleErreurVocale } from '../../lib/erreursVocales';
import { DetailDuMicro } from './DetailDuMicro';
import { niveauOndeVocale } from '../../lib/niveauOndeVocale';
import { deconnecterBrancheAudio } from '../../lib/connexionAudio';

function OndeVocale({ source }: { source: AudioNode | null }) {
  const canevas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canevas.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    const analyseur = source?.context.state !== 'closed' ? source?.context.createAnalyser() : undefined;
    if (analyseur) { analyseur.fftSize = 512; analyseur.smoothingTimeConstant = 0.2; source?.connect(analyseur); }
    const donnees = new Uint8Array(256);
    const echantillons = new Uint8Array(512).fill(128);
    const reduit = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let image = 0, precedent = 0, niveau = 0;
    const dessiner = (maintenant: number) => {
      if (maintenant - precedent >= 16 || reduit) {
        const delai = maintenant - precedent;
        precedent = maintenant;
        ctx.clearRect(0, 0, 80, 24);
        ctx.fillStyle = getComputedStyle(canvas).color;
        if (analyseur && !document.hidden && !reduit) {
          analyseur.getByteFrequencyData(donnees);
          analyseur.getByteTimeDomainData(echantillons);
        } else echantillons.fill(128);
        niveau = niveauOndeVocale(echantillons, niveau, delai);
        for (let i = 0; i < 16; i++) {
          const h = 2 + niveau * (0.25 + 0.75 * donnees[i * 4] / 255) * 20;
          ctx.fillRect(i * 5, (24 - h) / 2, 2, h);
        }
      }
      if (!reduit && source) image = requestAnimationFrame(dessiner);
    };
    dessiner(40);
    return () => {
      cancelAnimationFrame(image);
      if (analyseur && source) {
        try { deconnecterBrancheAudio(source, analyseur); }
        finally { analyseur.disconnect(); }
      }
    };
  }, [source]);
  return <canvas ref={canevas} width={80} height={24} className="onde-vocale" aria-hidden="true" />;
}

export function BarreVocale({ voix, onClavier }: { voix: ReturnType<typeof useConversationVocale>; onClavier: () => void }) {
  const { t } = useTranslation();
  const etape = cleEtatVocal(voix.statusLabel);
  const statut = voix.enFermeture ? t('talk.stage.ending') : voix.microEnPause ? t('composer.micPaused')
    : voix.state === 'connecting' ? t('talk.resonance.connecting')
    : voix.state === 'speaking' ? t('talk.resonance.speaking')
    : etape ? t(etape) : voix.isActive ? t('talk.resonance.listening') : t('composer.voiceEnded');
  const erreur = voix.error && t(cleErreurVocale(voix.error));
  return <div className="barre-vocale" data-state={voix.state}>
    <div className="barre-vocale-ligne">
      {voix.state === 'connecting' ? <Loader2 size={16} className="animate-spin motion-reduce:animate-none shrink-0" />
        : <OndeVocale source={voix.state === 'speaking' ? voix.outputNode : voix.microEnPause ? null : voix.micNode} />}
      <span role="status" className="min-w-0 flex-1 text-xs">{statut}</span>
      <div className="barre-vocale-commandes">
        {voix.isActive && !voix.enFermeture && <>
          <button type="button" onClick={() => voix.mettreMicroEnPause(!voix.microEnPause)} aria-pressed={voix.microEnPause}
            aria-label={t(voix.microEnPause ? 'composer.micResume' : 'composer.micPause')} title={t(voix.microEnPause ? 'composer.micResume' : 'composer.micPause')}>
            {voix.microEnPause ? <MicOff size={16} /> : <Mic size={16} />}
          </button>
          <button type="button" onClick={() => { voix.mettreMicroEnPause(true); onClavier(); }} aria-label={t('composer.keyboard')} title={t('composer.keyboard')}><Keyboard size={17} /></button>
          {(voix.state === 'speaking' || voix.statusLabel === 'responding') && <button type="button" onClick={voix.interrupt}
            aria-label={t('composer.interrupt')} title={t('composer.interrupt')}><Square size={14} /></button>}
        </>}
        <button type="button" onClick={voix.arreter} aria-label={t('composer.endVoice')} title={t('composer.endVoice')}><X size={17} /></button>
      </div>
    </div>
    {voix.conversationSeule && <p className="mt-1 text-xs">{t('talk.conversation.start')}</p>}
    {erreur && <p role="alert" className="mt-2 text-xs" style={{ color: 'var(--color-error)' }}>{erreur}</p>}
    {erreur && <DetailDuMicro micro={voix.micro} onOuvrirReglages={() => void voix.ouvrirReglagesMicro()} />}
  </div>;
}

export function BrouillonVocal() {
  const voix = useVoixPartagee();
  const { t } = useTranslation();
  const dernier = voix.transcripts[voix.transcripts.length - 1];
  if (!voix.isActive || dernier?.role !== 'user' || dernier.final || !dernier.text
    || ['voiceNotRecognized', 'voiceNeedsMoreSpeech', 'voiceProfileRequired', 'voiceCheckUnavailable', 'noSpeech', 'waitingForName'].includes(voix.statusLabel)) return null;
  return <div className="flex justify-end px-4 pb-3" aria-label={t('composer.transcriptDraft')}>
    <div className="brouillon-vocal max-w-[85%] px-4 py-3 text-sm">{dernier.text}<span aria-hidden="true"> …</span></div>
  </div>;
}
