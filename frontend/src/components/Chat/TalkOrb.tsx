import { Suspense, lazy, useEffect, useId, useRef, useState } from 'react';
import { AudioLines, Check, Copy, Info, Mic, Monitor, Square, X } from 'lucide-react';
import '@fontsource-variable/geist';
import { useTranslation } from '../../i18n/useTranslation';
import { useLiveDictation } from '../../hooks/useLiveDictation';
import type { VoiceLiveProvider, VoiceLiveState, TranscriptLine, ToolEventLine } from '../../hooks/useVoiceLive';
import { useAppStore } from '../../lib/store';
import { useSurfaceVitree } from './useSurfaceVitree';
import { badgeDeVerification, type Verification } from './notesDeVerification';
import './ComposerGlass.css';
import '../Glass/CarteVitree.css';
import './TalkOrb.css';

// Three reste hors du chargement initial : la présence ne coûte rien tant
// que la conversation n'est pas ouverte.
const VoiceResonance = lazy(() =>
  import('../VoiceResonance/VoiceResonance').then((m) => ({ default: m.VoiceResonance })),
);

interface TalkOrbProps {
  open: boolean;
  state: VoiceLiveState;
  statusLabel: string;
  error: string | null;
  serviceReady: boolean;
  checkingService: boolean;
  provider: VoiceLiveProvider;
  transcripts: TranscriptLine[];
  toolEvents?: ToolEventLine[];
  /** Le niveau du dernier tour d'actualité — la pastille que le panneau
   *  n'avait pas (22/09/2026). L'épilogue parlé ne se prononce QUE lorsqu'il
   *  a quelque chose à avouer : son silence disait aussi bien « vérifié en
   *  ligne » que « personne n'a rien vérifié ». */
  verification?: Verification;
  screenSharing?: boolean;
  audioSource?: AudioNode | null;
  micSource?: AudioNode | null;
  onProviderChange: (p: VoiceLiveProvider) => void;
  onStart: () => void;
  onStop: () => void;
  onInterrupt: () => void;
  onClose: () => void;
}

const ERREURS = {
  'missing-key-gemini': 'talk.missingKeyGemini',
  'missing-key-openai': 'talk.missingKeyOpenai',
  'local-not-ready': 'talk.localNotReady',
  'local-components-missing': 'talk.localComponentsMissing',
  'voice-auth-unavailable': 'talk.authUnavailable',
  'voice-service-unavailable': 'talk.serviceUnavailable',
  'voice-connection-failed': 'talk.connectionFailed',
  'microphone-denied': 'talk.microphoneDenied',
  'voice-session-failed': 'talk.sessionFailed',
} as const;

function CopieTranscript({ texte, etiquette }: { texte: string; etiquette: string }) {
  const [copie, setCopie] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  return <button type="button" className="resonance-copie" title={etiquette} aria-label={etiquette}
    onClick={() => {
      void navigator.clipboard.writeText(texte).then(() => {
        setCopie(true);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopie(false), 2000);
      }).catch(() => setCopie(false));
    }}>
    {copie ? <Check size={14} /> : <Copy size={14} />}
  </button>;
}

