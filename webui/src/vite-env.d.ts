/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_STUB_BASE?: string;
  readonly VITE_INGESTOR_BASE?: string;
  readonly VITE_RUNTIME_BASE?: string;
  readonly VITE_REGISTRY_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// bpmn-js ships no types for its prebuilt bundles.
declare module "bpmn-js/dist/bpmn-navigated-viewer.production.min.js" {
  const NavigatedViewer: {
    new (opts: { container: HTMLElement }): {
      importXML: (xml: string) => Promise<{ warnings: unknown[] }>;
      get: (name: string) => { zoom: (mode: string) => void };
      destroy: () => void;
    };
  };
  export default NavigatedViewer;
}
