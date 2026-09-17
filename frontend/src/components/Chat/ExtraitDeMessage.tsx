import type { ResultatRecherche } from '../../lib/discussions';

/**
 * 17 sept. 2026, chantier « discussions dans le mini-panneau ».
 *
 * La seconde ligne d'un résultat venu d'un message : qui l'a écrit, puis
 * l'extrait avec le terme en <mark>. Partagée avec la barre latérale — même
 * rendu partout. `hidden sm:block` : sous 340 px, le titre seul (règle 5).
 */
export function ExtraitDeMessage({
  extrait,
  role,
  t,
}: {
  extrait: NonNullable<ResultatRecherche['extrait']>;
  role: ResultatRecherche['role'];
  t: (key: 'chat.jump.fromYou' | 'chat.jump.fromAssistant') => string;
}) {
  return (
    <span
      className="hidden sm:block truncate text-[11px] leading-4"
      style={{ color: 'var(--color-text-tertiary)' }}
    >
      {role && (
        <span className="font-medium">
          {t(role === 'user' ? 'chat.jump.fromYou' : 'chat.jump.fromAssistant')}
          {' : '}
        </span>
      )}
      {extrait.avant}
      <mark className="extrait-terme">{extrait.terme}</mark>
      {extrait.apres}
    </span>
  );
}
