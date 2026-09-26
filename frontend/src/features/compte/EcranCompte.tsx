/**
 * L'écran d'activation du compte (compte-chiffre.md §3.11, étape 9).
 *
 * Deux usages : une fois après l'installation, en plein écran dans la
 * fenêtre de bureau (D13, avec « Plus tard ») ; et à la demande, en voile
 * au-dessus des Réglages ou du bandeau. L'étape affichée ne se décide pas
 * ici : `etapeActivation` (lib/compte.ts) la déduit du statut du serveur
 * local, qui fait foi.
 *
 * Ce fichier porte aussi les morceaux que SectionCompte et BandeauCompte
 * réutilisent (champ de mot de passe, case de mémorisation, bloc de la clé,
 * déverrouillage) : une seule rédaction de chaque texte du §3.11.
 */

import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertTriangle,
  Check,
  Copy,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Lock,
  Printer,
  ShieldAlert,
  ShieldCheck,
  X,
} from 'lucide-react';
import { useTranslation } from '../../i18n/useTranslation';
import type { MessageKey, Vars } from '../../i18n/translate';
import { useConfirm } from '../../components/ConfirmDialog';
import { useSondeVisible } from '../../lib/useSondeVisible';
import { ouvrirLienExterne } from '../../lib/lienExterne';
import { isTauri } from '../../lib/api';
import { estMobile } from '../../lib/natif';
import {
  actionEchap,
  blocageAdresse,
  courrielValide,
  destinationBloquee,
  etapeActivation,
  etapeReinitialisation,
  extraitConcorde,
  formaterDate,
  formeCle,
  genererPhrase,
  groupesDeLaCle,
  iconeEncadre,
  impressionDisponible,
  indiceFocusSuivant,
  inscriptionExpiree,
  libelleSynchro,
  listeUtilisable,
  lireListeMots,
  mettreEnGroupes,
  messageErreur,
  motifRefusMemorisation,
  moyensDeSecours,
  reglesMotDePasse,
  sortieAccueil,
  texteAucunSecours,
  texteMemorisation,
  type CleMontree,
  type ErreurLue,
  type EtatVue,
  type Parcours,
  type StatutCompte,
  type Ton,
} from '../../lib/compte';
import {
  ErreurCompteApi,
  accueilTermine,
  commencerInscription,
  confirmerCle,
  connecter,
  consentir,
  deverrouiller,
  estErreurCompte,
  lireStatutCompte,
  preparerInscription,
  recuperer,
  reinitAnnuler,
  reinitConfirmer,
  reinitDemander,
  reinitTerminer,
  seDeconnecter,
  surChangementCompte,
  terminerInscription,
  verifierCodeInscription,
} from './api';
import './compte.css';

// ---------------------------------------------------------------------------
// La liste de mots (D6)
// ---------------------------------------------------------------------------

