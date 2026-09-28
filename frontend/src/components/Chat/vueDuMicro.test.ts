import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it, vi } from 'vitest';

import { translate } from '../../i18n/translate';
import {
  DUREE_TOAST_AVEC_BOUTON_MS,
  DUREE_TOAST_MS,
  optionsDuToastDictee,
  texteDeLAvis,
  vueDuDetailDuMicro,
  type MicroAAfficher,
  type Traduire,
} from './vueDuMicro';

const fr: Traduire = (cle, vars) => translate('fr', cle, vars);
const en: Traduire = (cle, vars) => translate('en', cle, vars);

/** Ce que les hooks rendent au bureau : ni détail, ni bouton. */
const auBureau: MicroAAfficher = { technique: null, reglages: false, avis: null };
const auTelephone: MicroAAfficher = { technique: 'NotAllowedError · Permission denied', reglages: true, avis: null };

/**
 * 28/09/2026, revue du chantier du micro : quatre mutations du rendu (MU1d,
 * MU2, MU4, MU5) survivaient aux 1 814 tests — dont le bouton « Ouvrir les
 * réglages » montré au bureau, où aucune coquille ne l'ouvrirait (§5).
 */
describe('TestLaVueDuDetailDuMicro — le bouton n’existe qu’avec une coquille', () => {
  it('au bureau, rien ne s’affiche sous la phrase', () => {
    expect(vueDuDetailDuMicro(auBureau, fr), 'un bouton des réglages au bureau').toBeNull();
    expect(vueDuDetailDuMicro(null, fr)).toBeNull();
  });

  it('au téléphone, le détail et le bouton, dans la langue de la page', () => {
    expect(vueDuDetailDuMicro(auTelephone, fr)).toEqual({
      detail: 'Détail : NotAllowedError · Permission denied', bouton: 'Ouvrir les réglages', avis: null, reponse: null,
    });
    expect(vueDuDetailDuMicro(auTelephone, en)?.bouton).toBe('Open settings');
  });

  it('au téléphone sans état rendu par la coquille : le détail, sans bouton', () => {
    const vue = vueDuDetailDuMicro({ ...auTelephone, reglages: false }, fr);
    expect(vue?.detail).toBe('Détail : NotAllowedError · Permission denied');
    expect(vue?.bouton, 'un bouton qu’une coquille ancienne n’ouvrirait pas').toBeNull();
  });

  it('un avis des réglages se montre, même sans détail', () => {
    const vue = vueDuDetailDuMicro({ ...auBureau, avis: { cle: 'talk.micro.reglagesEchec', reponse: null } }, fr);
    expect(vue?.avis).toBe(fr('talk.micro.reglagesEchec'));
    expect(vue?.reponse).toBeNull();
    expect(texteDeLAvis({ cle: 'talk.micro.reglagesIndisponibles', reponse: null }, en))
      .toEqual({ texte: en('talk.micro.reglagesIndisponibles'), reponse: null });
  });

  it('en anglais, la phrase française de la coquille est citée sous une phrase anglaise, jamais seule', () => {
    // 28/09/2026, revue (sonde P2) : la phrase de la coquille s'affichait
    // seule — en français et au tutoiement, au milieu d'un écran anglais.
    // La phrase exacte de coquille_controller.dart quand Android refuse.
    const phrase = 'Les réglages d’Android n’ont pas pu s’ouvrir : ouvre Paramètres › Applis › Diapason › Autorisations › Micro.';
    const vue = vueDuDetailDuMicro({ ...auTelephone, avis: { cle: 'talk.micro.reglagesEchec', reponse: phrase } }, en);
    expect(vue?.avis, 'la phrase principale suit la langue de la page').toBe(en('talk.micro.reglagesEchec'));
    expect(vue?.reponse, 'le récepteur est cité et nommé (§100)').toBe(`The phone app replied: “${phrase}”`);
    expect(vueDuDetailDuMicro({ ...auTelephone, avis: { cle: 'talk.micro.reglagesEchec', reponse: phrase } }, fr)?.avis,
      'le vouvoiement de la page, pas le tutoiement de la coquille').not.toMatch(/\bouvre\b/);
  });
});

