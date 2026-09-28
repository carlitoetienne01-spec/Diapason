import { useContext, useEffect, useRef, useState } from 'react';
import { Check, Mic, Square, X } from 'lucide-react';
import { ContexteVoix } from '../../hooks/contexteVoix';
import { useTranslation } from '../../i18n/useTranslation';
import { PHRASES_PROFIL, ErreurProfil, capturerProfil, requeteProfil, type EtatProfil } from './captureProfil';

const erreurs = {
  tooShort: 'voiceProfile.tooShort', tooQuiet: 'voiceProfile.tooQuiet', clipped: 'voiceProfile.clipped',
  differentVoice: 'voiceProfile.differentVoice', conflict: 'voiceProfile.conflict', unavailable: 'voiceProfile.unavailable',
  notLoaded: 'voiceProfile.notLoaded', saveFailed: 'voiceProfile.saveFailed',
} as const;
const verdicts = { recognized: 'voiceProfile.recognized', notRecognized: 'talk.stage.voiceNotRecognized',
  insufficientAudio: 'talk.stage.voiceNeedsMoreSpeech', profileMissing: 'talk.stage.voiceProfileRequired',
  unavailable: 'talk.stage.voiceCheckUnavailable' } as const;

type Phase = 'repos' | 'permission' | 'capture' | 'validation' | 'sauvegarde';
export function ProfilVocal() {
  const { t } = useTranslation();
  const voix = useContext(ContexteVoix);
  const [profil, setProfil] = useState<EtatProfil | null>(null);
  const [ouvert, setOuvert] = useState(false);
  const [echantillons, setEchantillons] = useState<Array<string | null>>(() => PHRASES_PROFIL.map(() => null));
  const [indice, setIndice] = useState(0);
  const [phase, setPhase] = useState<Phase>('repos');
  const [niveau, setNiveau] = useState(0);
  const [message, setMessage] = useState('');
  const [erreur, setErreur] = useState('');
  const generation = useRef(0);
  const annulation = useRef<AbortController | null>(null);
  const finir = useRef<(() => void) | null>(null);
  const bouton = 'min-h-10 inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm cursor-pointer disabled:opacity-50 disabled:cursor-default focus-visible:outline-2 focus-visible:outline-offset-2';
  const secondaire = { border: '1px solid var(--color-border)', color: 'var(--color-text)' };
  const libre = phase === 'repos';
  const complets = echantillons.every(Boolean);
  function afficherErreur(e: unknown) {
    const cle = e instanceof ErreurProfil && e.motif in erreurs ? erreurs[e.motif as keyof typeof erreurs] : 'voiceProfile.error';
    setErreur(t(cle));
    if (e instanceof ErreurProfil && e.indice !== undefined) setIndice(e.indice);
  }
  useEffect(() => {
    let present = true;
    requeteProfil<EtatProfil>().then(p => { if (present) setProfil(p); })
      .catch(e => { if (present) afficherErreur(e); });
    return () => { present = false; generation.current++; annulation.current?.abort(); };
  }, []);
  useEffect(() => {
    const masquer = () => { if (document.hidden) annulation.current?.abort(); };
    document.addEventListener('visibilitychange', masquer);
    return () => document.removeEventListener('visibilitychange', masquer);
  }, []);
  function fermer() {
    generation.current++;
    annulation.current?.abort(); finir.current = null;
    setEchantillons(PHRASES_PROFIL.map(() => null)); setOuvert(false); setPhase('repos'); setNiveau(0); setErreur('');
  }
  async function enregistrer(essai = false) {
    if (!libre || !profil) return;
    voix?.stop();
    const tour = ++generation.current;
    const controle = new AbortController(); annulation.current = controle;
    setPhase('permission'); setErreur(''); setMessage('');
    try {
      const fin = new Promise<void>(resolve => { finir.current = resolve; });
      const audio = await capturerProfil({ signal: controle.signal, fin,
        pret: () => { if (tour === generation.current) setPhase('capture'); },
        niveau: v => { if (tour === generation.current) setNiveau(v); },
      });
      if (tour !== generation.current || controle.signal.aborted) return;
      setPhase('validation');
      if (essai) {
        const reponse = await requeteProfil<{ result: keyof typeof verdicts }>('/check', 'POST', { audio });
        if (tour === generation.current) setMessage(t(verdicts[reponse.result] ?? 'voiceProfile.error'));
      } else {
        await requeteProfil('/sample', 'POST', { audio, index: indice });
        if (tour !== generation.current) return;
        const suivants = [...echantillons]; suivants[indice] = audio;
        setEchantillons(suivants);
        const prochain = suivants.findIndex(e => !e);
        if (prochain >= 0) setIndice(prochain);
        setMessage(t(prochain < 0 ? 'voiceProfile.review' : 'voiceProfile.sampleReady'));
      }
    } catch (e) { if (tour === generation.current && !controle.signal.aborted) afficherErreur(e); }
    finally { if (tour === generation.current) { setPhase('repos'); finir.current = null; annulation.current = null; } }
  }
  async function sauvegarder() {
    if (!profil || !complets || !libre) return;
    const tour = ++generation.current;
    setPhase('sauvegarde'); setErreur('');
    try {
      const nouveau = await requeteProfil<EtatProfil>('', 'PUT', { revision: profil.revision,
        samples: echantillons.map(audio => ({ audio })),
      });
      if (tour !== generation.current) return;
      setProfil(nouveau); fermer(); setMessage(t('voiceProfile.saved'));
    } catch (e) {
      if (tour !== generation.current) return;
      afficherErreur(e);
      if (e instanceof ErreurProfil && e.motif === 'conflict') {
        // Un autre panneau a enregistré entre-temps : on recharge sa version
        // mais un NOUVEAU clic explicite reste nécessaire pour la remplacer.
        try { setProfil(await requeteProfil<EtatProfil>()); } catch { /* erreur affichée conservée */ }
      }
    } finally { if (tour === generation.current) setPhase('repos'); }
  }
  return <div className="my-4 min-w-0 rounded-xl p-4" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-medium">{t('voiceProfile.title')}</h3>
        <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>{t('voiceProfile.description')}</p>
      </div>
      {ouvert && <button type="button" className={bouton} disabled={phase === 'sauvegarde'} onClick={fermer} aria-label={t('common.cancel')}><X size={16} /></button>}
    </div>
    {!ouvert ? <>
      <p className="my-3 text-xs">{profil ? t(profil.enrolled ? 'voiceProfile.ready' : 'voiceProfile.missing') : t(erreur ? 'common.unavailable' : 'common.checking')}</p>
      <div className="flex flex-wrap gap-2">
        {libre && <button type="button" className={bouton} style={secondaire} disabled={!profil} onClick={() => { setOuvert(true); setIndice(0); setErreur(''); setMessage(''); }}>{t(profil?.enrolled ? 'voiceProfile.redo' : 'voiceProfile.create')}</button>}
        {profil?.enrolled && libre && <button type="button" className={bouton} style={secondaire} onClick={() => void enregistrer(true)}><Mic size={15} />{t('voiceProfile.test')}</button>}
      </div>
    </> : <>
      <p className="mt-3 text-xs leading-relaxed">{t('voiceProfile.hint')}</p>
      <div className="my-3 flex flex-wrap gap-1" aria-label={t('voiceProfile.progress')}>
        {PHRASES_PROFIL.map((_, i) => <button key={i} type="button" className="size-10 rounded-lg cursor-pointer flex items-center justify-center disabled:opacity-50"
          style={{ border: `1px solid ${indice === i ? 'var(--color-accent)' : 'var(--color-border)'}` }}
          disabled={!libre} aria-current={indice === i ? 'step' : undefined} aria-label={t('voiceProfile.sample', { count: i + 1 })}
          onClick={() => { setIndice(i); setErreur(''); setMessage(''); }}>{echantillons[i] ? <Check size={15} aria-hidden="true" /> : i + 1}</button>)}
      </div>
      <blockquote className="my-4 text-base leading-relaxed">{PHRASES_PROFIL[indice]}</blockquote>
      {libre && <div className="flex flex-wrap gap-2">
        <button type="button" className={bouton} style={secondaire} onClick={() => void enregistrer()}><Mic size={16} />{t(echantillons[indice] ? 'voiceProfile.retake' : 'voiceProfile.record')}</button>
        {complets && <button type="button" className={bouton} style={{ background: 'var(--color-accent)', color: 'var(--color-bg)' }} onClick={() => void sauvegarder()}>{t('voiceProfile.save')}</button>}
      </div>}
    </>}
    {phase === 'capture' && <div className="mt-3 flex flex-wrap items-center gap-3">
      <button type="button" className={bouton} style={secondaire} onClick={() => finir.current?.()}><Square size={14} />{t('voiceProfile.stop')}</button>
      <meter aria-label={t('voiceProfile.level')} min={0} max={1} value={niveau} className="h-2 w-24" />
      <span className="text-xs">{t('voiceProfile.limit')}</span>
    </div>}
    {phase !== 'repos' && phase !== 'capture' && <p role="status" className="mt-3 text-xs">{t(phase === 'permission' ? 'voiceProfile.permission' : phase === 'sauvegarde' ? 'voiceProfile.saving' : 'voiceProfile.validating')}</p>}
    {!ouvert && !libre && phase !== 'sauvegarde' && <button type="button" className={bouton} onClick={fermer}>{t('common.cancel')}</button>}
    {message && <p role="status" className="mt-3 text-xs leading-relaxed">{message}</p>}
    {erreur && <p role="alert" className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--color-error)' }}>{erreur}</p>}
    <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--color-text-tertiary)' }}>{t('voiceProfile.privacy')}</p>
  </div>;
}