// D6 n'est pas tranchée (24/09/2026) : la liste EFF n'est PAS téléchargée
// sans l'accord de Carlito. Le fichier versionné n'existe donc pas encore ;
// `import.meta.glob` rend alors un objet vide, sans casser la compilation,
// et la suggestion est MASQUÉE — l'interface ne propose rien d'inventé. Le
// jour où `liste-mots-eff.txt` est ajouté à côté de ce fichier, elle paraît.
const FICHIERS_MOTS = import.meta.glob('./liste-mots-eff.txt', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

const MOTS: string[] = (() => {
  const textes = Object.values(FICHIERS_MOTS);
  if (textes.length === 0) return [];
  const mots = lireListeMots(textes[0]);
  return listeUtilisable(mots) ? mots : [];
})();

// ---------------------------------------------------------------------------
// Le statut, partagé par toutes les vues du compte
// ---------------------------------------------------------------------------

export interface LectureStatut {
  statut: StatutCompte | null;
  /** Une réponse (bonne ou non) est arrivée au moins une fois. */
  lu: boolean;
  /** Le serveur a répondu, mais sa forme n'est pas celle du contrat. */
  illisible: boolean;
  erreur: ErreurCompteApi | null;
}

/**
 * Le statut du serveur local, sondé tant que la vue est visible, et relu
 * dès qu'un geste le change (`surChangementCompte`). `GET /status` n'entre
 * dans aucun seau du limiteur (auth_middleware, §3.8).
 */
export function useStatutCompte(intervalleMs: number, actif = true): LectureStatut & { relire: () => void } {
  const [lecture, setLecture] = useState<LectureStatut>({ statut: null, lu: false, illisible: false, erreur: null });
  const lire = useCallback(async (signal: AbortSignal) => {
    try {
      const statut = await lireStatutCompte(signal);
      if (signal.aborted) return;
      setLecture({ statut, lu: true, illisible: statut === null, erreur: null });
    } catch (e) {
      if (signal.aborted) return;
      // Le dernier statut connu est GARDÉ avec l'erreur : un serveur local
      // qui redémarre ne doit pas faire croire qu'il n'y a plus de compte.
      setLecture((avant) => ({
        ...avant,
        lu: true,
        erreur: estErreurCompte(e) ? e : new ErreurCompteApi(0, { code: 'localServerUnreachable' }),
      }));
    }
  }, []);
  const relire = useSondeVisible(lire, intervalleMs, actif);
  useEffect(
    () =>
      surChangementCompte((statut) => {
        if (statut) setLecture({ statut, lu: true, illisible: false, erreur: null });
        else relire();
      }),
    [relire],
  );
  return { ...lecture, relire };
}

// ---------------------------------------------------------------------------
// Petits morceaux de présentation
// ---------------------------------------------------------------------------

const STYLE_CHAMP = {
  background: 'var(--color-bg-secondary)',
  color: 'var(--color-text)',
  border: '1px solid var(--color-border)',
} as const;

const TEINTES: Record<Ton | 'danger' | 'info', { fond: string; bord: string; texte: string }> = {
  ok: {
    fond: 'var(--color-accent-subtle)',
    bord: 'color-mix(in srgb, var(--color-success) 30%, transparent)',
    texte: 'var(--color-text)',
  },
  neutre: { fond: 'var(--color-bg-secondary)', bord: 'var(--color-border)', texte: 'var(--color-text-secondary)' },
  info: { fond: 'var(--color-accent-subtle)', bord: 'var(--color-border)', texte: 'var(--color-text)' },
  attente: {
    fond: 'color-mix(in srgb, var(--color-warning) 10%, transparent)',
    bord: 'color-mix(in srgb, var(--color-warning) 30%, transparent)',
    texte: 'var(--color-text)',
  },
  alerte: {
    fond: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
    bord: 'color-mix(in srgb, var(--color-error) 25%, transparent)',
    texte: 'var(--color-text)',
  },
  danger: {
    fond: 'color-mix(in srgb, var(--color-error) 10%, transparent)',
    bord: 'color-mix(in srgb, var(--color-error) 35%, transparent)',
    texte: 'var(--color-text)',
  },
};

export function Encadre({ ton = 'info', titre, children }: { ton?: keyof typeof TEINTES; titre?: string; children: ReactNode }) {
  const teinte = TEINTES[ton];
  // L'icône suit le ton, titre ou non : sur la peau ardéchine, c'est elle
  // qui distingue un danger d'une attente (iconeEncadre, 24/09/2026).
  const sorte = iconeEncadre(ton);
  const Icone = sorte === 'alerte' ? ShieldAlert : sorte === 'ok' ? ShieldCheck : null;
  const icone = Icone && (
    <Icone
      size={15}
      aria-hidden="true"
      className="shrink-0 mt-[0.2rem]"
      style={{ color: sorte === 'ok' ? 'var(--color-success)' : 'var(--color-error)' }}
    />
  );
  return (
    <div
      className="rounded-xl px-4 py-3 text-sm leading-6"
      style={{ background: teinte.fond, border: `1px solid ${teinte.bord}`, color: teinte.texte }}
    >
      {titre && (
        <div className="flex items-start gap-2 font-medium mb-1" style={{ color: 'var(--color-text)' }}>
          {icone}
          <span>{titre}</span>
        </div>
      )}
      <div className={`min-w-0 ${!titre && icone ? 'flex items-start gap-2' : ''}`} style={{ overflowWrap: 'anywhere' }}>
        {!titre && icone}
        {!titre && icone ? <div className="min-w-0 flex-1">{children}</div> : children}
      </div>
    </div>
  );
}

type Variante = 'principal' | 'secondaire' | 'danger' | 'lien';

export function Bouton({
  variante = 'secondaire',
  occupe = false,
  children,
  className = '',
  ...reste
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variante?: Variante; occupe?: boolean }) {
  const styles: Record<Variante, React.CSSProperties> = {
    principal: { background: 'var(--color-accent)', color: 'var(--color-on-accent)' },
    secondaire: { background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' },
    danger: { background: 'var(--color-error)', color: '#fff' },
    lien: { background: 'transparent', color: 'var(--color-accent)' },
  };
  // L'anneau de focus (24/09/2026) : sans lui, un bouton focalisé au
  // clavier ne se distinguait de rien. L'accent est l'encre en ardéchine.
  const anneau = 'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]';
  const forme =
    variante === 'lien'
      ? `text-sm underline underline-offset-2 cursor-pointer disabled:opacity-50 disabled:cursor-default text-left rounded-sm ${anneau}`
      : `inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium cursor-pointer disabled:opacity-50 disabled:cursor-default ${anneau}`;
  return (
    <button type="button" {...reste} disabled={reste.disabled || occupe} className={`${forme} ${className}`} style={styles[variante]}>
      {occupe && <Loader2 size={14} className="animate-spin shrink-0" />}
      {children}
    </button>
  );
}

/**
 * Le champ relie son libellé par `htmlFor` au lieu d'envelopper la saisie.
 *
 * 24/09/2026 : le <label> englobait l'input ET le bouton œil du mot de
 * passe ; le nom accessible devenait « Mot de passe Afficher le mot de
 * passe ». L'identifiant passe à la saisie par ce contexte.
 */
const ContexteChamp = createContext<{ id: string; aideId?: string } | null>(null);

export function Champ({
  libelle,
  aide,
  children,
}: {
  libelle: string;
  aide?: ReactNode;
  children: ReactNode;
}) {
  const id = useId();
  const aideId = aide ? `${id}-aide` : undefined;
  return (
    <div className="flex flex-col gap-1.5 min-w-0">
      <label htmlFor={id} className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
        {libelle}
      </label>
      <ContexteChamp.Provider value={{ id, aideId }}>{children}</ContexteChamp.Provider>
      {aide && (
        <span id={aideId} className="text-xs leading-5" style={{ color: 'var(--color-text-tertiary)' }}>
          {aide}
        </span>
      )}
    </div>
  );
}

export function Saisie(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const champ = useContext(ContexteChamp);
  return (
    <input
      {...props}
      id={props.id ?? champ?.id}
      aria-describedby={props['aria-describedby'] ?? champ?.aideId}
      // Un anneau au focus (24/09/2026) : `outline-none` seul ne laissait
      // que le curseur, invisible dans un champ vide en VT323.
      className={`w-full min-w-0 px-3 py-2 rounded-lg text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)] ${props.className ?? ''}`}
      style={{ ...STYLE_CHAMP, ...(props.style ?? {}) }}
    />
  );
}

/**
 * Un mot de passe. Jamais dicté (§3.11) : `dictation_history.jsonl`
 * journalise le texte de la dictée de l'app, qui n'écrit que dans le
 * compositeur. Aucune correction ni capitale automatique : un mot de passe
 * « corrigé » ne rouvre plus rien.
 */
export function SaisieMotDePasse({
  valeur,
  onChange,
  nouveau = false,
  autoFocus,
  id,
  placeholder,
  nomAccessible,
}: {
  valeur: string;
  onChange: (v: string) => void;
  nouveau?: boolean;
  autoFocus?: boolean;
  id?: string;
  placeholder?: string;
  /** Hors d'un `Champ` (déverrouillage) : sans lui, le nom venait du seul placeholder. */
  nomAccessible?: string;
}) {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative min-w-0">
      <Saisie
        id={id}
        type={visible ? 'text' : 'password'}
        value={valeur}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={nouveau ? 'new-password' : 'current-password'}
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={false}
        autoFocus={autoFocus}
        placeholder={placeholder}
        aria-label={nomAccessible}
        style={{ paddingRight: '2.5rem' }}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={t('compte.mdp.afficher')}
        aria-pressed={visible}
        className="absolute right-1 top-1/2 -translate-y-1/2 w-8 h-8 flex items-center justify-center rounded-md cursor-pointer focus-visible:outline-2 focus-visible:outline-[var(--color-accent)]"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        {visible ? <EyeOff size={15} /> : <Eye size={15} />}
      </button>
    </div>
  );
}

export function MessageErreur({ erreur }: { erreur: ErreurLue | null }) {
  const { t } = useTranslation();
  if (!erreur) return null;
  const { cle, vars } = messageErreur(erreur);
  return (
    <div
      role="alert"
      className="flex items-start gap-2 px-3 py-2.5 rounded-xl text-sm"
      style={{
        background: 'color-mix(in srgb, var(--color-error) 10%, transparent)',
        border: '1px solid color-mix(in srgb, var(--color-error) 20%, transparent)',
        color: 'var(--color-error)',
      }}
    >
      <AlertTriangle size={15} className="shrink-0 mt-0.5" />
      <span style={{ overflowWrap: 'anywhere' }}>{t(cle, vars)}</span>
    </div>
  );
}

/** Le texte d'une rotation (§2.8), repris tel quel après chaque changement de secret. */
export function AvisRotation({ cle = 'compte.rotation.texte' }: { cle?: MessageKey }) {
  const { t } = useTranslation();
  return (
    <Encadre ton="ok" titre={t('compte.rotation.titre')}>
      {t(cle)}
    </Encadre>
  );
}

/** « Garder cet appareil déverrouillé » — décochée par défaut (D7), texte du §2.11. */
export function CaseMemoriser({
  statut,
  valeur,
  onChange,
}: {
  statut: StatutCompte;
  valeur: boolean;
  onChange: (v: boolean) => void;
}) {
  const { t } = useTranslation();
  const refus = statut.rememberAllowed ? null : motifRefusMemorisation(statut.rememberRefusal);
  return (
    <label className={`flex items-start gap-3 min-w-0 ${refus ? 'opacity-70' : 'cursor-pointer'}`}>
      <input
        type="checkbox"
        className="mt-1 shrink-0"
        checked={valeur && !refus}
        disabled={!!refus}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="flex flex-col gap-1 min-w-0">
        <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          {t('compte.memoriser.libelle')}
        </span>
        <span className="text-xs leading-5" style={{ color: 'var(--color-text-tertiary)' }}>
          {refus ? t(refus) : t(texteMemorisation(statut.protector))}
        </span>
      </span>
    </label>
  );
}

/** Les règles D5, cochées au fil de la frappe. */
export function ReglesMotDePasse({
  motDePasse,
  confirmation,
  courriel,
}: {
  motDePasse: string;
  confirmation: string;
  courriel: string | null;
}) {
  const { t } = useTranslation();
  const jugement = reglesMotDePasse(motDePasse, courriel, confirmation);
  const lignes: { ok: boolean; cle: MessageKey; vars?: Vars }[] = [
    { ok: !jugement.defauts.includes('tropCourt') && !jugement.defauts.includes('tropLong'), cle: 'compte.mdp.regle.longueur', vars: { count: jugement.longueur } },
    { ok: !jugement.defauts.includes('contientAdresse'), cle: 'compte.mdp.regle.adresse' },
    { ok: confirmation.length > 0 && !jugement.defauts.includes('differents'), cle: 'compte.mdp.regle.identiques' },
  ];
  // La liste n'est PAS une région vivante (24/09/2026) : sa première ligne
  // porte le compte des caractères, et un lecteur d'écran annonçait à chaque
  // frappe la longueur du mot de passe tapé. Seul le passage à « accepté »
  // est annoncé.
  return (
    <>
      <ul className="flex flex-col gap-1 text-xs">
        {lignes.map((l) => (
          <li key={l.cle} className="flex items-center gap-2" style={{ color: l.ok ? 'var(--color-success)' : 'var(--color-text-tertiary)' }}>
            {l.ok ? <Check size={12} className="shrink-0" /> : <span className="w-3 h-3 shrink-0 rounded-full" style={{ border: '1px solid currentColor' }} />}
            <span>{t(l.cle, l.vars)}</span>
          </li>
        ))}
      </ul>
      <span className="sr-only" aria-live="polite">
        {jugement.valide ? t('compte.mdp.reglesRespectees') : ''}
      </span>
    </>
  );
}

/**
 * La phrase de passe proposée (D5). Masquée tant que la liste de mots n'est
 * pas dans le dépôt (D6) : rien d'inventé.
 */
export function SuggestionPhrase({ onChoisir }: { onChoisir: (phrase: string) => void }) {
  const { t } = useTranslation();
  const [phrase, setPhrase] = useState<ReturnType<typeof genererPhrase>>(null);
  if (MOTS.length === 0) return null;
  return (
    <div className="flex flex-col gap-2 rounded-xl px-3 py-2.5" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          {t('compte.phrase.intro')}
        </span>
        <Bouton variante="lien" onClick={() => setPhrase(genererPhrase(MOTS))}>
          {phrase ? t('compte.phrase.autre') : t('compte.phrase.proposer')}
        </Bouton>
      </div>
      {phrase && (
        <>
          <code className="text-sm break-all select-all" style={{ fontFamily: 'var(--font-hud)', color: 'var(--color-text)' }}>
            {phrase.texte}
          </code>
          <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('compte.phrase.detail', { mots: phrase.mots, bits: phrase.bits })}
          </span>
          <Bouton variante="secondaire" onClick={() => onChoisir(phrase.texte)}>
            {t('compte.phrase.utiliser')}
          </Bouton>
        </>
      )}
    </div>
  );
}