describe('TestLeToastDeLaDictee — la même décision que la barre et l’orbe', () => {
  it('au bureau : ni action, ni détail, la durée d’avant', () => {
    const options = optionsDuToastDictee(auBureau, fr, vi.fn());
    expect(options.action, 'l’action des réglages dans le toast du bureau').toBeUndefined();
    expect(options.description).toBeUndefined();
    expect(options.duration).toBe(DUREE_TOAST_MS);
  });

  it('au téléphone : le détail, et l’action à 40 px qui ouvre les réglages', () => {
    const ouvrir = vi.fn();
    const options = optionsDuToastDictee(auTelephone, fr, ouvrir);
    expect(options.description).toBe('Détail : NotAllowedError · Permission denied');
    expect(options.duration).toBe(DUREE_TOAST_AVEC_BOUTON_MS);
    expect(options.action?.label).toBe('Ouvrir les réglages');
    expect(options.action?.actionButtonStyle.minHeight, 'une cible sous 40 px au doigt').toBeGreaterThanOrEqual(40);
    options.action?.onClick();
    expect(ouvrir).toHaveBeenCalledOnce();
  });

  it('au téléphone sans bouton : le détail seul, 8 s', () => {
    const options = optionsDuToastDictee({ ...auTelephone, reglages: false }, fr, vi.fn());
    expect(options.action).toBeUndefined();
    expect(options.description).toBeDefined();
    expect(options.duration).toBe(DUREE_TOAST_MS);
  });
});

// ---------------------------------------------------------------------------
// Le branchement, lu comme du texte (à la manière de telephoneSeulement.test.ts).

const lire = (fichier: string) => readFileSync(join(__dirname, fichier), 'utf8');
const sansCommentaires = (code: string) =>
  code.replace(/\{\/\*[\s\S]*?\*\/\}/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
/** Le source sans commentaires, les blancs réduits à une espace. */
const source = (fichier: string) => sansCommentaires(lire(fichier)).replace(/\s+/g, ' ');

describe('TestLeBranchementDuDetailDuMicro — la barre, l’orbe et la dictée le montrent', () => {
  it('DetailDuMicro rend ce que décide vueDuDetailDuMicro, et rien d’autre', () => {
    const code = source('DetailDuMicro.tsx');
    expect(code).toContain('const vue = vueDuDetailDuMicro(micro, t); if (!vue) return null;');
    expect(code, 'le bouton ne dépend plus de la vue (MU1d)').toContain('{vue.bouton && ( <button type="button" onClick={onOuvrirReglages}');
    expect(code).toContain('{vue.detail && (');
    expect(code, 'la réponse de la coquille, dans la même annonce que l’avis').toContain('{vue.avis && ( <p role="status" className="text-xs"> {vue.avis} {vue.reponse && (');
    expect(code, 'une décision prise dans le composant échappe aux tests').not.toMatch(/micro\.(reglages|technique|avis)/);
  });

  it('la barre de la Discussion montre le détail et le bouton sous sa phrase (MU4)', () => {
    expect(source('BarreVocale.tsx'))
      .toContain('{erreur && <DetailDuMicro micro={voix.micro} onOuvrirReglages={() => void voix.ouvrirReglagesMicro()} />}');
  });

  it('l’orbe les montre aussi, et son hôte les lui passe (MU5)', () => {
    expect(source('TalkOrb.tsx'))
      .toContain('{error && onOuvrirReglagesMicro && <DetailDuMicro micro={micro} onOuvrirReglages={onOuvrirReglagesMicro}');
    const hote = sansCommentaires(readFileSync(join(__dirname, '..', 'TalkToDiapasonHost.tsx'), 'utf8')).replace(/\s+/g, ' ');
    expect(hote).toContain('micro={voice.micro}');
    expect(hote).toContain('onOuvrirReglagesMicro={() => void voice.ouvrirReglagesMicro()}');
  });

  it('la dictée prend ses options de toast à optionsDuToastDictee (MU2)', () => {
    expect(source('InputArea.tsx')).toContain('toast.error(speechError, optionsDuToastDictee(speechMicro, t, () => {');
  });
});
