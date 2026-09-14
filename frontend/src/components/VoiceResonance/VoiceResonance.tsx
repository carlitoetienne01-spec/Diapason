import { useEffect, useRef, useState } from 'react';
import type { VoiceLiveState } from '../../hooks/useVoiceLive';
import { useAudioSpectrum } from '../../hooks/useAudioSpectrum';
import { useAdaptiveQuality } from '../../hooks/useAdaptiveQuality';
import { SceneResonance } from './scene';

export function VoiceResonance({ state, audioSource, micSource }: {
  state: VoiceLiveState;
  audioSource?: AudioNode | null;
  micSource?: AudioNode | null;
}) {
  const hote = useRef<HTMLDivElement>(null);
  const scene = useRef<SceneResonance | null>(null);
  const etat = useRef(state);
  etat.current = state;
  const voix = useAudioSpectrum(audioSource, state === 'speaking');
  const micro = useAudioSpectrum(micSource, state === 'listening' || state === 'speaking');
  const { quality, request } = useAdaptiveQuality();
  const qualiteInitiale = useRef(quality);
  const [indisponible, setIndisponible] = useState(false);

  useEffect(() => {
    const element = hote.current;
    if (!element) return;
    const canvas = document.createElement('canvas');
    canvas.setAttribute('aria-hidden', 'true');
    element.appendChild(canvas);
    let rendu: SceneResonance;
    try {
      rendu = new SceneResonance(canvas, qualiteInitiale.current, () => {
        const entree = micro.read();
        if (etat.current !== 'speaking') return entree;
        const sortie = voix.read();
        // La reprise de parole reste visible avant même que le serveur
        // confirme l'interruption ; aucun événement réseau n'anime le micro.
        return entree.level > sortie.level ? entree : sortie;
      }, request);
    } catch {
      canvas.remove();
      setIndisponible(true);
      return;
    }
    scene.current = rendu;
    setIndisponible(false);
    let perdu = false;
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const mouvement = () => rendu.configurer(etat.current, preference.matches);
    const visibilite = () => rendu.setVisible(!document.hidden && !perdu);
    const taille = new ResizeObserver(([entree]) =>
      rendu.redimensionner(entree.contentRect.width, entree.contentRect.height));
    const perte = (event: Event) => {
      event.preventDefault();
      perdu = true;
      rendu.setVisible(false);
      setIndisponible(true);
    };
    canvas.addEventListener('webglcontextlost', perte);
    preference.addEventListener('change', mouvement);
    document.addEventListener('visibilitychange', visibilite);
    taille.observe(element);
    mouvement();
    visibilite();
    return () => {
      taille.disconnect();
      preference.removeEventListener('change', mouvement);
      document.removeEventListener('visibilitychange', visibilite);
      canvas.removeEventListener('webglcontextlost', perte);
      rendu.detruire();
      scene.current = null;
      canvas.remove();
    };
  }, [voix, micro, request]);

  useEffect(() => { scene.current?.setQualite(quality); }, [quality]);
  useEffect(() => {
    scene.current?.configurer(state, window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }, [state]);

  return <div ref={hote} className="resonance-volume" aria-hidden="true">
    {indisponible && <div className="resonance-repli" />}
  </div>;
}