/** Nouveau mot de passe, sa confirmation, ses règles et la suggestion. */
export function NouveauMotDePasse({
  motDePasse,
  confirmation,
  onMotDePasse,
  onConfirmation,
  courriel,
  libelle,
}: {
  motDePasse: string;
  confirmation: string;
  onMotDePasse: (v: string) => void;
  onConfirmation: (v: string) => void;
  courriel: string | null;
  libelle?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3">
      <Champ libelle={libelle ?? t('compte.mdp.nouveau')}>
        <SaisieMotDePasse valeur={motDePasse} onChange={onMotDePasse} nouveau />
      </Champ>
      <Champ libelle={t('compte.mdp.confirmation')}>
        <SaisieMotDePasse valeur={confirmation} onChange={onConfirmation} nouveau />
      </Champ>
      <ReglesMotDePasse motDePasse={motDePasse} confirmation={confirmation} courriel={courriel} />
      <SuggestionPhrase
        onChoisir={(p) => {
          onMotDePasse(p);
          onConfirmation(p);
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// La clé de récupération (§2.7) : montrée une fois, puis prouvée
// ---------------------------------------------------------------------------

/** `false` : l'impression n'a pas pu s'ouvrir — dit à l'écran, jamais tu. */
async function imprimerLaCle(): Promise<boolean> {
  const racine = document.documentElement;
  racine.setAttribute('data-impression-cle', '1');
  const retirer = () => {
    racine.removeAttribute('data-impression-cle');
    window.removeEventListener('afterprint', retirer);
  };
  window.addEventListener('afterprint', retirer);
  try {
    const rendu: unknown = (window.print as () => unknown)();
    if (rendu && typeof (rendu as PromiseLike<unknown>).then === 'function') {
      // 24/09/2026 : sous Tauri macOS, `print()` rend une promesse (invoke).
      // Retirer les règles d'impression avant qu'elle se règle imprimait la
      // fenêtre entière derrière la clé ; un refus passait sans un mot.
      await rendu;
      retirer();
    } else {
      // Dans un navigateur, `print()` bloque jusqu'à la fermeture de la
      // boîte ; `afterprint` n'arrive pas partout, d'où le filet.
      window.setTimeout(retirer, 1000);
    }
    return true;
  } catch {
    retirer();
    return false;
  }
}

export function BlocCle({
  cle,
  onConfirmer,
  onSansCle,
  libelleSansCle,
  occupe,
  erreur,
  avant,
}: {
  cle: CleMontree;
  onConfirmer: (extrait: [string, string]) => void;
  onSansCle?: () => void;
  libelleSansCle?: string;
  occupe: boolean;
  erreur: ErreurLue | null;
  avant?: ReactNode;
}) {
  const { t } = useTranslation();
  const [copiee, setCopiee] = useState(false);
  const [impressionEchouee, setImpressionEchouee] = useState(false);
  const [saisies, setSaisies] = useState<[string, string]>(['', '']);
  const [tentee, setTentee] = useState(false);
  const groupes = useMemo(() => groupesDeLaCle(cle.cle), [cle]);
  const concorde = extraitConcorde(cle.cle, cle.groupes, saisies);

  const copier = async () => {
    try {
      await navigator.clipboard.writeText(cle.cle);
      setCopiee(true);
      window.setTimeout(() => setCopiee(false), 2500);
    } catch {
      setCopiee(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {avant}
      <div className="impression-cle flex flex-col gap-3 rounded-xl p-4" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
        <div className="seulement-impression text-sm">{t('compte.cle.impressionTitre')}</div>
        <div className="flex items-center gap-2 text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          <KeyRound size={16} style={{ color: 'var(--color-accent)' }} />
          {t('compte.cle.titre')}
        </div>
        <div
          className="grid grid-cols-4 gap-2 select-all"
          aria-label={t('compte.cle.titre')}
          style={{ fontFamily: 'var(--font-hud)', color: 'var(--color-text)' }}
        >
          {groupes.map((g, i) => (
            <span key={i} className="flex flex-col items-center rounded-md py-1.5" style={{ background: 'var(--color-bg-secondary)' }}>
              <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
                {i + 1}
              </span>
              <span className="text-base tracking-wider">{g}</span>
            </span>
          ))}
        </div>
        <div className="seulement-impression text-xs">{t('compte.cle.impressionPied')}</div>
        <div className="masque-impression flex flex-wrap gap-2">
          <Bouton onClick={() => void copier()}>
            {copiee ? <Check size={14} /> : <Copy size={14} />}
            {copiee ? t('compte.cle.copiee') : t('compte.cle.copier')}
          </Bouton>
          {impressionDisponible(isTauri(), estMobile) && (
            <Bouton onClick={() => void imprimerLaCle().then((ok) => setImpressionEchouee(!ok))}>
              <Printer size={14} />
              {t('compte.cle.imprimer')}
            </Bouton>
          )}
        </div>
        {impressionEchouee && (
          <p role="alert" className="masque-impression text-xs" style={{ color: 'var(--color-error)' }}>
            {t('compte.cle.impressionEchec')}
          </p>
        )}
        <p className="masque-impression text-xs leading-5" style={{ color: 'var(--color-text-tertiary)' }}>
          {t('compte.cle.pressePapiers')}
        </p>
      </div>

      <Encadre ton="attente" titre={t('compte.cle.noterTitre')}>
        {t('compte.cle.noter')}
      </Encadre>

      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setTentee(true);
          if (concorde) onConfirmer(saisies);
        }}
      >
        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          {t('compte.cle.preuve', { a: cle.groupes[0], b: cle.groupes[1] })}
        </p>
        <div className="grid grid-cols-2 gap-3">
          {[0, 1].map((i) => (
            <Champ key={i} libelle={t('compte.cle.groupe', { n: cle.groupes[i] })}>
              <Saisie
                value={saisies[i]}
                onChange={(e) => {
                  const suivantes: [string, string] = [...saisies] as [string, string];
                  suivantes[i] = e.target.value;
                  setSaisies(suivantes);
                }}
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="characters"
                spellCheck={false}
                maxLength={8}
                style={{ fontFamily: 'var(--font-hud)', textTransform: 'uppercase' }}
              />
            </Champ>
          ))}
        </div>
        {tentee && !concorde && <MessageErreur erreur={{ code: 'recoveryExcerptMismatch' }} />}
        <MessageErreur erreur={erreur} />
        <Bouton type="submit" variante="principal" occupe={occupe}>
          {t('compte.cle.confirmer')}
        </Bouton>
        {onSansCle && (
          <Bouton variante="lien" onClick={onSansCle} disabled={occupe}>
            {libelleSansCle ?? t('compte.cle.sansCle')}
          </Bouton>
        )}
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Le déverrouillage — aussi dans le mini-panneau (D14)
// ---------------------------------------------------------------------------

export function FormulaireDeverrouillage({
  statut,
  avecMemorisation = true,
  compact = false,
  focus = false,
  onOubli,
  onConnexion,
}: {
  statut: StatutCompte;
  avecMemorisation?: boolean;
  compact?: boolean;
  /** Le curseur d'emblée — jamais dans le bandeau du mini-panneau, où il
   * volerait la frappe destinée au compositeur. */
  focus?: boolean;
  onOubli?: () => void;
  /** `/login` avec un nouveau mot de passe : le déverrouillage, hors ligne,
   * ne connaît que l'ancien (P4 chemin 2, P5 faits ailleurs). */
  onConnexion?: () => void;
}) {
  const { t } = useTranslation();
  const [motDePasse, setMotDePasse] = useState('');
  const [memoriser, setMemoriser] = useState(false);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<ErreurLue | null>(null);
  const envoyer = async () => {
    if (!motDePasse) return;
    setOccupe(true);
    setErreur(null);
    try {
      await deverrouiller(motDePasse, memoriser && statut.rememberAllowed);
      setMotDePasse('');
    } catch (e) {
      setErreur(estErreurCompte(e) ? e : { code: 'localServerUnreachable' });
    } finally {
      setOccupe(false);
    }
  };
  return (
    <form
      className={`flex flex-col ${compact ? 'gap-2' : 'gap-3'} min-w-0`}
      onSubmit={(e) => {
        e.preventDefault();
        void envoyer();
      }}
    >
      <div className="flex gap-2 min-w-0">
        <div className="flex-1 min-w-0">
          <SaisieMotDePasse
            valeur={motDePasse}
            onChange={setMotDePasse}
            placeholder={t('compte.mdp.saisir')}
            nomAccessible={t('compte.mdp.saisir')}
            autoFocus={focus}
          />
        </div>
        <Bouton type="submit" variante="principal" occupe={occupe} disabled={!motDePasse} className="shrink-0">
          <Lock size={14} className={occupe ? 'hidden' : ''} />
          <span className="hidden sm:inline">{t('compte.deverrouiller')}</span>
          <span className="sr-only sm:hidden">{t('compte.deverrouiller')}</span>
        </Bouton>
      </div>
      {avecMemorisation && <CaseMemoriser statut={statut} valeur={memoriser} onChange={setMemoriser} />}
      <MessageErreur erreur={erreur} />
      {onConnexion && erreur?.code === 'invalidPassword' && (
        <p className="text-xs leading-5 compact:hidden" style={{ color: 'var(--color-text-secondary)' }}>
          {t('compte.deverrouillage.changeAilleurs')}
        </p>
      )}
      {(onOubli || onConnexion) && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 compact:hidden">
          {onOubli && (
            <Bouton variante="lien" onClick={onOubli}>
              {t('compte.oubli.lien')}
            </Bouton>
          )}
          {onConnexion && (
            <Bouton variante="lien" onClick={onConnexion}>
              {t('compte.deverrouillage.connexion')}
            </Bouton>
          )}
        </div>
      )}
    </form>
  );
}

// ---------------------------------------------------------------------------
// Les étapes
// ---------------------------------------------------------------------------

interface Contexte {
  statut: StatutCompte;
  vue: EtatVue;
  allerA: (p: Partial<EtatVue>) => void;
  courriel: string;
  setCourriel: (v: string) => void;
  occupe: boolean;
  erreur: ErreurLue | null;
  agir: (f: () => Promise<void>) => Promise<boolean>;
  maintenant: number;
  enReglages: boolean;
}

function Titre({ children, sous }: { children: ReactNode; sous?: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h2 tabIndex={-1} className="text-lg font-semibold outline-none" style={{ color: 'var(--color-text)' }}>
        {children}
      </h2>
      {sous && (
        <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
          {sous}
        </p>
      )}
    </div>
  );
}

function Destination({ statut }: { statut: StatutCompte }) {
  const { t } = useTranslation();
  if (!statut.serverOrigin) return null;
  if (!statut.serverOriginAllowed) {
    return (
      <Encadre ton="danger" titre={t('compte.destination.refuseeTitre')}>
        {t('compte.destination.refusee', { origine: statut.serverOrigin })}
      </Encadre>
    );
  }
  return (
    <p className="text-xs leading-5" style={{ color: 'var(--color-text-tertiary)', overflowWrap: 'anywhere' }}>
      {t('compte.destination.nommee', { origine: statut.serverOrigin })}
    </p>
  );
}

function EtapeAccueil({ c, onPlusTard }: { c: Contexte; onPlusTard: () => void }) {
  const { t } = useTranslation();
  const bloque = destinationBloquee(c.statut);
  return (
    <div className="flex flex-col gap-5">
      <Titre sous={t('compte.accueil.texte')}>{t('compte.accueil.titre')}</Titre>
      <Encadre ton="neutre">{t('compte.accueil.serveurVoit')}</Encadre>
      <Destination statut={c.statut} />
      <div className="flex flex-col gap-2">
        <Bouton variante="principal" disabled={bloque} onClick={() => c.allerA({ parcours: 'inscription', inscription: 'adresse' })}>
          {t('compte.accueil.creer')}
        </Bouton>
        <Bouton disabled={bloque} onClick={() => c.allerA({ parcours: 'connexion' })}>
          {t('compte.accueil.connecter')}
        </Bouton>
        <Bouton variante="lien" className="self-center mt-1" onClick={onPlusTard}>
          {c.enReglages ? t('compte.fermer') : t('compte.accueil.plusTard')}
        </Bouton>
      </div>
    </div>
  );
}

function LiensLegaux({ statut }: { statut: StatutCompte }) {
  const { t } = useTranslation();
  if (!statut.serverOrigin) return null;
  const origine = statut.serverOrigin.replace(/\/+$/, '');
  return (
    <span className="inline-flex flex-wrap gap-x-3">
      <Bouton variante="lien" onClick={() => void ouvrirLienExterne(`${origine}/conditions`)}>
        {t('compte.adresse.conditions')}
      </Bouton>
      <Bouton variante="lien" onClick={() => void ouvrirLienExterne(`${origine}/confidentialite`)}>
        {t('compte.adresse.confidentialite')}
      </Bouton>
    </span>
  );
}

function EtapeAdresse({ c }: { c: Contexte }) {
  const { t } = useTranslation();
  const [conditions, setConditions] = useState(false);
  const [refus, setRefus] = useState<ReturnType<typeof blocageAdresse>>(null);
  const caseConditions = useRef<HTMLInputElement>(null);
  const bloque = destinationBloquee(c.statut);
  const expiree = inscriptionExpiree(c.statut, c.vue);
  const envoyer = () =>
    c.agir(async () => {
      await commencerInscription(c.courriel, conditions);
      c.allerA({ parcours: 'inscription', inscription: 'code' });
    });
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (bloque) return;
        const blocage = blocageAdresse(c.courriel, conditions);
        setRefus(blocage);
        // La case reçoit le focus : Espace la coche, Entrée renvoie — sans
        // souris, même là où Tab ne visite pas les cases (WKWebView).
        if (blocage === 'conditions') caseConditions.current?.focus();
        if (!blocage) void envoyer();
      }}
    >
      <Titre sous={t('compte.adresse.texte')}>{t('compte.adresse.titre')}</Titre>
      {expiree && <Encadre ton="attente">{t('compte.inscription.expiree')}</Encadre>}
      <Champ libelle={t('compte.adresse.courriel')}>
        <Saisie type="email" value={c.courriel} onChange={(e) => c.setCourriel(e.target.value)} autoComplete="email" autoFocus spellCheck={false} />
      </Champ>
      <label className="flex items-start gap-3 cursor-pointer">
        <input
          ref={caseConditions}
          type="checkbox"
          className="mt-1 shrink-0 focus-visible:outline-2 focus-visible:outline-[var(--color-accent)]"
          checked={conditions}
          onChange={(e) => {
            setConditions(e.target.checked);
            if (e.target.checked && refus === 'conditions') setRefus(null);
          }}
        />
        <span className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
          {t('compte.adresse.accepter')}
        </span>
      </label>
      <LiensLegaux statut={c.statut} />
      <Destination statut={c.statut} />
      {refus === 'conditions' && (
        <p role="alert" className="text-sm" style={{ color: 'var(--color-error)' }}>
          {t('compte.adresse.cocherConditions')}
        </p>
      )}
      {refus === 'adresse' && <MessageErreur erreur={{ code: 'emailInvalid' }} />}
      <MessageErreur erreur={c.erreur} />
      {/* Jamais grisé pour la case (24/09/2026) : un bouton d'envoi grisé
          annule l'envoi par Entrée, et le refus devenait muet. */}
      <Bouton type="submit" variante="principal" occupe={c.occupe} disabled={bloque}>
        {t('compte.adresse.envoyer')}
      </Bouton>
      <Bouton variante="lien" onClick={() => c.allerA({ parcours: 'accueil', inscription: undefined })}>
        {t('compte.retour')}
      </Bouton>
    </form>
  );
}

function EtapeCode({ c }: { c: Contexte }) {
  const { t } = useTranslation();
  const [code, setCode] = useState('');
  const propre = code.replace(/\s/g, '');
  const valide = /^\d{6}$/.test(propre);
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valide) return;
        void c.agir(async () => {
          await verifierCodeInscription(propre);
          c.allerA({ parcours: 'inscription', inscription: 'motDePasse' });
        });
      }}
    >
      <Titre sous={c.courriel ? t('compte.code.texte', { courriel: c.courriel }) : t('compte.code.texteSansAdresse')}>
        {t('compte.code.titre')}
      </Titre>
      <Champ libelle={t('compte.code.libelle')} aide={t('compte.code.aide')}>
        <Saisie
          value={code}
          onChange={(e) => setCode(e.target.value)}
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={7}
          autoFocus
          style={{ fontFamily: 'var(--font-hud)', letterSpacing: '0.2em' }}
        />
      </Champ>
      <MessageErreur erreur={c.erreur} />
      <Bouton type="submit" variante="principal" occupe={c.occupe} disabled={!valide}>
        {t('compte.code.verifier')}
      </Bouton>
      <Bouton variante="lien" onClick={() => c.allerA({ parcours: 'inscription', inscription: 'adresse' })}>
        {t('compte.code.recommencer')}
      </Bouton>
    </form>
  );
}

