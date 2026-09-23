declare module 'plotly.js-cartesian-dist-min' {
  const Plotly: {
    newPlot(element: HTMLElement, data: unknown[], layout: Record<string, unknown>, config: Record<string, unknown>): Promise<HTMLElement>;
    relayout(element: HTMLElement, layout: Record<string, unknown>): Promise<void>;
    purge(element: HTMLElement): void;
    toImage(element: HTMLElement, options: { format: 'svg' | 'png'; width: number; height: number }): Promise<string>;
    Plots: { resize(element: HTMLElement): Promise<void> };
  };
  export default Plotly;
}

declare module 'plotly.js-gl3d-dist-min' {
  import Plotly from 'plotly.js-cartesian-dist-min';
  export default Plotly;
}
