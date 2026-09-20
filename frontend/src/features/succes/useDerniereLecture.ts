import { useEffect, useRef } from 'react';
import { creerDerniereLecture } from './lecturesPartagees';

/** Invalide dès la frappe, pas seulement au départ du GET temporisé. */
export function useDerniereLecture(cle = '') {
  const lecture = useRef(creerDerniereLecture());
  const precedente = useRef(cle);
  if (precedente.current !== cle) {
    precedente.current = cle;
    lecture.current.invalider();
  }
  useEffect(() => () => lecture.current.invalider(), []);
  return lecture.current;
}
