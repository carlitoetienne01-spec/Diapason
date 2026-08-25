/**
 * Ouvrir la caméra, capturer, envoyer — et surtout : refermer.
 *
 * Le §78 gouverne ce hook : rien ne guette en permanence. La caméra ne
 * s'ouvre qu'à l'armement et se referme à tout coup — désarmement,
 * démontage du composant, onglet fermé. Le voyant vert doit dire la vérité.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { armer, desarmer, EchecGeste, envoyerImage, type EtatGeste } from './api';

// Le serveur reconnaît en ~4 ms ; la limite est le codage JPEG et la boucle
// locale, pas l'analyse. Douze images par seconde suffisent à un geste de
// main et laissent la machine respirer.
const IMAGES_PAR_SECONDE = 12;
const LARGEUR = 640;

export type ModeGestes = {
  actif: boolean;
  etat: EtatGeste | null;
  mainVue: boolean;
  erreur: string | null;
  basculer: () => void;
};

export function useModeGestes(): ModeGestes {
  const [actif, setActif] = useState(false);
  const [etat, setEtat] = useState<EtatGeste | null>(null);
  const [mainVue, setMainVue] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const flux = useRef<MediaStream | null>(null);
  const video = useRef<HTMLVideoElement | null>(null);
  const canevas = useRef<HTMLCanvasElement | null>(null);
  const boucle = useRef<number | null>(null);
  const enVol = useRef(false);
  const echecs = useRef(0);

  const eteindre = useCallback(() => {
    if (boucle.current !== null) {
      window.clearInterval(boucle.current);
      boucle.current = null;
    }
    // Couper les pistes AVANT tout le reste : c'est ce qui éteint le voyant.
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
    const image = await new Promise<Blob | null>((resoudre) =>
      c.toBlob(resoudre, 'image/jpeg', 0.7),
    );
    if (!image) return;
    enVol.current = true;
    try {
      const reponse = await envoyerImage(await image.arrayBuffer());
      if (reponse === null) {
        // Le serveur s'est désarmé tout seul : on suit, caméra comprise.
        eteindre();
        return;
      }
      setEtat(reponse.state);
      setMainVue(reponse.hand);
      echecs.current = 0;
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

  const allumer = useCallback(async () => {
    setErreur(null);
    echecs.current = 0;
    try {
      await armer();
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
    boucle.current = window.setInterval(
      () => void capturer(),
      Math.round(1000 / IMAGES_PAR_SECONDE),
    );
  }, [capturer]);

  const basculer = useCallback(() => {
    if (actif) {
      void desarmer();
      eteindre();
    } else {
      void allumer();
    }
  }, [actif, allumer, eteindre]);

  // Le filet de sécurité : quoi qu'il arrive au composant, la caméra se
  // ferme. Une caméra qui survit à sa page est exactement ce que le voyant
  // vert est censé rendre impossible.
  useEffect(() => () => eteindre(), [eteindre]);

  return { actif, etat, mainVue, erreur, basculer };
}
