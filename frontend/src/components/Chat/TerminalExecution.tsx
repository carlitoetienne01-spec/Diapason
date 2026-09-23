import { memo, useEffect, useId, useMemo, useRef, useState, type CSSProperties } from 'react';
import { Check, ChevronDown, CircleDashed, Terminal, X } from 'lucide-react';
import type { ChatReception, ResearchSource, ToolCallInfo } from '../../types';
import { useTranslation } from '../../i18n/useTranslation';
import { bilanExecution, dureeOutil, dureeValide, etatExecution } from './etatExecution';
import { commandeOutil, courbeReception, journalExecution } from './receptionTerminal';
import { useSurfaceVitree } from './useSurfaceVitree';
import './TerminalDiscussion.css';

interface Props {
  appels: ToolCallInfo[];
  enDirect: boolean;
  reception?: ChatReception;
  sources?: ResearchSource[];
}

export const TerminalExecution = memo(function TerminalExecution({ appels, enDirect, reception, sources }: Props) {
  const { t, locale } = useTranslation();
  const panneauId = useId();
  const existe = enDirect || !!reception || appels.length > 0;
  const surface = useSurfaceVitree<HTMLElement>(false, existe);
  const journal = useRef<HTMLDivElement>(null);
  const suivre = useRef(true);
  // 22/09 : le repli à 900 ms faisait disparaître le journal pendant la
  // réponse. Seul le clic replie un tour en cours, puis le laisse ainsi.
  const [ouvert, setOuvert] = useState(enDirect || reception?.status === 'open');
  const etaitEnDirect = useRef(enDirect);
  useEffect(() => {
    if (enDirect && !etaitEnDirect.current) setOuvert(true);
    etaitEnDirect.current = enDirect;
  }, [enDirect]);
  const [maintenant, setMaintenant] = useState(Date.now);
  useEffect(() => {
    if (!enDirect) return;
    const timer = window.setInterval(() => { if (!document.hidden) setMaintenant(Date.now()); }, 250);
    return () => window.clearInterval(timer);
  }, [enDirect]);

  const bilan = bilanExecution(appels, enDirect);
  const lignes = useMemo(() => journalExecution(appels, reception, enDirect), [appels, reception, enDirect]);
  const signature = lignes.map(l => l.id).join('|');
  const instant = reception?.endedAtMs ?? (enDirect ? maintenant : reception?.lastReceivedAtMs ?? reception?.startedAtMs ?? maintenant);
  const graphe = reception ? courbeReception(reception, instant) : null;
  const mesureMax = Math.max(0, ...appels.filter(a => dureeValide(a.latency)).map(a => a.latency!));
  const courant = appels.find(a => a.status === 'running') ?? appels[appels.length - 1];
  const nbSources = new Set((sources ?? []).filter(s => s.url).map(s => s.url)).size;
  const nf = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const octets = (n: number) => n >= 1000 ? `${nf.format(n / 1000)} ko` : `${nf.format(n)} o`;
  const heure = reception ? `t+${nf.format(Math.max(0, instant - reception.startedAtMs) / 1000)} s` : '';
  const signal = `${signature}:${reception?.samples[reception.samples.length - 1]?.second ?? ''}`;

  useEffect(() => {
    const el = journal.current;
    if (el && suivre.current && ouvert) el.scrollTop = el.scrollHeight;
  }, [signature, ouvert]);

  if (!existe) return null;
  const etat = bilan.erreurs || reception?.status === 'error' ? 'error'
    : bilan.nonConfirmes || reception?.status === 'interrupted' || (!enDirect && reception?.status === 'open') ? 'unconfirmed'
    : enDirect ? 'running' : 'success';
  const Icone = etat === 'success' ? Check : etat === 'error' ? X : CircleDashed;
  const resume = [
    bilan.actifs ? t('chat.terminal.activeCount', { count: bilan.actifs }) : '',
    bilan.reussis ? t('chat.terminal.doneCount', { count: bilan.reussis }) : '',
    bilan.erreurs ? t('chat.terminal.errorCount', { count: bilan.erreurs }) : '',
    bilan.nonConfirmes ? t('chat.terminal.unknownCount', { count: bilan.nonConfirmes }) : '',
    nbSources ? t('chat.terminal.sourcesCount', { count: nbSources }) : '',
  ].filter(Boolean).join(' · ') || t(enDirect ? 'chat.terminal.waiting' : etat === 'unconfirmed' ? 'chat.terminal.unconfirmed' : etat === 'error' ? 'chat.terminal.streamError' : 'chat.terminal.closed');
  const texteLigne = (ligne: typeof lignes[number]) => {
    if (ligne.tag === 'REQ') return t('chat.terminal.request');
    if (ligne.tag === 'TEXT') return t('chat.terminal.textReceived');
    if (ligne.tag === 'CLOSE') return t('chat.terminal.closed');
    if (ligne.tag === 'STOP') return t(ligne.texte === 'error' ? 'chat.terminal.streamError' : 'chat.terminal.interrupted');
    if (ligne.tag === 'WAIT') return `${ligne.texte} · ${t('chat.terminal.unconfirmed')}`;
    return ligne.texte;
  };

  return (
    <section ref={surface} className="terminal-execution" data-live={enDirect} data-state={etat}>
      <div className="terminal-corners" aria-hidden="true" />
      <header className="terminal-entete">
        <Terminal size={17} aria-hidden="true" />
        <span><strong>diapason</strong><span className="terminal-chemin"> / {appels.length ? 'tools' : 'chat'}</span></span>
        <span className="terminal-horloge" title={t('chat.terminal.clientTime')}>{heure}<i data-live={enDirect} /></span>
      </header>
      <div className="terminal-repli" data-open={ouvert} id={panneauId} inert={!ouvert} aria-hidden={!ouvert}>
        <div className="terminal-repli-interieur">
          <div className="terminal-commande"><span aria-hidden="true">›</span><code>{commandeOutil(courant) || t('chat.terminal.waiting')}</code></div>
          <div className="terminal-circuit" aria-hidden="true">
            <div><span>{t('chat.terminal.command')}</span><span>{courant?.tool || 'chat'}</span><span>{t('chat.terminal.received')}</span></div>
            <svg viewBox="0 0 600 28" preserveAspectRatio="none">
              <path className="terminal-fil" d="M4 14 H170 l8 -8 h115 l8 8 H320 l8 8 H560 l8 -8 H596" />
              <path key={signal} className="terminal-impulsion" d="M4 14 H170 l8 -8 h115 l8 8 H320 l8 8 H560 l8 -8 H596" pathLength="1" />
              <circle cx="4" cy="14" r="2" /><circle cx="301" cy="14" r="2" /><circle cx="596" cy="14" r="2" />
            </svg>
          </div>
          <div className="terminal-colonnes">
            <div className="terminal-journal" ref={journal} tabIndex={0} aria-label={t('chat.terminal.log')}
              onScroll={e => {
                const el = e.currentTarget;
                suivre.current = el.scrollHeight - el.clientHeight - el.scrollTop < 24;
              }}>
              {lignes.map((ligne, i) => <div key={ligne.id} className="terminal-ligne" data-tag={ligne.tag}
                data-fresh={ligne.atMs != null && Math.abs(Date.now() - ligne.atMs) < 1500}>
                <span className="terminal-numero" aria-hidden="true">{String(i + 1).padStart(3, '0')}</span>
                <span className="terminal-tag">{ligne.tag}</span>
                <span className="terminal-ligne-texte">{texteLigne(ligne)}
                  {ligne.resume && <span className="terminal-resume" data-vide={ligne.vide}> · {ligne.resume}</span>}
                  <i className="terminal-ligne-laser" aria-hidden="true" /></span>
              </div>)}
              {!lignes.length && <p className="terminal-attente">{t('chat.terminal.waiting')}</p>}
            </div>
            <aside className="terminal-mesures" aria-label={t('chat.terminal.measures')}>
              {graphe && <figure className="terminal-graphe">
                <figcaption><span className="terminal-graphe-titre">{t('chat.terminal.flow')}</span><span>{octets(graphe.valeurs[graphe.valeurs.length - 1]?.bytes ?? 0)} / 1 s</span></figcaption>
                <div className="terminal-axes"><span>{octets(graphe.maximum === 1 && !reception?.receivedBytes ? 0 : graphe.maximum)}</span><span>0</span></div>
                <svg viewBox="0 0 200 70" preserveAspectRatio="none" role="img" aria-label={t('chat.terminal.flowLegend')}>
                  <path className="terminal-grille" d="M0 6 H200 M0 35 H200 M0 64 H200 M0 6 V64 M50 6 V64 M100 6 V64 M150 6 V64 M200 6 V64" />
                  <polygon className="terminal-aire" points={`0,64 ${graphe.points} 200,64`} />
                  <polyline className="terminal-courbe" points={graphe.points} />
                </svg>
                <small>{t('chat.terminal.flowLegend')}</small>
              </figure>}
              {appels.length > 0 && <div className="terminal-executions">
                <div className="terminal-legende">{t('chat.terminal.execution')}<span>{bilan.reussis + bilan.erreurs}/{appels.length}</span></div>
                {appels.map(appel => <div className="terminal-mesure" key={appel.id}>
                  <span title={appel.tool}>{appel.tool}</span>
                  <div className="terminal-regle" data-running={etatExecution(appel, enDirect) === 'running'} aria-hidden="true">
                    {dureeValide(appel.latency) && <i style={{ '--longueur': `${mesureMax > 0 ? appel.latency! / mesureMax * 100 : 0}%` } as CSSProperties} />}
                  </div>
                  <span>{dureeValide(appel.latency) ? dureeOutil(appel.latency, locale) : etatExecution(appel, enDirect) === 'running' ? '…' : '—'}</span>
                </div>)}
                <small>{t('chat.terminal.durations')}</small>
              </div>}
              {reception && <div className="terminal-octets"><span>{t('chat.terminal.utf8')}</span><code>{reception.tailHex || '—'}</code>
                <span>{t('chat.terminal.total')}<b>{octets(reception.receivedBytes)}</b></span></div>}
              {!reception && <small>{t('chat.terminal.noMeasure')}</small>}
            </aside>
          </div>
        </div>
      </div>
      <button type="button" className="terminal-pied" aria-expanded={ouvert} aria-controls={panneauId} onClick={() => setOuvert(!ouvert)}>
        <Icone size={16} aria-hidden="true" /><span>{resume}</span><b>{t(ouvert ? 'chat.terminal.collapse' : 'chat.terminal.expand')}</b>
        <ChevronDown size={14} className="terminal-chevron" data-open={ouvert} aria-hidden="true" />
      </button>
    </section>
  );
});
