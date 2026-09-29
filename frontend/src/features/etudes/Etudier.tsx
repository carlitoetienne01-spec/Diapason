import { useEffect, useRef, useState } from 'react';
import { BookOpen, ChevronDown, ChevronLeft, ChevronRight, X, FileText, RefreshCw } from 'lucide-react';
import { TexteEtude } from './TexteEtude';
import { apiFetch } from '../../lib/api';
import { lireDocument, trierDocuments } from '../../components/Chat/piecesJointes';
import { agirEtude, creerEtude, lireEtude, supprimerEtude, lireMateriel, garderMateriel } from './api';
import { bilanEtude, erreurEtude, reponseModifiee, type EmplacementEtude, type Etude, type SourceEtude } from './etudes';
import { apercuEtude } from './filEtudes';
import { DicteeEtude } from './DicteeEtude';
import './Etudier.css';

interface ProprietesEtudier {
  conversationId: string; modele: string; onFermer: () => void;
  initiale?: Etude; nouvelle?: boolean; emplacement?: EmplacementEtude;
  onChanger: (etude: Etude) => void; onCreer: (etude: Etude) => void;
  onSupprimer: (id: string) => void; onNouvelle: () => void;
}

export function Etudier({ conversationId, modele, onFermer, initiale, nouvelle, emplacement, onChanger, onCreer, onSupprimer, onNouvelle }: ProprietesEtudier) {
  const [etude, setEtude] = useState<Etude | null>(initiale ?? null);
  const cleRepli = initiale ? `diapason-etude-repliee:${conversationId}:${initiale.id}` : '';
  const [repliee, setRepliee] = useState(() => {
    if (!initiale) return false;
    try {
      const choix = localStorage.getItem(cleRepli);
      return choix === 'repliee' ? true : choix === 'ouverte' ? false : !nouvelle;
    } catch { return !nouvelle; }
  });
  const [sujet, setSujet] = useState('');
  const [niveau, setNiveau] = useState('Débutant');
  const [mode, setMode] = useState<'practice' | 'exam'>('practice');
  const [nombre, setNombre] = useState(5);
  const [sources, setSources] = useState<SourceEtude[]>([]);
  const [position, setPosition] = useState(() => Math.max(0, initiale?.questions.findIndex(q => q.id === initiale.currentQuestionId) ?? 0));
  const [brouillons, setBrouillons] = useState<Record<string, string>>({});
  const [occupe, setOccupe] = useState('');
  const [enDictee, setEnDictee] = useState(false);
  const indisponible = !!occupe || enDictee;
  const [erreur, setErreur] = useState('');
  const [confirmerFin, setConfirmerFin] = useState(false);
  const [confirmerSuppression, setConfirmerSuppression] = useState(false);
  const [listeChargee, setListeChargee] = useState(false);
  const titreRef = useRef<HTMLHeadingElement>(null);
  const present = useRef(true);
  const verrou = useRef(false);

  useEffect(() => {
    present.current = true;
    if (!initiale) {
      void lireMateriel(conversationId).then(m => { if (present.current) { setSources(m.sources); setListeChargee(true); } })
        .catch(e => { if (present.current) setErreur(erreurEtude(e)); });
      titreRef.current?.focus();
      titreRef.current?.scrollIntoView({ block: 'start' });
    }
    return () => { present.current = false; };
  }, [conversationId]);

  useEffect(() => {
    if (cleRepli) try { localStorage.setItem(cleRepli, repliee ? 'repliee' : 'ouverte'); } catch { /* La carte reste utilisable sans stockage de présentation. */ }
  }, [cleRepli, repliee]);

  const adopter = (e: Etude) => {
    if (!present.current) return;
    setEtude(e); setBrouillons({}); onChanger(e);
    setPosition(Math.max(0, e.questions.findIndex(q => q.id === e.currentQuestionId)));
  };
  const executer = async (libelle: string, operation: () => Promise<void>) => {
    if (verrou.current || enDictee) return;
    verrou.current = true; setOccupe(libelle); setErreur('');
    try { await operation(); } catch (e) { if (present.current) setErreur(erreurEtude(e)); }
    finally { verrou.current = false; if (present.current) setOccupe(''); }
  };
  const q = etude?.questions[position];
  const texte = q ? brouillons[q.id] ?? etude?.responses[q.id]?.text ?? '' : '';
  const modifie = !!(etude && q && reponseModifiee(etude, q.id, texte));
  const bilan = etude ? bilanEtude(etude) : null;
  const note = q ? etude?.grades[q.id] : undefined;
  useEffect(() => {
    // 29/09/2026 : la dernière étude modifiée remplaçait celle qu'on relisait.
    // Chaque carte ne reçoit désormais que sa propre révision, sans écraser
    // un brouillon ni une dictée en cours.
    if (initiale && etude && initiale.id === etude.id && initiale.version > etude.version && !occupe && !modifie && !enDictee) {
      setEtude(initiale); setBrouillons({});
      setPosition(Math.max(0, initiale.questions.findIndex(q => q.id === initiale.currentQuestionId)));
    };
  }, [initiale, etude?.id, etude?.version, occupe, enDictee, modifie]);
  const enregistrer = async () => {
    if (!etude || !q) throw new Error('Aucune question sélectionnée.');
    if (!modifie) return etude;
    const e = await agirEtude(etude, 'answer', { questionId: q.id, text: texte });
    adopter(e); return e;
  };
  const importer = (fichiers: File[]) => executer('Lecture des documents…', async () => {
    const tri = trierDocuments(fichiers, sources.length);
    if (tri.refus.length) throw new Error(tri.refus.map(r => `${r.fichier} : ${r.raison}`).join(' · '));
    const ajouts: SourceEtude[] = [];
    for (const f of tri.acceptees) {
      const d = await lireDocument(f, apiFetch);
      if (d.tronque) throw new Error(`${d.nom} est trop long pour être étudié intégralement ici. Joins les chapitres concernés.`);
      ajouts.push({ name: d.nom, text: d.texte, truncated: false });
    }
    if ([...sources, ...ajouts].reduce((s, d) => s + d.text.length, 0) > 48_000) throw new Error('Les documents dépassent 48 000 caractères. Choisis les chapitres à étudier.');
    const prochaines = [...sources, ...ajouts];
    await garderMateriel(conversationId, prochaines);
    if (present.current) setSources(prochaines);
  });

  const basculer = () => {
    if (repliee && etude) void executer('Reprise de l’étude…', async () => { adopter(await agirEtude(etude, 'resume')); setRepliee(false); });
    else if (!repliee && modifie) void executer('Enregistrement avant repli…', async () => { await enregistrer(); setRepliee(true); });
    else setRepliee(r => !r);
  };
  const contenuId = `etude-contenu-${etude?.id ?? 'preparation'}`;
  return <section className={`etude-carte${repliee ? ' etude-repliee' : ''}`} aria-label={etude ? `Étude : ${etude.title}` : 'Préparer une étude'} aria-busy={!!occupe} data-study-id={etude?.id}>
    <header className="etude-entete">
      {etude ? <button type="button" className="etude-plier" aria-label={`${repliee ? 'Déplier' : 'Replier'} l’étude : ${etude.title}`} aria-expanded={!repliee} aria-controls={contenuId} disabled={indisponible} onClick={basculer}>
        <span>{repliee ? apercuEtude(etude) : etude.title}</span><ChevronDown size={18} aria-hidden="true" className={repliee ? '' : 'etude-chevron-ouvert'} />
      </button> : <><h2 ref={titreRef} tabIndex={-1}><BookOpen size={21} /> Nouvelle étude</h2>
        <button type="button" aria-label="Fermer la préparation" disabled={indisponible} onClick={onFermer}><X size={18} /></button></>}
    </header>
    {erreur && <div role="alert" className="etude-erreur">{erreur}
      {etude && <button type="button" disabled={indisponible} onClick={() => void executer('Relecture…', async () => adopter(await lireEtude(etude.id)))}><RefreshCw size={16} /> Recharger l’épreuve</button>}
    </div>}
    {occupe && <p role="status" className="etude-attente">{occupe}</p>}
    <div id={contenuId} hidden={repliee}>
    <p className="etude-secondaire">Comprendre · S’entraîner · S’évaluer</p>
    {!etude ? <>
      <form onSubmit={e => { e.preventDefault(); void executer('Préparation du cours, des questions et du corrigé…', async () => {
        const resultat = await creerEtude({ conversationId, model: modele, topic: sujet, level: niveau, mode, questionCount: nombre, sources, placement: emplacement });
        if (present.current) onCreer(resultat);
      }); }}>
        <label>Que veux-tu apprendre ?<textarea required minLength={3} maxLength={1200} value={sujet} disabled={indisponible}
          onChange={e => setSujet(e.target.value)} placeholder="Ex. : comprendre les fractions et savoir les additionner" rows={2} /></label>
        <div className="etude-grille">
          <label>Niveau<input value={niveau} required maxLength={120} disabled={indisponible} onChange={e => setNiveau(e.target.value)} /></label>
          <label>Parcours<select value={mode} disabled={indisponible} onChange={e => setMode(e.target.value as 'practice' | 'exam')}><option value="practice">Entraînement avec indices</option><option value="exam">Examen — correction à la fin</option></select></label>
          <label>Questions<input type="number" min={2} max={12} value={nombre} disabled={indisponible} onChange={e => setNombre(Number(e.target.value))} /></label>
        </div>
        <label className="etude-fichier"><FileText size={17} /> Ajouter mes documents
          <input aria-label="Documents du cours" type="file" multiple accept=".txt,.md,.csv,.pdf,.docx" disabled={indisponible || sources.length >= 2} onChange={e => { void importer(Array.from(e.target.files ?? [])); e.target.value = ''; }} />
        </label>
        <p className="etude-secondaire">PDF avec texte, Word ou texte · deux documents maximum. Sans document, le cours repose sur les connaissances du modèle local.</p>
        {sources.map((d, i) => <div key={i} className="etude-source"><span>{d.name} · {d.text.length.toLocaleString('fr')} caractères lus</span><button type="button" disabled={indisponible} aria-label={`Retirer ${d.name}`} onClick={() => void executer('Mise à jour des documents…', async () => { const prochaines = sources.filter((_, n) => n !== i); await garderMateriel(conversationId, prochaines); setSources(prochaines); })}><X size={16} /></button></div>)}
        <button className="etude-primaire" type="submit" disabled={indisponible || !modele || !listeChargee}>Préparer mon parcours</button>
        {!modele && <p role="status">Choisis d’abord un modèle local dans la discussion.</p>}
      </form>
    </> : <>
      <p className="etude-secondaire">{etude.level} · {etude.mode === 'exam' ? 'Examen' : 'Entraînement'} · {etude.questions.length} questions</p>
      {!!etude.sources.length && <p className="etude-secondaire">Documents : {etude.sources.map(d => d.name).join(', ')}. Les corrections citent les extraits utilisés.</p>}
      {etude.state === 'ready' && <>
        <h4>Objectifs</h4><ul>{etude.objectives.map(o => <li key={o}><TexteEtude ligne>{o}</TexteEtude></li>)}</ul>
        <div className="etude-cours"><TexteEtude>{etude.lesson}</TexteEtude></div>
        <h4>À retenir</h4><ul>{etude.essentials.map(o => <li key={o}><TexteEtude ligne>{o}</TexteEtude></li>)}</ul>
        <p className="etude-secondaire">{etude.mode === 'exam' ? 'Le cours sera masqué pendant l’examen. Le corrigé apparaîtra à la fin.' : 'Tu peux consulter le cours, demander un indice et corriger chaque réponse.'}</p>
        <button className="etude-primaire" type="button" disabled={indisponible} onClick={() => void executer('Ouverture de l’épreuve…', async () => adopter(await agirEtude(etude, 'start')))}>Commencer</button>
      </>}
      {etude.state === 'finished' && bilan && <div className="etude-bilan">
        <h4>Bilan : {bilan.score} / {bilan.maximum}</h4>
        <p>Ce résultat décrit cet essai. Il ne suffit pas à démontrer une maîtrise durable.</p>
        {!!etude.assisted.length && <p>{etude.assisted.length} question(s) avec indice.</p>}
        {!!bilan.nonEvalues.length && <><h4>Pas encore évalué</h4><ul>{bilan.nonEvalues.map(o => <li key={o}><TexteEtude ligne>{o}</TexteEtude></li>)}</ul></>}
        <h4>À consolider</h4>{bilan.aRevoir.length ? <ul>{bilan.aRevoir.map(o => <li key={o}><TexteEtude ligne>{o}</TexteEtude></li>)}</ul> : <p>Les objectifs évalués sont réussis sur cet essai. Reprends-les plus tard dans un autre contexte.</p>}
        <details><summary>Relire le cours</summary><div className="etude-cours"><TexteEtude>{etude.lesson}</TexteEtude></div></details>
      </div>}
      {etude.state === 'active' && etude.mode === 'practice' && <details><summary>Relire le cours</summary><div className="etude-cours"><TexteEtude>{etude.lesson}</TexteEtude></div><h4>À retenir</h4><ul>{etude.essentials.map(o => <li key={o}><TexteEtude ligne>{o}</TexteEtude></li>)}</ul></details>}
      {etude.state !== 'ready' && q && <div className="etude-question" key={q.id}>
        <div className="etude-progression"><span>Question {position + 1} / {etude.questions.length}</span><span>{q.maxScore} point(s)</span></div>
        <progress value={bilan?.repondues ?? 0} max={etude.questions.length} aria-label="Réponses enregistrées" />
        <div className="etude-intitule" role="heading" aria-level={4}><TexteEtude>{q.prompt}</TexteEtude></div><p className="etude-secondaire">Objectif : <TexteEtude ligne>{q.objective}</TexteEtude></p>
        {q.kind === 'choice' ? <fieldset disabled={indisponible || !!note || etude.state === 'finished'}><legend>Choisis une réponse</legend>
          {q.choices.map(c => <label className="etude-choix" key={c}><input type="radio" name={`reponse-${etude.id}-${q.id}`} value={c} checked={texte === c} onChange={() => setBrouillons(b => ({ ...b, [q.id]: c }))} /><span><TexteEtude ligne>{c}</TexteEtude></span></label>)}
        </fieldset> : <label>Ta réponse<textarea aria-label="Ta réponse" rows={4} value={texte} maxLength={8000} disabled={indisponible || !!note || etude.state === 'finished'} onChange={e => setBrouillons(b => ({ ...b, [q.id]: e.target.value }))} /></label>}
        {etude.state === 'active' && !note && <>
          {q.kind === 'open' && <DicteeEtude disabled={!!occupe} onActivite={setEnDictee} onTexte={t => setBrouillons(b => ({ ...b, [q.id]: [b[q.id] ?? etude.responses[q.id]?.text ?? '', t].filter(Boolean).join(' ') }))} />}
          <div className="etude-actions"><button type="button" disabled={indisponible || !modifie} onClick={() => void executer('Enregistrement…', async () => { await enregistrer(); })}>Enregistrer la réponse</button>
            {etude.mode === 'practice' && <><button type="button" disabled={indisponible} onClick={() => void executer('Ouverture de l’indice…', async () => { const e = await enregistrer(); adopter(await agirEtude(e, 'hint', { questionId: q.id })); })}>Un indice</button>
              <button type="button" disabled={indisponible || !texte.trim()} onClick={() => void executer('Correction expliquée…', async () => { const e = await enregistrer(); adopter(await agirEtude(e, 'check', { questionId: q.id })); })}>Corriger</button></>}
          </div>
          <p role="status" className="etude-secondaire">{modifie ? 'Brouillon non enregistré' : texte ? 'Réponse enregistrée sur le serveur' : 'Prends le temps de réfléchir.'}</p>
        </>}
        {etude.hints[q.id] && <aside className="etude-indice">Indice : <TexteEtude ligne>{etude.hints[q.id]}</TexteEtude></aside>}
        {note && <div className="etude-correction"><h4>{note.score} / {note.maxScore} — {note.method === 'proposed' ? 'Évaluation proposée' : 'Correction'}</h4>
          <TexteEtude>{note.feedback}</TexteEtude><p><strong>Réponse attendue :</strong> <TexteEtude ligne>{q.answer ?? ""}</TexteEtude></p><TexteEtude>{q.explanation ?? ""}</TexteEtude>
          {q.criteria && <ul>{q.criteria.map((c, i) => <li key={i}>{note.criteriaMet ? (note.criteriaMet[i] ? '✓ ' : 'À revoir : ') : ''}<TexteEtude ligne>{c}</TexteEtude></li>)}</ul>}
          {q.quote && <blockquote>{q.quote}<cite>{etude.sources[q.sourceIndex ?? 0]?.name}</cite></blockquote>}
        </div>}
        <div className="etude-actions etude-navigation">
          <button type="button" disabled={indisponible || position === 0} onClick={() => void executer('Enregistrement…', async () => { const e = etude.state === 'active' && !note ? await enregistrer() : etude; adopter(await agirEtude(e, 'navigate', { questionId: e.questions[position - 1].id })); })}><ChevronLeft size={17} /> Précédente</button>
          <button type="button" disabled={indisponible || position === etude.questions.length - 1} onClick={() => void executer('Enregistrement…', async () => { const e = etude.state === 'active' && !note ? await enregistrer() : etude; adopter(await agirEtude(e, 'navigate', { questionId: e.questions[position + 1].id })); })}>Suivante <ChevronRight size={17} /></button>
        </div>
        {etude.state === 'active' && <>
          {!confirmerFin ? <button type="button" disabled={indisponible} onClick={() => setConfirmerFin(true)}>Terminer et voir le bilan</button> : <div className="etude-confirmation">
            <p>Terminer l’épreuve ? Les questions laissées sans réponse vaudront zéro. Les réponses seront ensuite verrouillées.</p>
            <div className="etude-actions"><button className="etude-primaire" type="button" disabled={indisponible} onClick={() => void executer('Correction de l’épreuve et préparation du bilan…', async () => { const e = await enregistrer(); adopter(await agirEtude(e, 'finish')); setConfirmerFin(false); })}>Terminer l’épreuve</button><button type="button" disabled={indisponible} onClick={() => setConfirmerFin(false)}>Continuer</button></div>
          </div>}
        </>}
      </div>}
      <footer className="etude-actions">
        <button type="button" disabled={indisponible || modifie} onClick={onNouvelle}>Nouvelle étude</button>
        {!confirmerSuppression ? <button type="button" disabled={indisponible} onClick={() => setConfirmerSuppression(true)}>Supprimer cette étude</button> : <>
          <span>Supprimer le cours et ses réponses ?</span><button type="button" disabled={indisponible} onClick={() => void executer('Suppression…', async () => { await supprimerEtude(etude.id); onSupprimer(etude.id); try { localStorage.removeItem(cleRepli); } catch { /* Présentation locale uniquement. */ } })}>Confirmer la suppression</button><button type="button" onClick={() => setConfirmerSuppression(false)}>Conserver</button>
        </>}
      </footer>
    </>}
    </div>
  </section>;
}
