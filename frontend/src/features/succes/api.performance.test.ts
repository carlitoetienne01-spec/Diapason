import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
const reseau=vi.hoisted(()=>vi.fn());
let base='http://local',cle='test';
vi.mock('../../lib/api',()=>({apiFetch:reseau,getBase:()=>base,getApiKey:()=>cle}));
let api:typeof import('./api');
const response=(value:unknown,status=200)=>({ok:status<400,status,headers:new Headers(),json:async()=>value});
beforeEach(async()=>{vi.resetModules();reseau.mockReset();base='http://local';cle='test';api=await import('./api');});
afterEach(()=>vi.useRealTimers());
describe('client Succès et réessais',()=>{
  it('ne charge qu’une fois les mêmes tâches simultanées',async()=>{
    reseau.mockResolvedValue(response({tasks:[{id:'a'}]}));const [a,b]=await Promise.all([api.listSuccesTasks(),api.listSuccesTasks()]);
    expect(reseau).toHaveBeenCalledTimes(1);expect(a).toEqual(b);expect(a[0]).not.toBe(b[0]);
  });
  it('sépare les recherches, clés et serveurs',async()=>{
    reseau.mockResolvedValue(response({tasks:[]}));const a=api.listSuccesTasks();cle='nouvelle';const b=api.listSuccesTasks();base='http://autre';const c=api.listSuccesTasks();const d=api.listSuccesTasks({search:'autre'});
    await Promise.all([a,b,c,d]);expect(reseau).toHaveBeenCalledTimes(4);
  });
  it('ne rejoue pas une création quand la réponse réseau est perdue',async()=>{
    reseau.mockRejectedValue(Error('Load failed'));await expect(api.createSuccesNote({title:'Unique'})).rejects.toThrow();expect(reseau).toHaveBeenCalledTimes(1);
  });
  it('une panne de lecture temporaire est réessayée',async()=>{
    vi.useFakeTimers();reseau.mockRejectedValueOnce(Error('Load failed')).mockResolvedValue(response({notes:[]}));
    const p=api.listSuccesNoteResumes();await vi.advanceTimersByTimeAsync(250);expect(await p).toEqual([]);expect(reseau).toHaveBeenCalledTimes(2);
  });
  it('ne réutilise pas une lecture antérieure à une écriture',async()=>{
    let rendre!: (v:unknown)=>void;reseau.mockReturnValueOnce(new Promise(r=>{rendre=r;})).mockResolvedValueOnce(response({note:{id:'b'}})).mockResolvedValueOnce(response({notes:[{id:'b'}]}));
    const ancienne=api.listSuccesNoteResumes();await api.createSuccesNote({title:'B'});const suivante=await api.listSuccesNoteResumes();rendre(response({notes:[]}));await ancienne;
    expect(suivante).toEqual([{id:'b'}]);expect(reseau).toHaveBeenCalledTimes(3);
  });
});
