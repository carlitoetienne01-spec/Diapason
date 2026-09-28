// Ce qui s'affiche sous la phrase d'un micro qui ne s'est pas ouvert : le
// détail technique, le bouton « Ouvrir les réglages » et ce que la coquille
// a dit des réglages — dans la barre de la Discussion, dans l'orbe, et dans
// le toast de la dictée.
//
// 28/09/2026, revue du chantier du micro : quatre mutations de ce rendu
// laissaient les 1 814 tests verts — le bouton montré au bureau sous tout
// échec du micro, l'action du toast de la dictée au bureau, le détail et le
// bouton retirés de la barre, puis de l'orbe. Seules les valeurs du hook
// étaient éprouvées. Faute de tests de composants dans ce dépôt, la décision
// vit ici, en fonctions pures, et le branchement des composants est gardé
// par une lecture de leur source (vueDuMicro.test.ts).

import type { MessageKey, Vars } from '../../i18n/translate';
import type { AvisDesReglages } from '../../lib/echecMicro';

export type Traduire = (cle: MessageKey, vars?: Vars) => string;

/** Ce qu'un échec du micro porte sous sa phrase : la voix ou la dictée. */
export interface MicroAAfficher {
  /** « NotReadableError · Could not start audio source » ; null au bureau. */
  technique: string | null;
  /** Vrai seulement quand la coquille a rendu un état : elle sait ouvrir ses réglages. */
  reglages: boolean;
  /** Les réglages ne se sont pas ouverts : ce qu'il faut en dire. */
  avis?: AvisDesReglages | null;
}

export interface VueDuDetail {
  /** « Détail : … », ou rien. */
  detail: string | null;
  /** Le libellé du bouton des réglages, ou rien : pas de bouton. */
  bouton: string | null;
  /** La phrase sur les réglages qui ne se sont pas ouverts, ou rien. */
  avis: string | null;
  /** Ce que la coquille en a dit, cité et attribué, ou rien. */
  reponse: string | null;
}

/**
 * Un avis des réglages : la phrase de la page, dans sa langue, et celle de
 * la coquille — qui ne parle que français — citée dessous, attribuée.
 */
export function texteDeLAvis(avis: AvisDesReglages, t: Traduire): { texte: string; reponse: string | null } {
  return {
    texte: t(avis.cle),
    reponse: avis.reponse ? t('talk.micro.reponseDeLApp', { phrase: avis.reponse }) : null,
  };
}

/**
 * `null` : rien à montrer. Au bureau, le hook rend `technique: null` et
 * `reglages: false` — la vue est donc vide, et aucun bouton n'y promet des
 * réglages qu'aucune coquille n'ouvrirait.
 */
export function vueDuDetailDuMicro(micro: MicroAAfficher | null, t: Traduire): VueDuDetail | null {
  if (!micro) return null;
  const avis = micro.avis ? texteDeLAvis(micro.avis, t) : null;
  const vue: VueDuDetail = {
    detail: micro.technique ? t('talk.micro.detail', { technique: micro.technique }) : null,
    bouton: micro.reglages ? t('talk.micro.ouvrirReglages') : null,
    avis: avis?.texte ?? null,
    reponse: avis?.reponse ?? null,
  };
  return vue.detail || vue.bouton || vue.avis ? vue : null;
}

/**
 * Faut-il rendre le focus au détail ? 28/09/2026, revue : au retour des
 * Paramètres avec le micro accordé, « Ouvrir les réglages » — qui avait le
 * focus, puisqu'on venait de le toucher — quittait le DOM, et le focus
 * tombait sur <body> : TalkBack reprenait la lecture du haut de la page.
 * Seulement quand c'est le bouton qui vient de disparaître ET que personne
 * d'autre n'a pris le focus : on ne l'arrache jamais au champ où l'on écrit.
 */
export function doitReprendreLeFocus(
  boutonAvant: boolean,
  boutonApres: boolean,
  actif: Element | null,
  corps: Element | null,
): boolean {
  return boutonAvant && !boutonApres && (actif === null || actif === corps);
}

/**
 * La durée du toast de la dictée. 8 s pour une phrase seule, comme avant le
 * 28/09/2026. 15 s quand un bouton attend le pouce : la phrase la plus longue
 * et son détail font une quarantaine de mots, une dizaine de secondes de
 * lecture à 250 mots par minute, plus le geste.
 */
export const DUREE_TOAST_MS = 8000;
export const DUREE_TOAST_AVEC_BOUTON_MS = 15000;

export interface OptionsDuToast {
  duration: number;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
    /** 40 px : c'est un doigt qui le touche (CLAUDE.md §3). */
    actionButtonStyle: { minHeight: number; paddingInline: number };
  };
}

/** Les options du toast d'une dictée dont le micro ne s'est pas ouvert. */
export function optionsDuToastDictee(
  micro: MicroAAfficher | null,
  t: Traduire,
  ouvrirReglages: () => void,
): OptionsDuToast {
  const vue = vueDuDetailDuMicro(micro, t);
  return {
    duration: vue?.bouton ? DUREE_TOAST_AVEC_BOUTON_MS : DUREE_TOAST_MS,
    ...(vue?.detail ? { description: vue.detail } : {}),
    ...(vue?.bouton
      ? { action: { label: vue.bouton, onClick: ouvrirReglages, actionButtonStyle: { minHeight: 40, paddingInline: 12 } } }
      : {}),
  };
}
