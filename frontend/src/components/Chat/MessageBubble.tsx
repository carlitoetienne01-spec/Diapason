import { memo, useState, useMemo, useRef, type RefObject } from 'react';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import 'katex/dist/katex.min.css';
import { Copy, Check } from 'lucide-react';
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

export const MessageBubble = memo(function MessageBubble({ message, isLive = false, cible = false }: Props) {
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

      {/* Footer: copy + x-ray */}
      <div className="flex items-center gap-2 mt-1.5">
        <CopyMessageButton content={cleanContent} rendu={rendu} />
      </div>
      <XRayFooter
        usage={message.usage}
        telemetry={message.telemetry}
        isResearch={message.isResearch}
      />
    </div>
  );
});
