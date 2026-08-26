/**
 * Ouvrir la caméra, capturer, envoyer — et surtout : refermer.
 *
 * Le §78 gouverne ce hook : rien ne guette en permanence. La caméra ne
 * s'ouvre qu'à l'armement et se referme à tout coup — désarmement,
 * démontage du composant, onglet fermé. Le voyant vert doit dire la vérité.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  armer,
  choisirLAppareil,
  desarmer,
  type Diagnostic,
  EchecGeste,
  envoyerImage,
  ecouterLesClaps,
  lireDiagnostic,
  renoncerAuDepot,
  type EtatGeste,
} from './api';

// La cadence de DÉPART, avant que le serveur ne dise la sienne. Le serveur
// reconnaît en ~4 ms ; la limite est le codage JPEG et la boucle locale, pas
// l'analyse. Douze images par seconde suffisent à un geste de main.
//
// Elle ne reste pas à douze (§83) : le serveur rend `fps` avec chaque image,
// et il tombe à trois quand aucune main n'a été vue depuis trois secondes.
// Filmer une chaise vide à douze images par seconde pendant dix minutes,
// c'était le prix que le mode armé coûtait sans rien rendre.
const IMAGES_PAR_SECONDE = 12;
const LARGEUR = 640;

export type ModeGestes = {
  actif: boolean;
  etat: EtatGeste | null;
  mainVue: boolean;
  erreur: string | null;
  diagnostic: Diagnostic | null;
  clapsEcoutent: boolean;
  basculerLesClaps: () => void;
  basculer: () => void;
  /** Répondre à « vers lequel ? » — l'appareil vient de `pendingDrop`. */
  choisir: (deviceId: string) => void;
  /** Renoncer au dépôt en attente sans rien envoyer. */
  renoncer: () => void;
};

