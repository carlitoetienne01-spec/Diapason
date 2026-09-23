/** 19 sept. 2026 : Copier ne transmettait que le Markdown. Notes recevait
 * des barres verticales au lieu des cellules visibles dans la discussion.
 * On clone uniquement le contenu rendu, jamais les outils de la bulle. */
export function htmlDeLaReponse(contenu: HTMLElement): string {
  const copie = contenu.cloneNode(true) as HTMLElement;
  copie.querySelectorAll('.code-block-wrapper').forEach((bloc) => {
    const pre = bloc.querySelector('pre');
    if (pre) bloc.replaceWith(pre);
  });
  copie.querySelectorAll('.visuel-secondaire, .visuel-outils, .visuel-laser, .visuel-statut').forEach(el => el.remove());
  copie.querySelectorAll('button, input, script, style').forEach((el) => el.remove());
  // Les couleurs du thème sombre ne doivent pas devenir de l'encre blanche
  // sur le papier d'une note. La destination fournit sa police et son thème.
  for (const el of [copie, ...copie.querySelectorAll('*')]) {
    const alignement = (el as HTMLElement).style?.textAlign;
    if (/^(left|center|right)$/.test(alignement ?? '') && /^(TH|TD)$/.test(el.tagName)) {
      el.setAttribute('align', alignement);
    }
    el.removeAttribute('class');
    el.removeAttribute('style');
    el.removeAttribute('id');
  }
  copie.querySelectorAll('table').forEach((table) => {
    table.setAttribute('style', 'border-collapse:collapse');
    table.setAttribute('border', '1');
  });
  copie.querySelectorAll('th, td').forEach((cellule) => {
    const alignement = cellule.getAttribute('align');
    const style = 'border:1px solid #808080;padding:6px 10px';
    cellule.setAttribute('style', /^(left|center|right)$/.test(alignement ?? '')
      ? `${style};text-align:${alignement}` : style);
  });
  return copie.innerHTML;
}

export async function copierMessage(texte: string, contenu?: HTMLElement | null): Promise<void> {
  if (!contenu) {
    await navigator.clipboard.writeText(texte);
    return;
  }
  const html = htmlDeLaReponse(contenu);
  if (typeof ClipboardItem !== 'undefined' && navigator.clipboard?.write) {
    // Préparer les deux formats dans le geste de clic : WebKit exige que
    // l'écriture commence avant de perdre l'activation de l'utilisateur.
    await navigator.clipboard.write([new ClipboardItem({
      'text/plain': new Blob([texte], { type: 'text/plain' }),
      'text/html': new Blob([html], { type: 'text/html' }),
    })]);
    return;
  }
  // Anciennes WebViews : conserver les DEUX formats, sans sélectionner ni
  // modifier le document de l'utilisateur. Aucun succès si le geste échoue.
  let transmis = false;
  const copier = (event: ClipboardEvent) => {
    if (!event.clipboardData) return;
    event.preventDefault();
    event.clipboardData.setData('text/plain', texte);
    event.clipboardData.setData('text/html', html);
    transmis = true;
  };
  document.addEventListener('copy', copier);
  try {
    document.execCommand('copy');
    if (!transmis) throw new Error('Clipboard unavailable');
  } finally {
    document.removeEventListener('copy', copier);
  }
}