function EtapeMotDePasse({ c, onCle }: { c: Contexte; onCle: (cle: CleMontree) => void }) {
  const { t } = useTranslation();
  const [motDePasse, setMotDePasse] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [memoriser, setMemoriser] = useState(false);
  const valide = reglesMotDePasse(motDePasse, c.courriel || null, confirmation).valide;
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valide) return;
        void c.agir(async () => {
          const rendue = await preparerInscription(motDePasse, memoriser && c.statut.rememberAllowed);
          setMotDePasse('');
          setConfirmation('');
          onCle({ cle: rendue.cle, groupes: rendue.groupes, origine: 'inscription' });
        });
      }}
    >
      <Titre>{t('compte.mdp.titre')}</Titre>
      <Encadre ton="attente" titre={t('compte.mdp.encadreTitre')}>
        {t('compte.mdp.encadre')}
      </Encadre>
      <NouveauMotDePasse
        motDePasse={motDePasse}
        confirmation={confirmation}
        onMotDePasse={setMotDePasse}
        onConfirmation={setConfirmation}
        courriel={c.courriel || null}
        libelle={t('compte.mdp.libelle')}
      />
      <CaseMemoriser statut={c.statut} valeur={memoriser} onChange={setMemoriser} />
      <MessageErreur erreur={c.erreur} />
      <Bouton type="submit" variante="principal" occupe={c.occupe} disabled={!valide}>
        {t('compte.mdp.continuer')}
      </Bouton>
      {/* 24/09/2026 : sans Retour, un `/signup/prepare` qui échouait
          durablement (serveur injoignable, mémorisation refusée) laissait
          l'écran sans issue. */}
      <Bouton variante="lien" onClick={() => c.allerA({ parcours: 'inscription', inscription: 'adresse' })}>
        {t('compte.retour')}
      </Bouton>
    </form>
  );
}

