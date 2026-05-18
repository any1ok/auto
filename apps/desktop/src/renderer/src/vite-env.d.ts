/// <reference types="vite/client" />

import type { AutosendApi } from "../../main/types";

declare global {
  interface Window {
    autosend: AutosendApi;
  }
}