export function useModeGestes(): ModeGestes {
  const [actif, setActif] = useState(false);
  const [etat, setEtat] = useState<EtatGeste | null>(null);
  const [mainVue, setMainVue] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [diagnostic, setDiagnostic] = useState<Diagnostic | null>(null);
  const [clapsEcoutent, setClapsEcoutent] = useState(false);
  const flux = useRef<MediaStream | null>(null);
  const video = useRef<HTMLVideoElement | null>(null);
  const canevas = useRef<HTMLCanvasElement | null>(null);
  const boucle = useRef<number | null>(null);
  const enVol = useRef(false);
  const echecs = useRef(0);
  // La cadence appliquée à cet instant. Un ref et non un state : la changer
  // ne doit rien redessiner, seulement replanifier un minuteur.
  const cadence = useRef(IMAGES_PAR_SECONDE);
  const replanifier = useRef<((fps: number) => void) | null>(null);

  const eteindre = useCallback(() => {
    if (boucle.current !== null) {
      window.clearInterval(boucle.current);
      boucle.current = null;
    }
    // L'ordre compte, deux fois. D'abord couper la replanification : une
    // réponse d'image encore en vol appellerait `replanifier` après coup et
    // rallumerait un minuteur sur une caméra éteinte. Ensuite couper les
    // pistes — c'est ce qui éteint le voyant vert, et il doit s'éteindre
    // avant tout le reste.
    replanifier.current = null;
    cadence.current = IMAGES_PAR_SECONDE;
    flux.current?.getTracks().forEach((piste) => piste.stop());
    flux.current = null;
    video.current = null;
    setActif(false);
    setEtat(null);
    setMainVue(false);
  }, []);

  const capturer = useCallback(async () => {
    // La dernière image gagne : si l'envoi précédent n'est pas revenu, on
    // saute celle-ci plutôt que d'empiler une file qui prendrait du retard.
    if (enVol.current || !video.current || !canevas.current) return;
    const v = video.current;
    if (!v.videoWidth) return;
    const c = canevas.current;
    const hauteur = Math.round((v.videoHeight / v.videoWidth) * LARGEUR);
    c.width = LARGEUR;
    c.height = hauteur;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(v, 0, 0, LARGEUR, hauteur);
    // toDataURL plutôt que toBlob : le base64 est ce qui part, autant
    // l'obtenir directement que reconvertir un binaire qui ne voyagera pas.
    const donnees = c.toDataURL('image/jpeg', 0.7);
    const base64 = donnees.slice(donnees.indexOf(',') + 1);
    if (!base64) return;
    enVol.current = true;
    try {
      const reponse = await envoyerImage(base64);
      if (reponse === null) {
        // Le serveur s'est désarmé tout seul : on suit, caméra comprise.
        eteindre();
        return;
      }
      setEtat(reponse.state);
      setMainVue(reponse.hand);
      echecs.current = 0;
      // §83 : le serveur décide, l'interface obéit. Elle ne devine jamais
      // une cadence — elle ne sait pas si une main a été vue.
      if (reponse.fps && reponse.fps > 0) replanifier.current?.(reponse.fps);
    } catch (exc) {
      // Un hoquet réseau ne doit pas tuer le mode ; trois d'affilée, si.
      echecs.current += 1;
      const message = exc instanceof Error ? exc.message : String(exc);
      if (echecs.current >= 3) {
        setErreur(`Échec à l'envoi des images : ${message}`);
        eteindre();
      }
    } finally {
      enVol.current = false;
    }
  }, [eteindre]);

  const allumer = useCallback(async (dejaArme = false) => {
    setErreur(null);
    echecs.current = 0;
    try {
      // `dejaArme` : la session a été ouverte par un double-clap, côté
      // serveur. Ré-armer ici la réinitialiserait — et perdrait le geste
      // qui vient d'être fait.
      if (!dejaArme) await armer();
    } catch (exc) {
      const etape = exc instanceof EchecGeste ? exc.etape : 'armement';
      setErreur(`Échec à l'${etape} : ${exc instanceof Error ? exc.message : exc}`);
      return;
    }
    try {
      // C'est ICI que macOS demande l'accès — à l'application, qui a le
      // droit de poser la question.
      flux.current = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: LARGEUR } },
        audio: false,
      });
    } catch (exc) {
      await desarmer();
      setErreur(
        exc instanceof Error && exc.name === 'NotAllowedError'
          ? 'Accès à la caméra refusé. Réglages Système → Confidentialité et sécurité → Caméra.'
          : `Échec à l'ouverture de la caméra : ${exc}`,
      );
      return;
    }
    const v = document.createElement('video');
    v.srcObject = flux.current;
    v.muted = true;
    v.playsInline = true;
    await v.play();
    video.current = v;
    canevas.current = document.createElement('canvas');
    setActif(true);
    // Replanifier plutôt que de recréer le hook : la boucle est un minuteur,
    // pas un état. On ne touche à rien tant que la cadence ne change pas —
    // couper et relancer à chaque image ferait perdre des captures.
    const poser = (fps: number) => {
      if (fps === cadence.current && boucle.current !== null) return;
      cadence.current = fps;
      if (boucle.current !== null) window.clearInterval(boucle.current);
      boucle.current = window.setInterval(
        () => void capturer(),
        Math.round(1000 / fps),
      );
    };
    replanifier.current = poser;
    poser(IMAGES_PAR_SECONDE);
  }, [capturer]);

  const basculerLesClaps = useCallback(() => {
    const voulu = !clapsEcoutent;
    void ecouterLesClaps(voulu)
      .then(setClapsEcoutent)
      .catch((exc) => setErreur(String(exc?.message ?? exc)));
  }, [clapsEcoutent]);

  const basculer = useCallback(() => {
    if (actif) {
      void desarmer();
      eteindre();
    } else {
      void allumer();
    }
  }, [actif, allumer, eteindre]);

  // Aligner la case sur ce que le serveur CONSTATE, jamais l'inverse.
  // Le fil d'écoute peut mourir sans que personne ne l'ait demandé — casque
  // débranché, micro repris par une autre application. La case restait
  // cochée, le panneau affichait « le micro écoute en continu » et un
  // compteur de claps figé, et on pouvait claper indéfiniment sans que rien
  // ne contredise l'écran.
  const accorder = useCallback((d: Diagnostic) => {
    setDiagnostic(d);
    if (d.clapListening === undefined) return;
    setClapsEcoutent((avant) => {
      if (avant && !d.clapListening) {
        setErreur('Le micro s’est fermé tout seul — réactive l’écoute.');
      }
      return d.clapListening ?? avant;
    });
  }, []);

  // Après avoir tranché, relire l'état TOUT DE SUITE plutôt que d'attendre
  // la seconde suivante : celui qui vient de cliquer regarde l'écran, et une
  // seconde de silence après un clic se lit comme un clic perdu.
  const rafraichir = useCallback(() => {
    void lireDiagnostic().then(accorder).catch(() => {});
  }, [accorder]);

  const choisir = useCallback(
    (deviceId: string) => {
      const jeton = diagnostic?.pendingDrop?.token;
      // Sans jeton, aucune question n'est en cours : ne rien envoyer vaut
      // mieux qu'envoyer vers un appareil que plus rien ne désigne.
      if (!jeton) return;
      void choisirLAppareil(jeton, deviceId)
        .catch((exc) => setErreur(String(exc?.message ?? exc)))
        .finally(rafraichir);
    },
    [diagnostic, rafraichir],
  );

  const renoncer = useCallback(() => {
    void renoncerAuDepot()
      .catch((exc) => setErreur(String(exc?.message ?? exc)))
      .finally(rafraichir);
  }, [rafraichir]);

  // Suivre le serveur quand un DOUBLE-CLAP arme la session : la caméra
  // n'est pas ouverte, donc rien ne l'apprendrait autrement. On sonde
  // toutes les deux secondes, et seulement tant que le micro écoute — un
  // sondage perpétuel pour une fonction éteinte serait du bruit.
  useEffect(() => {
    if (actif || !clapsEcoutent) return;
    const t = window.setInterval(() => {
      void lireDiagnostic()
        .then((d) => {
          // Le diagnostic sert aussi caméra éteinte : c'est là qu'on voit
          // si le micro entend les claps, et donc si le seuil convient.
          accorder(d);
          if (d.armed) void allumer(true);
        })
        .catch(() => {});
    }, 2000);
    return () => window.clearInterval(t);
  }, [actif, clapsEcoutent, allumer, accorder]);

  // Le diagnostic se relit une fois par seconde : assez pour juger, trop
  // peu pour peser. Il n'est jamais dans le chemin des images.
  useEffect(() => {
    if (!actif) {
      setDiagnostic(null);
      return;
    }
    const t = window.setInterval(() => {
      // Caméra allumée, cette boucle est la SEULE qui tourne : sans cet
      // accord, plus rien ne surveillait l'écoute dès que les gestes
      // s'activaient — c'est-à-dire au moment où elle sert le plus.
      void lireDiagnostic().then(accorder).catch(() => {});
    }, 1000);
    return () => window.clearInterval(t);
  }, [actif, accorder]);

  // Le filet de sécurité : quoi qu'il arrive au composant, la caméra se
  // ferme. Une caméra qui survit à sa page est exactement ce que le voyant
  // vert est censé rendre impossible.
  useEffect(() => () => eteindre(), [eteindre]);

  return {
    actif,
    etat,
    mainVue,
    erreur,
    diagnostic,
    clapsEcoutent,
    basculerLesClaps,
    basculer,
    choisir,
    renoncer,
  };
}