function EtapeConsentement({ c }: { c: Contexte }) {
  const { t } = useTranslation();
  const n = c.statut.localConversations ?? 0;
  return (
    <div className="flex flex-col gap-4">
      <Titre sous={t('compte.consentement.texte', { count: n })}>{t('compte.consentement.titre')}</Titre>
      <Encadre ton="neutre">{t('compte.synchro.pasEncore')}</Encadre>
      <MessageErreur erreur={c.erreur} />
      <Bouton variante="principal" occupe={c.occupe} onClick={() => void c.agir(async () => void (await consentir()))}>
        {t('compte.consentement.ajouter')}
      </Bouton>
      <Bouton occupe={c.occupe} onClick={() => void c.agir(async () => void (await seDeconnecter()))}>
        {t('compte.consentement.annuler')}
      </Bouton>
    </div>
  );
}

function LigneSecours({ statut }: { statut: StatutCompte }) {
  const { t } = useTranslation();
  const moyens = moyensDeSecours(statut);
  if (!moyens) return null;
  if (moyens.avertir) {
    return (
      <Encadre ton="danger" titre={t('compte.secours.aucunTitre')}>
        {t(texteAucunSecours(statut))}
      </Encadre>
    );
  }
  return (
    <Encadre ton="ok" titre={t('compte.secours.titre', { count: moyens.total })}>
      <ul className="flex flex-col gap-0.5">
        {moyens.cle && <li>{t('compte.secours.cle')}</li>}
        {moyens.cetAppareil && <li>{t('compte.secours.cetAppareil')}</li>}
      </ul>
      <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
        {t('compte.secours.autresAppareils')}
      </p>
    </Encadre>
  );
}

export { LigneSecours };

function EtapeSynchro({ c }: { c: Contexte }) {
  const { t, locale } = useTranslation();
  const libelle = libelleSynchro(c.statut.sync, c.maintenant, locale);
  return (
    <div className="flex flex-col gap-4">
      <Titre sous={t('compte.synchro.contenu')}>{t('compte.synchro.titre')}</Titre>
      <Encadre ton="neutre" titre={t('compte.synchro.resteIciTitre')}>
        {t('compte.synchro.resteIci')}
      </Encadre>
      {/* Sans moteur (étape 8), « inactive » et « pas encore active » disent
          la même chose : une seule phrase, la plus complète. */}
      <Encadre ton="attente">
        {c.statut.sync.state === 'disabled' ? t('compte.synchro.pasEncore') : t(libelle.cle, libelle.vars)}
      </Encadre>
      <Bouton variante="principal" onClick={() => c.allerA({ synchroVue: true })}>
        {t('compte.synchro.compris')}
      </Bouton>
    </div>
  );
}

function EtapeTermine({ c, onFin }: { c: Contexte; onFin: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-4">
      <Titre sous={c.statut.email ? t('compte.termine.texte', { courriel: c.statut.email }) : undefined}>
        {t('compte.termine.titre')}
      </Titre>
      <LigneSecours statut={c.statut} />
      <Bouton variante="principal" onClick={onFin}>
        {c.enReglages ? t('compte.fermer') : t('compte.termine.continuer')}
      </Bouton>
    </div>
  );
}

function EtapeConnexion({ c, entete }: { c: Contexte; entete?: ReactNode }) {
  const { t } = useTranslation();
  const [motDePasse, setMotDePasse] = useState('');
  const [memoriser, setMemoriser] = useState(false);
  const bloque = destinationBloquee(c.statut);
  const valide = courrielValide(c.courriel) && motDePasse.length > 0;
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valide || bloque) return;
        void c.agir(async () => {
          await connecter(c.courriel, motDePasse, memoriser && c.statut.rememberAllowed);
          setMotDePasse('');
        });
      }}
    >
      {entete ?? <Titre sous={t('compte.connexion.texte')}>{t('compte.connexion.titre')}</Titre>}
      <Champ libelle={t('compte.adresse.courriel')}>
        <Saisie type="email" value={c.courriel} onChange={(e) => c.setCourriel(e.target.value)} autoComplete="username" spellCheck={false} />
      </Champ>
      <Champ libelle={t('compte.mdp.libelleActuel')}>
        <SaisieMotDePasse valeur={motDePasse} onChange={setMotDePasse} autoFocus={!!c.courriel} />
      </Champ>
      <CaseMemoriser statut={c.statut} valeur={memoriser} onChange={setMemoriser} />
      <Destination statut={c.statut} />
      <MessageErreur erreur={c.erreur} />
      <Bouton type="submit" variante="principal" occupe={c.occupe} disabled={!valide || bloque}>
        {t('compte.connexion.envoyer')}
      </Bouton>
      <Bouton variante="lien" onClick={() => c.allerA({ parcours: 'oubli' })}>
        {t('compte.oubli.lien')}
      </Bouton>
      {(c.statut.state === 'none' || c.statut.state === 'locked') && (
        <Bouton variante="lien" onClick={() => c.allerA({ parcours: 'accueil' })}>
          {t('compte.retour')}
        </Bouton>
      )}
    </form>
  );
}

function AvisReinitialisationEchue({ c }: { c: Contexte }) {
  const { t, locale } = useTranslation();
  if (c.statut.pendingResetAt === null || c.statut.pendingResetAt > c.maintenant) return null;
  return (
    <Encadre ton="attente" titre={t('compte.reinit.echueTitre')}>
      <p>{t('compte.reinit.echue', { date: formaterDate(c.statut.pendingResetAt, locale) })}</p>
      <Bouton variante="lien" onClick={() => c.allerA({ parcours: 'reinitialisation' })}>
        {t('compte.reinit.terminerLien')}
      </Bouton>
    </Encadre>
  );
}

function EtapeDeverrouillage({ c }: { c: Contexte }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-4">
      <Titre sous={c.statut.email ? t('compte.deverrouillage.texte', { courriel: c.statut.email }) : undefined}>
        {t('compte.deverrouillage.titre')}
      </Titre>
      <AvisReinitialisationEchue c={c} />
      <FormulaireDeverrouillage
        statut={c.statut}
        focus
        onOubli={() => c.allerA({ parcours: 'oubli' })}
        onConnexion={() => c.allerA({ parcours: 'connexion' })}
      />
    </div>
  );
}

function EtapeOubli({ c }: { c: Contexte }) {
  const { t } = useTranslation();
  const [chemin, setChemin] = useState<'appareil' | 'rien' | null>(null);
  // Depuis un appareil qui n'a jamais ouvert ce compte, `reset/*` répond
  // `resetNeedsKnownAccount` (écart de l'étape 8) : l'écran le dit ICI,
  // au lieu de laisser attendre un code puis échouer au bout.
  const compteConnu = c.statut.state !== 'none' && c.statut.state !== 'signupInProgress' && !!c.statut.email;
  // Sans compte ici, on revient à la connexion ; avec, à l'étape que l'état
  // commande (déverrouillage, reconnexion…).
  const retour: Parcours = compteConnu ? 'accueil' : 'connexion';
  return (
    <div className="flex flex-col gap-4">
      <Titre sous={t('compte.oubli.texte')}>{t('compte.oubli.titre')}</Titre>
      <Bouton variante="principal" onClick={() => c.allerA({ parcours: 'recuperation' })}>
        <KeyRound size={14} />
        {t('compte.oubli.cle')}
      </Bouton>
      <Bouton onClick={() => setChemin(chemin === 'appareil' ? null : 'appareil')}>{t('compte.oubli.appareil')}</Bouton>
      {chemin === 'appareil' && (
        <Encadre ton="info">
          <p>{t('compte.oubli.appareilMarche')}</p>
          {/* Le texte dit « revenez ici vous connecter » : le lien y mène
              (24/09/2026 — il n'existait pas sur un appareil verrouillé). */}
          <Bouton variante="lien" className="mt-2" onClick={() => c.allerA({ parcours: 'connexion' })}>
            {t('compte.deverrouillage.connexion')}
          </Bouton>
        </Encadre>
      )}
      <Bouton onClick={() => setChemin(chemin === 'rien' ? null : 'rien')}>{t('compte.oubli.rien')}</Bouton>
      {chemin === 'rien' && (
        <Encadre ton="danger" titre={t('compte.oubli.rienTitre')}>
          <p>{t('compte.oubli.rienTexte')}</p>
          {compteConnu ? (
            <Bouton variante="danger" className="mt-3" onClick={() => c.allerA({ parcours: 'reinitialisation' })}>
              {t('compte.oubli.reinitialiser')}
            </Bouton>
          ) : (
            <p className="mt-2">{t('compte.oubli.appareilInconnu')}</p>
          )}
        </Encadre>
      )}
      <Bouton variante="lien" onClick={() => c.allerA({ parcours: retour })}>
        {t('compte.retour')}
      </Bouton>
    </div>
  );
}

