import { beforeEach,afterEach,describe,it,expect,vi } from 'vitest';
import { creerSondeVisible } from './sondeVisible';
beforeEach(()=>vi.useFakeTimers());afterEach(()=>vi.useRealTimers());
describe('sonde système',()=>{
 it('ne démarre pas une sonde déjà fermée au remontage StrictMode',async()=>{
  const lire=vi.fn(async()=>{});
  const sonde=creerSondeVisible(lire,()=>true,3000);
  const attente=sonde.rafraichir();sonde.fermer();await attente;
  expect(lire).not.toHaveBeenCalled();
 });
 it('partage le montage et les compteurs puis s’arrête hors écran',async()=>{
  let visible=true;const lire=vi.fn(async()=>{});const s=creerSondeVisible(lire,()=>visible,3000);
  await Promise.all([s.rafraichir(),s.rafraichir()]);expect(lire).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(3000);expect(lire).toHaveBeenCalledTimes(2);
  visible=false;s.suspendre();await vi.advanceTimersByTimeAsync(9000);expect(lire).toHaveBeenCalledTimes(2);
  visible=true;await s.rafraichir();expect(lire).toHaveBeenCalledTimes(3);s.fermer();await vi.advanceTimersByTimeAsync(9000);expect(lire).toHaveBeenCalledTimes(3);
 });
 it('annule la lecture en vol et reprend sans attendre la réponse abandonnée',async()=>{
  const signaux:AbortSignal[]=[];const lire=vi.fn((signal:AbortSignal)=>{signaux.push(signal);return new Promise<void>(()=>{});});const s=creerSondeVisible(lire,()=>true,3000);
  void s.rafraichir();await vi.advanceTimersByTimeAsync(0);s.suspendre();expect(signaux[0].aborted).toBe(true);
  void s.rafraichir();await vi.advanceTimersByTimeAsync(0);expect(lire).toHaveBeenCalledTimes(2);s.fermer();expect(signaux[1].aborted).toBe(true);
 });
});
