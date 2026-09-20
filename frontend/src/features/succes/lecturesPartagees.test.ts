import { describe, it, expect } from 'vitest';
import { creerLecturesPartagees, creerDerniereLecture, creerFileEcritures } from './lecturesPartagees';
const differee = <T,>() => { let resolve!: (v:T)=>void; const promise = new Promise<T>(r=>{resolve=r;}); return {resolve,promise}; };
describe('lectures des modules', () => {
  it('partage une réception sans partager les objets modifiables', async () => {
    const c=creerLecturesPartagees();const d=differee<{id:string}[]>();let appels=0;
    const get=()=>{appels++;return d.promise;}; const a=c.lire('tasks',get);const b=c.lire('tasks',get);
    d.resolve([{id:'a'}]);const [x,y]=await Promise.all([a,b]);x[0].id='modifié';
    expect(appels).toBe(1);expect(y[0].id).toBe('a');
    await c.lire('tasks',get);expect(appels).toBe(2);
  });
  it('une mutation sépare les générations et un ancien finally ne supprime pas la suivante', async () => {
    const c=creerLecturesPartagees();const d=differee<number>();const n=differee<number>();
    const a=c.lire('tasks',()=>d.promise);c.invalider();let appels=0;
    const get=()=>{appels++;return n.promise;};const b=c.lire('tasks',get);
    d.resolve(1);await a;const j=c.lire('tasks',get);n.resolve(2);
    expect(await b).toBe(2);expect(await j).toBe(2);expect(appels).toBe(1);
  });
  it('oublie une lecture échouée et peut réessayer', async () => {
    const c=creerLecturesPartagees();await expect(c.lire('a',()=>Promise.reject(Error('panne')))).rejects.toThrow('panne');
    expect(await c.lire('a',()=>Promise.resolve(3))).toBe(3);
  });
  it('ignore les réponses à une ancienne frappe, mutation ou page fermée', () => {
    const g=creerDerniereLecture();const a=g.commencer();expect(a()).toBe(true);g.invalider();expect(a()).toBe(false);
    const b=g.commencer();const c=g.commencer();expect(b()).toBe(false);expect(c()).toBe(true);g.invalider();expect(c()).toBe(false);
  });
});

it('sauvegarde dans l’ordre et relit le brouillon après l’écriture précédente', async () => {
  const file=creerFileEcritures();const d=differee<void>();let brouillon='premier';const envoyes:string[]=[];
  const a=file(async()=>{envoyes.push(brouillon);await d.promise;});await Promise.resolve();
  brouillon='suite';const b=file(async()=>{envoyes.push(brouillon);});
  expect(envoyes).toEqual(['premier']);d.resolve();await Promise.all([a,b]);expect(envoyes).toEqual(['premier','suite']);
  await expect(file(async()=>{throw Error('panne');})).rejects.toThrow('panne');expect(await file(async()=>3)).toBe(3);
});