function EtapeRecuperation({ c, onCle }: { c: Contexte; onCle: (cle: CleMontree) => void }) {
  const { t } = useTranslation();
  const [cle, setCle] = useState('');
  const [motDePasse, setMotDePasse] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [memoriser, setMemoriser] = useState(false);
  const [garder, setGarder] = useState(false);
  const forme = formeCle(cle);
  const bloque = destinationBloquee(c.statut);
  const valide =
    courrielValide(c.courriel) && forme === 'complete' && reglesMotDePasse(motDePasse, c.courriel, confirmation).valide;
  const aideCle: Record<typeof forme, MessageKey> = {
    vide: 'compte.recup.cleAide',
    incomplete: 'compte.recup.cleIncomplete',
    caractereInconnu: 'compte.recup.cleCaractere',
    tropLongue: 'compte.recup.cleTropLongue',
    complete: 'compte.recup.cleComplete',
  };
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valide || bloque) return;
        void c.agir(async () => {
          const neuve = await recuperer({
            email: c.courriel,
            recoveryKey: cle,
            newPassword: motDePasse,
            remember: memoriser && c.statut.rememberAllowed,
            keepRecoveryKey: garder,
          });
          setCle('');
          setMotDePasse('');
          setConfirmation('');
          if (neuve) onCle({ cle: neuve.cle, groupes: neuve.groupes, origine: 'remplacement' });
        });
      }}
    >
      <Titre sous={t('compte.recup.texte')}>{t('compte.recup.titre')}</Titre>
      {c.statut.state === 'serverRolledBack' && <Encadre ton="attente">{t('compte.retourArriere.recup')}</Encadre>}
      <Champ libelle={t('compte.adresse.courriel')}>
        <Saisie type="email" value={c.courriel} onChange={(e) => c.setCourriel(e.target.value)} autoComplete="username" spellCheck={false} />
      </Champ>
      <Champ libelle={t('compte.recup.cle')} aide={t(aideCle[forme])}>
        <Saisie
          value={cle}
          onChange={(e) => setCle(e.target.value)}
          onBlur={() => forme === 'complete' && setCle(mettreEnGroupes(cle))}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="characters"
          spellCheck={false}
          style={{ fontFamily: 'var(--font-hud)', textTransform: 'uppercase' }}
        />
      </Champ>
      <NouveauMotDePasse
        motDePasse={motDePasse}
        confirmation={confirmation}
        onMotDePasse={setMotDePasse}
        onConfirmation={setConfirmation}
        courriel={c.courriel || null}
      />
      <CaseMemoriser statut={c.statut} valeur={memoriser} onChange={setMemoriser} />
      <label className="flex items-start gap-3 cursor-pointer">
        <input type="checkbox" className="mt-1 shrink-0" checked={garder} onChange={(e) => setGarder(e.target.checked)} />
        <span className="flex flex-col gap-1">
          <span className="text-sm" style={{ color: 'var(--color-text)' }}>
            {t('compte.recup.garder')}
          </span>
          <span className="text-xs leading-5" style={{ color: garder ? 'var(--color-error)' : 'var(--color-text-tertiary)' }}>
            {garder ? t('compte.recup.garderDanger') : t('compte.recup.remplacerDefaut')}
          </span>
        </span>
      </label>
      <Encadre ton="neutre">{t('compte.rotation.texte')}</Encadre>
      {/* Depuis un appareil neuf, `/recover` est le premier geste qui joint
          le serveur : l'écran nomme la destination (§3.12, condition 2). */}
      <Destination statut={c.statut} />
      <MessageErreur erreur={c.erreur} />
      <Bouton type="submit" variante="principal" occupe={c.occupe} disabled={!valide || bloque}>
        {t('compte.recup.envoyer')}
      </Bouton>
      <Bouton variante="lien" onClick={() => c.allerA({ parcours: 'oubli' })}>
        {t('compte.retour')}
      </Bouton>
    </form>
  );
}

function EtapeReinitialisation({ c, onCle }: { c: Contexte; onCle: (cle: CleMontree) => void }) {
  const { t, locale } = useTranslation();
  const confirmer = useConfirm();
  const [code, setCode] = useState('');
  const [codeEnvoye, setCodeEnvoye] = useState(false);
  const [motDePasse, setMotDePasse] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [memoriser, setMemoriser] = useState(false);
  const etape = etapeReinitialisation(c.statut.pendingResetAt, c.maintenant);
  const email = c.statut.email ?? c.courriel;
  const codePropre = code.replace(/\s/g, '');
  const codeValide = /^\d{6}$/.test(codePropre);
  const bloque = destinationBloquee(c.statut);

  if (etape === 'attente' && c.statut.pendingResetAt !== null) {
    return (
      <div className="flex flex-col gap-4">
        <Titre sous={t('compte.reinit.attente', { date: formaterDate(c.statut.pendingResetAt, locale) })}>
          {t('compte.reinit.titre')}
        </Titre>
        <MessageErreur erreur={c.erreur} />
        <Bouton occupe={c.occupe} onClick={() => void c.agir(async () => void (await reinitAnnuler()))}>
          {t('compte.reinit.annuler')}
        </Bouton>
      </div>
    );
  }

  const demanderCode = () =>
    c.agir(async () => {
      await reinitDemander(email);
      setCodeEnvoye(true);
    });

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!codeValide || bloque) return;
        if (etape === 'programmer') {
          void (async () => {
            const ok = await confirmer({
              title: t('compte.reinit.confirmerTitre'),
              description: t('compte.oubli.rienTexte'),
              confirmLabel: t('compte.reinit.programmer'),
              keepLabel: t('compte.garder'),
              tone: 'danger',
            });
            if (!ok) return;
            await c.agir(async () => {
              await reinitConfirmer(email, codePropre);
              setCode('');
            });
          })();
          return;
        }
        if (!reglesMotDePasse(motDePasse, email, confirmation).valide) return;
        void c.agir(async () => {
          const neuve = await reinitTerminer(email, codePropre, motDePasse, memoriser && c.statut.rememberAllowed);
          setCode('');
          setMotDePasse('');
          setConfirmation('');
          if (neuve) onCle({ cle: neuve.cle, groupes: neuve.groupes, origine: 'remplacement' });
        });
      }}
    >
      <Titre sous={etape === 'programmer' ? t('compte.reinit.programmerTexte') : t('compte.reinit.terminerTexte')}>
        {t('compte.reinit.titre')}
      </Titre>
      <Encadre ton="danger">{t('compte.oubli.rienTexte')}</Encadre>
      <p className="text-sm" style={{ color: 'var(--color-text-secondary)', overflowWrap: 'anywhere' }}>
        {t('compte.reinit.adresse', { courriel: email })}
      </p>
      <Destination statut={c.statut} />
      <Bouton occupe={c.occupe && !codeEnvoye} onClick={() => void demanderCode()} disabled={!courrielValide(email) || bloque}>
        {codeEnvoye ? t('compte.reinit.renvoyer') : t('compte.reinit.envoyerCode')}
      </Bouton>
      {codeEnvoye && <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{t('compte.reinit.codeEnvoye')}</p>}
      <Champ libelle={t('compte.code.libelle')}>
        <Saisie
          value={code}
          onChange={(e) => setCode(e.target.value)}
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={7}
          style={{ fontFamily: 'var(--font-hud)', letterSpacing: '0.2em' }}
        />
      </Champ>
      {etape === 'terminer' && (
        <>
          <NouveauMotDePasse
            motDePasse={motDePasse}
            confirmation={confirmation}
            onMotDePasse={setMotDePasse}
            onConfirmation={setConfirmation}
            courriel={email}
          />
          <CaseMemoriser statut={c.statut} valeur={memoriser} onChange={setMemoriser} />
        </>
      )}
      <MessageErreur erreur={c.erreur} />
      <Bouton
        type="submit"
        variante="danger"
        occupe={c.occupe}
        disabled={bloque || !codeValide || (etape === 'terminer' && !reglesMotDePasse(motDePasse, email, confirmation).valide)}
      >
        {etape === 'programmer' ? t('compte.reinit.programmer') : t('compte.reinit.terminer')}
      </Bouton>
      <Bouton variante="lien" onClick={() => c.allerA({ parcours: 'oubli' })}>
        {t('compte.retour')}
      </Bouton>
    </form>
  );
}

