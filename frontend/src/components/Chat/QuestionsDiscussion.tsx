import { useEffect, useId, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, ChevronDown, MessageSquare } from 'lucide-react';
import { useAppStore } from '../../lib/store';
import { composerReponses, EVENEMENT_REPONSES_CHAT, type QuestionsChat, type EnvoiReponses } from '../../lib/questionsChat';
import { useTranslation } from '../../i18n/useTranslation';
import { CarteVitree } from '../Glass/CarteVitree';
import './QuestionsDiscussion.css';

export function QuestionsDiscussion({ messageId, demande }: { messageId: string; demande: QuestionsChat }) {
  const { t } = useTranslation();
  const id = useId();
  const titre = useRef<HTMLLegendElement>(null);
  const [etape, setEtape] = useState(0);
  const [choix, setChoix] = useState<string[]>(() => demande.questions.map(() => ''));
  const [libres, setLibres] = useState<string[]>(() => demande.questions.map(() => ''));
  const dernierId = useAppStore(s => s.messages[s.messages.length - 1]?.id);
  const enCours = useAppStore(s => s.streamState.isStreaming);
  const reponse = useAppStore(s => s.messages.find(m => m.questionReply?.requestId === demande.id)?.questionReply);
  const disponible = dernierId === messageId && !enCours;
  const reponses = demande.questions.map((_, i) => libres[i].trim() || choix[i]);
  const courante = demande.questions[etape];
  useEffect(() => {
    if (!disponible) return;
    // 19/09/2026 : l'auto-défilement du chat épinglait les boutons au bas
    // du mini-panneau en cachant la question. La rendre visible après le fil.
    const frame = requestAnimationFrame(() => titre.current?.scrollIntoView({ block: 'nearest' }));
    return () => cancelAnimationFrame(frame);
  }, [etape, disponible]);
  const modifier = (valeur: string, libre: boolean) => {
    (libre ? setLibres : setChoix)(avant => avant.map((v, i) => i === etape ? valeur : v));
    (libre ? setChoix : setLibres)(avant => avant.map((v, i) => i === etape ? '' : v));
  };
  const envoyer = () => {
    const reply = composerReponses(demande, reponses);
    const conversationId = useAppStore.getState().activeId;
    if (!reply || !conversationId || !disponible) return;
    window.dispatchEvent(new CustomEvent<EnvoiReponses>(EVENEMENT_REPONSES_CHAT, {
      detail: { conversationId, messageId, reply },
    }));
  };

  if (dernierId !== messageId) {
    return <details className="questions-discussion questions-terminees">
      <summary>{reponse ? <Check size={16} aria-hidden="true" /> : <MessageSquare size={16} aria-hidden="true" />}{t(reponse ? 'chat.questions.answered' : 'chat.questions.closed')}<ChevronDown size={16} aria-hidden="true" /></summary>
      <dl>{demande.questions.map(q => <div key={q.id}><dt>{q.title}</dt><dd>{reponse?.answers.find(r => r.questionId === q.id)?.answer || '—'}</dd></div>)}</dl>
    </details>;
  }

  return <CarteVitree contenuClassName="questions-discussion"><section aria-label={t('chat.questions.label')}>
    {demande.intro && <p className="questions-intro">{demande.intro}</p>}
    <div className="questions-position">
      <span>{t('chat.questions.step', { current: etape + 1, total: demande.questions.length })}</span>
      <div aria-hidden="true" className="questions-progression"><span style={{ transform: `scaleX(${(etape + 1) / demande.questions.length})` }} /></div>
    </div>
    <form onSubmit={e => { e.preventDefault(); if (!disponible || !reponses[etape]) return; if (etape < demande.questions.length - 1) setEtape(etape + 1); else envoyer(); }}>
      <fieldset disabled={!disponible}>
        <legend ref={titre} id={`${id}-titre`} aria-live="polite">{courante.title}</legend>
        <div className="questions-etape" key={courante.id}>
          <div className="questions-choix" role="group" aria-labelledby={`${id}-titre`}>
            {courante.options.map(c => <button type="button" key={c.id} aria-pressed={!libres[etape].trim() && choix[etape] === c.label} onClick={() => modifier(c.label, false)}>
              <span><strong>{c.label}</strong>{c.description && <small>{c.description}</small>}</span>
              <span className="questions-coche" aria-hidden="true"><Check size={12} /></span>
            </button>)}
          </div>
          <label className="questions-libre" htmlFor={`${id}-libre`}>{t('chat.questions.free')}</label>
          <textarea id={`${id}-libre`} rows={1} maxLength={1500} value={libres[etape]} placeholder={t('chat.questions.placeholder')} onChange={e => modifier(e.target.value, true)} />
        </div>
        <div className="questions-actions">
          <button type="button" className="questions-retour" disabled={etape === 0} onClick={() => setEtape(etape - 1)}><ArrowLeft size={15} aria-hidden="true" />{t('chat.questions.back')}</button>
          <button type="submit" className="questions-suite" disabled={!reponses[etape]}>{t(etape === demande.questions.length - 1 ? 'chat.questions.send' : 'chat.questions.next')}<ArrowRight size={15} aria-hidden="true" /></button>
        </div>
      </fieldset>
    </form>
  </section></CarteVitree>;
}
