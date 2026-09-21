import { memo, useState, useMemo, useRef, type RefObject } from 'react';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import 'katex/dist/katex.min.css';
import { Copy, Check, Globe } from 'lucide-react';
import { AudioPlayer } from './AudioPlayer';
import { ToolCallCard } from './ToolCallCard';
import { ResearchTimeline } from './ResearchTimeline';
import { rehypeCitations } from '../../lib/rehype-citations';
import { XRayFooter } from './XRayFooter';
import { useTranslation } from '../../i18n/useTranslation';
import type { ChatMessage } from '../../types';
import { copierMessage } from './copieMessage';
import { lireQuestions, texteQuestions } from '../../lib/questionsChat';
import { QuestionsDiscussion } from './QuestionsDiscussion';
import { lignesDeSources } from './sourcesDeReponse';
import {
  EVENEMENT_VERIFIER_EN_LIGNE,
  badgeDeVerification,
  notesDeVerification,
  peutVerifierEnLigne,
  type DemandeDeVerification,
} from './notesDeVerification';
import { useAppStore } from '../../lib/store';
import { isCloudModel } from '../../lib/cloud-models';

function stripThinkTags(text: string): string {
  let cleaned = text.replace(/<think>[\s\S]*?<\/think>\s*/gi, '');
  cleaned = cleaned.replace(/^[\s\S]*?<\/think>\s*/i, '');
  return cleaned.trim();
}

interface Props {
  message: ChatMessage;
  isLive?: boolean;
  /** 17 sept. 2026 : la bulle qu'un résultat de recherche vient d'ouvrir —
   * halo d'accent 800 ms, le temps de la trouver des yeux. */
  cible?: boolean;
}

function getTextContent(node: any): string {
  if (typeof node === 'string' || typeof node === 'number') {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(getTextContent).join('');
  }
  if (node?.props?.children) {
    return getTextContent(node.props.children);
  }
  return '';
}

function CodeBlockPre({ children, ...props }: any) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const codeElement = Array.isArray(children) ? children[0] : children;
  const className = codeElement?.props?.className || '';
  const match = /language-([\w-]+)/.exec(className);
  const lang = match ? match[1] : '';
  const code = getTextContent(codeElement?.props?.children).replace(/\n$/, '');

  const handleCopy = async () => {
    try {
      await copierMessage(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t('chat.message.copyFailed'));
    }
  };

  return (
    <div
      className="code-block-wrapper relative my-3"
      style={{ borderRadius: 'var(--radius-md)', overflow: 'hidden' }}
    >
      <div
        className="flex items-center justify-between px-4 py-1.5 text-xs"
        style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}
      >
        <span className="font-mono">{lang || 'code'}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 px-2 py-0.5 rounded transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-text-secondary)')}
          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-tertiary)')}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? t('common.copied') : t('common.copy')}
        </button>
      </div>
      <pre {...props} style={{ margin: 0, borderRadius: 0 }}>
        {children}
      </pre>
    </div>
  );
}

function CopyMessageButton({ content, rendu }: {
  content: string;
  rendu?: RefObject<HTMLDivElement | null>;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await copierMessage(content, rendu?.current);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t('chat.message.copyFailed'));
    }
  };

  // Dans le mini-panneau (NSPanel non activant), le survol n'arrive plus dès
  // qu'une autre app est devant : un bouton Copier à `opacity-0` y était
  // cliquable à l'aveugle seulement (revue du 16 sept. 2026).
  return (
    <button
      onClick={handleCopy}
      className="p-1 rounded opacity-0 group-hover:opacity-100 focus-visible:opacity-100 compact:opacity-100 transition-opacity cursor-pointer"
      style={{ color: 'var(--color-text-tertiary)' }}
      title={t('chat.message.copy')}
      aria-label={t('chat.message.copy')}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}