export function TalkOrb({
  open, state, statusLabel, error, serviceReady, checkingService, provider,
  transcripts, toolEvents = [], verification, screenSharing = false, audioSource = null,
  micSource = null, onStart, onStop, onInterrupt, onClose,
}: TalkOrbProps) {
  const { t, locale } = useTranslation();
  const titreId = useId();
  const detailsId = useId();
  const fenetre = useSurfaceVitree(true, open);
  const [details, setDetails] = useState(false);
  const filRef = useRef<HTMLDivElement>(null);
  const suiviRef = useRef(true);
  const fil = [
    ...transcripts.map((l) => ({ kind: 'msg' as const, ...l })),
    ...toolEvents.map((e) => ({ kind: 'tool' as const, ...e })),
  ].sort((a, b) => a.at - b.at);
  // Le MÊME calcul qu'au chat : deux façons de décider du même niveau
  // finiraient par diverger, et c'est celle qu'on oublierait qui mentirait.
  const badge = badgeDeVerification(verification);
  const derniere = fil[fil.length - 1];
  const dernierTexte = derniere ? `${fil.length}:${derniere.kind === 'msg' ? derniere.text : derniere.name}` : '';
  useEffect(() => {
    if (filRef.current && suiviRef.current) filRef.current.scrollTop = filRef.current.scrollHeight;
  }, [dernierTexte]);

  // Le panneau est modal aussi au clavier. Le focus revient au bouton qui
  // l'a ouvert ; ni une tabulation ni Échap ne doivent agir sur le chat dessous.
  useEffect(() => {
    if (!open) return;
    const precedent = document.activeElement;
    fenetre.current?.focus();
    return () => { if (precedent instanceof HTMLElement) precedent.focus(); };
  }, [open]);

  const active = state === 'listening' || state === 'speaking' || state === 'connecting';
  const { supported, transcript: heard, start: startCaptions, stop: stopCaptions } = useLiveDictation(locale);
  const [caption, setCaption] = useState('');
  useEffect(() => {
    if (!supported || !open || state !== 'listening') return;
    void startCaptions();
    return () => { void stopCaptions(); };
  }, [supported, open, state, startCaptions, stopCaptions]);
  useEffect(() => { if (heard) setCaption(heard); }, [heard]);
  useEffect(() => { if (!active) setCaption(''); }, [active]);

  const selectedModel = useAppStore((s) => s.selectedModel);
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef<number | null>(null);
  useEffect(() => {
    if (!active) { startedAt.current = null; setElapsed(0); return; }
    startedAt.current ??= Date.now();
    const timer = window.setInterval(() => {
      if (startedAt.current) setElapsed(Math.floor((Date.now() - startedAt.current) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [active]);

  if (!open) return null;
  const fournisseur = provider === 'local' ? t('talk.resonance.local')
    : provider === 'gemini' ? 'Gemini Live' : 'OpenAI Realtime';
  const titres = {
    idle: 'talk.resonance.idle', connecting: 'talk.resonance.connecting',
    listening: 'talk.resonance.listening', speaking: 'talk.resonance.speaking',
    error: 'talk.resonance.error',
  } as const;
  const aide = checkingService ? t('talk.checkingService')
    : !active && !serviceReady ? t('talk.serviceUnavailable')
    : state === 'listening' ? t('talk.resonance.listeningHint')
    : state === 'speaking' ? t('talk.resonance.speakingHint')
    : state === 'connecting' ? t('talk.resonance.connectingHint')
    : t('talk.resonance.micOff');
  const agir = (action: () => void) => {
    // Reprendre la parole remplace son propre bouton. Sans ce déplacement,
    // le focus retombait sur le document derrière la fenêtre modale.
    fenetre.current?.focus();
    action();
  };

  return <div className="resonance-rideau" onClick={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <div ref={fenetre} className="composer-glass carte-vitree resonance-dialogue" role="dialog" aria-modal="true"
      aria-labelledby={titreId} tabIndex={-1} data-conversation={fil.length > 0} data-state={state}
      onKeyDown={(event) => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(); }
        // Le raccourci global Espace du moteur vocal ne doit pas voler
        // l'activation clavier de Terminer, Copier ou Détails.
        if (event.code === 'Space' && (event.target as HTMLElement).closest('button')) event.stopPropagation();
        if (event.key !== 'Tab') return;
        const boutons = Array.from(fenetre.current?.querySelectorAll<HTMLElement>('button:not(:disabled), [tabindex="0"]') ?? []);
        const premier = boutons[0], dernier = boutons[boutons.length - 1];
        if (event.shiftKey && (document.activeElement === premier || document.activeElement === fenetre.current)) {
          event.preventDefault(); dernier?.focus();
        } else if (!event.shiftKey && document.activeElement === dernier) {
          event.preventDefault(); premier?.focus();
        }
      }}>
      <header className="resonance-entete">
        <div className="resonance-identite"><AudioLines size={22} strokeWidth={1.5} aria-hidden="true" />
          <span id={titreId}>Diapason</span><span className="resonance-sous-titre">{t('talk.resonance.voice')}</span>
        </div>
        <div className="resonance-actions-entete">
          {screenSharing && <span className="resonance-partage" title={t('chat.talk.screenShareTooltip')}>
            <Monitor size={14} />{t('chat.talk.sharingScreen')}
          </span>}
          <button type="button" className="resonance-icone" onClick={() => setDetails(!details)}
            aria-expanded={details} aria-controls={detailsId} aria-label={t('talk.resonance.details')} title={t('talk.resonance.details')}>
            <Info size={18} />
          </button>
          <button type="button" className="resonance-icone" onClick={onClose} title={t('chat.talk.close')} aria-label={t('chat.talk.close')}>
            <X size={20} />
          </button>
        </div>
      </header>
      {details && <div id={detailsId} className="resonance-details">
        <span>{fournisseur}{provider === 'local' && selectedModel ? ` / ${selectedModel}` : ''}</span>
        <span>{statusLabel}</span>
      </div>}
      <div className="resonance-corps">
        <section className="resonance-presence">
          <div className="resonance-scene">
            <Suspense fallback={<div className="resonance-repli" aria-hidden="true" />}>
              <VoiceResonance state={state} audioSource={audioSource} micSource={micSource} />
            </Suspense>
          </div>
          <div className="resonance-parole">
            <h2 className="resonance-titre" aria-live="polite">{t(titres[state])}</h2>
            <p className="resonance-aide">{aide}</p>
            {caption && <p className="resonance-caption" aria-live="polite">{caption}</p>}
          </div>
          <div className="resonance-commandes">
            {active ? <>
              {state === 'speaking' && <button type="button" className="resonance-principal" onClick={() => agir(onInterrupt)}>
                <Mic size={17} />{t('talk.resonance.interrupt')}
              </button>}
              <button type="button" className="resonance-terminer" onClick={() => agir(onStop)}>
                <Square size={12} fill="currentColor" />{t('chat.talk.end')}
              </button>
            </> : <button type="button" className="resonance-principal" onClick={() => agir(onStart)}
              disabled={!serviceReady || checkingService}>
              <Mic size={18} />{t('chat.talk.startHint')}
            </button>}
          </div>
          {error && <p className="resonance-erreur" role="alert">
            {error in ERREURS ? t(ERREURS[error as keyof typeof ERREURS]) : error}
          </p>}
        </section>
        {fil.length > 0 && <section className="resonance-conversation" aria-label={t('talk.resonance.transcript')}>
          <div className="resonance-fil-titre">{t('talk.resonance.transcript')}</div>
          <div ref={filRef} className="resonance-fil" tabIndex={0} onScroll={() => {
            const el = filRef.current;
            if (el) suiviRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
          }}>
            {fil.map((entree) => entree.kind === 'tool' ? <div key={`t-${entree.at}`} className="resonance-outil" data-ok={entree.ok}>
              {entree.ok ? <Check size={14} /> : <X size={14} />}
              <span>{entree.name}{entree.detail ? ` — ${entree.detail}` : ''}</span>
            </div> : <div key={`m-${entree.at}`} className="resonance-message" data-role={entree.role}>
              <div className="resonance-auteur"><span>{entree.role === 'user' ? t('common.you') : 'Diapason'}</span>
                <CopieTranscript texte={entree.text} etiquette={t('chat.message.copy')} />
              </div>
              <p>{entree.text}{!entree.final && <span className="resonance-en-cours"> ▍</span>}</p>
            </div>)}
            {badge && <p className="resonance-verification" data-ton={badge.ton}>{t(badge.cle)}</p>}
          </div>
        </section>}
      </div>
      <footer className="resonance-pied">
        <span className="resonance-source"><span className="resonance-temoin" />{fournisseur}</span>
        {active ? <span className="resonance-duree" aria-label={t('talk.resonance.duration')}>
          {String(Math.floor(elapsed / 60)).padStart(2, '0')}:{String(elapsed % 60).padStart(2, '0')}
        </span> : <span>{t('talk.resonance.escape')}</span>}
      </footer>
    </div>
  </div>;
}
