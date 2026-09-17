import type { ResultatRecherche } from '../../lib/discussions';
import type { MessageKey, Vars } from '../../i18n/translate';

/**
 * 17 sept. 2026, chantier « discussions dans le mini-panneau ».
 *
 * La seconde ligne d'un résultat venu d'un message : qui l'a écrit, puis
 * l'extrait avec le terme en <mark>. Partagée avec la barre latérale — même
 * rendu partout. `hidden sm:block` : sous 340 px, le titre seul (règle 5).
 *
 * Le séparateur après le nom vient du catalogue (`chat.jump.from`) : codé en
 * dur `' : '` dans ce composant, la typographie française fuyait dans
 * l'interface anglaise — « You : … » là où tout le catalogue anglais écrit
 * « Command: {target} » (contre-revue du 17 sept. 2026).
 */
export function ExtraitDeMessage({
  extrait,
  role,
  t,
}: {
  extrait: NonNullable<ResultatRecherche['extrait']>;
  role: ResultatRecherche['role'];
  t: (key: MessageKey, vars?: Vars) => string;
}) {
  return (
    <span
      className="hidden sm:block truncate text-[11px] leading-4"
      style={{ color: 'var(--color-text-tertiary)' }}
    >
      {role && (
        <span className="font-medium">
          {t('chat.jump.from', {
            who: t(role === 'user' ? 'chat.jump.fromYou' : 'chat.jump.fromAssistant'),
          })}
        </span>
      )}
      {extrait.avant}
      <mark className="extrait-terme">{extrait.terme}</mark>
      {extrait.apres}
    </span>
  );
}
