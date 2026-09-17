import { describe, expect, it } from 'vitest';

import {
  AUCUN_EMOJI,
  HABIT_EMOJIS,
  PANNEAU_EMOJI_HAUTEUR_MAX,
  PANNEAU_EMOJI_LARGEUR,
  choixEmoji,
  placerPanneauEmoji,
} from './EmojiPicker';

describe('Où le panneau d’emojis se pose (portail fixed, revue du 17 sept. 2026, défaut 13)', () => {
  const fenetre = { largeur: 1384, hauteur: 868 };

  it('s’ouvre sous le bouton, en coordonnées de fenêtre, quand la place existe', () => {
    // Le formulaire de création vit en haut de page : ancré `absolute` dans
    // sa rangée vitrée, le panneau passait SOUS les rangées suivantes.
    const p = placerPanneauEmoji({ top: 200, bottom: 246, left: 300 }, fenetre);
    expect(p.top).toBe(252);
    expect(p.bottom).toBeUndefined();
    expect(p.left).toBe(300);
    expect(p.width).toBe(PANNEAU_EMOJI_LARGEUR);
    expect(p.maxHeight).toBe(PANNEAU_EMOJI_HAUTEUR_MAX);
  });

  it('se retourne vers le haut quand la place manque dessous et existe dessus', () => {
    const p = placerPanneauEmoji({ top: 760, bottom: 806, left: 300 }, fenetre);
    expect(p.top).toBeUndefined();
    expect(p.bottom).toBe(868 - 760 + 6);
  });

  it('reste dessous quand il n’y a de place ni dessus ni dessous', () => {
    // Fenêtre basse : mieux vaut déborder en bas (le panneau défile) que
    // sortir par le haut, hors d'atteinte.
    const p = placerPanneauEmoji({ top: 100, bottom: 146, left: 20 }, { largeur: 340, hauteur: 250 });
    expect(p.top).toBe(152);
    expect(p.bottom).toBeUndefined();
    expect(p.maxHeight).toBe(100);
  });

  it('est borné aux bords : ni à droite hors fenêtre, ni collé au bord gauche', () => {
    const droite = placerPanneauEmoji({ top: 10, bottom: 56, left: 1300 }, fenetre);
    expect(droite.left + droite.width).toBe(1384 - 8);
    const gauche = placerPanneauEmoji({ top: 10, bottom: 56, left: 2 }, fenetre);
    expect(gauche.left).toBe(8);
  });

  it('se rétrécit dans le mini-panneau plus étroit que lui', () => {
    const p = placerPanneauEmoji({ top: 10, bottom: 56, left: 0 }, { largeur: 200, hauteur: 600 });
    expect(p.width).toBe(184);
    expect(p.left).toBe(8);
  });
});

describe('Ce que le sélecteur d’emoji propose', () => {
  it('offre « Aucun » quand la valeur est facultative — effacer doit rester atteignable au clic (§82)', () => {
    // Revue du 17 sept. 2026, défaut 20 : l'emoji de tâche ne pouvait plus
    // redevenir vide qu'à la voix ou par l'API.
    const choix = choixEmoji('🔥', true);
    const aucun = choix[choix.length - 1];
    expect(aucun.emoji).toBe(AUCUN_EMOJI);
    expect(aucun.libelle).toBe('Aucun emoji');
  });

  it('ne l’offre pas là où l’icône est obligatoire (Habitudes, Finances)', () => {
    const choix = choixEmoji('🔥', false);
    expect(choix.some((c) => c.emoji === AUCUN_EMOJI)).toBe(false);
    expect(choix).toHaveLength(HABIT_EMOJIS.length);
  });

  it('garde la valeur courante hors liste, en tête et sélectionnable', () => {
    // Un 📞 posé à la voix : le bouton l'affichait, la liste ne le
    // retrouvait plus une fois changé.
    const choix = choixEmoji('📞', true);
    expect(choix[0]).toEqual({ emoji: '📞', libelle: 'Emoji 📞 (actuel)' });
    expect(choix).toHaveLength(HABIT_EMOJIS.length + 2);
  });

  it('ne double pas une valeur qui est déjà des 48, ni une valeur vide', () => {
    expect(choixEmoji('🔥', true).filter((c) => c.emoji === '🔥')).toHaveLength(1);
    expect(choixEmoji('', true)[0].emoji).toBe(HABIT_EMOJIS[0]);
  });
});
