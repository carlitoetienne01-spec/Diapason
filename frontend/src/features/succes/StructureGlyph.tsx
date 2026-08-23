import type { SuccesProjectStructure } from './types';

type GlyphProps = {
  stroke: string;
};

function FlatGlyph({ stroke }: GlyphProps) {
  return (
    <g fill="none" stroke={stroke} strokeWidth="1.75" strokeLinecap="round">
      <line x1="9" y1="13" x2="39" y2="13" />
      <line x1="9" y1="21" x2="33" y2="21" />
      <line x1="9" y1="29" x2="39" y2="29" />
      <line x1="9" y1="37" x2="28" y2="37" />
    </g>
  );
}

function TreeGlyph({ stroke }: GlyphProps) {
  return (
    <g fill="none" stroke={stroke} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="24" cy="9" r="4" />
      <path d="M24 13 V20" />
      <path d="M12 20 H36" />
      <path d="M12 20 V27" />
      <path d="M36 20 V27" />
      <circle cx="12" cy="31" r="3.4" />
      <circle cx="36" cy="31" r="3.4" />
      <path d="M12 34.4 V38" />
      <circle cx="12" cy="41.5" r="2.6" />
    </g>
  );
}

function MindmapGlyph({ stroke }: GlyphProps) {
  const rays = [
    [24, 8],
    [38, 16],
    [38, 32],
    [24, 40],
    [10, 32],
    [10, 16],
  ] as const;
  return (
    <g fill="none" stroke={stroke} strokeWidth="1.75" strokeLinecap="round">
      <circle cx="24" cy="24" r="5" />
      {rays.map(([x, y], index) => (
        <g key={index}>
          <line x1="24" y1="24" x2={x} y2={y} />
          <circle cx={x} cy={y} r="2.4" />
        </g>
      ))}
    </g>
  );
}

function PipelineGlyph({ stroke }: GlyphProps) {
  return (
    <g fill="none" stroke={stroke} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="5" y="10" width="10" height="28" rx="2" />
      <rect x="19" y="10" width="10" height="28" rx="2" />
      <rect x="33" y="10" width="10" height="28" rx="2" />
      <path d="M16.2 24 H18.2" />
      <path d="M30.2 24 H32.2" />
    </g>
  );
}

function NetworkGlyph({ stroke }: GlyphProps) {
  return (
    <g fill="none" stroke={stroke} strokeWidth="1.75" strokeLinecap="round">
      <line x1="14" y1="14" x2="24" y2="24" />
      <line x1="34" y1="14" x2="24" y2="24" />
      <line x1="24" y1="24" x2="14" y2="36" />
      <line x1="24" y1="24" x2="34" y2="36" />
      <circle cx="14" cy="14" r="3.2" />
      <circle cx="34" cy="14" r="3.2" />
      <circle cx="24" cy="24" r="3.6" />
      <circle cx="14" cy="36" r="3.2" />
      <circle cx="34" cy="36" r="3.2" />
    </g>
  );
}

function CycleGlyph({ stroke }: GlyphProps) {
  return (
    <g fill="none" stroke={stroke} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M24 8 A16 16 0 1 1 8 24" />
      <path d="M24 8 L20.5 13.5 M24 8 L29 11.5" />
      <circle cx="24" cy="24" r="3" />
    </g>
  );
}

/** Pictogramme du type de projet — même dessin pour tous les projets d'une forme. */
export function StructureGlyph({
  structure,
  stroke,
}: {
  structure: SuccesProjectStructure;
  stroke: string;
}) {
  switch (structure) {
    case 'tree':
      return <TreeGlyph stroke={stroke} />;
    case 'mindmap':
      return <MindmapGlyph stroke={stroke} />;
    case 'pipeline':
      return <PipelineGlyph stroke={stroke} />;
    case 'network':
      return <NetworkGlyph stroke={stroke} />;
    case 'cycle':
      return <CycleGlyph stroke={stroke} />;
    default:
      return <FlatGlyph stroke={stroke} />;
  }
}