function VerifierEnLigneButton({ messageId }: { messageId: string }) {
  const { t } = useTranslation();
  const isStreaming = useAppStore((s) => s.streamState.isStreaming);
  const activeId = useAppStore((s) => s.activeId);
  // Revue du 21/09 : sur une bulle ancienne, le bouton vérifiait la DERNIÈRE
  // question du fil, pas celle de la bulle ; et sur un modèle distant, rien
  // n'était vérifié sans un mot. Dernière bulle du fil, modèle local seulement.
  const estLaDerniere = useAppStore((s) => s.messages[s.messages.length - 1]?.id === messageId);
  const modeleDistant = useAppStore((s) => isCloudModel(s.selectedModel));
  if (!estLaDerniere || modeleDistant) return null;
  const demander = () => {
    if (!activeId || isStreaming) return;
    window.dispatchEvent(
      new CustomEvent<DemandeDeVerification>(EVENEMENT_VERIFIER_EN_LIGNE, {
        detail: { conversationId: activeId, messageId },
      }),
    );
  };
  return (
    <button
      onClick={demander}
      disabled={isStreaming}
      className="inline-flex items-center gap-1 text-[11px] px-1.5 py-px rounded-full opacity-0 group-hover:opacity-100 focus-visible:opacity-100 compact:opacity-100 transition-opacity cursor-pointer disabled:cursor-default disabled:opacity-40"
      style={{ color: 'var(--color-accent)', border: '1px solid currentColor' }}
      title={t('chat.verification.verifierEnLigne')}
      aria-label={t('chat.verification.verifierEnLigne')}
    >
      <Globe size={11} />
      {t('chat.verification.verifierEnLigne')}
    </button>
  );
}

