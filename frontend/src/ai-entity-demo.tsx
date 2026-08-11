import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { AIEntityDemo } from './components/AIEntity/AIEntityDemo';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AIEntityDemo />
  </StrictMode>,
);