function EtapeReinitPrevue({ c }: { c: Contexte }) {
  const { t, locale } = useTranslation();
  const date = c.statut.pendingResetAt !== null ? formaterDate(c.statut.pendingResetAt, locale) : null;
  return (
    <div className="flex flex-col gap-4">
      <Titre>{t('compte.reinit.prevueTitre')}</Titre>
      <Encadre ton="danger">{date ? t('compte.reinit.prevue', { date }) : t('compte.bandeau.reinitPrevueSansDate')}</Encadre>
      <MessageErreur erreur={c.erreur} />
      <Bouton variante="principal" occupe={c.occupe} onClick={() => void c.agir(async () => void (await reinitAnnuler()))}>
        {t('compte.reinit.annuler')}
      </Bouton>
      {!c.statut.unlocked && <FormulaireDeverrouillage statut={c.statut} />}
    </div>
  );
}

function EtapeCleNeuve({
  c,
  cle,
  onFini,
}: {
  c: Contexte;
  cle: CleMontree;
  onFini: () => void;
}) {
  const { t } = useTranslation();
  const confirmer = useConfirm();
  const sansCle = async () => {
    // Après `reset/complete`, le coffre neuf n'a AUCUNE clé de récupération ;
    // après `/recover`, l'ancienne reste valable jusqu'à la confirmation.
    const aucune = !c.statut.recoveryConfigured;
    const ok = await confirmer({
      title: t('compte.cle.plusTardTitre'),
      description: aucune ? t('compte.cle.plusTardAucune') : t('compte.cle.plusTardAncienne'),
      confirmLabel: t('compte.cle.plusTard'),
      keepLabel: t('compte.retour'),
      tone: aucune ? 'danger' : 'warning',
    });
    if (ok) onFini();
  };
  return (
    <BlocCle
      cle={cle}
      occupe={c.occupe}
      erreur={c.erreur}
      avant={
        <>
          <Titre sous={t('compte.cle.neuveTexte')}>{t('compte.cle.neuveTitre')}</Titre>
          <AvisRotation />
        </>
      }
      onConfirmer={(extrait) =>
        void c.agir(async () => {
          await confirmerCle(extrait);
          onFini();
        })
      }
      onSansCle={() => void sansCle()}
      libelleSansCle={t('compte.cle.plusTard')}
    />
  );
}

// ---------------------------------------------------------------------------
// L'écran
// ---------------------------------------------------------------------------

const FOCALISABLES =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Les éléments atteignables au clavier dans `racine`, visibles, dans l'ordre du document. */
function focalisables(racine: HTMLElement): HTMLElement[] {
  return Array.from(racine.querySelectorAll<HTMLElement>(FOCALISABLES)).filter((el) => el.getClientRects().length > 0);
}