export const MessageBubble = memo(function MessageBubble({ message, isLive = false, cible = false }: Props) {
  const { t } = useTranslation();
  const rendu = useRef<HTMLDivElement>(null);
  const isUser = message.role === 'user';
  // `data-message-id` : la cible du défilement « au message » (sauteur,
  // barre latérale) ; ChatArea la cherche dans le DOM une fois rendue.
  // Le halo, lui, entoure l'élément COLORÉ : côté utilisateur la bulle
  // (contre-revue du 17 sept. 2026 : posé sur la rangée, l'anneau faisait
  // 688 px autour d'une bulle de 323, bouton Copier englobé — un
  // surlignage de rangée, pas de bulle) ; côté assistant le contenu occupe
  // toute la rangée, l'anneau y désigne bien ce qu'on cherche.
  const halo = cible ? ' bulle-cible' : '';

  const questions = useMemo(() => lireQuestions(message.questions), [message.questions]);
  const cleanContent = useMemo(() => questions ? texteQuestions(questions) : stripThinkTags(message.content), [message.content, questions]);

  // Build a ref→source lookup once per render. Memoized so the rehype plugin
  // identity stays stable until the source list actually changes.
  const sourcesMap = useMemo(() => {
    const m = new Map<number, NonNullable<ChatMessage['researchSources']>[number]>();
    for (const s of message.researchSources ?? []) {
      if (typeof s.ref === 'number') m.set(s.ref, s);
    }
    return m;
  }, [message.researchSources]);

  const lignes = useMemo(() => lignesDeSources(message.researchSources), [message.researchSources]);
  const notes = useMemo(() => notesDeVerification(message.verification, t), [message.verification, t]);
  const badge = useMemo(() => badgeDeVerification(message.verification), [message.verification]);

  const rehypePlugins = useMemo(() => {
    const base: any[] = [[rehypeHighlight, { detect: true }], rehypeKatex];
    if (sourcesMap.size > 0) base.push([rehypeCitations, { sources: sourcesMap }]);
    return base;
  }, [sourcesMap]);


  if (isUser) {
    // Ses propres mots se copient aussi (demandé le 23 août 2026) : même
    // bouton que côté réponse, à gauche de la bulle, révélé au survol.
    return (
      <div className="flex justify-end mb-4 group" data-message-id={message.id}>
        <div className="flex items-end gap-1.5 max-w-[85%]">
          <CopyMessageButton content={message.content} />
          <div
            className={`px-4 py-2.5 text-sm leading-relaxed${halo}`}
            style={{
              background: 'var(--color-user-bubble)',
              color: 'var(--color-user-bubble-text)',
              borderRadius: 'var(--radius-xl) var(--radius-xl) var(--radius-sm) var(--radius-xl)',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`group mb-6${halo}`} data-message-id={message.id}>
      {/* Deep Research timeline (steps + status) */}
      {(message.isResearch || (message.researchTraces && message.researchTraces.length > 0)) && (
        <ResearchTimeline
          traces={message.researchTraces ?? []}
          isLive={isLive}
          hasContent={cleanContent.length > 0}
        />
      )}

      {/* Tool calls */}
      {message.toolCalls && message.toolCalls.length > 0 && (
        <div className="mb-3 flex flex-col gap-2">
          {message.toolCalls.map((tc) => (
            <ToolCallCard key={tc.id} toolCall={tc} />
          ))}
        </div>
      )}

      {/* Audio player (e.g. morning digest) */}
      {message.audio?.url && <AudioPlayer src={message.audio.url} />}

      {/* Assistant message */}
      {questions ? <QuestionsDiscussion key={questions.id} messageId={message.id} demande={questions} /> : cleanContent && (
        <div ref={rendu} className="prose max-w-none">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={rehypePlugins}
            components={{
              pre: CodeBlockPre,
            }}
          >
            {cleanContent}
          </ReactMarkdown>
        </div>
      )}

      {/* Sources d'une recherche (20/09/2026) : toutes, cliquables, datées. */}
      {!message.isResearch && lignes.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          {lignes.map((l) => (
            <a
              key={l.ref}
              href={l.url}
              target="_blank"
              rel="noopener noreferrer"
              title={l.titre || l.url}
              className="inline-flex items-center gap-1 min-w-0 max-w-full hover:underline"
            >
              <span className="research-citation">{l.ref}</span>
              <span className="truncate">{l.domaine}</span>
              {l.officielle && (
                <span className="whitespace-nowrap" style={{ color: 'var(--color-success)' }}>
                  · {t('chat.sources.officielle')}
                </span>
              )}
              {l.date && <span className="opacity-70 whitespace-nowrap">· {l.date}</span>}
            </a>
          ))}
        </div>
      )}

      {/* Ce que la réponse affirme sans source (20/09/2026), le titulaire que
          les sources désignent, l'âge des sources (21/09) : des signaux, pas
          un verdict — une ligne chacun. */}
      {notes.length > 0 && (
        <div className="mt-1.5 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          {notes.map((note) => (
            <div key={note}>⚠︎ {note}</div>
          ))}
        </div>
      )}

      {/* Footer: copy + badge de vérification + x-ray. 21/09/2026 (P1/P2 du
          jury) : le niveau vient du serveur, jamais du modèle ; le bouton
          « Vérifier en ligne » force la recherche à la main (§82) et n'apparaît
          que quand il peut changer quelque chose. Visible sans survol dans le
          mini-panneau (compact:opacity-100), comme Copier. */}
      <div className="flex items-center gap-2 mt-1.5 flex-wrap">
        <CopyMessageButton content={cleanContent} rendu={rendu} />
        {badge && (
          <span
            className="text-[11px] px-1.5 py-px rounded-full whitespace-nowrap"
            style={{
              color: badge.ton === 'ok' ? 'var(--color-success)' : 'var(--color-warning)',
              border: '1px solid currentColor',
              opacity: 0.85,
            }}
          >
            {t(badge.cle)}
          </span>
        )}
        {!isLive && message.role === 'assistant' && peutVerifierEnLigne(message.verification) && (
          <VerifierEnLigneButton messageId={message.id} />
        )}
      </div>
      <XRayFooter
        usage={message.usage}
        telemetry={message.telemetry}
        isResearch={message.isResearch}
      />
    </div>
  );
});
