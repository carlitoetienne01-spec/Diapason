import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

// Le 29/09/2026, le premier cours natif affichait les commandes de fractions
// jusque dans les choix du QCM. Le même rendu couvre cours, questions et corrigés.
export function TexteEtude({ children, ligne = false }: { children: string; ligne?: boolean }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[[rehypeKatex, { trust: false }]]}
    components={{
      img: ({ alt }) => <span>{alt || 'Illustration'}</span>,
      ...(ligne ? { p: ({ children }: { children?: React.ReactNode }) => <span>{children}</span> } : {}),
    }}>{children}</ReactMarkdown>;
}
