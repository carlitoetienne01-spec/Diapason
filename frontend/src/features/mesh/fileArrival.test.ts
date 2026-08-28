import { describe, expect, it } from 'vitest';

import { fileArrivalKind, formatFileArrivalSize } from './fileArrival';

describe('la présentation d’un fichier reçu', () => {
  it('reconnaît photo, vidéo et audio par leur type MIME', () => {
    expect(fileArrivalKind({ fileName: 'portrait.bin', mimeType: 'image/heic' })).toBe(
      'image',
    );
    expect(fileArrivalKind({ fileName: 'film.bin', mimeType: 'video/mp4' })).toBe(
      'video',
    );
    expect(fileArrivalKind({ fileName: 'voix.bin', mimeType: 'audio/mpeg' })).toBe(
      'audio',
    );
  });

  it('retombe sur l’extension quand un ancien émetteur omet le MIME', () => {
    expect(fileArrivalKind({ fileName: 'vacances.MOV', mimeType: '' })).toBe('video');
    expect(fileArrivalKind({ fileName: 'notes.pdf', mimeType: '' })).toBe('file');
  });

  it('affiche une taille stable et jamais négative', () => {
    expect(formatFileArrivalSize(479)).toBe('479 o');
    expect(formatFileArrivalSize(2 * 1024 ** 2)).toBe('2.0 Mio');
    expect(formatFileArrivalSize(-12)).toBe('0 o');
  });
});
