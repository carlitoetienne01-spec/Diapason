import {
  AdditiveBlending, BufferAttribute, BufferGeometry, NoToneMapping,
  PerspectiveCamera, Points, Scene, ShaderMaterial, Vector2, WebGLRenderer,
} from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import type { VoiceLiveState } from '../../hooks/useVoiceLive';
import type { SpectrumFrame } from '../../hooks/useAudioSpectrum';
import type { AIQuality } from '../AIEntity/types';
import { approcher, DENSITES, energieVocale, pointsDesVoiles, PROFILS } from './mouvement';
import { FRAGMENT, SOMMET, SORTIE_VITREE } from './shaders';

export class SceneResonance {
  private rendu: WebGLRenderer;
  private monde = new Scene();
  private camera = new PerspectiveCamera(36, 1, 0.1, 30);
  private composition: EffectComposer;
  private halo = new UnrealBloomPass(new Vector2(1, 1), 0.5, 0.7, 0.48);
  private sortie = new OutputPass();
  private transparence = new ShaderPass(SORTIE_VITREE);
  private matiere: ShaderMaterial;
  private points: Points;
  private qualite: AIQuality;
  private etat: VoiceLiveState = 'idle';
  private reduit = false;
  private visible = false;
  private frame = 0;
  private precedent = 0;
  private temps = 2.4;
  private taille = PROFILS.idle.taille;
  private voix = 0;
  private compteur = 0;
  private mesure = 0;

  constructor(
    canvas: HTMLCanvasElement,
    qualite: AIQuality,
    private lire: () => SpectrumFrame,
    private ralentir: (qualite: AIQuality) => void,
  ) {
    this.qualite = qualite;
    this.rendu = new WebGLRenderer({ canvas, alpha: true, premultipliedAlpha: true, antialias: false, powerPreference: 'low-power' });
    this.rendu.setClearColor(0x000000, 0);
    this.rendu.toneMapping = NoToneMapping;
    this.rendu.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.camera.position.z = 4.5;
    this.matiere = new ShaderMaterial({
      vertexShader: SOMMET, fragmentShader: FRAGMENT,
      transparent: true, depthWrite: false, depthTest: false, blending: AdditiveBlending,
      uniforms: {
        uTemps: { value: this.temps }, uTaille: { value: this.taille },
        uVoix: { value: 0 }, uAigus: { value: 0 },
        uPixels: { value: this.rendu.getPixelRatio() }, uDensite: { value: 1 },
      },
    });
    this.points = new Points(new BufferGeometry(), this.matiere);
    this.points.frustumCulled = false;
    this.monde.add(this.points);
    this.composition = new EffectComposer(this.rendu);
    this.composition.addPass(new RenderPass(this.monde, this.camera));
    this.composition.addPass(this.halo);
    this.composition.addPass(this.sortie);
    this.composition.addPass(this.transparence);
    this.setQualite(qualite);
  }

  setQualite(qualite: AIQuality) {
    this.qualite = qualite;
    const geometrie = new BufferGeometry();
    geometrie.setAttribute('position', new BufferAttribute(pointsDesVoiles(qualite), 3));
    this.points.geometry.dispose();
    this.points.geometry = geometrie;
    const [x, y] = DENSITES[qualite];
    this.matiere.uniforms.uDensite.value = Math.sqrt((240*128)/(x*y));
    this.dessiner(0);
  }

  redimensionner(largeur: number, hauteur: number) {
    if (!largeur || !hauteur) return;
    this.camera.aspect = largeur / hauteur;
    // Le volume reste entier sur une fenêtre étroite, même pendant une réponse.
    this.camera.position.z = 4.5 / Math.min(1, this.camera.aspect);
    this.camera.updateProjectionMatrix();
    this.rendu.setSize(largeur, hauteur, false);
    this.composition.setSize(largeur, hauteur);
    this.dessiner(0);
  }

  configurer(etat: VoiceLiveState, reduit: boolean) {
    this.etat = etat;
    this.reduit = reduit;
    if (reduit) {
      this.voix = 0;
      this.taille = PROFILS.idle.taille;
    }
    this.dessiner(0);
    this.boucler();
  }

  setVisible(visible: boolean) {
    this.visible = visible;
    this.precedent = 0;
    this.boucler();
  }

  private boucler() {
    cancelAnimationFrame(this.frame);
    if (this.visible && !this.reduit && this.etat !== 'error') {
      this.frame = requestAnimationFrame(this.tick);
    }
  }

  private tick = (maintenant: number) => {
    const delta = this.precedent ? Math.min(0.08, (maintenant-this.precedent)/1000) : 0;
    this.precedent = maintenant;
    this.dessiner(delta);
    this.compteur++;
    this.mesure += delta;
    // Deux secondes sous 32 i/s réduisent les points. Ne pas confondre un
    // onglet caché (sans boucle) avec une machine trop lente.
    if (this.mesure > 2) {
      if (this.compteur / this.mesure < 32) {
        const niveaux: AIQuality[] = ['low', 'medium', 'high', 'ultra'];
        this.ralentir(niveaux[Math.max(0, niveaux.indexOf(this.qualite)-1)]);
      }
      this.compteur = 0;
      this.mesure = 0;
    }
    this.frame = requestAnimationFrame(this.tick);
  };

  private dessiner(delta: number) {
    const profil = PROFILS[this.etat];
    const son = this.reduit ? null : this.lire();
    const energie = energieVocale(son?.level ?? 0, this.etat, this.reduit);
    // Une attaque de 65 ms garde les consonnes ; 180 ms de relâchement évitent
    // le clignotement entre deux syllabes sans prolonger une interruption.
    const cible = energie * profil.voix;
    this.voix = approcher(this.voix, cible, delta, cible > this.voix ? 0.065 : 0.18);
    if (!this.reduit) {
      this.temps += delta * profil.vitesse;
      this.taille = approcher(this.taille, profil.taille, delta, 0.65);
    }
    const u = this.matiere.uniforms;
    u.uTemps.value = this.temps;
    u.uTaille.value = this.taille * (this.reduit ? 1 : 1 + 0.012*Math.sin(this.temps*6));
    u.uVoix.value = this.voix;
    u.uAigus.value = energie > 0 ? (son?.bins[40] ?? 0) * energie : 0;
    this.composition.render();
  }

  detruire() {
    this.visible = false;
    cancelAnimationFrame(this.frame);
    this.points.geometry.dispose();
    this.matiere.dispose();
    this.halo.dispose();
    this.sortie.dispose();
    this.transparence.dispose();
    this.composition.dispose();
    this.rendu.dispose();
    this.rendu.forceContextLoss();
  }
}
