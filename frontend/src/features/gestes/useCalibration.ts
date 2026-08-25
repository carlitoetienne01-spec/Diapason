/**
 * L'assistant de calibration (§16) : deux poses, mesurées, pas devinées.
 *
 * Les seuils d'usine sont des points de départ raisonnables — pas des
 * vérités. La taille des mains, la distance à l'objectif et la façon de
 * fermer le poing varient d'une personne à l'autre, et c'est exactement ce
 * qui faisait dire « la sensibilité n'est pas la bonne ».
 */

import { useCallback, useState } from 'react';

import {
  appliquerCalibration,
  finirLaMesure,
  mesurerPose,
  oublierCalibration,
} from './api';

const DUREE_MESURE_MS = 2500;

export type EtapeCalibration = 'repos' | 'ouverte' | 'fermee' | 'terminee';

export type Calibration = {
  etape: EtapeCalibration;
  message: string;
  erreur: string | null;
  demarrer: () => void;
  reinitialiser: () => void;
};

export function useCalibration(actif: boolean): Calibration {
  const [etape, setEtape] = useState<EtapeCalibration>('repos');
  const [message, setMessage] = useState('');
  const [erreur, setErreur] = useState<string | null>(null);

  const mesurer = useCallback(
    async (pose: 'ouverte' | 'fermee', consigne: string): Promise<number> => {
      setMessage(consigne);
      await mesurerPose(pose);
      await new Promise((r) => window.setTimeout(r, DUREE_MESURE_MS));
      return finirLaMesure(pose);
    },
    [],
  );

  const demarrer = useCallback(() => {
    if (!actif) return;
    setErreur(null);
    void (async () => {
      try {
        setEtape('ouverte');
        const ouverte = await mesurer(
          'ouverte',
          'Ouvre bien la main devant la caméra, doigts écartés…',
        );
        setEtape('fermee');
        const fermee = await mesurer(
          'fermee',
          'Maintenant serre le poing, franchement…',
        );
        await appliquerCalibration(ouverte, fermee);
        setEtape('terminee');
        setMessage(
          `Calibré sur ta main : ${fermee.toFixed(2)} poing fermé, ${ouverte.toFixed(2)} main ouverte.`,
        );
      } catch (exc) {
        setEtape('repos');
        setMessage('');
        setErreur(exc instanceof Error ? exc.message : String(exc));
      }
    })();
  }, [actif, mesurer]);

  const reinitialiser = useCallback(() => {
    void oublierCalibration().then(() => {
      setEtape('repos');
      setMessage('Réglages d’usine rétablis.');
      setErreur(null);
    });
  }, []);

  return { etape, message, erreur, demarrer, reinitialiser };
}