export function EcranCompte({
  contexte,
  onFermer,
  parcoursInitial = 'accueil',
}: {
  /** `accueil` : plein écran, une fois après l'installation (D13). `reglages` : en voile. */
  contexte: 'accueil' | 'reglages';
  onFermer: () => void;
  parcoursInitial?: Parcours;
}) {
  const { t, locale } = useTranslation();
  const confirmer = useConfirm();
  const { statut, illisible, erreur: erreurStatut, lu, relire } = useStatutCompte(30000);
  const [vue, setVue] = useState<EtatVue>({ parcours: parcoursInitial });
  const [courriel, setCourriel] = useState('');
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<ErreurLue | null>(null);
  const [maintenant, setMaintenant] = useState(() => Date.now());
  const enReglages = contexte === 'reglages';

  useEffect(() => {
    const minuteur = window.setInterval(() => setMaintenant(Date.now()), 30000);
    return () => window.clearInterval(minuteur);
  }, []);

  // L'adresse du compte connu pré-remplit les champs ; jamais l'inverse.
  useEffect(() => {
    if (statut?.email && !courriel) setCourriel(statut.email);
  }, [statut?.email]); // eslint-disable-line react-hooks/exhaustive-deps

  const allerA = useCallback((p: Partial<EtatVue>) => {
    setErreur(null);
    setVue((v) => ({ ...v, ...p }));
  }, []);

  const agir = useCallback(
    async (f: () => Promise<void>) => {
      setOccupe(true);
      setErreur(null);
      try {
        await f();
        return true;
      } catch (e) {
        setErreur(estErreurCompte(e) ? e : { code: 'localServerUnreachable' });
        // Un refus peut avoir posé un état (sessionExpired, serverRolledBack…) :
        // l'étape suit le serveur, pas ce que la vue croyait.
        relire();
        return false;
      } finally {
        setOccupe(false);
      }
    },
    [relire],
  );

  const fermer = useCallback(async () => {
    if (!enReglages) {
      // Le drapeau vit dans compte/accueil.json, jamais dans le
      // localStorage (§3.11 P1) : fenêtre et mini-panneau ne le partagent
      // pas. S'il ne s'écrit pas, l'écran reviendra au prochain lancement —
      // ce qui est vrai, plutôt que de le dire vu.
      try {
        await accueilTermine();
      } catch {
        /* reviendra au prochain lancement */
      }
    }
    onFermer();
  }, [enReglages, onFermer]);

  const etape = etapeActivation(illisible ? 'illisible' : statut, vue);

  // Une clé d'inscription que le serveur local a oubliée (expiration,
  // redémarrage) ne vaut plus rien : la garder masquait la croix et
  // neutralisait Échap sur une étape sans issue (24/09/2026).
  const expiree = inscriptionExpiree(statut, vue);
  useEffect(() => {
    if (expiree && vue.cle) allerA({ cle: null });
  }, [expiree, vue.cle, allerA]);

  // Échap — consommé : le script natif du mini-panneau lit
  // `defaultPrevented` (même règle que ConfirmDialog, 17 sept. 2026). La
  // décision vit dans `actionEchap` (lib/compte.ts).
  const voileRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const touche = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const autreModale = Array.from(document.querySelectorAll('[aria-modal="true"]')).some(
        (el) => el !== voileRef.current,
      );
      const action = actionEchap({
        contexte,
        cleAffichee: !!vue.cle,
        autreModale,
        dejaConsomme: e.defaultPrevented,
        etape,
      });
      if (!action) return;
      e.preventDefault();
      if (action === 'fermer') onFermer();
      else void fermer();
    };
    window.addEventListener('keydown', touche);
    return () => window.removeEventListener('keydown', touche);
  }, [contexte, onFermer, fermer, vue.cle, etape]);

  // Le focus (24/09/2026) : à chaque étape, il entre dans la carte s'il n'y
  // est pas déjà (un `autoFocus` d'étape garde la main) ; à la fermeture, il
  // revient d'où il venait. Sans cela, l'envoi d'un formulaire démontait le
  // champ focalisé, le focus retombait sur <body>, et Tab parcourait la
  // barre latérale et les Réglages cachés sous le voile avant d'y revenir.
  const carteRef = useRef<HTMLDivElement>(null);
  const boiteRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const avant = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      if (avant && document.contains(avant)) avant.focus();
    };
  }, []);
  useEffect(() => {
    const carte = carteRef.current;
    if (!carte || carte.contains(document.activeElement)) return;
    const [premier] = focalisables(carte);
    (premier ?? carte.querySelector<HTMLElement>('h2'))?.focus();
  }, [etape, !!statut]); // eslint-disable-line react-hooks/exhaustive-deps

  // Tab boucle dans la carte, boutons compris : WKWebView, avec les
  // réglages macOS par défaut, ne visite au Tab que les champs texte — et
  // l'écran d'accueil n'a que des boutons (§82).
  const boucleTab = (e: React.KeyboardEvent) => {
    if (e.key !== 'Tab' || !boiteRef.current) return;
    const liste = focalisables(boiteRef.current);
    const suivant = indiceFocusSuivant(liste.length, liste.indexOf(document.activeElement as HTMLElement), e.shiftKey);
    if (suivant < 0) return;
    e.preventDefault();
    liste[suivant].focus();
  };

  // Ouvert depuis le bandeau ou les Réglages pour un compte qui existe déjà
  // (déverrouiller, se reconnecter), le voile se referme une fois le compte
  // rouvert : « Ce qui se synchronise » et « Votre compte est prêt » sont
  // les étapes d'une INSCRIPTION, pas d'un déverrouillage.
  const etatALOuverture = useRef<string | null>(null);
  if (statut && etatALOuverture.current === null) etatALOuverture.current = statut.state;
  const compteDejaLa =
    etatALOuverture.current !== null && etatALOuverture.current !== 'none' && etatALOuverture.current !== 'signupInProgress';
  useEffect(() => {
    if (!enReglages || !compteDejaLa) return;
    if (etape === 'synchro' || etape === 'termine') onFermer();
  }, [enReglages, compteDejaLa, etape, onFermer]);

  const c: Contexte | null = statut
    ? { statut, vue, allerA, courriel, setCourriel, occupe, erreur, agir, maintenant, enReglages }
    : null;
  const montrerCle = (cle: CleMontree) => allerA({ cle });

  const sansCleInscription = async () => {
    const ok = await confirmer({
      title: t('compte.cle.sansCleTitre'),
      description: t('compte.cle.sansCleTexte'),
      confirmLabel: t('compte.cle.sansCleConfirmer'),
      keepLabel: t('compte.retour'),
      tone: 'danger',
    });
    if (!ok) return;
    await agir(async () => {
      await terminerInscription({ skipRecovery: true });
      allerA({ cle: null, synchroVue: false, inscription: undefined });
    });
  };

  // Sans statut lisible, l'écran a son propre « Plus tard » : pas de second.
  const blocIllisible = !c && lu && (illisible || !!erreurStatut);
  let contenu: ReactNode;
  if (!c) {
    contenu =
      blocIllisible ? (
        <div className="flex flex-col gap-4">
          <Titre>{t('compte.illisible.titre')}</Titre>
          <MessageErreur erreur={erreurStatut ?? { code: 'responseUnreadable' }} />
          <Bouton onClick={relire}>{t('compte.reessayer')}</Bouton>
          <Bouton variante="lien" onClick={() => void fermer()}>
            {enReglages ? t('compte.fermer') : t('compte.accueil.plusTard')}
          </Bouton>
        </div>
      ) : (
        <div role="status" className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          <Loader2 size={16} className="animate-spin" /> {t('compte.chargement')}
        </div>
      );
  } else {
    switch (etape) {
      case 'accueil':
        contenu = <EtapeAccueil c={c} onPlusTard={() => void fermer()} />;
        break;
      case 'adresse':
        contenu = <EtapeAdresse c={c} />;
        break;
      case 'code':
        contenu = <EtapeCode c={c} />;
        break;
      case 'motDePasse':
        contenu = <EtapeMotDePasse c={c} onCle={montrerCle} />;
        break;
      case 'cle':
        contenu = vue.cle ? (
          <BlocCle
            cle={vue.cle}
            occupe={occupe}
            erreur={erreur}
            avant={<Titre sous={t('compte.cle.texte')}>{t('compte.cle.etapeTitre')}</Titre>}
            onConfirmer={(extrait) =>
              void agir(async () => {
                await terminerInscription({ recoveryExcerpt: extrait });
                allerA({ cle: null, synchroVue: false, inscription: undefined });
              })
            }
            onSansCle={() => void sansCleInscription()}
          />
        ) : null;
        break;
      case 'nouvelleCle':
        contenu = vue.cle ? <EtapeCleNeuve c={c} cle={vue.cle} onFini={() => allerA({ cle: null })} /> : null;
        break;
      case 'consentement':
        contenu = <EtapeConsentement c={c} />;
        break;
      case 'synchro':
        contenu = <EtapeSynchro c={c} />;
        break;
      case 'termine':
        contenu = <EtapeTermine c={c} onFin={() => void fermer()} />;
        break;
      case 'connexion':
        contenu = (
          <EtapeConnexion
            c={c}
            entete={
              c.statut.state === 'sessionExpired' ? (
                <Titre sous={t('compte.sessionExpiree.texte')}>{t('compte.sessionExpiree.titre')}</Titre>
              ) : undefined
            }
          />
        );
        break;
      case 'compteReinitialise':
        contenu = (
          <EtapeConnexion c={c} entete={<Titre sous={t('compte.compteReinitialise.texte')}>{t('compte.compteReinitialise.titre')}</Titre>} />
        );
        break;
      case 'retourArriere':
        contenu = (
          <div className="flex flex-col gap-4">
            <EtapeConnexion
              c={c}
              entete={
                <Titre
                  sous={
                    c.statut.lastKeyChangeAt !== null
                      ? t('compte.retourArriere.texte', { date: formaterDate(c.statut.lastKeyChangeAt, locale) })
                      : t('compte.retourArriere.texteSansDate')
                  }
                >
                  {t('compte.retourArriere.titre')}
                </Titre>
              }
            />
            <Bouton variante="lien" onClick={() => allerA({ parcours: 'recuperation' })}>
              {t('compte.oubli.cle')}
            </Bouton>
          </div>
        );
        break;
      case 'serveurPerdu':
        contenu = (
          <div className="flex flex-col gap-4">
            <Titre sous={t('compte.serveurPerdu.texte')}>{t('compte.serveurPerdu.titre')}</Titre>
            <Bouton variante="principal" onClick={() => allerA({ parcours: 'inscription', inscription: 'adresse' })}>
              {t('compte.serveurPerdu.recreer')}
            </Bouton>
          </div>
        );
        break;
      case 'deverrouillage':
        contenu = <EtapeDeverrouillage c={c} />;
        break;
      case 'oubli':
        contenu = <EtapeOubli c={c} />;
        break;
      case 'recuperation':
        contenu = <EtapeRecuperation c={c} onCle={montrerCle} />;
        break;
      case 'reinitialisation':
        contenu = <EtapeReinitialisation c={c} onCle={montrerCle} />;
        break;
      case 'reinitPrevue':
        contenu = <EtapeReinitPrevue c={c} />;
        break;
      case 'fermee':
        // 24/09/2026 : aucun parcours n'est proposé tant que les comptes ne
        // sont pas ouverts — chacun échouerait au premier appel réseau.
        contenu = (
          <div className="flex flex-col gap-4">
            <Titre sous={t('compte.fermee.texte')}>{t('compte.fermee.titre')}</Titre>
            <Bouton variante="principal" onClick={() => void fermer()}>
              {t('compte.fermer')}
            </Bouton>
          </div>
        );
        break;
      default:
        contenu = null;
    }
  }

  const carte = (
    <div ref={carteRef} className="flex flex-col gap-6 w-full">
      {contenu}
      {erreurStatut && c && (
        <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {t('compte.statutPerime')}
        </p>
      )}
      {/* D13 : une sortie à chaque étape du plein écran (sortieAccueil). */}
      {!enReglages && !blocIllisible && sortieAccueil(etape) && (
        <Bouton variante="lien" className="self-center" onClick={() => void fermer()}>
          {t('compte.accueil.plusTard')}
        </Bouton>
      )}
    </div>
  );

  if (enReglages) {
    // Rendu sur <body> (24/09/2026) : dans la section des Réglages, le voile
    // restait pris dans le contexte d'empilement `relative z-10` de Layout,
    // et la cloche (`fixed z-40`, contexte racine) se peignait par-dessus
    // lui, jusque sur la croix en fenêtre étroite.
    return createPortal(
      <div
        ref={voileRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('compte.section.titre')}
        className="voile-modal z-50 overflow-y-auto backdrop-blur-md"
        style={{ background: 'color-mix(in srgb, #000 55%, transparent)' }}
        onKeyDown={boucleTab}
        onClick={() => {
          if (!vue.cle) onFermer();
        }}
      >
        <div className="min-h-full flex items-start sm:items-center justify-center p-4 sm:p-6" style={{ paddingTop: 'calc(var(--surplomb-panneau, 0px) + 1rem)' }}>
          <div
            ref={boiteRef}
            onClick={(e) => e.stopPropagation()}
            className="relative w-full max-w-md rounded-2xl p-5 sm:p-6"
            style={{
              background: 'color-mix(in srgb, var(--color-surface) 96%, transparent)',
              border: '1px solid var(--color-border)',
              boxShadow: '0 24px 60px rgba(0,0,0,0.45)',
            }}
          >
            {!vue.cle && (
              <button
                type="button"
                onClick={onFermer}
                aria-label={t('compte.fermer')}
                className="absolute top-3 right-3 w-8 h-8 flex items-center justify-center rounded-lg cursor-pointer focus-visible:outline-2 focus-visible:outline-[var(--color-accent)]"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                <X size={16} />
              </button>
            )}
            {carte}
          </div>
        </div>
      </div>,
      document.body,
    );
  }

  return (
    <div className="fixed inset-0 overflow-y-auto" style={{ background: 'var(--color-bg)' }} onKeyDown={boucleTab}>
      <div ref={boiteRef} className="w-full max-w-md mx-auto px-4 sm:px-6 py-10">
        <div className="text-center mb-8">
          {/* L'icône de l'app, comme SetupScreen : l'écran d'activation est
              la suite de l'installation, pas une page d'un autre produit. */}
          <img
            src="/pwa-192x192.png"
            alt=""
            width={56}
            height={56}
            draggable={false}
            className="w-14 h-14 rounded-2xl mx-auto mb-3 select-none"
          />
          <h1 className="text-xl font-bold" style={{ color: 'var(--color-text)' }}>
            Diapason
          </h1>
        </div>
        {carte}
      </div>
    </div>
  );
}
